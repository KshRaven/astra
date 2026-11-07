"""Operating-system layer. Everything that differs between Linux and Windows lives here, so the rest of
Astra asks questions ("am I an administrator?", "where is nginx?") instead of checking os.name everywhere.
Standard library only. Supported: Linux and Windows (10/11, Server 2016+). Other systems fall back to the Linux paths."""
import ctypes, glob, os, re, shutil, subprocess, sys
from pathlib import Path

IS_WIN = os.name == "nt"
IS_LINUX = sys.platform.startswith("linux")
OS_NAME = "windows" if IS_WIN else "linux" if IS_LINUX else sys.platform
NO_WINDOW = 0x08000000 if IS_WIN else 0          # CREATE_NO_WINDOW: no console flashing when run as a service/task
SHELL_CMD = ["cmd.exe", "/c"] if IS_WIN else ["/bin/sh", "-c"]
RESERVED = re.compile(r"^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$", re.I)   # Windows device names
EXAMPLE_ROOT = "C:\\www" if IS_WIN else "/var/www"


def pick(linux, windows):
    return windows if IS_WIN else linux


def is_admin():
    """root on Linux, an elevated Administrator on Windows."""
    if IS_WIN:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return os.geteuid() == 0


IS_ROOT = is_admin()


def default_home():
    env = os.environ.get("ASTRA_HOME")
    if env:
        return Path(env)
    if IS_WIN:
        pd = os.environ.get("ProgramData") or (os.environ.get("SystemDrive", "C:") + "\\ProgramData")
        return Path(pd) / "astra" if IS_ROOT else Path.home() / ".astra"
    return Path("/etc/astra") if IS_ROOT else Path.home() / ".astra"


def defaults(home):
    """OS specific config defaults (merged into config.DEFAULTS)."""
    if IS_WIN:
        sd = os.environ.get("SystemDrive", "C:") + "\\"
        return {"services": ["W3SVC", "nginx", "sshd"],
                "file_roots": [sd + "www", sd + "inetpub\\wwwroot"],
                "web_roots": [sd + "www"],
                "log_files": [sd + "nginx\\logs\\access.log", sd + "nginx\\logs\\error.log"],
                "backup_dir": str(home / "backups"),
                "bin_dirs": [sd + "nginx", sd + "Program Files\\nginx"],   # extra places to look for tools not on PATH
                "cron_user": "SYSTEM"}
    return {"services": ["nginx", "ssh"],
            "file_roots": ["/var/www", "/srv"],
            "web_roots": ["/var/www"],
            "log_files": ["/var/log/syslog", "/var/log/auth.log", "/var/log/nginx/access.log",
                          "/var/log/nginx/error.log", "/var/log/messages"],
            "backup_dir": "/var/backups/astra" if IS_ROOT else str(home / "backups"),
            "bin_dirs": [],
            "cron_user": "root"}


_WIN_BIN_GLOBS = ["{pf}\\PostgreSQL\\*\\bin", "{pf}\\MySQL\\MySQL Server *\\bin", "{pf}\\MariaDB *\\bin",
                  "{pf}\\Docker\\Docker\\resources\\bin", "{pf}\\Certbot\\bin"]


def which(name, extra=()):
    """Like shutil.which, but also searches config `bin_dirs` and (Windows) the usual install folders,
    because services on Windows rarely have database/nginx folders on PATH."""
    hit = shutil.which(name)
    if hit:
        return hit
    try:
        from . import config
        dirs = list(config.cfg.get("bin_dirs") or [])
    except Exception:
        dirs = []
    dirs += list(extra)
    if IS_WIN:
        for base in {os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")} - {None}:
            for pat in _WIN_BIN_GLOBS:
                dirs += sorted(glob.glob(pat.format(pf=base)), reverse=True)
    return shutil.which(name, path=os.pathsep.join(dirs)) if dirs else None


def secure(path, directory=True):
    """Make a file/folder private to the operator. POSIX: chmod 700/600. Windows: replace the ACL with
    SYSTEM + Administrators + the current user (S-1-5-18 and S-1-5-32-544 are language independent)."""
    try:
        if IS_WIN:
            flag = "(OI)(CI)F" if directory else "F"
            grants = [f"*S-1-5-18:{flag}", f"*S-1-5-32-544:{flag}"]
            user, dom = os.environ.get("USERNAME", ""), os.environ.get("USERDOMAIN", "")
            if user and not user.endswith("$"):          # machine accounts (SYSTEM) are covered above
                grants.append(f"{dom + chr(92) if dom else ''}{user}:{flag}")
            subprocess.run(["icacls", str(path), "/inheritance:r", "/grant:r", *grants],
                           capture_output=True, timeout=30, creationflags=NO_WINDOW, stdin=subprocess.DEVNULL)
        else:
            os.chmod(path, 0o700 if directory else 0o600)
    except (OSError, subprocess.SubprocessError):
        pass


def perms_private(path):
    """True/False on POSIX. None on Windows, where permissions are ACLs and not mode bits."""
    if IS_WIN:
        return None
    return (os.stat(path).st_mode & 0o077) == 0


def pkg_manager():
    """Name of the system package manager the panel can drive, or None.
    Linux: apt, dnf, yum, zypper, pacman, apk.  Windows: winget or choco."""
    if IS_WIN:
        return "winget" if which("winget") else "choco" if which("choco") else None
    for exe, name in (("apt-get", "apt"), ("dnf", "dnf"), ("yum", "dnf"), ("zypper", "zypper"),
                      ("pacman", "pacman"), ("apk", "apk")):
        if shutil.which(exe):
            return name
    return None


def has_systemd():
    return IS_LINUX and os.path.isdir("/run/systemd/system")


def local_ips():
    """Non-loopback IPv4 addresses of this machine (no network traffic: a UDP socket is only 'connected')."""
    import socket
    ips = []
    for target in ("192.0.2.1", "10.255.255.255"):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
                s.connect((target, 9))
                ip = s.getsockname()[0]
                if ip not in ips and not ip.startswith("127."):
                    ips.append(ip)
        except OSError:
            pass
    try:
        for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = i[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except OSError:
        pass
    return ips
