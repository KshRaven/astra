"""Desktop tab. The web desktop itself (windows over the other tabs) needs nothing installed.
This file backs the *optional* Linux GUI session (TigerVNC + noVNC + Openbox + xterm), which is only
installed after an explicit confirmation and only if the server has enough disk and memory.
The session runs as an unprivileged user (config desktop.user), never root, as transient systemd units
bound to 127.0.0.1 and protected by a random VNC password; reach it through an SSH tunnel."""
import os, re, secrets, shutil, string, subprocess, threading, time
from .. import config, plat
from ..errors import PanelError
from ..shell import run
from . import Extension

try:
    import pwd
except ImportError:  # Windows
    pwd = None
SUPPORTED = plat.IS_LINUX  # the VNC/Openbox session is Linux-only; the web desktop itself runs everywhere

EXT = Extension("desktop", "Desktop", "▦", order=5, ui="desktop",
                description="Web desktop with windows for every tab (any OS), plus an optional Linux-only GUI session installed on demand")

PKGS = ["tigervnc-standalone-server", "novnc", "websockify", "openbox", "xterm"]
BINS = ["Xtigervnc", "websockify", "openbox", "xterm", "vncpasswd"]
NOVNC = "/usr/share/novnc"
MIN_DISK_MB, MIN_RAM_MB = 800, 400
UNITS = ("astra-novnc", "astra-wm", "astra-vnc")
RUN_DIR = "/run/astra-desktop"
LOG = config.LOGDIR / "desktop-install.log"
_job = {"running": False, "rc": None}
_lock = threading.Lock()


def _ram_mb():
    if not SUPPORTED:
        return 0
    for line in open("/proc/meminfo"):
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    return 0


def _linux_only():
    if not SUPPORTED:
        raise PanelError(f"the optional GUI session is Linux-only (this is {plat.OS_NAME}). On Windows use Remote Desktop (RDP), "
                         "ideally through an SSH tunnel or VPN.", 501)


def _installed():
    return all(shutil.which(b) for b in BINS) and os.path.isdir(NOVNC)


def _active(unit):
    return run(["systemctl", "is-active", unit])[1].strip() == "active"


def _checks():
    disk = shutil.disk_usage("/usr").free // 2 ** 20
    ram = _ram_mb()
    return [
        {"label": "Running as root", "ok": config.IS_ROOT, "detail": "needed to install packages and start units"},
        {"label": "apt and systemd available", "ok": bool(shutil.which("apt-get") and shutil.which("systemd-run")), "detail": "Debian/Ubuntu with systemd"},
        {"label": f"Free disk at least {MIN_DISK_MB} MB", "ok": disk >= MIN_DISK_MB, "detail": f"{disk} MB free"},
        {"label": f"Free memory at least {MIN_RAM_MB} MB", "ok": ram >= MIN_RAM_MB, "detail": f"{ram} MB available"},
    ]


def _user():
    name = config.cfg["desktop"].get("user", "")
    try:
        u = pwd.getpwnam(name)
    except KeyError:
        raise PanelError("set an unprivileged user first: astra config set desktop '{\"user\":\"alice\"}' (the GUI never runs as root)")
    if u.pw_uid < 1000 or u.pw_shell.endswith(("nologin", "false")):
        raise PanelError(f"desktop.user '{name}' must be a normal login user")
    return u


@EXT.route("status")
def status(p):
    if not SUPPORTED:
        return {"supported": False, "installed": False, "packages": PKGS, "can_install": False, "running": False, "partial": False,
                "install_running": False, "user": "", "size_note": "",
                "checks": [{"label": "Linux with apt and systemd", "ok": False, "detail": f"this machine runs {plat.OS_NAME}"}]}
    checks = _checks()
    running = [u for u in UNITS if _active(u)] if shutil.which("systemctl") else []
    return {"supported": True, "installed": _installed(), "packages": PKGS, "checks": checks, "can_install": all(c["ok"] for c in checks[:3]) or False,
            "running": len(running) == len(UNITS), "partial": bool(running) and len(running) != len(UNITS),
            "install_running": _job["running"], "user": config.cfg["desktop"].get("user", ""),
            "size_note": "about 350 MB of disk; roughly 150-300 MB of RAM while a session runs (capped by desktop.mem_max_mb)"}


