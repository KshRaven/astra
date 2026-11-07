"""Start/stop the web panel in the background (`astra start`, `astra stop`) without systemd or a Windows service.
The foreground `astra web` also writes the pid file, so `astra stop` works for both."""
import os, re, socket, subprocess, sys, time
from . import config, plat


def pidfile():
    return config.HOME / "astra.pid"


def write_pid():
    try:
        config.HOME.mkdir(parents=True, exist_ok=True)
        pidfile().write_text(str(os.getpid()))
    except OSError:
        pass


def clear_pid():
    try:
        if pidfile().read_text().strip() == str(os.getpid()):
            pidfile().unlink()
    except OSError:
        pass


def _alive(pid):
    if plat.IS_WIN:
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True,
                                 creationflags=plat.NO_WINDOW).stdout
            return str(pid) in out
        except (OSError, subprocess.SubprocessError):
            return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def pid():
    try:
        p = int(pidfile().read_text().strip())
    except (OSError, ValueError):
        return None
    return p if _alive(p) else None


def listening():
    host = "127.0.0.1" if config.cfg["host"] in ("0.0.0.0", "::", "") else config.cfg["host"]
    try:
        with socket.socket() as s:
            s.settimeout(0.4)
            return s.connect_ex((host, int(config.cfg["port"]))) == 0
    except OSError:
        return False


def start():
    """Returns (ok, message)."""
    if listening():
        return True, "already running"
    config.LOGDIR.mkdir(parents=True, exist_ok=True)
    out = open(config.LOGDIR / "panel-out.log", "ab")
    kw = {"stdin": subprocess.DEVNULL, "stdout": out, "stderr": out}
    if plat.IS_WIN:
        kw["creationflags"] = 0x00000008 | 0x00000200 | plat.NO_WINDOW   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen([sys.executable, "-m", "astra", "web"], **kw)
    for _ in range(40):
        time.sleep(0.15)
        if listening():
            return True, "started"
    return False, f"did not start in time: see {config.LOGDIR / 'panel-out.log'}"


def _run(cmd, timeout=20):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=plat.NO_WINDOW,
                           stdin=subprocess.DEVNULL)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)


def listener_pids():
    """Process ids that are listening on the panel port (whoever started them)."""
    port = int(config.cfg["port"])
    found = set()
    if plat.IS_WIN:
        _, out = _run(["netstat", "-ano", "-p", "tcp"])
        for line in out.splitlines():
            f = line.split()
            if len(f) >= 5 and f[3].upper() == "LISTENING" and f[1].rsplit(":", 1)[-1] == str(port) and f[4].isdigit():
                found.add(int(f[4]))
    else:
        _, out = _run(["ss", "-ltnpH", f"sport = :{port}"])
        found.update(int(m) for m in re.findall(r"pid=(\d+)", out))
        if not found:
            _, out = _run(["lsof", "-t", f"-iTCP:{port}", "-sTCP:LISTEN"])
            found.update(int(x) for x in out.split() if x.isdigit())
    found.discard(os.getpid())
    return found


def _cmdline(p):
    if plat.IS_WIN:
        _, out = _run(["powershell", "-NoProfile", "-Command",
                       f"(Get-CimInstance Win32_Process -Filter 'ProcessId={int(p)}').CommandLine"])
        return out.strip()
    try:
        return open(f"/proc/{int(p)}/cmdline", "rb").read().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return ""


def _kill(p):
    if plat.IS_WIN:
        return _run(["taskkill", "/PID", str(p), "/T", "/F"])[0] == 0
    try:
        os.kill(p, 15)
        return True
    except OSError:
        return False


def _wait_down(n=30):
    for _ in range(n):
        if not listening():
            return True
        time.sleep(0.15)
    return not listening()


def stop():
    """Stop the panel however it was started: pid file, boot service/task, or (last resort) whatever astra
    process is listening on the panel port."""
    p = pid()
    if p is not None:
        _kill(p)
        _wait_down()
        try:
            pidfile().unlink()
        except OSError:
            pass
    if not listening():
        return True, "stopped" if p is not None else "not running"
    # started by the boot service / scheduled task, or from another config folder
    if plat.IS_WIN:
        _run(["schtasks", "/end", "/tn", "AstraPanel"])
    else:
        _run(["systemctl", "stop", "astra"], 60)
    if not _wait_down(20):
        for lp in listener_pids():
            cl = _cmdline(lp).lower()
            if "astra" in cl or "-m astra" in cl:
                _kill(lp)
        _wait_down()
    if listening():
        owners = ", ".join(map(str, sorted(listener_pids()))) or "unknown"
        return False, (f"something is still listening on port {config.cfg['port']} (pid {owners}). "
                       + ("Run this from an Administrator terminal" if plat.IS_WIN else "Run this with sudo")
                       + ", or it is not an astra process.")
    return True, "stopped"
