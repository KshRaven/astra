import re
from .. import plat
from ..errors import PanelError
from ..shell import ps, ps_json, run
from . import Extension

WIN = plat.IS_WIN
EXT = Extension("firewall", "Firewall", "🛡", order=50, requires=["netsh"] if WIN else ["ufw"],
                description="Windows Defender Firewall: inbound rules created by Astra" if WIN else "UFW rules")
RULE = re.compile(r"^\[\s*(\d+)\]\s+(.+?)\s{2,}(ALLOW|DENY|REJECT|LIMIT)(?:\s+(?:IN|OUT|FWD))?\s+(.+)$")
# Windows rules are named Astra:<allow|block>-<tcp|udp>-<port>[-<port>] so they can be listed and deleted safely
WIN_RULE = re.compile(r"^Astra:(allow|block)-(tcp|udp)-(\d{1,5}(?:-\d{1,5})?)$")


def _check_port(port):
    if not re.fullmatch(r"\d{1,5}(:\d{1,5})?", port) or any(int(x) > 65535 or int(x) < 1 for x in port.split(":")):
        raise PanelError("port must be 1-65535 or a range like 8000:8100")


def _win_rules():
    rows = ps_json("$r=@(Get-NetFirewallRule -DisplayName 'Astra:*' -ErrorAction SilentlyContinue | "
                   "ForEach-Object { [pscustomobject]@{name=$_.DisplayName} }); ConvertTo-Json -InputObject $r -Compress")
    out = []
    for i, r in enumerate(sorted(rows, key=lambda r: r.get("name", "")), 1):
        m = WIN_RULE.match(r.get("name", ""))
        if m:
            out.append({"num": str(i), "name": r["name"], "to": f"{m[3]}/{m[2]}", "action": m[1], "from": "Any (inbound)"})
    return out


@EXT.route("rules")
def rules(p):
    if WIN:
        return _win_rules()
    rows = []
    for line in run(["ufw", "status", "numbered"])[1].splitlines():
        m = RULE.match(line.strip())
        if m:
            rows.append({"num": m[1], "to": m[2].strip(), "action": m[3], "from": m[4].strip()})
    return rows


@EXT.route("status")
def status(p):
    if WIN:
        txt = ps("Get-NetFirewallProfile | ForEach-Object { '{0}: firewall {1}, inbound default {2}' -f $_.Name, $_.Enabled, $_.DefaultInboundAction }")
        return {"text": txt + f"\nAstra rules: {len(_win_rules())}"}
    return {"text": run(["ufw", "status", "verbose"])[1]}


@EXT.route("add", write=True)
def add(p):
    port, proto, act = str(p.get("port", "")), p.get("proto", "tcp"), p.get("action", "allow")
    _check_port(port)
    if proto not in ("tcp", "udp", "any") or act not in ("allow", "deny", "limit", "reject"):
        raise PanelError("invalid protocol or action")
    if WIN:
        if act == "limit":
            raise PanelError("'limit' is a ufw (Linux) feature; use allow or deny on Windows")
        wact, nport = ("allow" if act == "allow" else "block"), port.replace(":", "-")
        existing = {r["name"] for r in _win_rules()}
        for pr in (("tcp", "udp") if proto == "any" else (proto,)):
            name = f"Astra:{wact}-{pr}-{nport}"
            if name in existing:
                raise PanelError("that rule already exists", 409)
            run(["netsh", "advfirewall", "firewall", "add", "rule", f"name={name}", "dir=in", f"action={wact}",
                 f"protocol={pr.upper()}", f"localport={nport}"], check=True)
        return {"ok": True}
    if proto == "any" and ":" in port:
        raise PanelError("port ranges need tcp or udp")
    run(["ufw", act, port if proto == "any" else f"{port}/{proto}"], check=True)
    return {"ok": True}


@EXT.route("delete", write=True)
def delete(p):
    if WIN:
        name = str(p.get("name", ""))
        if not WIN_RULE.match(name):
            raise PanelError("only rules created by Astra can be deleted here")
        run(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={name}"], check=True)
        return {"ok": True}
    n = str(p.get("num", ""))
    if not n.isdigit():
        raise PanelError("invalid rule number")
    run(["ufw", "--force", "delete", n], check=True)
    return {"ok": True}


@EXT.route("power", write=True)
def power(p):
    if p.get("op") not in ("enable", "disable"):
        raise PanelError("invalid action")
    if WIN:
        run(["netsh", "advfirewall", "set", "allprofiles", "state", "on" if p["op"] == "enable" else "off"], check=True)
    else:
        run(["ufw", "--force", p["op"]], check=True)
    return {"ok": True}


EXT.sections = [
    {"type": "text", "title": "Status", "source": "status"},
    {"type": "table", "title": "Rules" + (" (created by Astra)" if WIN else ""), "source": "rules",
     "columns": [["#", "num"], ["Rule", "name"], ["To", "to"], ["Action", "action"], ["From", "from"]] if WIN else
                [["#", "num"], ["To", "to"], ["Action", "action"], ["From", "from"]],
     "actions": [{"label": "Delete", "route": "delete", "params": {"name": "$name"} if WIN else {"num": "$num"},
                  "confirm": "Delete rule $num ($to)?", "danger": True}]},
    {"type": "form", "title": "Add a rule", "route": "add", "submit": "Add rule",
     "fields": [{"name": "port", "label": "Port or range", "required": True, "placeholder": "443"},
                {"name": "proto", "label": "Protocol", "type": "select", "options": ["tcp", "udp", "any"]},
                {"name": "action", "label": "Action", "type": "select",
                 "options": ["allow", "deny"] if WIN else ["allow", "deny", "limit", "reject"]}]},
    {"type": "form", "title": "Turn firewall on/off (allow your " + ("RDP/SSH" if WIN else "SSH") + " port first!)",
     "route": "power", "submit": "Apply",
     "fields": [{"name": "op", "label": "State", "type": "select", "options": ["enable", "disable"]}]},
]
