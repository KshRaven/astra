import os, signal
from .. import monitor, plat
from ..errors import PanelError
from ..shell import run
from . import Extension

WIN = plat.IS_WIN
EXT = Extension("processes", "Processes", "🧮", order=80,
                description="Top processes by memory; " + ("close or force-kill (taskkill)" if WIN else "send TERM/KILL"))
# Windows processes the system needs to stay alive (killing them blue-screens or locks the machine out)
PROTECTED = {"system", "system idle process", "registry", "smss.exe", "csrss.exe", "wininit.exe",
             "services.exe", "lsass.exe", "winlogon.exe", "memory compression"}


@EXT.route("list")
def list_(p):
    return monitor.processes(50)


def _win_kill(pid, sig):
    names = {x["pid"]: x["name"].lower() for x in monitor.processes(100000)}
    if pid not in names:
        raise PanelError("no such process", 404)
    if pid <= 4 or names[pid] in PROTECTED:
        raise PanelError("refusing: protected system process", 403)
    rc, out = run(["taskkill", "/PID", str(pid)] + (["/F"] if sig == "KILL" else []), timeout=20)
    if rc:
        msg = out.strip()[-300:] or "taskkill failed"
        raise PanelError(msg + ("  (use Kill to force it)" if sig == "TERM" else ""), 403 if "denied" in out.lower() else 400)


@EXT.route("kill", write=True)
def kill(p):
    try:
        pid = int(p.get("pid"))
    except (TypeError, ValueError):
        raise PanelError("invalid pid")
    sig = p.get("signal")
    if sig not in ("TERM", "KILL") or pid <= 1 or pid in (os.getpid(), os.getppid()):
        raise PanelError("refusing: invalid signal or protected process", 403)
    if WIN:
        _win_kill(pid, sig)
        return {"ok": True}
    try:
        os.kill(pid, signal.SIGTERM if sig == "TERM" else signal.SIGKILL)
    except ProcessLookupError:
        raise PanelError("no such process", 404)
    except PermissionError:
        raise PanelError("permission denied", 403)
    return {"ok": True}


_COLS = ([["PID", "pid"], ["Name", "name"], ["Memory", "rss", "bytes"], ["Session", "uid"]] if WIN else
         [["PID", "pid"], ["Name", "name"], ["State", "state"], ["Memory", "rss", "bytes"], ["UID", "uid"]])
EXT.sections = [{"type": "table", "title": "Top 50 by memory", "source": "list", "refresh": 10, "columns": _COLS,
                 "actions": [{"label": "Close" if WIN else "Terminate", "route": "kill", "params": {"pid": "$pid", "signal": "TERM"},
                              "confirm": ("Ask $name ($pid) to close?" if WIN else "Send SIGTERM to $name ($pid)?")},
                             {"label": "Kill", "route": "kill", "params": {"pid": "$pid", "signal": "KILL"},
                              "confirm": "Force-kill $name ($pid)?", "danger": True}]}]
