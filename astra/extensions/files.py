import base64, functools, os, re, shutil, stat, sys
from .. import config, plat
from ..errors import PanelError
from ..shell import safe_path
from . import Extension, Raw

EXT = Extension("files", "Files", "📁", order=30, description="Sandboxed file manager (limited to file_roots)")
BAD_WIN_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MAX_EDIT, MAX_UPLOAD, MAX_DOWNLOAD = 2 << 20, 8 << 20, 100 << 20


def _roots():
    return config.cfg["file_roots"]


def _dir(path):
    return safe_path(path or _roots()[0], _roots())


def _oserr(fn):
    """Turn OS errors (locked file, permission, missing path) into a clean API error instead of a 500."""
    @functools.wraps(fn)
    def wrapper(p):
        try:
            return fn(p)
        except PermissionError as e:
            raise PanelError(f"permission denied or file in use: {e.filename}", 403)
        except OSError as e:
            raise PanelError(f"{e.strerror}: {e.filename}", 400)
    return wrapper


def _name(n):
    if not isinstance(n, str) or n in ("", ".", "..") or "/" in n or "\0" in n:
        raise PanelError("invalid name")
    if plat.IS_WIN and (BAD_WIN_NAME.search(n) or n.endswith((" ", ".")) or plat.RESERVED.match(n)):
        raise PanelError("invalid name for a Windows file system")
    return n


def _is_link(path):
    """Symlink, or on Windows any reparse point (junctions are not reported by islink)."""
    if os.path.islink(path):
        return True
    if plat.IS_WIN:
        try:
            return bool(os.lstat(path).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        except OSError:
            return False
    return False


def _rmtree(path):
    def fix(func, p, *_):  # Windows refuses to delete read-only files
        os.chmod(p, stat.S_IWRITE)
        func(p)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=fix)
    else:
        shutil.rmtree(path, onerror=fix)


def _entry(path):
    """Resolve the parent directory only, so symlinks are acted on, not followed."""
    d, n = os.path.split(str(path).rstrip("/\\" if plat.IS_WIN else "/"))
    return os.path.join(safe_path(d or os.sep, _roots()), _name(n))


def _is_root(p):
    return any(os.path.realpath(r) == os.path.realpath(p) for r in _roots())


@EXT.route("list")
@_oserr
def list_(p):
    path = _dir(p.get("path"))
    if not os.path.isdir(path):
        raise PanelError("not a directory")
    rows = []
    with os.scandir(path) as it:
        for e in it:
            try:
                st = e.stat(follow_symlinks=False)
            except OSError:
                continue
            kind = "link" if _is_link(e.path) else "dir" if e.is_dir() else "file"
            rows.append({"name": e.name, "type": kind, "size": st.st_size, "mtime": int(st.st_mtime)})
    rows.sort(key=lambda r: (r["type"] != "dir", r["name"].lower()))
    return {"path": path, "parent": None if _is_root(path) else os.path.dirname(path), "entries": rows}


@EXT.route("read")
@_oserr
def read(p):
    path = _dir(p.get("path"))
    if not os.path.isfile(path):
        raise PanelError("not a file")
    if os.path.getsize(path) > MAX_EDIT:
        raise PanelError("file is larger than the 2 MB edit limit; download it instead")
    with open(path, "rb") as f:
        data = f.read()
    if b"\0" in data:
        raise PanelError("binary file; use download")
    return {"path": path, "content": data.decode("utf-8", "replace")}


@EXT.route("write", write=True)
@_oserr
def write(p):
    path = _dir(p.get("path"))
    data = str(p.get("content", "")).encode()
    if len(data) > MAX_EDIT:
        raise PanelError("content too large")
    if os.path.isdir(path):
        raise PanelError("path is a directory")
    with open(path, "wb") as f:
        f.write(data)
    return {"ok": True}


@EXT.route("mkdir", write=True)
@_oserr
def mkdir(p):
    os.mkdir(os.path.join(_dir(p.get("path")), _name(p.get("name"))))
    return {"ok": True}


@EXT.route("delete", write=True)
@_oserr
def delete(p):
    t = _entry(p.get("path"))
    if _is_root(t):
        raise PanelError("cannot delete a root folder", 403)
    if _is_link(t):  # remove the link itself, never what it points at
        os.rmdir(t) if plat.IS_WIN and os.path.isdir(t) else os.remove(t)
    elif os.path.isdir(t):
        _rmtree(t)
    else:
        os.remove(t)
    return {"ok": True}


@EXT.route("rename", write=True)
@_oserr
def rename(p):
    src = _entry(p.get("path"))
    dst = os.path.join(os.path.dirname(src), _name(p.get("new_name")))
    if _is_root(src) or os.path.lexists(dst):
        raise PanelError("cannot rename (root folder or target exists)")
    os.rename(src, dst)
    return {"ok": True}


@EXT.route("upload", write=True)
@_oserr
def upload(p):
    dest = os.path.join(_dir(p.get("path")), _name(p.get("name")))
    b64 = str(p.get("data", ""))
    if len(b64) * 3 // 4 > MAX_UPLOAD:
        raise PanelError("upload exceeds 8 MB")
    if os.path.isdir(dest):
        raise PanelError("a folder with that name exists")
    try:
        raw = base64.b64decode(b64, validate=True)
    except ValueError:
        raise PanelError("invalid upload data")
    with open(dest, "wb") as f:
        f.write(raw)
    return {"ok": True}


@EXT.route("download")
@_oserr
def download(p):
    path = _dir(p.get("path"))
    if not os.path.isfile(path):
        raise PanelError("not a file")
    if os.path.getsize(path) > MAX_DOWNLOAD:
        raise PanelError("file exceeds the 100 MB download limit; use scp/rsync")
    with open(path, "rb") as f:
        return Raw(f.read(), filename=os.path.basename(path))


EXT.sections = [{"type": "files"}]
