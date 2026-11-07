import re, time
from .. import config, plat
from ..errors import PanelError
from ..shell import NAME, WIN_SERVICE, need, run
from . import Extension
from .. import catalog, jobs

WIN = plat.IS_WIN
EXT = Extension("services", "Services", "layers", order=10, group="Server",
                description="Install, update and control the software this server runs: web servers, databases, languages and tools.")
OPS = ("start", "stop", "restart", "enable", "disable") if WIN else ("start", "stop", "restart", "reload", "enable", "disable")
# `sc` prints localised labels but the state/start-type keywords stay English, so match on those.
_STATE = re.compile(r"\b(STOPPED|START_PENDING|STOP_PENDING|RUNNING|CONTINUE_PENDING|PAUSE_PENDING|PAUSED)\b")
_START = re.compile(r"\b(AUTO_START|DEMAND_START|DISABLED|BOOT_START|SYSTEM_START)\b")
_STATE_NAME = {"RUNNING": "active", "STOPPED": "inactive", "START_PENDING": "starting", "STOP_PENDING": "stopping",
               "CONTINUE_PENDING": "starting", "PAUSE_PENDING": "stopping", "PAUSED": "paused"}
_START_NAME = {"AUTO_START": "enabled", "BOOT_START": "enabled", "SYSTEM_START": "enabled",
               "DEMAND_START": "manual", "DISABLED": "disabled"}


def _name(p):
    return need(p.get("name"), WIN_SERVICE if WIN else NAME, "service name")


def _catalog_units():
    return {u for e in catalog.CATALOG for u in e["units"]}


def _allowed(p):
    n = _name(p)
    if n not in config.cfg["services"] and n not in _catalog_units():
        raise PanelError("service is not in the panel allowlist", 403)
    return n


def _win_state(n):
    rc, out = run(["sc", "query", n])
    if rc == 1060:
        return "not-installed"
    m = _STATE.search(out)
    return _STATE_NAME[m[1]] if m else "unknown"


def _win_enabled(n):
    rc, out = run(["sc", "qc", n])
    m = _START.search(out)
    return _START_NAME[m[1]] if m else "unknown"


def _sc(args, ok=(0,)):
    rc, out = run(["sc", *args], timeout=60)
    if rc not in ok:
        raise PanelError(out.strip()[-400:] or "sc failed", 400)


def _win_action(n, op):
    if op == "start":
        _sc(["start", n], ok=(0, 1056))            # 1056: already running
    elif op == "stop":
        _sc(["stop", n], ok=(0, 1062))             # 1062: not started
    elif op == "restart":
        _sc(["stop", n], ok=(0, 1062))
        for _ in range(60):                        # wait up to 30 s for the service to stop
            if _win_state(n) in ("inactive", "not-installed"):
                break
            time.sleep(0.5)
        else:
            raise PanelError("service did not stop within 30 seconds", 504)
        _sc(["start", n])
    elif op in ("enable", "disable"):
        _sc(["config", n, "start=", "auto" if op == "enable" else "disabled"])
    else:
        raise PanelError("reload is not supported for Windows services; use restart")


@EXT.route("list")
def list_(p):
    if not WIN and not plat.has_systemd():
        return []
    if WIN:
        return [{"name": n, "state": _win_state(n), "enabled": _win_enabled(n)} for n in config.cfg["services"]]
    return [{"name": n, "state": run(["systemctl", "is-active", n])[1].strip() or "unknown",
             "enabled": run(["systemctl", "is-enabled", n])[1].strip() or "unknown"}
            for n in config.cfg["services"]]


@EXT.route("catalog")
def catalog_(p):
    return catalog.listing()


@EXT.route("detail")
def detail_(p):
    return catalog.detail(str(p.get("id", "")))


@EXT.route("installed")
def installed_(p):
    rows = [r for r in catalog.listing() if r["installed"]]
    return [{"id": r["id"], "name": r["title"], "category": r["category"], "version": "", "state": r["state"], "enabled": r["enabled"],
             "ports": ", ".join(map(str, r["ports"])), "unit": r["units"][0] if r["units"] else ""} for r in rows]


@EXT.route("install", write=True)
def install_(p):
    title, steps, env = catalog.install_plan(str(p.get("id", "")))
    j = jobs.start(title, steps, kind="install", env=env, ext="services")
    return {"job": j.id, "title": title}


@EXT.route("uninstall", write=True)
def uninstall_(p):
    title, steps, env = catalog.uninstall_plan(str(p.get("id", "")))
    j = jobs.start(title, steps, kind="install", env=env, ext="services")
    return {"job": j.id, "title": title}


@EXT.route("action", write=True)
def action(p):
    n, op = _allowed(p), p.get("op")
    if op not in ("start", "stop", "restart", "reload", "enable", "disable"):
        raise PanelError("invalid action")
    if WIN:
        _win_action(n, op)
    else:
        run(["systemctl", op, n], timeout=60, check=True)
    return {"ok": True}


