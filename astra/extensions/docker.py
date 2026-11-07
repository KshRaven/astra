import json, os, re, subprocess, time
from .. import catalog, jobs, plat
from ..shell import NAME, need, run
from ..errors import PanelError
from . import Extension

WIN = plat.IS_WIN
EXT = Extension("docker", "Docker", "box", order=55, description="Run apps in containers. Shows whether Docker is installed and running, and lets you install, start or remove it.")
_cache = {"t": 0, "v": None}


def _cli():
    return plat.which("docker")


def _state(force=False):
    """(state, detail): state is missing | stopped | ready. Cached a few seconds; a stopped engine never raises, it is a normal state."""
    if not force and _cache["v"] and time.time() - _cache["t"] < 4:
        return _cache["v"]
    if not _cli():
        v = ("missing", "")
    else:
        try:
            rc, out = run(["docker", "version", "--format", "{{.Server.Version}}"], timeout=8)
        except PanelError as e:
            rc, out = 1, str(e)
        v = ("ready", out.strip()) if rc == 0 and out.strip() else ("stopped", out.strip()[-600:])
    _cache.update(t=time.time(), v=v)
    return v


def _need_ready():
    st, detail = _state()
    if st != "ready":
        raise PanelError("Docker is not installed" if st == "missing" else "Docker is installed but its engine is not running. Start it from this page.", 503)


def _desktop_exe():
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramW6432")):
        if base:
            f = os.path.join(base, "Docker", "Docker", "Docker Desktop.exe")
            if os.path.isfile(f):
                return f
    return None


@EXT.route("status")
def status(p):
    st, detail = _state(True)
    help_ = {"type": "help", "title": "What is Docker?", "text": "Docker runs apps in sealed boxes called containers, so a database, a CMS or a bot runs the same everywhere without touching the rest of the server. "
             "You pull an image (the template), start a container from it, and map a port so the website or other apps can reach it.",
             "example": {"title": "Example", "text": "Run a quick web page on port 8081:", "code": "docker run -d --name hello -p 8081:80 nginx"}}
    if st == "ready":
        return {"ok": True, "version": detail}
    if st == "missing":
        acts = [{"label": "Install Docker", "route": "install", "primary": True, "icon": "download", "confirm": "Install Docker on this server? Progress shows in the console. " + ("On Windows this installs Docker Desktop and may need a restart." if WIN else "")},
                {"label": "Open the software library", "go": "services", "sub": "library"}]
        return {"ok": False, "sections": [help_, {"type": "notice", "level": "warn", "title": "Docker is not installed", "text": "Install it to run containers. Nothing else on this page works until then.", "actions": acts}]}
    low = detail.lower()
    why = ("The Docker engine is not answering. " + ("Docker Desktop is probably closed or still starting; it needs to be running (and WSL 2 or Hyper-V enabled)." if WIN else "The docker service is stopped.")
           if any(k in low for k in ("pipe", "cannot connect", "daemon", "docker.sock", "connect")) else "Docker did not answer: " + (detail or "no output"))
    acts = [{"label": "Start Docker", "route": "start_engine", "primary": True, "icon": "play"}, {"label": "Check again", "route": "recheck", "icon": "refresh", "quiet": True},
            {"label": "Uninstall Docker", "route": "uninstall", "icon": "trash", "danger": True, "confirm": "Remove Docker from this server? Containers and images may be deleted."}]
    return {"ok": False, "sections": [help_, {"type": "notice", "level": "warn", "title": "Docker is installed but not running", "text": why, "actions": acts},
                                      {"type": "text", "title": "Technical details", "desc": "What Docker reported, in case you need to search for it.", "source": "details"}]}


@EXT.route("details")
def details(p):
    return {"text": _state()[1] or "(no output)"}


@EXT.route("recheck", write=True)
def recheck(p):
    st = _state(True)[0]
    return {"message": "Docker is running." if st == "ready" else "Still not running."}


@EXT.route("install", write=True)
def install(p):
    title, steps, env = catalog.install_plan("docker")
    return {"job": jobs.start(title, steps, kind="install", env=env, ext="docker").id, "title": title}


@EXT.route("uninstall", write=True)
def uninstall(p):
    title, steps, env = catalog.uninstall_plan("docker")
    return {"job": jobs.start(title, steps, kind="install", env=env, ext="docker").id, "title": title}


