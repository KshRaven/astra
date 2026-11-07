import os, signal, time
from .. import monitor, plat
from ..errors import PanelError
from ..shell import ps_json, run
from . import Extension

WIN = plat.IS_WIN
EXT = Extension("processes", "Processes", "cpu", order=80,
                description="Everything running on this server: who owns it, how much CPU and memory it uses, where it lives on disk" + (", and who published it." if WIN else ", and which service started it."))
# Windows processes the system needs to stay alive (killing them blue-screens or locks the machine out)
PROTECTED = {"system", "system idle process", "registry", "smss.exe", "csrss.exe", "wininit.exe",
             "services.exe", "lsass.exe", "winlogon.exe", "memory compression"}
_snap = {"t": 0, "rows": [], "cpu": {}}

_WIN_PS = r"""
$u=@{}; try{ Get-CimInstance Win32_Process | ForEach-Object { $u[[int]$_.ProcessId]=$_ } }catch{}
Get-Process | ForEach-Object {
  $c=$u[[int]$_.Id]; $s=0; try{ $s=[int](([datetime]$_.StartTime).ToUniversalTime()-[datetime]'1970-01-01').TotalSeconds }catch{}
  [pscustomobject]@{ pid=$_.Id; name=$_.ProcessName; publisher=$_.Company; description=$_.Description; version=$_.ProductVersion; path=$_.Path;
    cpu_s=[math]::Round([double]$_.CPU,2); rss=[int64]$_.WorkingSet64; threads=$_.Threads.Count; handles=$_.HandleCount; session=$_.SessionId; start=$s;
    ppid=$(if($c){[int]$c.ParentProcessId}else{0}); cmd=$(if($c){$c.CommandLine}else{''}) } } | ConvertTo-Json -Compress
"""


def _win_rows():
    return [{"pid": int(r["pid"]), "name": (r.get("name") or "") + (".exe" if r.get("path") else ""),
             "publisher": r.get("publisher") or "", "description": r.get("description") or "", "version": r.get("version") or "", "path": r.get("path") or "",
             "cpu_s": float(r.get("cpu_s") or 0), "rss": int(r.get("rss") or 0), "threads": int(r.get("threads") or 0), "handles": int(r.get("handles") or 0),
             "user": "Session %s" % r.get("session"), "start": int(r.get("start") or 0), "ppid": int(r.get("ppid") or 0), "cmd": r.get("cmd") or "", "state": "-"}
            for r in ps_json(_WIN_PS, timeout=40)]


def _unit(pid):
    try:
        for line in open(f"/proc/{pid}/cgroup", errors="replace"):
            for part in reversed(line.strip().split("/")):
                if part.endswith((".service", ".scope")):
                    return part
    except OSError:
        pass
    return ""


