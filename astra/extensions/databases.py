import time
from pathlib import Path
from .. import config
from ..errors import PanelError
from .. import plat
from ..shell import IDENT, need, run, run_to_file
from . import Extension

EXT = Extension("databases", "Databases", "🗄", order=60,
                description="MySQL/MariaDB and PostgreSQL on this server (Linux: local socket auth, run panel as root; "
                            "Windows: client option files / pgpass.conf for credentials)")
SYSTEM = {"information_schema", "mysql", "performance_schema", "sys", "postgres"}


def _pg(args):
    """Linux: run the PostgreSQL tool as the postgres OS user. Windows has no runuser: connect as the postgres
    role and never prompt (-w), so credentials must come from pgpass.conf or trust authentication."""
    if plat.IS_WIN:
        return [args[0], "-w", "-U", "postgres", *args[1:]]
    return ["runuser", "-u", "postgres", "--", *args]


def _engine(p):
    e = p.get("engine")
    if e not in ("mysql", "postgres"):
        raise PanelError("engine must be mysql or postgres")
    return e


@EXT.route("list")
def list_(p):
    which = plat.which
    rows = []
    if which("mysql"):
        rc, out = run(["mysql", "-N", "-B", "-e", "SHOW DATABASES"])
        if rc:
            raise PanelError("mysql: " + out.strip()[-300:])
        rows += [{"engine": "mysql", "name": n} for n in out.split() if n not in SYSTEM]
    if which("psql"):
        rc, out = run(_pg(["psql", "-Atc", "SELECT datname FROM pg_database WHERE NOT datistemplate"]))
        if rc:
            raise PanelError("postgres: " + out.strip()[-300:])
        rows += [{"engine": "postgres", "name": n} for n in out.split() if n not in SYSTEM]
    if not which("mysql") and not which("psql"):
        raise PanelError("no mysql or psql client found on this server", 404)
    return rows


@EXT.route("create", write=True)
def create(p):
    e, n = _engine(p), need(p.get("name"), IDENT, "database name")
    if e == "mysql":
        run(["mysql", "-e", f"CREATE DATABASE `{n}` CHARACTER SET utf8mb4"], check=True)
    else:
        run(_pg(["createdb", n]), check=True)
    return {"ok": True}


@EXT.route("drop", write=True)
def drop(p):
    e, n = _engine(p), need(p.get("name"), IDENT, "database name")
    if n in SYSTEM:
        raise PanelError("refusing to drop a system database", 403)
    if e == "mysql":
        run(["mysql", "-e", f"DROP DATABASE `{n}`"], check=True)
    else:
        run(_pg(["dropdb", n]), check=True)
    return {"ok": True}


@EXT.route("backup", write=True)
def backup(p):
    e, n = _engine(p), need(p.get("name"), IDENT, "database name")
    d = Path(config.cfg["backup_dir"])
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"{e}-{n}-{time.strftime('%Y%m%d-%H%M%S')}.sql"
    cmd = ["mysqldump", "--single-transaction", n] if e == "mysql" else _pg(["pg_dump", n])
    run_to_file(cmd, str(dest))
    return {"text": f"saved {dest}"}


EXT.sections = [
    {"type": "table", "title": "Databases", "source": "list",
     "columns": [["Engine", "engine"], ["Name", "name"]],
     "actions": [{"label": "Back up", "route": "backup", "params": {"engine": "$engine", "name": "$name"}},
                 {"label": "Drop", "route": "drop", "params": {"engine": "$engine", "name": "$name"},
                  "confirm": "Permanently drop database $name?", "danger": True}]},
    {"type": "form", "title": "Create a database", "route": "create", "submit": "Create",
     "fields": [{"name": "engine", "label": "Engine", "type": "select", "options": ["mysql", "postgres"]},
                {"name": "name", "label": "Name (letters, digits, _)", "required": True}]},
]
