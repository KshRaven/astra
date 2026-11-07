# Writing extensions

An extension is one Python file that defines **routes** (the API) and **sections** (the GUI tab). The same routes work from the web GUI and from `astra call`.

```python
from astra.extensions import Extension
from astra.shell import run, need, NAME
from astra.errors import PanelError

EXT = Extension("redis", "Redis", "🧰", order=75, requires=["redis-cli"], description="Redis keys")

@EXT.route("info")                       # GET /api/ext/redis/info
def info(p):
    return {"text": run(["redis-cli", "info", "server"], check=True)[1]}

@EXT.route("flush", write=True)          # POST only, audited
def flush(p):
    run(["redis-cli", "flushdb"], check=True)
    return {"ok": True}

EXT.sections = [
    {"type": "text", "title": "Server info", "source": "info"},
    {"type": "form", "title": "Danger zone", "route": "flush", "submit": "Flush DB", "fields": []},
]
```

Install: copy to `/etc/astra/extensions/redis.py` (owned by the panel user, not group/world-writable, otherwise it is skipped) and `systemctl restart astra`. Disable built-ins with `disabled_extensions`.

## Route rules

- A route receives one dict of parameters (query string for GET, JSON body for POST). Values are untrusted: validate with `need(value, regex, "what")`.
- Return JSON-serialisable data, or `Raw(bytes, content_type, filename)` for downloads.
- Raise `PanelError("message", status)` for expected failures; anything else becomes a generic 500 and is logged.
- Run commands with `run([...])` (argument list). Never build a shell string.
- Anything that changes the system must use `write=True`; it then requires POST and is written to the audit log.

## Section types

| type | fields |
|---|---|
| `table` | `title`, `source` (route returning a list of dicts), `columns` = `[[label, key, format?]]` (format: `bytes`, `time`, `state`), `actions`, `refresh` (seconds) |
| `form` | `title`, `route`, `method` (default POST), `submit`, `fields` = `{name,label,type: text/number/password/select, options, placeholder, required, value}`. If the route returns `{"text": ...}` it is shown under the form |
| `text` | `title`, `source` (returns `{"text": ...}`) |
| `files` | the built-in file manager |

Row action: `{"label", "route", "params": {"id": "$id"}, "method": "GET|POST", "confirm": "Delete $name?", "danger": true, "download": true}`. `$key` is replaced by that row's value. If an action returns `{"text": ...}` it is shown in a dialog.

`EXT.sections` may also be a function returning the list, evaluated when the page loads (the Logs tab uses this to list current files).

## Custom UI modules

For a page that does not fit table/form/text sections, give the extension `ui="name"` and ship `astra/web/ui/name.js` (built-in only). The file registers `window.ASTRA_UI.name = (view, ext, ASTRA) => {...}` and is downloaded only when the tab is opened. `ASTRA` offers `h`, `call`, `req`, `card`, `toast`, `showText`, `extView`, `timers` and `onLeave(fn)` for cleanup. See `web/ui/desktop.js`.
