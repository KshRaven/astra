"""HTTP server: static web GUI + login-protected JSON API (stdlib only)."""
import gzip, hashlib, http.cookies, ipaddress, json, os, re, signal, socket, ssl, sys, threading, traceback, urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from . import __version__, audit, config, core, daemon, deploy, jobs, mfa, notify, plat, sitehost
from .auth import Limiter
from .errors import PanelError
from .extensions import Raw, load_extensions, registry
from .shell import EMAIL

WEB = Path(__file__).parent / "web"
MAX_BODY = 12 * 1024 * 1024
JS, CSS = "text/javascript; charset=utf-8", "text/css; charset=utf-8"
STATIC = {"/": ("index.html", "text/html; charset=utf-8"), "/app.js": ("app.js", JS),
          "/theme.js": ("theme.js", JS), "/style.css": ("style.css", CSS),
          "/favicon.svg": ("favicon.svg", "image/svg+xml"), "/favicon.ico": ("favicon.svg", "image/svg+xml")}
UI_FILE = re.compile(r"/ui/([a-z0-9_-]+\.(js|css))")  # lazily loaded UI modules (e.g. the desktop)
AUTH_BODY_MAX = 4096
_cache = {}  # path -> (mtime, raw, gzipped, etag)
HEADERS = {
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
}
limiter = Limiter()
COOKIE = "astra_sid"