@EXT.route("add", write=True)
def add(p):
    n = _name(p)
    if WIN:
        if run(["sc", "qc", n])[0] != 0:
            raise PanelError("Windows does not know that service (use the service name, not the display name)", 404)
    elif run(["systemctl", "cat", n])[0] != 0:
        raise PanelError("systemd does not know that unit", 404)
    if n not in config.cfg["services"]:
        config.cfg["services"].append(n)
        config.save()
    return {"ok": True}


@EXT.route("remove", write=True)
def remove(p):
    n = _name(p)
    if n in config.cfg["services"]:
        config.cfg["services"].remove(n)
        config.save()
    return {"ok": True}


_ACTIONS = [{"label": "Start", "route": "action", "params": {"name": "$name", "op": "start"}, "if": {"state": ["inactive", "failed", "unknown"]}},
            {"label": "Restart", "route": "action", "params": {"name": "$name", "op": "restart"}, "if": {"state": ["active"]}},
            {"label": "Stop", "route": "action", "params": {"name": "$name", "op": "stop"},
             "confirm": "Stop $name? Anything that depends on it stops working.", "danger": True, "if": {"state": ["active"]}},
            {"label": "Start at boot", "route": "action", "params": {"name": "$name", "op": "enable"}, "more": True, "ifnot": {"enabled": ["enabled"]}},
            {"label": "Do not start at boot", "route": "action", "params": {"name": "$name", "op": "disable"}, "more": True, "if": {"enabled": ["enabled"]}},
            {"label": "Remove from this list", "route": "remove", "params": {"name": "$name"}, "danger": True,
             "confirm": "Remove $name from this list? (the service itself is untouched)"}]
if not WIN:  # systemd can reload a unit's configuration without a restart; Windows has no equivalent
    _ACTIONS.insert(2, {"label": "Reload config", "route": "action", "params": {"name": "$name", "op": "reload"}, "more": True, "if": {"state": ["active"]}})

_INST_ACTIONS = [{"label": "Start", "route": "action", "params": {"name": "$unit", "op": "start"}, "if": {"state": ["inactive", "failed"]}},
                 {"label": "Restart", "route": "action", "params": {"name": "$unit", "op": "restart"}, "if": {"state": ["active"]}},
                 {"label": "Stop", "route": "action", "params": {"name": "$unit", "op": "stop"}, "danger": True, "confirm": "Stop $name?", "if": {"state": ["active"]}},
                 {"label": "Details", "route": "detail", "method": "GET", "params": {"id": "$id"}, "more": True, "quiet": True}]

EXT.sections = [
    {"type": "help", "title": "What is this page?", "text": "Everything installed on this server that runs in the background (a web server, a database, a cache...) is a service. "
        "This page shows what is running, lets you start or stop it, and has a library of popular software you can install in one click.",
     "steps": [["Running now:", "see which installed services are up, and start, restart or stop them."],
               ["Software library:", "read what each program is for and whether you need it, then press Install. A console shows the progress."],
               ["Other services:", "watch any other service on the machine by adding its name."]],
     "example": {"title": "Example", "text": "Want to host a website? Open Software library, install Nginx, then go to the Websites tab to add your domain."}},
    {"type": "tabs", "tabs": [
        {"id": "running", "title": "Running now", "icon": "activity", "sections": [
            {"type": "table", "title": "Installed software", "source": "installed", "refresh": 10, "search": False,
             "columns": [["Software", "name"], ["Type", "category"], ["State", "state", "state"], ["At boot", "enabled", "state"], ["Ports", "ports"]],
             "actions": _INST_ACTIONS,
             "empty": {"icon": "package", "title": "Nothing installed through the panel yet",
                       "text": "Open the Software library to see what you can install, with a short explanation of each.",
                       "actions": [{"label": "Browse the library", "go": "services", "sub": "library", "primary": True, "icon": "package"}]}}]},
        {"id": "library", "title": "Software library", "icon": "package", "sections": [{"type": "catalog", "source": "catalog", "detail": "detail", "install": "install", "uninstall": "uninstall"}]},
        {"id": "other", "title": "Other services", "icon": "list", "sections": [
            {"type": "table", "title": "Watched services", "desc": "Services you added by name. The panel can start, stop and restart these.", "source": "list", "refresh": 10,
             "columns": [["Service", "name"], ["State", "state", "state"], ["At boot", "enabled", "state"]], "actions": _ACTIONS,
             "empty": {"icon": "list", "title": "No extra services watched", "text": "Add a service name below, for example redis-server on Linux or MSSQLSERVER on Windows."}},
            {"type": "form", "title": "Watch another service", "route": "add", "submit": "Add service", "icon": "plus",
             "fields": [{"name": "name", "label": "Service name (e.g. MSSQLSERVER)" if WIN else "Unit name (e.g. redis-server)", "required": True,
                         "help": "Use the service name, not the display name." if WIN else "As shown by systemctl list-units."}]}]}]},
]
