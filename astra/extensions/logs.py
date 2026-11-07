import os
from .. import config, plat
from ..errors import PanelError
from ..shell import NAME, need, run
from . import Extension

WIN = plat.IS_WIN
EXT = Extension("logs", "Logs", "📜", order=70,
                description="Tail log files and the Windows Event Log" if WIN else "Tail log files and service journals")
EVENT_LOGS = ("Application", "System", "Security", "Setup")   # Windows Event Log channels (Security needs Administrator)


def _tail(path, n):
    with open(path, "rb") as f:
        f.seek(max(0, os.path.getsize(path) - 512 * 1024))
        data = f.read()
    return b"\n".join(data.splitlines()[-n:]).decode("utf-8", "replace")


@EXT.route("view")
def view(p):
    try:
        n = max(10, min(int(p.get("lines") or 200), 2000))
    except ValueError:
        raise PanelError("lines must be a number")
    kind, _, target = str(p.get("source", "")).partition(":")
    if kind == "file" and target in config.cfg["log_files"]:
        try:
            return {"text": _tail(target, n)}
        except OSError as e:
            raise PanelError(f"cannot read {target}: {e.strerror}")
    if WIN and kind == "eventlog" and target in EVENT_LOGS:  # newest first, plain text
        rc, out = run(["wevtutil", "qe", target, f"/c:{n}", "/rd:true", "/f:text"], timeout=30)
        if rc:
            raise PanelError(out.strip()[-300:] or "wevtutil failed")
        return {"text": out[:400000]}
    if not WIN and kind == "unit" and target in config.cfg["services"]:
        return {"text": run(["journalctl", "-u", need(target, NAME, "unit"), "-n", str(n), "--no-pager"], timeout=20)[1]}
    raise PanelError("source is not in the allowlist", 403)


def _sections():
    opts = [[f"file:{f}", f] for f in config.cfg["log_files"] if os.path.exists(f)]
    if WIN:
        opts += [[f"eventlog:{c}", f"Windows Event Log: {c}"] for c in EVENT_LOGS]
    else:
        opts += [[f"unit:{u}", f"journal: {u}"] for u in config.cfg["services"]]
    return [{"type": "form", "title": "Log viewer", "route": "view", "method": "GET", "submit": "Show log",
             "fields": [{"name": "source", "label": "Source", "type": "select", "options": opts},
                        {"name": "lines", "label": "Lines", "type": "number", "value": "200"}]}]


EXT.sections = _sections