class Handler(BaseHTTPRequestHandler):
    server_version, sys_version = "astra", ""

    def log_message(self, *a):
        pass

    def _send(self, code, body, ctype="application/json", extra=None):
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in {**HEADERS, **(extra or {})}.items():
            self.send_header(k, v)
        if getattr(self, "_cookie", None) is not None:
            self.send_header("Set-Cookie", self._cookie)
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path):
        if path == "/custom.css":  # user theme overrides: <config dir>/custom.css
            f = config.HOME / "custom.css"
            return self._send(200, f.read_bytes() if f.is_file() else b"", CSS)
        m = UI_FILE.fullmatch(path)
        if m:
            f, ctype = WEB / "ui" / m[1], JS if m[2] == "js" else CSS
        else:
            f, ctype = WEB / STATIC[path][0], STATIC[path][1]
        if not f.is_file():
            return self._send(404, {"error": "not found"})
        mt = f.stat().st_mtime
        hit = _cache.get(path)
        if not hit or hit[0] != mt:  # compress once, serve many times
            raw = f.read_bytes()
            hit = _cache[path] = (mt, raw, gzip.compress(raw, 6), '"' + hashlib.sha1(raw).hexdigest()[:16] + '"')
        extra = {"Cache-Control": "no-cache", "ETag": hit[3], "Vary": "Accept-Encoding"}
        if self.headers.get("If-None-Match") == hit[3]:
            return self._send(304, b"", ctype, extra)
        if "gzip" in self.headers.get("Accept-Encoding", ""):
            return self._send(200, hit[2], ctype, {**extra, "Content-Encoding": "gzip"})
        self._send(200, hit[1], ctype, extra)

    def _reject(self, code, msg):
        """Error before the body is read: drain a little so the client sees the reply instead of a reset."""
        try:
            n = int(self.headers.get("Content-Length") or 0)
            if 0 < n <= 65536:
                self.rfile.read(n)
        except (ValueError, OSError):
            pass
        self._send(code, {"error": msg}, extra={"Connection": "close"})

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def _dispatch(self, method):
        u = urllib.parse.urlsplit(self.path)
        path = u.path
        base = (config.cfg.get("base_path") or "").rstrip("/")   # the panel also answers under /astra/ (behind a proxy or directly)
        if base and (path == base or path.startswith(base + "/")):
            if path == base:
                self.send_response(301)
                self.send_header("Location", base + "/" + ("?" + u.query if u.query else ""))
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            path = path[len(base):]
        if method == "GET" and (path in STATIC or path == "/custom.css" or UI_FILE.fullmatch(path)):
            return self._static(path)
        if not path.startswith("/api/"):
            return self._send(404, {"error": "not found"})
        ip = self.client_address[0]
        if not ip_allowed(ip, config.cfg.get("allowed_ips")):
            return self._reject(403, "forbidden")
        if limiter.blocked(ip):
            return self._reject(429, "too many failed attempts, try again later")
        self._cookie = None
        auth = self.headers.get("Authorization", "")
        bearer = auth[7:] if auth.startswith("Bearer ") else ""
        by_cookie = False
        if not bearer:
            jar = http.cookies.SimpleCookie()
            try:
                jar.load(self.headers.get("Cookie", ""))
            except http.cookies.CookieError:
                pass
            if COOKIE in jar:
                bearer, by_cookie = jar[COOKIE].value, True
        is_auth = path.startswith("/api/auth/")
        origin = self.headers.get("Origin")
        if method == "POST" and origin and urllib.parse.urlsplit(origin).netloc != self.headers.get("Host", ""):
            return self._reject(403, "cross-site request refused")  # CSRF guard on top of SameSite=Strict
        if not is_auth:  # authenticate BEFORE reading any request body
            # every API route needs a session (cookie or Bearer) from /api/auth/login (+ /api/auth/verify when MFA is on)
            if not mfa.session_ok(bearer):
                limiter.fail(ip)
                audit.log("auth_fail", ip=ip)
                return self._reject(401, "invalid or expired session")
            limiter.ok(ip)
        params = dict(urllib.parse.parse_qsl(u.query))
        if method == "POST":
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self._send(400, {"error": "bad Content-Length"})
            if n > (AUTH_BODY_MAX if is_auth else MAX_BODY):
                return self._reject(413, "body too large")
            if n:
                try:
                    body = json.loads(self.rfile.read(n))
                except ValueError:
                    return self._send(400, {"error": "invalid JSON"})
                if not isinstance(body, dict):
                    return self._send(400, {"error": "JSON object expected"})
                params.update(body)
        try:
            result = (self._auth(method, path, params, ip, bearer) if is_auth
                      else self._route(method, path, params, ip, bearer))
        except PanelError as e:
            if is_auth and e.status == 401:  # wrong password / wrong code counts toward the lockout
                limiter.fail(ip)
                audit.log("auth_fail", ip=ip, stage=path[10:])
            return self._send(e.status, {"error": e.message})
        except Exception:
            traceback.print_exc()
            audit.applog(f"500 on {method} {path}\n" + traceback.format_exc())
            return self._send(500, {"error": "internal error (see Logs > Panel log)"})
        if isinstance(result, Raw):
            name = re.sub(r"[^\w.\-]", "_", result.filename or "download")
            return self._send(200, result.data, result.ctype,
                              {"Content-Disposition": f'attachment; filename="{name}"'})
        self._send(200, result)

    def _auth(self, method, path, params, ip, bearer):
        if path == "/api/auth/status" and method == "GET":  # does the browser still hold a valid session? never counts as a failed attempt
            return {"signed_in": bool(mfa.session_ok(bearer))}
        if method != "POST":
            raise PanelError("POST required", 405)
        step = path[len("/api/auth/"):]
        if step == "login":
            r = mfa.login(params.get("username", ""), params.get("password", ""))
            if "session" in r:
                limiter.ok(ip)
                audit.log("login", ip=ip, mfa=False, user=config.cfg["admin"]["username"])
                notify.visit(ip)
                self._set_session(r["session"])
            return r
        if step == "send":
            return mfa.send_login_code(params.get("challenge"))
        if step == "verify":
            r = mfa.verify_login(params.get("challenge"), params.get("method"), params.get("code"))
            limiter.ok(ip)
            audit.log("login", ip=ip, mfa=True, user=config.cfg["admin"]["username"])
            notify.visit(ip)
            self._set_session(r["session"])
            return r
        if step == "logout":
            mfa.revoke(bearer)
            self._cookie = f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Strict"
            audit.log("logout", ip=ip)
            return {"ok": True}
        raise PanelError("not found", 404)

    def _set_session(self, sid):
        ttl = int(float(config.cfg.get("session_ttl_hours", 8)) * 3600)
        secure = "; Secure" if (config.cfg["tls_cert"] and config.cfg["tls_key"]) else ""
        self._cookie = f"{COOKIE}={sid}; Path=/; Max-Age={ttl}; HttpOnly; SameSite=Strict{secure}"

    def _route(self, method, path, params, ip, bearer=""):
        parts = path[len("/api/"):].strip("/").split("/")
        head = parts[0]
        if head == "ping":
            return {"version": __version__}
        if head == "dashboard":
            return core.dashboard()
        if head == "history":
            return {"samples": core.mon.history() if core.mon else []}
        if head == "alerts":
            return list(core.mon.alerts) if core.mon else []
        if head == "extensions":
            return sorted((e.meta() for e in registry.values()), key=lambda m: (m["order"], m["title"]))
        if head == "me":
            return {"user": config.cfg["admin"]["username"], "version": __version__, "mfa": mfa.methods(),
                    "console": bool(config.cfg.get("console_enabled", True)), "os": plat.OS_NAME, "root": plat.IS_ROOT}
        if head == "notifications":
            return notify.route(parts, method, params, ip)
        if head in ("jobs", "console"):
            return jobs.route(parts, method, params, ip)
        if head == "settings":
            return self._settings(method, params, ip)
        if head == "panel" and parts[1:2] in (["service"], ["domain"]):
            if method == "POST":
                audit.log("action", ip=ip, ext="panel", route="/".join(parts[1:]), params=audit.redact(params))
            return deploy.route(parts[1:], method, params)
        if head == "panel" and parts[1:] == ["restart"] and method == "POST":
            audit.log("action", ip=ip, ext="panel", route="restart", params={})
            threading.Timer(0.8, restart_process).start()
            return {"ok": True}
        if head == "account" and parts[1:] == ["update"]:
            if method != "POST":
                raise PanelError("POST required", 405)
            if not config.check_login(config.cfg["admin"]["username"], params.get("current", "")):
                limiter.fail(ip)
                raise PanelError("current password is wrong", 401)
            try:
                config.set_admin(params.get("username") or None, params.get("new_password") or None)
            except ValueError as e:
                raise PanelError(str(e))
            config.save()
            mfa.revoke(keep=bearer)  # every other session is signed out
            audit.log("account_changed", ip=ip, user=config.cfg["admin"]["username"])
            return {"ok": True, "user": config.cfg["admin"]["username"]}
        if head == "mfa":
            return self._mfa("/".join(parts[1:]), method, params, ip)
        if head == "privacy":
            return self._privacy(parts[1:], method, params, ip)
        if head == "ext" and len(parts) == 3:
            ext = registry.get(parts[1])
            if not ext or parts[2] not in ext.routes:
                raise PanelError("not found", 404)
            fn, write = ext.routes[parts[2]]
            if write and method != "POST":
                raise PanelError("POST required", 405)
            if not ext.available:
                raise PanelError("missing on this server: " + ", ".join(ext.missing), 404)
            if write:
                audit.log("action", ip=ip, ext=ext.name, route=parts[2], params=audit.redact(params))
            return fn(params)
        raise PanelError("not found", 404)


