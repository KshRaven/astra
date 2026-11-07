"""Built-in website engine: serves static folders, reverse-proxies to local apps and redirects, chosen by the Host header.

Used by the Websites tab whenever nginx is not installed (or `site_engine` is "builtin"). Stdlib only, one idle thread.
Reachable at http://<server>:<site_port>/ (default 8080); for a quick test without DNS use http://<server>:<site_port>/<domain>/.
Not a full nginx: no WebSocket proxying, no HTTPS (terminate TLS in front, or install nginx), whole responses are buffered.
"""
import http.client, json, mimetypes, os, re, socket, threading, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from . import config, plat
from .errors import PanelError
from .shell import _inside, safe_path

FILE = config.HOME / "sites.json"
NAME = re.compile(r"^(?=.{1,253}$)[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")
UPSTREAM = re.compile(r"^https?://[A-Za-z0-9.-]{1,253}(:\d{1,5})?$")
HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers", "transfer-encoding", "upgrade", "content-length"}
MAX_BODY = 64 << 20
_lock = threading.RLock()
_sites = {}
_srv = {"obj": None, "port": None, "error": ""}


def load():
    global _sites
    try:
        _sites = json.loads(FILE.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        _sites = {}


def _save():
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_sites, indent=2), encoding="utf-8")
    os.replace(tmp, FILE)


def _domain(d):
    d = str(d or "").strip().lower()
    if not NAME.match(d):
        raise PanelError("invalid domain name (e.g. example.com, or localhost for a local test)")
    return d


def names(s):
    return [s["domain"]] + (["www." + s["domain"]] if s.get("www") else [])


def listing():
    with _lock:
        return [{"domain": s["domain"], "type": s["type"], "target": s["target"], "https": False,
                 "aliases": " ".join(names(s)[1:]), "state": "enabled" if s.get("enabled", True) else "disabled"}
                for s in sorted(_sites.values(), key=lambda x: x["domain"])]


def _target(kind, target, domain):
    if kind == "static":
        t = safe_path(str(target or os.path.join(config.cfg["web_roots"][0], domain)), config.cfg["web_roots"])
        os.makedirs(t, exist_ok=True)
        idx = os.path.join(t, "index.html")
        if not os.path.exists(idx):
            with open(idx, "w", encoding="utf-8") as f:
                f.write(f"<!doctype html><meta charset=utf-8><title>{domain}</title><h1>{domain}</h1>\n")
        return t
    if kind == "proxy":
        if not UPSTREAM.match(str(target)):
            raise PanelError("upstream must look like http://127.0.0.1:3000")
        return str(target)
    if kind == "redirect":
        if not UPSTREAM.match(str(target)):
            raise PanelError("redirect address must look like https://example.org")
        return str(target)
    raise PanelError("type must be static, proxy or redirect")


def add(domain, kind, target, www=False):
    domain = _domain(domain)
    with _lock:
        if domain in _sites:
            raise PanelError("site already exists", 409)
        _sites[domain] = {"domain": domain, "type": kind, "target": _target(kind, target, domain),
                          "www": bool(www) and domain.count(".") == 1, "enabled": True}
        _save()
    ensure()


def get(domain):
    s = _sites.get(_domain(domain))
    if not s:
        raise PanelError("unknown site", 404)
    return s


def retarget(domain, target):
    with _lock:
        s = get(domain)
        s["target"] = _target(s["type"], target, s["domain"])
        _save()


def toggle(domain):
    with _lock:
        s = get(domain)
        s["enabled"] = not s.get("enabled", True)
        _save()
    ensure()


def delete(domain):
    with _lock:
        get(domain)
        del _sites[_domain(domain)]
        _save()


def config_text(domain):
    return json.dumps(get(domain), indent=2)


# ---------------- engine ----------------
def _find(host, path):
    host = host.rsplit(":", 1)[0] if not host.endswith("]") and host.count(":") == 1 else host
    with _lock:
        for s in _sites.values():
            if s.get("enabled", True) and host in names(s):
                return s, path
        seg = path.lstrip("/").split("/", 1)   # no DNS yet: /<domain>/...
        s = _sites.get(seg[0])
        if s and s.get("enabled", True):
            return s, "/" + (seg[1] if len(seg) > 1 else "")
    return None, path


