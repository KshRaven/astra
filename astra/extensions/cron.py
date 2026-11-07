import json, os, re, uuid
from pathlib import Path
from .. import config, plat
from ..errors import PanelError
from ..shell import NAME, need, run
from . import Extension

WIN = plat.IS_WIN
EXT = Extension("cron", "Tasks" if WIN else "Cron", "⏰", order=40,
                description=("Scheduled tasks, created in Windows Task Scheduler (folder \\Astra) and run as SYSTEM" if WIN
                             else "Scheduled tasks, written to a managed /etc/cron.d file"))
CRON_FILE = Path(os.environ.get("ASTRA_CRON_FILE", "/etc/cron.d/astra"))   # Linux only
FIELD = re.compile(r"^[0-9*/,\-]+$")
MACROS = {"@hourly", "@daily", "@weekly", "@monthly", "@yearly", "@reboot"}
DAYS = ["SUN", "MON", "TUE", "WED", "THU", "FRI", "SAT"]
WIN_CMD_MAX = 200   # Task Scheduler limits the /tr string to 261 characters; leave room for `cmd.exe /c ""`
WIN_FORMS = ("supported schedules on Windows: */N * * * * (every N minutes), M * * * * (hourly), M H * * * (daily), "
             "M H * * D (weekly, D=0-6), M H DOM * * (monthly), @hourly @daily @weekly @monthly @yearly @reboot")


def _store():
    return config.HOME / "cron.json"


