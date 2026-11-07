import os, re, tarfile, time
from pathlib import Path
from .. import config
from ..errors import PanelError
from .. import plat
from ..shell import NAME, need, safe_path
from . import Extension, Raw

EXT = Extension("backups", "Backups", "💾", order=65, description="tar.gz backups of folders (plus database dumps; .tar.gz opens with tar or 7-Zip on Windows)")


def _dir():
    d = Path(config.cfg["backup_dir"])
    fresh = not d.exists()
    d.mkdir(parents=True, exist_ok=True)
    if fresh and plat.IS_WIN:
        plat.secure(d)  # Windows: private ACL (Linux keeps the system default)
    return d


def _file(p):
    n = need(p.get("name"), NAME, "backup name")
    f = _dir() / n
    if not f.is_file() or f.is_symlink():
        raise PanelError("unknown backup", 404)
    return f


@EXT.route("list")
def list_(p):
    return [{"name": f.name, "size": f.stat().st_size, "mtime": int(f.stat().st_mtime)}
            for f in sorted(_dir().iterdir(), reverse=True) if f.is_file()]


@EXT.route("create", write=True)
def create(p):
    src = safe_path(str(p.get("path", "")), config.cfg["file_roots"])
    if not os.path.exists(src):
        raise PanelError("path does not exist", 404)
    base = re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(src) or "root").lstrip(".") or "root"
    dest = _dir() / f"{base}-{time.strftime('%Y%m%d-%H%M%S')}.tar.gz"
    try:
        with tarfile.open(dest, "w:gz") as t:
            t.add(src, arcname=os.path.basename(src) or "root")
    except OSError as e:  # e.g. a file locked by another program (common on Windows)
        Path(dest).unlink(missing_ok=True)
        raise PanelError(f"cannot read {e.filename}: {e.strerror} (is the file in use?)")
    plat.secure(dest, directory=False)  # 0600 on Linux, private ACL on Windows
    return {"text": f"created {dest}"}


@EXT.route("restore", write=True)
def restore(p):
    f = _file(p)
    dest = safe_path(str(p.get("dest", "")), config.cfg["file_roots"])
    if not f.name.endswith(".tar.gz") or not os.path.isdir(dest):
        raise PanelError("need a .tar.gz backup and an existing destination folder")
    if not hasattr(tarfile, "data_filter"):
        raise PanelError("this Python lacks safe tar extraction; upgrade Python", 500)
    with tarfile.open(f) as t:
        t.extractall(dest, filter="data")
    return {"text": f"restored into {dest}"}


@EXT.route("delete", write=True)
def delete(p):
    _file(p).unlink()
    return {"ok": True}


@EXT.route("download")
def download(p):
    f = _file(p)
    return Raw(f.read_bytes(), filename=f.name)


EXT.sections = [
    {"type": "table", "title": "Backups", "source": "list",
     "columns": [["Name", "name"], ["Size", "size", "bytes"], ["Created", "mtime", "time"]],
     "actions": [{"label": "Download", "route": "download", "method": "GET", "download": True, "params": {"name": "$name"}},
                 {"label": "Delete", "route": "delete", "params": {"name": "$name"}, "confirm": "Delete $name?", "danger": True}]},
    {"type": "form", "title": "Back up a folder", "route": "create", "submit": "Create backup",
     "fields": [{"name": "path", "label": "Folder (inside file roots)", "required": True, "placeholder": os.path.join(plat.EXAMPLE_ROOT, "example.com")}]},
    {"type": "form", "title": "Restore a backup", "route": "restore", "submit": "Restore",
     "fields": [{"name": "name", "label": "Backup file name", "required": True},
                {"name": "dest", "label": "Destination folder (must exist)", "required": True}]},
]