def _install():
    env = {**os.environ, "DEBIAN_FRONTEND": "noninteractive"}
    try:
        with open(LOG, "ab") as f:
            for cmd in (["apt-get", "update", "-qq"], ["apt-get", "install", "-y", "--no-install-recommends", *PKGS]):
                rc = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, env=env, timeout=1800).returncode
                if rc:
                    break
    except (OSError, subprocess.TimeoutExpired) as e:
        rc = 1
        LOG.write_text(f"install failed: {e}\n")
    _job.update(running=False, rc=rc)


@EXT.route("install", write=True)
def install(p):
    _linux_only()
    if _installed():
        raise PanelError("already installed")
    bad = [c["label"] for c in _checks()[:3] if not c["ok"]]
    if bad:
        raise PanelError("cannot install: " + "; ".join(bad))
    with _lock:
        if _job["running"]:
            raise PanelError("an install is already running")
        _job.update(running=True, rc=None)
    config.LOGDIR.mkdir(parents=True, exist_ok=True)
    LOG.write_bytes(b"")
    threading.Thread(target=_install, daemon=True).start()
    return {"started": True}


@EXT.route("install_log")
def install_log(p):
    text = LOG.read_bytes()[-4000:].decode(errors="replace") if LOG.exists() else ""
    return {"running": _job["running"], "rc": _job["rc"], "installed": _installed(), "text": text}


@EXT.route("start", write=True)
def start(p):
    _linux_only()
    if not _installed():
        raise PanelError("install the desktop packages first")
    u = _user()
    if _ram_mb() < MIN_RAM_MB:
        raise PanelError(f"only {_ram_mb()} MB of memory is free (need {MIN_RAM_MB} MB); not starting to protect the server")
    if any(_active(x) for x in UNITS):
        raise PanelError("a session is already running (stop it first)")
    d = config.cfg["desktop"]
    geo = d.get("geometry", "1280x720")
    if not re.fullmatch(r"\d{3,4}x\d{3,4}", geo):
        raise PanelError("desktop.geometry must look like 1280x720")
    mem = int(d.get("mem_max_mb", 600))
    pw = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(8))  # VNC auth uses 8 chars
    os.makedirs(RUN_DIR, mode=0o755, exist_ok=True)
    passfile = f"{RUN_DIR}/vnc.pass"
    obf = subprocess.run(["vncpasswd", "-f"], input=(pw + "\n").encode(), capture_output=True, timeout=10)
    if obf.returncode or not obf.stdout:
        raise PanelError("vncpasswd failed")
    fd = os.open(passfile, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(obf.stdout)
    os.chown(passfile, u.pw_uid, u.pw_gid)
    base = ["systemd-run", "--collect", "-p", f"User={u.pw_name}", f"--setenv=HOME={u.pw_dir}", "--setenv=DISPLAY=:1", "-p", "NoNewPrivileges=yes"]
    try:
        run(base + ["--unit=astra-vnc", "-p", f"MemoryMax={mem}M", "-p", "CPUWeight=50", "Xtigervnc", ":1", "-localhost", "yes",
                    "-rfbport", "5901", "-rfbauth", passfile, "-SecurityTypes", "VncAuth", "-geometry", geo, "-depth", "24"], check=True)
        time.sleep(1.5)
        run(base + ["--unit=astra-wm", "openbox"], check=True)
        run(base + ["--unit=astra-novnc", "websockify", "--web", NOVNC, "127.0.0.1:6080", "127.0.0.1:5901"], check=True)
    except PanelError:
        stop({})
        raise
    return {"password": pw, "user": u.pw_name, "tunnel": "ssh -L 6080:127.0.0.1:6080 you@this-server",
            "url": "http://127.0.0.1:6080/vnc.html?autoconnect=1&resize=scale"}


@EXT.route("stop", write=True)
def stop(p):
    _linux_only()
    for u in UNITS:
        run(["systemctl", "stop", u])
    shutil.rmtree(RUN_DIR, ignore_errors=True)
    return {"stopped": True}
