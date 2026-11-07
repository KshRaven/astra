import json
from ..shell import NAME, need, run
from ..errors import PanelError
from . import Extension

EXT = Extension("docker", "Docker", "🐳", order=55, requires=["docker"], description="Containers and images")


def _lines(args):
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
    cid, op = need(p.get("id"), NAME, "container"), p.get("op")
    cmd = {"start": ["start"], "stop": ["stop"], "restart": ["restart"], "remove": ["rm", "-f"]}.get(op)
    if not cmd:
        raise PanelError("invalid action")
    run(["docker", *cmd, cid], timeout=120, check=True)
    return {"ok": True}


@EXT.route("logs")
def logs(p):
    return {"text": run(["docker", "logs", "--tail", "300", need(p.get("id"), NAME, "container")], timeout=20)[1]}


@EXT.route("rmi", write=True)
def rmi(p):
    run(["docker", "rmi", need(p.get("id"), NAME, "image id")], timeout=60, check=True)
    return {"ok": True}


EXT.sections = [
    {"type": "table", "title": "Containers", "source": "containers", "refresh": 10,
     "columns": [["Name", "name"], ["Image", "image"], ["State", "state", "state"], ["Status", "status"], ["Ports", "ports"]],
     "actions": [{"label": "Start", "route": "action", "params": {"id": "$id", "op": "start"}},
                 {"label": "Stop", "route": "action", "params": {"id": "$id", "op": "stop"}},
                 {"label": "Restart", "route": "action", "params": {"id": "$id", "op": "restart"}},
                 {"label": "Logs", "route": "logs", "method": "GET", "params": {"id": "$id"}},
                 {"label": "Remove", "route": "action", "params": {"id": "$id", "op": "remove"},
                  "confirm": "Force-remove container $name?", "danger": True}]},
    {"type": "table", "title": "Images", "source": "images",
     "columns": [["Repository", "repo"], ["Tag", "tag"], ["Size", "size"]],
     "actions": [{"label": "Delete", "route": "rmi", "params": {"id": "$id"}, "confirm": "Delete image $repo:$tag?", "danger": True}]},
]