def _mfa_route(self, name, method, params, ip):
    if name == "status":
        return mfa.status()
    if method != "POST":
        raise PanelError("POST required", 405)
    audit.log("mfa_change", ip=ip, step=name)
    table = {"totp/begin": lambda: mfa.totp_begin(), "totp/confirm": lambda: mfa.totp_confirm(params.get("code")),
             "email/begin": lambda: mfa.email_begin(params.get("email")), "email/confirm": lambda: mfa.email_confirm(params.get("code")),
             "disable": lambda: mfa.disable(params.get("method"))}
    if name not in table:
        raise PanelError("not found", 404)
    return table[name]()


def _privacy_route(self, parts, method, params, ip):
    if parts == ["export"]:
        return {"config": config.public(), "audit_events": audit.tail(5000),
                "note": "Secrets are masked. Sessions are memory-only and not exported."}
    if parts == ["delete"]:
        if method != "POST" or params.get("confirm") != "delete":
            raise PanelError("POST with confirm=delete required", 405)
        n = audit.erase()
        mfa.reset_all()
        audit.log("privacy_delete", files=n)  # records that a deletion happened, with no personal data
        return {"audit_files_deleted": n, "mfa_cleared": True}
    raise PanelError("not found", 404)


EDITABLE_ALERTS = ("cpu", "mem", "disk")