@EXT.route("start_engine", write=True)
def start_engine(p):
    if WIN:
        exe = _desktop_exe()
        if exe:
            subprocess.Popen([exe], creationflags=plat.NO_WINDOW | 0x00000008, close_fds=True)   # DETACHED_PROCESS
            msg = "Docker Desktop is starting. It can take a minute; this page updates by itself."
        else:
            rc, out = run(["sc", "start", "docker"], timeout=30)   # Docker Engine installed as a plain Windows service
            msg = "Start requested." if rc == 0 else "Could not start Docker. Open Docker Desktop yourself once and accept its terms. " + out.strip()[-200:]
    else:
        run(["systemctl", "enable", "--now", "docker"], timeout=60, check=True)
        msg = "Docker started."
    _cache["v"] = None
    return {"message": msg}


def _lines(args):
    _need_ready()
    out = []
    for line in run(args, check=True)[1].splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out

@EXT.route("containers")
def containers(p):
    return [{"id": r["ID"], "name": r["Names"], "image": r["Image"], "state": r["State"],
             "status": r["Status"], "ports": r.get("Ports", "")}
            for r in _lines(["docker", "ps", "-a", "--format", "{{json .}}"])]


@EXT.route("images")
def images(p):
    return [{"id": r["ID"], "repo": r["Repository"], "tag": r["Tag"], "size": r["Size"]}
            for r in _lines(["docker", "images", "--format", "{{json .}}"])]


@EXT.route("action", write=True)
def action(p):
    _need_ready()
    cid, op = need(p.get("id"), NAME, "container"), p.get("op")
    cmd = {"start": ["start"], "stop": ["stop"], "restart": ["restart"], "remove": ["rm", "-f"]}.get(op)
    if not cmd:
        raise PanelError("invalid action")
    run(["docker", *cmd, cid], timeout=120, check=True)
    return {"ok": True}


@EXT.route("logs")
def logs(p):
    _need_ready()
    return {"text": run(["docker", "logs", "--tail", "300", need(p.get("id"), NAME, "container")], timeout=20)[1]}


@EXT.route("rmi", write=True)
def rmi(p):
    _need_ready()
    run(["docker", "rmi", need(p.get("id"), NAME, "image id")], timeout=60, check=True)
    return {"ok": True}


@EXT.route("pull", write=True)
def pull(p):
    _need_ready()
    img = str(p.get("image", "")).strip()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/:@-]{0,199}", img):
        raise PanelError("invalid image name (e.g. nginx or nginx:alpine)")
    return {"job": jobs.start("Pull " + img, [["docker", "pull", img]], kind="task", ext="docker").id}


EXT.sections = [{"type": "gate", "source": "status", "refresh": 8, "sections": [
    {"type": "table", "title": "Containers", "source": "containers", "refresh": 10,
     "columns": [["Name", "name"], ["Image", "image"], ["State", "state", "state"], ["Status", "status"], ["Ports", "ports"]],
     "actions": [{"label": "Start", "route": "action", "params": {"id": "$id", "op": "start"}, "ifnot": {"state": ["running"]}},
                 {"label": "Stop", "route": "action", "params": {"id": "$id", "op": "stop"}, "if": {"state": ["running"]}},
                 {"label": "Restart", "route": "action", "params": {"id": "$id", "op": "restart"}, "more": True},
                 {"label": "Logs", "route": "logs", "method": "GET", "params": {"id": "$id"}, "more": True},
                 {"label": "Remove", "route": "action", "params": {"id": "$id", "op": "remove"}, "confirm": "Force-remove container $name?", "danger": True}],
     "empty": {"icon": "box", "title": "No containers yet", "text": "Pull an image below, then start a container from it on the command line (console button, top right)."}},
    {"type": "table", "title": "Images", "source": "images", "buttons": [{"label": "Pull image", "route": "pull", "icon": "download", "primary": True, "form": [{"name": "image", "label": "Image", "placeholder": "nginx:alpine", "required": True}]}],
     "columns": [["Repository", "repo"], ["Tag", "tag"], ["Size", "size"]],
     "actions": [{"label": "Delete", "route": "rmi", "params": {"id": "$id"}, "confirm": "Delete image $repo:$tag?", "danger": True}],
     "empty": {"icon": "layers", "title": "No images yet", "text": "Use Pull image to download one."}}]}]
