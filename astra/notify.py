"""Notification centre: a short, categorised list of things that need you, instead of a firehose.

Rules that keep it useful:
  * repeats are merged into one item with a counter (1000 failed logins = one line, not 1000)
  * every item has a category (security, system, services, tasks, websites, panel) and a severity
    (critical, warning, info, ok); the GUI shows "needs attention" first and folds the rest
  * a problem that fixes itself (a service that comes back) is resolved in place
  * the list is capped and old items expire
Stored in <config dir>/notifications.json. Standard library only.
"""
import json, os, threading, time
from . import config

CATS = {"security": "Security", "system": "System", "services": "Services", "tasks": "Installs & tasks",
        "websites": "Websites", "backups": "Backups", "panel": "Panel"}
RANK = {"critical": 3, "warning": 2, "info": 1, "ok": 0}
MERGE_WINDOW = 6 * 3600
MAX_ITEMS = 300
EXPIRE = {"critical": 90 * 86400, "warning": 60 * 86400, "info": 14 * 86400, "ok": 7 * 86400}
_lock = threading.RLock()
_data = None


def _file():
    return config.HOME / "notifications.json"


def _load():
    global _data
    if _data is None:
        try:
            _data = json.loads(_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _data = {}
        _data.setdefault("items", [])
        _data.setdefault("seq", 0)
        _data.setdefault("known_ips", [])
        _data.setdefault("last_visit", 0)
        _data.setdefault("prev_visit", 0)
    return _data


def _save():
    d = _load()
    try:
        config.HOME.mkdir(parents=True, exist_ok=True)
        tmp = _file().with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, _file())
    except OSError:
        pass  # notifications are a convenience: never break the action that triggered one


def _title(tpl, n):
    if "{n}" in tpl:
        return tpl.replace("{n}", str(n))
    return tpl + (f" (x{n})" if n > 1 else "")


def _trim(d):
    now = time.time()
    d["items"] = [i for i in d["items"] if now - i["ts"] < EXPIRE.get(i["sev"], 14 * 86400)]
    if len(d["items"]) > MAX_ITEMS:  # drop the least important, oldest first
        d["items"].sort(key=lambda i: (RANK[i["sev"]] + (2 if not i["read"] else 0), i["ts"]))
        d["items"] = d["items"][len(d["items"]) - MAX_ITEMS:]


def add(cat, sev, title, detail="", key=None, escalate=()):
    """Add or merge a notification. `title` may contain {n} for the repeat counter.
    `escalate`: ((count, severity), ...) raises the severity once the counter reaches count."""
    with _lock:
        d = _load()
        now = time.time()
        item = next((i for i in d["items"] if key and i.get("key") == key and now - i["ts"] < MERGE_WINDOW and not i.get("resolved")), None)
        if item:
            item["n"] += 1
            item["ts"] = now
            item["tpl"] = title
            item["detail"] = detail or item["detail"]
        else:
            d["seq"] += 1
            item = {"id": d["seq"], "ts": now, "first": now, "cat": cat if cat in CATS else "system", "sev": sev,
                    "tpl": title, "detail": detail, "key": key, "n": 1, "read": False}
            d["items"].append(item)
        new_sev = sev
        for count, s in escalate:
            if item["n"] >= count and RANK[s] > RANK[new_sev]:
                new_sev = s
        if RANK[new_sev] > RANK[item["sev"]]:
            item["read"] = False
        item["sev"] = new_sev
        item["title"] = _title(item["tpl"], item["n"])
        _trim(d)
        _save()
        return item["id"]


def resolve(key, title):
    """A problem went away: update its item in place, mark it read."""
    with _lock:
        d = _load()
        for i in d["items"]:
            if i.get("key") == key and not i.get("resolved") and RANK[i["sev"]] >= 2:
                i.update(sev="ok", title=title, tpl=title, resolved=True, read=True, ts=time.time())
                _save()
                return True
    return False


def _view(i):
    return {k: i[k] for k in ("id", "ts", "cat", "sev", "title", "detail", "n", "read")} | {"first": i.get("first", i["ts"])}


