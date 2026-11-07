"""Config loading/saving. The admin password is stored only as a salted PBKDF2 hash."""
import copy, hashlib, hmac, json, os, re, secrets
from pathlib import Path
from . import plat

IS_ROOT = plat.IS_ROOT                      # root on Linux, elevated Administrator on Windows
HOME = plat.default_home()
CONFIG, LOGDIR = HOME / "config.json", HOME / "logs"
_OS = plat.defaults(HOME)

DEFAULTS = {
    "host": "0.0.0.0", "port": 8800,          # reachable from the network like aaPanel; set host to 127.0.0.1 to keep it local
    "base_path": "/astra",                    # the panel also answers at http://host:port/astra/ (and behind a reverse proxy at /astra/)
    "domain": "",                             # set by `astra domain set` / Settings > Domain and launch
    "site_engine": "auto",                    # auto = nginx when installed, else the built-in engine; "builtin" forces the built-in one
    "site_port": 8080,                        # built-in website server (used when nginx is not installed)
    "admin": {"username": "", "password_hash": ""},   # the one operator account (set by `astra init`)
    "tls_cert": "", "tls_key": "",            # set both to serve HTTPS directly
    "allowed_ips": [],                        # empty = any signed-in client
    "services": _OS["services"],              # allowlist: systemd units (Linux) / Windows service names
    "file_roots": _OS["file_roots"],          # file manager sandbox
    "web_roots": _OS["web_roots"],            # allowed document roots for new sites
    "log_files": _OS["log_files"],            # plain log files (Windows Event Log channels are built in)
    "backup_dir": _OS["backup_dir"],
    "cron_user": _OS["cron_user"],            # Linux cron user; Windows tasks run as SYSTEM
    "bin_dirs": _OS["bin_dirs"],              # extra folders searched for nginx, psql, mysql, docker ...
    "nginx_dir": "",                          # nginx conf folder; empty = auto-detect
    "disabled_extensions": [],
    "alerts": {"cpu": 90, "mem": 90, "disk": 90},   # percent; 0/absent disables
    "sample_interval": 5, "history_len": 360,        # 360 x 5s = 30 min
    "session_ttl_hours": 8,
    "job_concurrency": 1,                              # installs/updates that may run at once (1 = one after another)
    "console_enabled": True,                          # the Console drawer in the web panel (runs commands as the panel user)
    "audit_retention_days": 90,                       # older audit lines are deleted at start-up
    "mfa": {"totp_secret": "", "totp_enabled": False, "totp_last": 0, "email": "", "email_enabled": False},
    "smtp": {"host": "", "port": 587, "security": "starttls", "user": "", "password": "", "from": ""},
    "desktop": {"user": "", "geometry": "1280x720", "mem_max_mb": 600},  # optional Linux-only GUI session
}
SECRET_PATHS = (("admin", "password_hash"), ("mfa", "totp_secret"), ("smtp", "password"))

cfg = {}  # live config shared by all modules
_mtime = 0


def reload():
    global _mtime
    new = copy.deepcopy(DEFAULTS)
    if CONFIG.exists():
        for k, v in json.loads(CONFIG.read_text(encoding="utf-8-sig")).items():
            new[k] = {**new[k], **v} if isinstance(v, dict) and isinstance(new.get(k), dict) else v
    cfg.update(new)  # update in place: never leaves cfg empty for in-flight requests
    try:
        _mtime = CONFIG.stat().st_mtime_ns
    except OSError:
        _mtime = 0


def reload_if_changed():
    """Pick up `astra config set ...` made from another process. Replaces SIGHUP, which Windows lacks."""
    try:
        m = CONFIG.stat().st_mtime_ns
    except OSError:
        m = 0
    if m != _mtime:
        reload()


def save():
    global _mtime
    fresh = not HOME.exists()
    HOME.mkdir(parents=True, exist_ok=True, mode=0o700)
    if fresh:
        plat.secure(HOME)
    tmp = CONFIG.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, CONFIG)
    try:
        _mtime = CONFIG.stat().st_mtime_ns
    except OSError:
        pass


def public():
    """Config copy with secrets masked (for display and export)."""
    out = copy.deepcopy(cfg)
    for path in SECRET_PATHS:
        d = out
        for k in path[:-1]:
            d = d[k]
        if d.get(path[-1]):
            d[path[-1]] = "<set>"
    return out


PBKDF2_ROUNDS = 240_000
MIN_PASSWORD = 8


def hash_password(pw, rounds=PBKDF2_ROUNDS):
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, rounds)
    return f"pbkdf2_sha256${rounds}${salt.hex()}${dk.hex()}"


def verify_password(pw, stored):
    try:
        algo, rounds, salt, want = stored.split("$")
        got = hashlib.pbkdf2_hmac("sha256", pw.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return algo == "pbkdf2_sha256" and hmac.compare_digest(got, want)
    except (ValueError, AttributeError):
        return False


def has_admin():
    a = cfg.get("admin") or {}
    return bool(a.get("username") and a.get("password_hash"))


def set_admin(username=None, password=None):
    """Create or change the operator account. Caller must save()."""
    a = cfg.setdefault("admin", {"username": "", "password_hash": ""})
    if username is not None:
        username = username.strip()
        if not re.fullmatch(r"[A-Za-z0-9_.@-]{3,64}", username):
            raise ValueError("username: 3-64 letters, digits and . _ @ -")
        a["username"] = username
    if password is not None:
        if len(password) < MIN_PASSWORD:
            raise ValueError(f"password must be at least {MIN_PASSWORD} characters")
        a["password_hash"] = hash_password(password)


def new_password(n=14):
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "".join(secrets.choice(alphabet) for _ in range(n))


_DUMMY = hash_password("x", 1000)


def check_login(username, password):
    """Constant-ish time: always hashes, so a wrong user name is not distinguishable from a wrong password."""
    a = cfg.get("admin") or {}
    ok_user = hmac.compare_digest(str(username or "").encode(), str(a.get("username", "")).encode())
    ok_pw = verify_password(str(password or ""), a.get("password_hash") or _DUMMY)
    return bool(ok_user and ok_pw and a.get("password_hash"))


reload()
