import os, sqlite3, time
from pathlib import Path
from .. import config, plat
from ..errors import PanelError
from ..shell import IDENT, need, run, run_to_file
from . import Extension, services

EXT = Extension("databases", "Databases", "database", order=60,
                description="Create, inspect, back up and remove databases. SQLite works everywhere with nothing to install; "
                            "MySQL/MariaDB and PostgreSQL appear once installed.")
SYSTEM = {"information_schema", "mysql", "performance_schema", "sys", "postgres"}
SQLITE_DIR = config.HOME / "databases"
for r in ("catalog", "detail", "install", "uninstall", "action"):   # same install / start / stop machinery as the Services tab
    EXT.routes[r] = services.EXT.routes[r]


def _my(tool="mysql"):
    return plat.which("mariadb" if tool == "mysql" else "mariadb-dump") or plat.which(tool)


def _have_pg():
    return plat.which("psql")


def _pg(args):
    """Linux: run the PostgreSQL tool as the postgres OS user. Windows has no runuser: connect as the postgres
    role and never prompt (-w), so credentials must come from pgpass.conf or trust authentication."""
    if plat.IS_WIN:
        return [args[0], "-w", "-U", "postgres", *args[1:]]
    return ["runuser", "-u", "postgres", "--", *args]


def _engine(p):
    e = p.get("engine")
    if e not in ("sqlite", "mysql", "postgres"):
        raise PanelError("engine must be sqlite, mysql or postgres")
    if e == "mysql" and not _my():
        raise PanelError("MySQL / MariaDB is not installed. Install it on the 'Install / remove' tab.", 404)
    if e == "postgres" and not _have_pg():
        raise PanelError("PostgreSQL is not installed. Install it on the 'Install / remove' tab.", 404)
    return e


def _sqlite_file(n):
    return SQLITE_DIR / (need(n, IDENT, "database name") + ".sqlite3")


def _hint():
    return "set up a client option file (my.ini / .my.cnf) or pgpass.conf for the panel user" if plat.IS_WIN else "run the panel as root so local socket login works"


def _mysql_rows():
    rc, out = run([_my(), "-N", "-B", "-e", "SELECT s.schema_name, COALESCE(SUM(t.data_length+t.index_length),0) FROM information_schema.schemata s "
                   "LEFT JOIN information_schema.tables t ON t.table_schema=s.schema_name GROUP BY s.schema_name"], timeout=20)
    if rc:
        raise PanelError(out.strip()[-300:] or "mysql failed")
    rows = []
    for line in out.splitlines():
        name, _, size = line.partition("\t")
        if name and name not in SYSTEM:
            rows.append({"engine": "mysql", "name": name, "size": int(float(size or 0))})
    return rows


def _pg_rows():
    rc, out = run(_pg(["psql", "-At", "-F", "\t", "-c", "SELECT datname, pg_database_size(datname) FROM pg_database WHERE NOT datistemplate"]), timeout=20)
    if rc:
        raise PanelError(out.strip()[-300:] or "psql failed")
    return [{"engine": "postgres", "name": n, "size": int(s or 0)} for n, _, s in (l.partition("\t") for l in out.splitlines()) if n and n not in SYSTEM]


def _sqlite_rows():
    return [{"engine": "sqlite", "name": f.stem, "size": f.stat().st_size} for f in sorted(SQLITE_DIR.glob("*.sqlite3"))] if SQLITE_DIR.is_dir() else []


@EXT.route("list")
def list_(p):
    rows = _sqlite_rows()
    for have, fn in ((_my(), _mysql_rows), (_have_pg(), _pg_rows)):
        if have:
            try:
                rows += fn()
            except PanelError:
                pass   # shown on the Engines card instead of breaking the whole list
    return rows


@EXT.route("engines")
def engines(p):
    pairs = [["SQLite", f"Built in. Files live in {SQLITE_DIR}"]]
    for title, have, fn in (("MySQL / MariaDB", _my(), _mysql_rows), ("PostgreSQL", _have_pg(), _pg_rows)):
        if not have:
            pairs.append([title, "Not installed (see the 'Install / remove' tab)"])
            continue
        try:
            pairs.append([title, f"Connected, {len(fn())} database(s)"])
        except PanelError as e:
            pairs.append([title, f"Installed, but the panel cannot log in or the server is stopped: {str(e)[:160]}. Start it on the Install tab, or {_hint()}."])
    return {"pairs": pairs}


@EXT.route("tables")
def tables(p):
    e, n = _engine(p), need(p.get("name"), IDENT, "database name")
    if e == "sqlite":
        f = _sqlite_file(n)
        if not f.exists():
            raise PanelError("unknown database", 404)
        con = sqlite3.connect(f"file:{f}?mode=ro", uri=True)
        try:
            names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
            pairs = [[t, str(con.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]) + " rows"] for t in names]
        finally:
            con.close()
    elif e == "mysql":
        rc, out = run([_my(), "-N", "-B", "-e", f"SELECT table_name, table_rows FROM information_schema.tables WHERE table_schema='{n}' ORDER BY 1"], timeout=20)
        if rc:
            raise PanelError(out.strip()[-300:])
        pairs = [[a, b + " rows (approx.)"] for a, _, b in (l.partition("\t") for l in out.splitlines())]
    else:
        rc, out = run(_pg(["psql", "-d", n, "-At", "-F", "\t", "-c", "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY 1"]), timeout=20)
        if rc:
            raise PanelError(out.strip()[-300:])
        pairs = [[a, b + " rows (approx.)"] for a, _, b in (l.partition("\t") for l in out.splitlines())]
    return {"title": f"Tables in {n}", "kv": pairs or [["(no tables yet)", ""]]}