def feed(limit=60, cat=None, unread=False):
    with _lock:
        d = _load()
        items = [i for i in d["items"] if (not cat or i["cat"] == cat) and (not unread or not i["read"])]
        items.sort(key=lambda i: i["ts"], reverse=True)
        attention = [i for i in d["items"] if not i["read"] and RANK[i["sev"]] >= 2]
        by_cat = {}
        for i in d["items"]:
            if not i["read"]:
                by_cat[i["cat"]] = by_cat.get(i["cat"], 0) + 1
        return {"items": [_view(i) for i in items[:limit]], "total": len(items), "attention": len(attention),
                "critical": sum(1 for i in attention if i["sev"] == "critical"),
                "unread": sum(1 for i in d["items"] if not i["read"]), "by_cat": by_cat,
                "cats": CATS, "away": away()}


def mark_read(ids=None):
    with _lock:
        d = _load()
        for i in d["items"]:
            if ids is None or i["id"] in ids:
                i["read"] = True
        _save()


def clear(read_only=True):
    with _lock:
        d = _load()
        d["items"] = [i for i in d["items"] if not i["read"]] if read_only else []
        _save()


# ---------- "while you were away"
def visit(ip):
    """Called at every successful sign-in. Remembers the previous visit so the dashboard can summarise what happened since."""
    with _lock:
        d = _load()
        d["prev_visit"], d["last_visit"] = d["last_visit"], time.time()
        _save()


def away():
    d = _load()
    since = d.get("prev_visit") or 0
    if not since:
        return {"since": 0, "lines": []}
    counts = {}
    for i in d["items"]:
        if i["ts"] > since and i["sev"] != "ok" or (i["ts"] > since and i.get("resolved")):
            counts.setdefault(i["cat"], []).append(i)
    lines = []
    for cat, items in sorted(counts.items(), key=lambda kv: -max(RANK[i["sev"]] for i in kv[1])):
        worst = max(items, key=lambda i: RANK[i["sev"]])
        total = sum(i["n"] for i in items)
        lines.append({"cat": cat, "sev": worst["sev"], "text": f"{CATS[cat]}: {total} event{'s' if total != 1 else ''}, most serious: {worst['title']}"})
    return {"since": int(since), "lines": lines}


# ---------- audit hook (called from audit.log, so CLI actions and web actions are covered alike)
def from_audit(event, kw):
    ip = kw.get("ip", "")
    if event == "login":
        with _lock:
            d = _load()
            known = d["known_ips"]
            new = ip not in known and bool(known) and ip not in ("cli", "")
            if ip and ip not in known and ip != "cli":
                known.append(ip)
                del known[:-50]
                _save()
        if new:
            add("security", "warning", f"Sign-in from a new address: {ip}", "If this was not you, change the password in Settings.", key=f"newip:{ip}")
        else:
            add("security", "info", f"Signed in from {ip or 'this machine'}", key=f"login:{ip}")
    elif event == "auth_fail":
        add("security", "info", f"{{n}} failed sign-in attempt(s) from {ip}", "Repeated failures are blocked for a few minutes.",
            key=f"authfail:{ip}", escalate=((3, "warning"), (10, "critical")))
    elif event == "account_changed":
        add("security", "warning", "Admin username or password was changed", f"from {ip}", key="acct")
    elif event == "mfa_change":
        add("security", "info", "Two-step sign-in settings changed", f"from {ip}", key="mfa")
    elif event == "privacy_delete":
        add("security", "warning", "Audit log and MFA data were deleted", key="privacy")
    elif event == "alert":
        m, v, lim = kw.get("metric", "?"), kw.get("value", 0), kw.get("limit", 0)
        add("system", "critical" if v >= 97 else "warning", f"{str(m).upper()} is at {v}% (limit {lim}%)", key=f"alert:{m}")
    elif event == "start":
        add("panel", "info", "Panel started", key="start")
    elif event == "console" and ip not in ("cli", ""):
        add("panel", "info", "Console command run from the web panel", str(kw.get("command", ""))[:120], key="console")


def route(parts, method, params, ip):
    if method == "GET" and len(parts) == 1:
        try:
            limit = max(1, min(int(params.get("limit") or 60), 200))
        except ValueError:
            limit = 60
        return feed(limit, params.get("cat") or None, params.get("unread") in ("1", "true"))
    if method == "POST" and parts[1:] == ["read"]:
        ids = params.get("ids")
        mark_read([int(x) for x in ids] if isinstance(ids, list) else None)
        return {"ok": True}
    if method == "POST" and parts[1:] == ["clear"]:
        clear(read_only=params.get("all") != "1")
        return {"ok": True}
    from .errors import PanelError
    raise PanelError("not found", 404)