def _settings_route(self, method, params, ip):
    """Panel settings shown on Settings > Panel / Console / Notifications. Only whitelisted keys can be changed."""
    c = config.cfg
    if method == "GET":
        return {"host": c["host"], "port": c["port"], "tls": bool(c["tls_cert"] and c["tls_key"]),
                "tls_cert": c["tls_cert"], "tls_key": c["tls_key"], "allowed_ips": c["allowed_ips"],
                "session_ttl_hours": c["session_ttl_hours"], "audit_retention_days": c["audit_retention_days"],
                "console_enabled": c.get("console_enabled", True), "alerts": c["alerts"],
                "urls": urls(c["host"], int(c["port"])), "base_path": c.get("base_path", "/astra"), "domain": c.get("domain", ""), "home": str(config.HOME), "your_ip": ip,
                "version": __version__, "os": plat.OS_NAME,
                "smtp": {**{k: c["smtp"].get(k, "") for k in ("host", "port", "security", "user", "from")}, "password_set": bool(c["smtp"].get("password"))}}
    if method != "POST":
        raise PanelError("POST required", 405)
    restart = False
    try:
        if "allowed_ips" in params:
            raw = params["allowed_ips"]
            lst = [x.strip() for x in (raw.split(",") if isinstance(raw, str) else raw) if str(x).strip()]
            for x in lst:
                ipaddress.ip_network(x, strict=False)
            if lst and not ip_allowed(ip, lst):
                raise PanelError("that list would lock you out: your own address (" + ip + ") must be in it")
            c["allowed_ips"] = lst
        if "session_ttl_hours" in params:
            v = float(params["session_ttl_hours"])
            if not 0.25 <= v <= 720:
                raise PanelError("session length must be between 0.25 and 720 hours")
            c["session_ttl_hours"] = v
        if "audit_retention_days" in params:
            v = int(params["audit_retention_days"])
            if not 0 <= v <= 3650:
                raise PanelError("audit retention must be 0-3650 days")
            c["audit_retention_days"] = v
        if "console_enabled" in params:
            c["console_enabled"] = params["console_enabled"] in (True, "true", "1", "on", 1)
        if isinstance(params.get("alerts"), dict):
            for k in EDITABLE_ALERTS:
                if k in params["alerts"]:
                    v = int(params["alerts"][k])
                    if not 0 <= v <= 100:
                        raise PanelError("alert limits are percentages (0 turns one off)")
                    c["alerts"][k] = v
        if isinstance(params.get("smtp"), dict):   # outgoing mail (sign-in codes, alerts); empty host turns it off
            sm, new = c["smtp"], params["smtp"]
            if "host" in new:
                hv = str(new["host"]).strip()
                if hv and not re.fullmatch(r"[A-Za-z0-9.:-]{1,253}", hv):
                    raise PanelError("mail server: a host name or address such as smtp.example.com or 127.0.0.1")
                sm["host"] = hv
            if "port" in new and str(new["port"]).strip():
                pv = int(new["port"])
                if not 1 <= pv <= 65535:
                    raise PanelError("mail port must be 1-65535 (587 is usual)")
                sm["port"] = pv
            if new.get("security") in ("starttls", "ssl", "none"):
                sm["security"] = new["security"]
            if "user" in new:
                sm["user"] = str(new["user"]).strip()[:200]
            if new.get("password") and new["password"] != "<set>":
                sm["password"] = str(new["password"])[:200]
            if new.get("clear_password"):
                sm["password"] = ""
            if "from" in new:
                fv = str(new["from"]).strip()
                if fv and not EMAIL.match(fv):
                    raise PanelError("sender address must look like astra@example.com")
                sm["from"] = fv
            if any("\n" in str(sm.get(k, "")) or "\r" in str(sm.get(k, "")) for k in sm):
                raise PanelError("mail settings cannot contain line breaks")
        if "base_path" in params:
            bp = str(params["base_path"]).strip().rstrip("/")
            if bp and not re.fullmatch(r"/[A-Za-z0-9._-]{1,40}", bp):
                raise PanelError("path prefix looks like /astra (letters, digits . _ -), or empty to turn it off")
            c["base_path"] = bp
        if "host" in params:
            h = str(params["host"]).strip()
            if h != "localhost":
                ipaddress.ip_address(h)
            restart |= h != c["host"]
            c["host"] = h
        if "port" in params:
            v = int(params["port"])
            if not 1 <= v <= 65535:
                raise PanelError("port must be 1-65535")
            restart |= v != int(c["port"])
            c["port"] = v
        for k in ("tls_cert", "tls_key"):
            if k in params:
                v = str(params[k]).strip()
                if v and not os.path.isfile(v):
                    raise PanelError(f"{k}: file not found on this server")
                restart |= v != c[k]
                c[k] = v
    except ValueError:
        raise PanelError("invalid value")
    config.save()
    if params.get("mail_test"):   # after saving, so the test uses what was just entered
        to = str(params["mail_test"]).strip()
        if not EMAIL.match(to):
            raise PanelError("enter a valid address to send the test to")
        mfa.send_mail(to, "astra test message", "If you can read this, the panel can send e-mail.\nSign-in codes and alerts will use the same settings.\n")
    audit.log("action", ip=ip, ext="panel", route="settings", params=audit.redact({k: v for k, v in params.items()}))
    return {"ok": True, "restart_needed": restart}


