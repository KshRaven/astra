import glob, os
from .. import config, plat
from ..errors import PanelError
from ..shell import NAME, need, run
from . import Extension, Raw

WIN = plat.IS_WIN
EXT = Extension("logs", "Logs", "file-text", order=70, ui="logs",
                description="Read the panel's own logs, system logs, web server and database logs" + (", and the Windows Event Log." if WIN else ", and service journals."))
EVENT_LOGS = ("Application", "System", "Security", "Setup")   # Windows Event Log channels (Security needs Administrator)
PANEL = ("panel.log", "audit.log")
MAX_READ, MAX_DOWNLOAD = 512 * 1024, 5 * 1024 * 1024


def _globs():
    if WIN:
        pd, nd = os.environ.get("ProgramData", r"C:\ProgramData"), plat.which("nginx")
        out = [str(os.path.join(os.path.dirname(nd), "logs", "*.log"))] if nd else []
        return out + [pd + r"\MySQL\MySQL Server*\Data\*.err", pd + r"\Docker\log\*.log", r"C:\Windows\System32\LogFiles\HTTPERR\*.log"]
    return ["/var/log/syslog", "/var/log/messages", "/var/log/auth.log", "/var/log/secure", "/var/log/kern.log", "/var/log/dpkg.log", "/var/log/ufw.log",
            "/var/log/fail2ban.log", "/var/log/nginx/*.log", "/var/log/apache2/*.log", "/var/log/httpd/*.log", "/var/log/mysql/*.log", "/var/log/mariadb/*.log",
            "/var/log/postgresql/*.log", "/var/log/redis/*.log", "/var/log/php*.log"]


def _files():
    """label -> path for every readable log file we know about (panel logs, discovered system/app logs, configured log_files)."""
    out = {}
    for n in PANEL:
        f = config.LOGDIR / n
        if f.is_file():
            out["panel:" + n] = str(f)
    for g in _globs():
        for f in sorted(glob.glob(g)):
            if os.path.isfile(f):
                out["file:" + f] = f
    for f in config.cfg["log_files"]:
        if os.path.isfile(f):
            out["file:" + f] = f
    return out


def _tail(path, n, window=MAX_READ):
    with open(path, "rb") as f:
        f.seek(max(0, os.path.getsize(path) - window))
        data = f.read()
    return b"\n".join(data.splitlines()[-n:]).decode("utf-8", "replace")


def _read(source, n, window=MAX_READ):
    kind, _, target = str(source).partition(":")
    files = _files()
    if source in files:
        try:
            return _tail(files[source], n, window)
        except OSError as e:
            raise PanelError(f"cannot read {files[source]}: {e.strerror or e}")
    if WIN and kind == "eventlog" and target in EVENT_LOGS:  # newest first, plain text
        rc, out = run(["wevtutil", "qe", target, f"/c:{n}", "/rd:true", "/f:text"], timeout=30)
        if rc:
            raise PanelError(out.strip()[-300:] or "wevtutil failed (the Security log needs Administrator)")
        return out[:400000]
    if not WIN and kind == "unit" and target in config.cfg["services"]:
        return run(["journalctl", "-u", need(target, NAME, "unit"), "-n", str(n), "--no-pager"], timeout=20)[1]
    if not WIN and source in ("journal:all", "journal:kernel"):
        return run(["journalctl", "-n", str(n), "--no-pager"] + (["-k"] if source.endswith("kernel") else []), timeout=20)[1]
    raise PanelError("that log is not available (it may have been rotated away) or is not in the allowlist", 403)


@EXT.route("sources")
def sources(p):
    groups = []
    files = _files()
    panel = [{"value": k, "label": os.path.basename(v)} for k, v in files.items() if k.startswith("panel:")]
    if panel:
        groups.append({"title": "Astra panel", "items": [{"value": i["value"], "label": {"panel.log": "Panel activity", "audit.log": "Audit trail (sign-ins, changes)"}[i["label"]]} for i in panel]})
    rest = [{"value": k, "label": v} for k, v in files.items() if not k.startswith("panel:")]
    if rest:
        groups.append({"title": "Files", "items": rest})
    if WIN:
        groups.append({"title": "Windows Event Log", "items": [{"value": "eventlog:" + c, "label": c} for c in EVENT_LOGS]})
    else:
        groups.append({"title": "Journal", "items": [{"value": "journal:all", "label": "Everything"}, {"value": "journal:kernel", "label": "Kernel"}] + [{"value": "unit:" + u, "label": u} for u in config.cfg["services"]]})
    return {"groups": groups}


@EXT.route("view")
def view(p):
    try:
        n = max(10, min(int(p.get("lines") or 200), 2000))
    except ValueError:
        raise PanelError("lines must be a number")
    return {"text": _read(p.get("source", ""), n)}


@EXT.route("download")
def download(p):
    name = str(p.get("source", "")).replace(":", "-").replace("/", "_").replace("\\", "_") + ".log"
    return Raw(_read(p.get("source", ""), 20000, MAX_DOWNLOAD).encode("utf-8", "replace"), "text/plain; charset=utf-8", filename=name)
