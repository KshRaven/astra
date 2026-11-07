"""Append-only JSON-lines audit log of failed logins and every write action."""
import json, threading, time
from . import config

_lock = threading.Lock()
SECRET_KEYS = {"content", "data", "password", "token"}


def redact(params):
    return {k: ("<redacted>" if k in SECRET_KEYS else (v[:200] if isinstance(v, str) else v))
            for k, v in params.items()}


def log(event, **kw):
    config.LOGDIR.mkdir(parents=True, exist_ok=True, mode=0o700)
    p = config.LOGDIR / "audit.log"
    with _lock:
        if p.exists() and p.stat().st_size > 5_000_000:
            p.replace(p.with_suffix(".log.1"))
        with open(p, "a") as f:
            f.write(json.dumps({"ts": int(time.time()), "event": event, **kw}) + "\n")
    try:  # feed the notification centre (merged, categorised); never let it break the action being logged
        from . import notify
        notify.from_audit(event, kw)
    except Exception:
        pass


def tail(n=100):
    p = config.LOGDIR / "audit.log"
    if not p.exists():
        return []
    out = []
    with open(p, "rb") as f:  # read only the end of the file, never the whole 5 MB
        f.seek(0, 2)
        f.seek(max(0, f.tell() - n * 600))
        lines = f.read().decode(errors="replace").splitlines()[-n:]
    for line in reversed(lines):
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def prune(days=None):
    """Data minimisation: drop audit lines older than `days`, and the rotated file."""
    days = config.cfg.get("audit_retention_days", 90) if days is None else days
    if not days:
        return
    cut, p = time.time() - days * 86400, config.LOGDIR / "audit.log"
    old = p.with_suffix(".log.1")
    if old.exists() and old.stat().st_mtime < cut:
        old.unlink()
    if not p.exists():
        return
    keep = []
    for line in p.read_text(errors="replace").splitlines():
        try:
            if json.loads(line)["ts"] >= cut:
                keep.append(line)
        except (ValueError, KeyError, TypeError):
            pass
    with _lock:
        p.write_text("".join(x + "\n" for x in keep))


def erase():
    """Delete every audit file. Returns how many files were removed."""
    n = 0
    for f in config.LOGDIR.glob("audit.log*"):
        f.unlink()
        n += 1
    return n


def applog(text):
    """Panel's own diagnostic log (<config dir>/logs/panel.log): start-up, errors, tracebacks. Shown in the Logs tab."""
    try:
        config.LOGDIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        p = config.LOGDIR / "panel.log"
        with _lock:
            if p.exists() and p.stat().st_size > 2_000_000:
                p.replace(p.with_suffix(".log.1"))
            with open(p, "a", encoding="utf-8") as f:
                f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + str(text).rstrip() + "\n")
    except OSError:
        pass