def _load():
    try:
        return json.loads(_store().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _win_args(sched):
    """Translate the supported cron forms into schtasks /sc arguments."""
    macro = {"@reboot": ["/sc", "onstart"], "@hourly": ["/sc", "hourly", "/mo", "1", "/st", "00:00"],
             "@daily": ["/sc", "daily", "/st", "00:00"], "@weekly": ["/sc", "weekly", "/d", "SUN", "/st", "00:00"],
             "@monthly": ["/sc", "monthly", "/d", "1", "/st", "00:00"],
             "@yearly": ["/sc", "monthly", "/mo", "12", "/d", "1", "/st", "00:00"]}
    if sched in macro:
        return macro[sched]
    m, h, dom, mon, dow = sched.split()
    num = lambda v, hi: v.isdigit() and 0 <= int(v) <= hi
    if mon == "*":
        if re.fullmatch(r"\*/\d{1,4}", m) and (h, dom, dow) == ("*", "*", "*") and 1 <= int(m[2:]) <= 1439:
            return ["/sc", "minute", "/mo", m[2:]]
        if num(m, 59):
            if (h, dom, dow) == ("*", "*", "*"):
                return ["/sc", "hourly", "/mo", "1", "/st", f"00:{int(m):02d}"]
            if num(h, 23):
                at = ["/st", f"{int(h):02d}:{int(m):02d}"]
                if (dom, dow) == ("*", "*"):
                    return ["/sc", "daily", *at]
                if dom == "*" and num(dow, 7):
                    return ["/sc", "weekly", "/d", DAYS[int(dow) % 7], *at]
                if dow == "*" and dom.isdigit() and 1 <= int(dom) <= 31:
                    return ["/sc", "monthly", "/d", dom, *at]
    raise PanelError("this schedule cannot be expressed in Task Scheduler; " + WIN_FORMS)


def _task(j):
    return "Astra\\" + j["id"]


def _win_create(j):
    run(["schtasks", "/create", "/f", "/tn", _task(j), "/ru", "SYSTEM", "/rl", "HIGHEST",
         "/tr", f'cmd.exe /c "{j["command"]}"', *_win_args(j["schedule"])], timeout=30, check=True)


def _save(jobs):
    old = _load()
    if WIN:
        before = {j["id"]: j for j in old}
        for j in jobs:                                   # create/refresh first, so a failure leaves the old state intact
            if j["enabled"] and before.get(j["id"]) != j:
                _win_create(j)
        keep = {j["id"] for j in jobs if j["enabled"]}
        for j in old:
            if j["id"] not in keep:
                run(["schtasks", "/delete", "/tn", _task(j), "/f"])
    else:
        user = need(config.cfg["cron_user"], NAME, "cron_user")
        lines = ["# managed by astra - manual edits are overwritten", "SHELL=/bin/sh",
                 "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"]
        lines += [f"{j['schedule']} {user} {j['command'].replace('%', chr(92) + '%')}" for j in jobs if j["enabled"]]
        try:
            CRON_FILE.write_text("\n".join(lines) + "\n")
            os.chmod(CRON_FILE, 0o644)
        except OSError as e:
            raise PanelError(f"cannot write {CRON_FILE}: {e}", 500)
    config.HOME.mkdir(parents=True, exist_ok=True)
    _store().write_text(json.dumps(jobs, indent=1), encoding="utf-8")


def _line(v, what, limit):
    v = str(v or "").strip()
    if not v or len(v) > limit or any(ch in v for ch in "\r\n\0"):
        raise PanelError(f"invalid {what}")
    return v


def _find(jobs, p):
    for j in jobs:
        if j["id"] == p.get("id"):
            return j
    raise PanelError("unknown job", 404)


@EXT.route("list")
def list_(p):
    return [{**j, "state": "enabled" if j["enabled"] else "disabled"} for j in _load()]


@EXT.route("add", write=True)
def add(p):
    sched = _line(p.get("schedule"), "schedule", 60)
    parts = sched.split()
    if not (sched in MACROS or (len(parts) == 5 and all(FIELD.match(x) for x in parts))):
        raise PanelError("schedule must be 5 cron fields (e.g. */5 * * * *) or @daily etc.")
    command = _line(p.get("command"), "command", WIN_CMD_MAX if WIN else 500)
    if WIN:
        _win_args(sched)   # reject schedules Task Scheduler cannot do before anything is stored
    jobs = _load()
    jobs.append({"id": uuid.uuid4().hex[:8], "name": _line(p.get("name"), "name", 60), "schedule": sched,
                 "command": command, "enabled": True})
    _save(jobs)
    return {"ok": True}


@EXT.route("toggle", write=True)
def toggle(p):
    jobs = _load()
    j = _find(jobs, p)
    j["enabled"] = not j["enabled"]
    _save(jobs)
    return {"ok": True}


@EXT.route("delete", write=True)
def delete(p):
    jobs = _load()
    _save([j for j in jobs if j is not _find(jobs, p)])
    return {"ok": True}


@EXT.route("run", write=True)
def run_now(p):
    j = _find(_load(), p)
    rc, out = run([*plat.SHELL_CMD, j["command"]], timeout=60)
    return {"text": f"exit code {rc}\n{out[-4000:]}"}


EXT.sections = [
    {"type": "table", "title": "Jobs", "source": "list",
     "columns": [["Name", "name"], ["Schedule", "schedule"], ["Command", "command"], ["State", "state", "state"]],
     "actions": [{"label": "Run now", "route": "run", "params": {"id": "$id"}, "confirm": "Run '$name' now?"},
                 {"label": "Enable/disable", "route": "toggle", "params": {"id": "$id"}},
                 {"label": "Delete", "route": "delete", "params": {"id": "$id"}, "confirm": "Delete job '$name'?", "danger": True}]},
    {"type": "form", "title": "Add a job", "route": "add", "submit": "Add job",
     "fields": [{"name": "name", "label": "Name", "required": True},
                {"name": "schedule", "label": "Schedule (cron syntax" + ("; Windows supports common forms only)" if WIN else ")"),
                 "required": True, "placeholder": "*/15 * * * *  or  @daily"},
                {"name": "command", "label": "Command (runs as SYSTEM)" if WIN else "Command (runs as the configured cron user)",
                 "required": True}]},
]