Handler._mfa, Handler._privacy, Handler._settings = _mfa_route, _privacy_route, _settings_route


def ip_allowed(ip, allowed):
    """Empty list = anyone who can sign in. Entries may be single addresses or CIDR networks."""
    if not allowed:
        return True
    try:
        addr = ipaddress.ip_address(ip.split("%")[0])
    except ValueError:
        return False
    for entry in allowed:
        try:
            if addr in ipaddress.ip_network(str(entry), strict=False):
                return True
        except ValueError:
            continue
    return False


def restart_process():
    """Restart the panel: under systemd exit non-zero (Restart=on-failure brings it back), otherwise re-run ourselves."""
    audit.applog("restart requested from the web panel")
    if os.environ.get("INVOCATION_ID") and not plat.IS_WIN:
        os._exit(3)
    try:
        os.execv(sys.executable, [sys.executable, "-m", "astra", "web"])
    except OSError:
        os._exit(3)


class Server(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR lets another process bind the same port, so use exclusive binding there.
    allow_reuse_address = not plat.IS_WIN

    def server_bind(self):
        if plat.IS_WIN and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def urls(host, port, tls=None):
    """Addresses to open in a browser (all local interfaces when bound to 0.0.0.0)."""
    if tls is None:
        tls = bool(config.cfg["tls_cert"] and config.cfg["tls_key"])
    scheme = "https" if tls else "http"
    if host not in ("0.0.0.0", "::", ""):
        return [f"{scheme}://{host}:{port}"]
    ips = ["127.0.0.1"]
    try:
        ips += [i[4][0] for i in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET) if i[4][0] not in ips]
    except OSError:
        pass
    return [f"{scheme}://{ip}:{port}" for ip in ips]


def make_server(host, port):
    return Server((host, port), Handler)


def serve():
    config.reload()
    if not config.has_admin():
        sys.exit("No admin account yet. Run: astra init")
    load_extensions()
    audit.prune()
    core.start_monitor()
    try:
        sitehost.start()   # built-in website engine (idle unless a site is enabled)
    except Exception as e:
        print(f"site engine not started: {e}", file=sys.stderr)
    host, port = config.cfg["host"], int(config.cfg["port"])
    srv = make_server(host, port)
    tls = bool(config.cfg["tls_cert"] and config.cfg["tls_key"])
    if tls:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(config.cfg["tls_cert"], config.cfg["tls_key"])
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    elif host not in ("127.0.0.1", "::1", "localhost"):
        print("WARNING: listening on a non-loopback address without TLS: passwords travel in clear text. "
              "Put it behind HTTPS (docs/SECURITY.md) or run: astra config set host 127.0.0.1", file=sys.stderr)
    if hasattr(signal, "SIGTERM"):  # `astra stop` / systemctl stop: leave cleanly so the pid file is removed
        signal.signal(signal.SIGTERM, lambda *a: sys.exit(0))
    if hasattr(signal, "SIGHUP"):
        signal.signal(signal.SIGHUP, lambda *a: config.reload())  # `systemctl reload astra` (Windows: config changes are picked up by the monitor thread)
    audit.log("start", host=host, port=port, tls=tls, extensions=sorted(registry))
    audit.applog(f"astra {__version__} listening on {host}:{port} tls={tls}")
    print(f"astra {__version__}  ({len(registry)} extensions)", flush=True)
    for u in urls(host, port, tls):
        print("  open", u, flush=True)
    daemon.write_pid()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("bye")
    finally:
        daemon.clear_pid()
