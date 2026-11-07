"""Renders the bundled legal pages (privacy, terms) with the operator's details filled in."""
import html
from pathlib import Path
from . import config

DIR = Path(__file__).parent / "legal"
PAGES = {"privacy": "Privacy notice", "terms": "Terms of use"}


def _vars():
    op = config.cfg.get("operator", {})
    who = ", ".join(x for x in (op.get("name"), op.get("address")) if x) or "the person who installed this panel"
    contact = op.get("email") or "the operator (no contact address has been configured)"
    return {"operator": who, "contact": contact, "retention": config.cfg.get("audit_retention_days", 90),
            "session": config.cfg.get("session_ttl_hours", 8)}


def render(name):
    if name not in PAGES:
        return None
    text = (DIR / f"{name}.md").read_text()
    for k, v in _vars().items():
        text = text.replace("{{" + k + "}}", str(v))
    out, items = [], []
    flush = lambda: (out.append("<ul>" + "".join(items) + "</ul>"), items.clear()) if items else None
    for line in text.splitlines():
        e = html.escape(line)
        if line.startswith("- "):
            items.append(f"<li>{html.escape(line[2:])}</li>")
            continue
        flush()
        if line.startswith("# "):
            out.append(f"<h1>{html.escape(line[2:])}</h1>")
        elif line.startswith("## "):
            out.append(f"<h2>{html.escape(line[3:])}</h2>")
        elif line.strip():
            out.append(f"<p>{e}</p>")
    flush()
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{PAGES[name]} - astra</title><link rel="icon" href="data:,"><link rel="stylesheet" href="/style.css">'
            '<link rel="stylesheet" href="/custom.css"><script src="/theme.js"></script></head><body><main class="legal">'
            + "".join(out) + '<p><a href="/">Back to the panel</a></p></main></body></html>').encode()