class Handler(BaseHTTPRequestHandler):
    server_version, sys_version = "astra-sites", ""

    def log_message(self, *a):
        pass

    def _reply(self, code, body=b"", ctype="text/html; charset=utf-8", extra=None, head=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if not head and body:
            self.wfile.write(body)

    def _page(self, code, title, text, head=False):
        self._reply(code, f"<!doctype html><meta charset=utf-8><title>{title}</title><body style='font:16px system-ui;margin:3rem'>"
                          f"<h1>{title}</h1><p>{text}</p></body>".encode(), head=head)

    def _serve(self, method):
        head = method == "HEAD"
        url = urllib.parse.urlsplit(self.path)
        site, path = _find(self.headers.get("Host", "").lower(), url.path)
        if not site:
            return self._page(404, "No site here", "No website is set up for this address. Add one in the Astra Websites tab.", head)
        t = site["target"]
        if site["type"] == "redirect":
            return self._reply(301, extra={"Location": t + path + ("?" + url.query if url.query else "")}, head=head)
        if site["type"] == "proxy":
            return self._proxy(method, t, path + ("?" + url.query if url.query else ""))
        if method not in ("GET", "HEAD"):
            return self._page(405, "Method not allowed", "This site only serves files.", head)
        self._file(t, path, head)

    def _file(self, root, path, head):
        parts = [p for p in urllib.parse.unquote(path).split("/") if p not in ("", ".")]
        if any(p == ".." or "\0" in p or (plat.IS_WIN and re.search(r'[:\\*?"<>|]', p)) for p in parts):
            return self._page(403, "Forbidden", "That path is not allowed.", head)
        full = os.path.realpath(os.path.join(root, *parts))
        if not _inside(full, os.path.realpath(root)):
            return self._page(403, "Forbidden", "That path is not allowed.", head)
        if os.path.isdir(full):
            if not path.endswith("/"):
                return self._reply(301, extra={"Location": self.path.split("?")[0] + "/"}, head=head)
            full = next((os.path.join(full, i) for i in ("index.html", "index.htm") if os.path.isfile(os.path.join(full, i))), "")
        if not full or not os.path.isfile(full):
            return self._page(404, "Not found", "This page does not exist.", head)
        try:
            st = os.stat(full)
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                ctype += "; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(st.st_size))
            self.send_header("Last-Modified", self.date_time_string(st.st_mtime))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            if not head:
                with open(full, "rb") as f:
                    while chunk := f.read(65536):
                        self.wfile.write(chunk)
        except OSError:
            pass

    def _proxy(self, method, target, pathq):
        u = urllib.parse.urlsplit(target)
        cls = http.client.HTTPSConnection if u.scheme == "https" else http.client.HTTPConnection
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(min(n, MAX_BODY)) if n else None
            hdrs = {k: v for k, v in self.headers.items() if k.lower() not in HOP and k.lower() != "host"}
            hdrs.update({"Host": self.headers.get("Host", ""), "X-Forwarded-For": self.client_address[0], "X-Forwarded-Proto": "http", "Connection": "close"})
            conn = cls(u.hostname, u.port or (443 if u.scheme == "https" else 80), timeout=60)
            conn.request(method, pathq, body, hdrs)
            r = conn.getresponse()
            data = r.read()
            self.send_response(r.status)
            for k, v in r.getheaders():
                if k.lower() not in HOP:
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            if method != "HEAD":
                self.wfile.write(data)
            conn.close()
        except (OSError, http.client.HTTPException):
            self._page(502, "App not reachable", f"The app behind this site ({target}) is not answering. Is it running?")

    do_GET = lambda s: s._serve("GET")
    do_HEAD = lambda s: s._serve("HEAD")
    do_POST = lambda s: s._serve("POST")
    do_PUT = lambda s: s._serve("PUT")
    do_PATCH = lambda s: s._serve("PATCH")
    do_DELETE = lambda s: s._serve("DELETE")
    do_OPTIONS = lambda s: s._serve("OPTIONS")


class _Srv(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = not plat.IS_WIN


def running():
    return _srv["obj"] is not None


def stop():
    s, _srv["obj"] = _srv["obj"], None
    if s:
        threading.Thread(target=lambda: (s.shutdown(), s.server_close()), daemon=True).start()


def ensure():
    """Start the engine when at least one site is enabled, restart if site_port changed, stop when nothing is left to serve."""
    port = int(config.cfg.get("site_port") or 8080)
    want = any(s.get("enabled", True) for s in _sites.values())
    if running() and (not want or _srv["port"] != port):
        stop()
    if want and not running():
        try:
            srv = _Srv(("0.0.0.0", port), Handler)
        except OSError as e:
            _srv["error"] = f"cannot listen on port {port}: {e.strerror}. Change it: astra config set site_port 8081"
            return
        _srv.update(obj=srv, port=port, error="")
        threading.Thread(target=srv.serve_forever, daemon=True, name="astra-sites").start()


def status():
    return {"running": running(), "port": _srv["port"] or int(config.cfg.get("site_port") or 8080), "error": _srv["error"]}


def start():
    load()
    ensure()
