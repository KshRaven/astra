"""Start/stop the web panel in the background (`astra start`, `astra stop`) without systemd or a Windows service.
The foreground `astra web` also writes the pid file, so `astra stop` works for both."""
import os, socket, subprocess, sys, time
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


def stop():
    p = pid()
    if p is None:
        return (False, "the panel is running but was not started by astra (service?). Stop it with: "
                       + ("schtasks /end /tn AstraPanel" if plat.IS_WIN else "systemctl stop astra")) if listening() else (True, "not running")
    try:
        if plat.IS_WIN:
            subprocess.run(["taskkill", "/PID", str(p), "/T", "/F"], capture_output=True, creationflags=plat.NO_WINDOW)
        else:
            os.kill(p, 15)
    except OSError as e:
        return False, str(e)
    for _ in range(30):
        time.sleep(0.15)
        if not listening():
            break
    return True, "stopped"