def _lin_rows():
    import pwd
    hz, rows = os.sysconf("SC_CLK_TCK"), []
    try:
        boot = [int(l.split()[1]) for l in open("/proc/stat") if l.startswith("btime")][0]
    except (OSError, IndexError):
        boot = 0
    users = {}
    for pid in filter(str.isdigit, os.listdir("/proc")):
        try:
            st = dict((k, v.strip()) for k, _, v in (l.partition(":") for l in open(f"/proc/{pid}/status", errors="replace").read().splitlines()))
            raw = open(f"/proc/{pid}/stat", errors="replace").read()
            f = raw[raw.rindex(")") + 2:].split()   # fields after the (comm) part: [0]=state [1]=ppid ... [11]=utime [12]=stime [19]=starttime
            uid = int(st.get("Uid", "0").split()[0])
            if uid not in users:
                try:
                    users[uid] = pwd.getpwuid(uid).pw_name
                except KeyError:
                    users[uid] = str(uid)
            try:
                cmd = open(f"/proc/{pid}/cmdline", "rb").read().replace(b"\0", b" ").decode("utf-8", "replace").strip()
            except OSError:
                cmd = ""
            try:
                path = os.readlink(f"/proc/{pid}/exe")
            except OSError:
                path = ""
            rows.append({"pid": int(pid), "name": st.get("Name", ""), "publisher": _unit(pid), "description": "", "version": "", "path": path, "cpu_s": (int(f[11]) + int(f[12])) / hz,
                         "rss": int(st.get("VmRSS", "0 kB").split()[0]) * 1024, "threads": int(st.get("Threads", "1")), "handles": 0, "user": users[uid],
                         "start": boot + int(f[19]) // hz if boot else 0, "ppid": int(f[1]), "cmd": cmd or f"[{st.get('Name', '')}]", "state": st.get("State", "?")[:1]})
        except (OSError, ValueError, IndexError):
            continue
    return rows


def _rows():
    now = time.time()
    if now - _snap["t"] < 4 and _snap["rows"]:
        return _snap["rows"]
    rows = _win_rows() if WIN else _lin_rows()
    dt, prev = now - _snap["t"], _snap["cpu"]
    for r in rows:   # CPU % over the time since the last look (one core = 100 %)
        old = prev.get(r["pid"])
        r["cpu"] = round(max(0.0, (r["cpu_s"] - old) / dt * 100), 1) if old is not None and _snap["t"] and dt > 0.5 else 0.0
    _snap.update(t=now, rows=rows, cpu={r["pid"]: r["cpu_s"] for r in rows})
    return rows


@EXT.route("list")
def list_(p):
    return [{k: v for k, v in r.items() if k not in ("cmd", "description", "version")} for r in _rows()]


@EXT.route("summary")
def summary(p):
    rows = _rows()
    top_c, top_m = max(rows, key=lambda r: r["cpu"], default=None), max(rows, key=lambda r: r["rss"], default=None)
    from ..ui_fmt import human
    return {"items": [{"k": "Processes", "v": len(rows), "s": f"{sum(r['threads'] for r in rows)} threads", "icon": "cpu"},
                      {"k": "Memory in use", "v": human(sum(r["rss"] for r in rows)), "s": "sum of working sets" if WIN else "sum of resident sets", "icon": "activity"},
                      {"k": "Busiest (CPU)", "v": top_c["name"] if top_c else "-", "s": f"{top_c['cpu']:.1f} %" if top_c else "", "icon": "zap"},
                      {"k": "Biggest (memory)", "v": top_m["name"] if top_m else "-", "s": human(top_m["rss"]) if top_m else "", "icon": "hard-drive"}]}


@EXT.route("info")
def info(p):
    try:
        pid = int(p.get("pid"))
    except (TypeError, ValueError):
        raise PanelError("invalid pid")
    rows = _rows()
    r = next((x for x in rows if x["pid"] == pid), None)
    if not r:
        raise PanelError("that process has already ended", 404)
    parent = next((x["name"] for x in rows if x["pid"] == r["ppid"]), "")
    pairs = [["Name", r["name"]], ["PID", str(pid)], ["Parent", f"{parent} ({r['ppid']})" if parent else str(r["ppid"])], ["User / session", r["user"]]]
    pairs += [["Publisher", r["publisher"] or "unknown (needs Administrator, or a system process)"], ["Description", r["description"]], ["Version", r["version"]]] if WIN else [["Service", r["publisher"] or "not started by a service"]]
    pairs += [["Program", r["path"] or "not readable"], ["Command line", r["cmd"] or "not readable"], ["Memory", f"{r['rss'] / 1048576:.1f} MB"], ["CPU now", f"{r['cpu']:.1f} %"],
              ["CPU time used", f"{r['cpu_s']:.1f} s"], ["Threads", str(r["threads"])]]
    if WIN:
        pairs.append(["Handles", str(r["handles"])])
    if r["start"]:
        pairs.append(["Started", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["start"]))])
    return {"title": f"{r['name']} ({pid})", "kv": [x for x in pairs if x[1] != ""]}


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
    _snap["t"] = 0
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


_COLS = [["PID", "pid"], ["Name", "name"], ["Publisher" if WIN else "Service", "publisher"], ["User" if not WIN else "Session", "user"], ["CPU", "cpu", "pct"],
         ["Memory", "rss", "bytes"], ["Threads", "threads", "num"], ["Started", "start", "ago"]]
EXT.sections = [
    {"type": "stats", "source": "summary", "refresh": 15},
    {"type": "table", "title": "All processes", "source": "list", "refresh": 15, "sort": ["rss", "desc"], "limit": 100, "search": True, "searchHint": "Filter by name, publisher, user…", "columns": _COLS,
     "actions": [{"label": "Details", "route": "info", "method": "GET", "params": {"pid": "$pid"}, "icon": "info", "quiet": True},
                 {"label": "Close" if WIN else "Terminate", "route": "kill", "params": {"pid": "$pid", "signal": "TERM"}, "more": True,
                  "confirm": ("Ask $name ($pid) to close?" if WIN else "Send SIGTERM to $name ($pid)?")},
                 {"label": "Kill", "route": "kill", "params": {"pid": "$pid", "signal": "KILL"}, "confirm": "Force-kill $name ($pid)? Unsaved work in it is lost.", "danger": True}]},
]
