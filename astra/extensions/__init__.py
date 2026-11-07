"""Extension framework.

An extension is a module exposing `EXT = Extension(...)`. It declares:
  * routes   -> /api/ext/<name>/<route>   (GET = read, POST = write; writes are audited)
  * sections -> a declarative UI spec the web GUI renders: stats, notice, table, form, text, kv, help, catalog,
                tabs (see docs/EXTENSIONS.md), or `ui="name"` for a custom module in web/ui/name.js
Built-in extensions live in this package; yours go in <config dir>/extensions/*.py.
"""
import importlib, importlib.util, os, pkgutil, sys
from .. import config, plat


class Raw:
    """Return from a route to send bytes (e.g. a download) instead of JSON."""

    def __init__(self, data, ctype="application/octet-stream", filename=None):
        self.data, self.ctype, self.filename = data, ctype, filename


class Extension:
    def __init__(self, name, title, icon="box", order=100, requires=(), description="", ui=None,
                 group="Server", glyph="▣"):
        # icon: a name from the GUI icon set (server, globe, folder, clock, shield, box, database, ...) or any short text.
        # requires: binaries that must exist. Built-in tabs leave it empty and explain / offer the install themselves.
        self.name, self.title, self.icon, self.order = name, title, icon, order
        self.group, self.glyph = group, glyph
        self.requires, self.description, self.ui = tuple(requires), description, ui  # ui: name of web/ui/<name>.js
        self.routes, self.sections = {}, []

    def route(self, name, write=False):
        def deco(fn):
            self.routes[name] = (fn, write)
            return fn
        return deco

    @property
    def missing(self):
        return [b for b in self.requires if not plat.which(b)]

    @property
    def available(self):
        return not self.missing

    def meta(self):
        secs = self.sections() if callable(self.sections) else self.sections
        return {"name": self.name, "title": self.title, "icon": self.icon, "order": self.order,
                "group": self.group, "glyph": self.glyph, "description": self.description, "available": self.available,
                "missing": self.missing, "sections": secs, "ui": self.ui}


registry = {}


def _trusted(f):
    if plat.IS_WIN:
        # No uid/mode bits on Windows. The extensions folder lives under the config folder whose ACL `astra init`
        # restricts to SYSTEM, Administrators and the panel user; links are refused. (TODO.md: verify the ACL.)
        return not f.is_symlink()
    st = f.stat()
    return st.st_uid == os.geteuid() and not st.st_mode & 0o022


def load_extensions():
    registry.clear()
    mods = []
    for m in pkgutil.iter_modules(__path__):
        try:
            mods.append(importlib.import_module(f"{__name__}.{m.name}"))
        except Exception as e:
            print(f"extension {m.name} failed to load: {e}", file=sys.stderr)
    user = config.HOME / "extensions"
    for f in sorted(user.glob("*.py")) if user.is_dir() else []:
        if not _trusted(f):
            print(f"skipping {f}: must be owned by the panel user and not group/world-writable (Windows: not a link)", file=sys.stderr)
            continue
        try:
            spec = importlib.util.spec_from_file_location(f"astra_user_{f.stem}", f)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            mods.append(mod)
        except Exception as e:
            print(f"extension {f.name} failed to load: {e}", file=sys.stderr)
    for mod in mods:
        ext = getattr(mod, "EXT", None)
        if ext and ext.name not in config.cfg["disabled_extensions"]:
            registry[ext.name] = ext
    return registry