@EXT.route("create", write=True)
def create(p):
    e, n = _engine(p), need(p.get("name"), IDENT, "database name (letters, digits, _; start with a letter)")
    if e == "sqlite":
        SQLITE_DIR.mkdir(parents=True, exist_ok=True)
        f = _sqlite_file(n)
        if f.exists():
            raise PanelError("a database with that name exists", 409)
        sqlite3.connect(f).close()
    elif e == "mysql":
        run([_my(), "-e", f"CREATE DATABASE `{n}` CHARACTER SET utf8mb4"], check=True)
    else:
        run(_pg(["createdb", n]), check=True)
    return {"message": f"Database {n} created"}


@EXT.route("drop", write=True)
def drop(p):
    e, n = _engine(p), need(p.get("name"), IDENT, "database name")
    if n in SYSTEM:
        raise PanelError("refusing to drop a system database", 403)
    if e == "sqlite":
        f = _sqlite_file(n)
        if not f.exists():
            raise PanelError("unknown database", 404)
        try:
            f.unlink()
        except OSError as x:
            raise PanelError(f"cannot delete (in use?): {x.strerror}")
    elif e == "mysql":
        run([_my(), "-e", f"DROP DATABASE `{n}`"], check=True)
    else:
        run(_pg(["dropdb", n]), check=True)
    return {"ok": True}


@EXT.route("backup", write=True)
def backup(p):
    e, n = _engine(p), need(p.get("name"), IDENT, "database name")
    d = Path(config.cfg["backup_dir"])
    d.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    if e == "sqlite":
        src_f = _sqlite_file(n)
        if not src_f.exists():
            raise PanelError("unknown database", 404)
        dest = d / f"sqlite-{n}-{stamp}.sqlite3"
        src, dst = sqlite3.connect(f"file:{src_f}?mode=ro", uri=True), sqlite3.connect(dest)
        try:
            src.backup(dst)
        finally:
            dst.close(); src.close()
        return {"text": f"saved {dest}"}
    dest = d / f"{e}-{n}-{stamp}.sql"
    cmd = [_my("mysqldump") or "mysqldump", "--single-transaction", n] if e == "mysql" else _pg(["pg_dump", n])
    run_to_file(cmd, str(dest))
    return {"text": f"saved {dest}"}


def _sections():
    engines_ = [{"value": "sqlite", "label": "SQLite (built in, one file per database)"}]
    if _my():
        engines_.append({"value": "mysql", "label": "MySQL / MariaDB"})
    if _have_pg():
        engines_.append({"value": "postgres", "label": "PostgreSQL"})
    help_ = {"type": "help", "title": "What is a database?", "text": "A database stores structured data for your apps: users, orders, posts. Most websites (WordPress, Laravel, Django...) need one. "
             "SQLite is a single file and needs nothing installed; MySQL/MariaDB and PostgreSQL are full servers for bigger sites.",
             "steps": [["Pick an engine", "SQLite works right away. For a server database, install one on the 'Install / remove' tab."], ["Create a database", "give it a short name; your app connects to it by that name."],
                       ["Back up often", "each database has a Back up button; files go to the backup folder."]]}
    return [help_, {"type": "kv", "title": "Engines", "source": "engines", "refresh": 30},
            {"type": "tabs", "tabs": [
                {"id": "databases", "title": "Databases", "icon": "database", "sections": [{"type": "table", "title": "Your databases", "source": "list", "refresh": 20,
                    "buttons": [{"label": "New database", "route": "create", "icon": "plus", "primary": True, "form": [{"name": "engine", "label": "Engine", "type": "select", "options": engines_}, {"name": "name", "label": "Name (letters, digits, _)", "required": True}]}],
                    "columns": [["Engine", "engine"], ["Name", "name"], ["Size", "size", "bytes"]],
                    "actions": [{"label": "Tables", "route": "tables", "method": "GET", "params": {"engine": "$engine", "name": "$name"}, "quiet": True},
                                {"label": "Back up", "route": "backup", "params": {"engine": "$engine", "name": "$name"}},
                                {"label": "Drop", "route": "drop", "params": {"engine": "$engine", "name": "$name"}, "confirm": "Permanently drop database $name? This cannot be undone.", "danger": True}],
                    "empty": {"icon": "database", "title": "No databases yet", "text": "Create one with New database. SQLite needs nothing installed."}}]},
                {"id": "install", "title": "Install / remove", "icon": "package", "sections": [{"type": "catalog", "only": ["Databases"], "title": "Database servers",
                    "desc": "Installs run in the background; watch them in the console. On Windows these use winget or Chocolatey when available.", "source": "catalog", "detail": "detail", "install": "install", "uninstall": "uninstall", "action": "action"}]}]}]


EXT.sections = _sections
