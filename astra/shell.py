"""Safe subprocess + validation helpers. This project never uses shell=True."""
import json, os, re, subprocess
from . import plat
from .errors import PanelError

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@-]{0,63}$")
WIN_SERVICE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.@$-]{0,79}$")   # Windows service names may contain '$' (MSSQL$SQLEXPRESS)
IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
DOMAIN = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
EMAIL = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,63}$")


def need(value, rx, what):
    if not isinstance(value, str) or not rx.match(value):
        raise PanelError(f"invalid {what}")
    return value


def _resolve(args):
    """Find the executable (PATH, config bin_dirs, usual Windows folders). Batch files are refused:
    running .bat/.cmd with untrusted arguments is unsafe on Windows."""
    exe = args[0]
    if not os.path.isabs(exe):
        found = plat.which(exe)
        if found:
            args = [found, *args[1:]]
    if plat.IS_WIN and args[0].lower().endswith((".bat", ".cmd")):
        raise PanelError(f"{exe} resolves to a batch file; point bin_dirs at the real .exe", 400)
    return args


def run(args, timeout=30, check=False, cwd=None):
    """Run a command (argument list). Returns (returncode, combined output)."""
    args = _resolve(list(args))
    try:
        r = subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=timeout, cwd=cwd,
                           stdin=subprocess.DEVNULL, creationflags=plat.NO_WINDOW)
    except FileNotFoundError:
        raise PanelError(f"{args[0]} is not installed", 404)
    except subprocess.TimeoutExpired:
        raise PanelError(f"{args[0]} timed out after {timeout}s", 504)
    out = (r.stdout or "") + (r.stderr or "")
    if check and r.returncode:
        raise PanelError(out.strip()[-1000:] or f"{args[0]} failed", 400)
    return r.returncode, out


def run_to_file(args, path, timeout=900):
    args = _resolve(list(args))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(fd, "wb") as f:
            r = subprocess.run(args, stdout=f, stderr=subprocess.PIPE, timeout=timeout,
                               stdin=subprocess.DEVNULL, creationflags=plat.NO_WINDOW)
    except FileNotFoundError:
        os.unlink(path)
        raise PanelError(f"{args[0]} is not installed", 404)
    except subprocess.TimeoutExpired:
        os.unlink(path)
        raise PanelError("command timed out", 504)
    if r.returncode:
        os.unlink(path)
        raise PanelError(r.stderr.decode(errors="replace")[-500:] or "command failed")


def ps(script, timeout=30):
    """Run a fixed PowerShell snippet (Windows) and return stdout. Never interpolate unvalidated input into `script`."""
    exe = plat.which("powershell") or plat.which("pwsh")
    if not exe:
        raise PanelError("PowerShell is not available on this machine", 404)
    pre = "$ProgressPreference='SilentlyContinue';$ErrorActionPreference='Stop';[Console]::OutputEncoding=[Text.Encoding]::UTF8;"
    try:
        r = subprocess.run([exe, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", pre + script],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           stdin=subprocess.DEVNULL, creationflags=plat.NO_WINDOW)
    except subprocess.TimeoutExpired:
        raise PanelError(f"PowerShell timed out after {timeout}s", 504)
    if r.returncode:
        raise PanelError((r.stderr or r.stdout).strip()[-500:] or "PowerShell failed", 400)
    return r.stdout


def ps_json(script, timeout=30):
    """Run PowerShell that ends in ConvertTo-Json; always returns a list."""
    out = ps(script, timeout).strip().lstrip("\ufeff")
    if not out:
        return []
    try:
        data = json.loads(out)
    except ValueError:
        raise PanelError("unexpected PowerShell output")
    return data if isinstance(data, list) else [data]


def _inside(real, root):
    a, b = os.path.normcase(real), os.path.normcase(root)
    return a == b or a.startswith(b.rstrip("\\/") + os.sep)


def safe_path(path, roots):
    """Resolve symlinks/junctions and require the result to be inside one of `roots` (case-insensitive on Windows)."""
    if not isinstance(path, str) or not path or "\0" in path:
        raise PanelError("invalid path")
    if plat.IS_WIN:
        rest = path[2:] if re.match(r"^[A-Za-z]:", path) else path
        if ":" in rest or path.startswith(("\\\\?\\", "\\\\.\\")):      # alternate data streams, device/extended paths
            raise PanelError("invalid path")
        if any(plat.RESERVED.match(part) for part in re.split(r"[\\/]", path) if part):
            raise PanelError("invalid path")
    real = os.path.realpath(path)
    for r in roots:
        if _inside(real, os.path.realpath(r)):
            return real
    raise PanelError("path is outside the allowed roots", 403)
