import os, re, shutil, socket
from pathlib import Path
from .. import config, plat
from ..errors import PanelError
from ..shell import DOMAIN, EMAIL, need, run, safe_path
from . import Extension
from .. import catalog, jobs, sitehost

WIN = plat.IS_WIN
PREFIX = "astra-"
UPSTREAM = re.compile(r"^https?://[A-Za-z0-9.-]{1,253}(:\d{1,5})?$")
PATH_OK = re.compile(r"^(?:[A-Za-z]:)?/[A-Za-z0-9_./-]+$")   # nginx paths use forward slashes, also on Windows
META = re.compile(r"^# astra:type=(\w+) target=(\S+)")

EXT = Extension("websites", "Websites", "globe", order=20, group="Server",
                description="Host websites, point domain names at them, run apps behind a reverse proxy and get HTTPS certificates.")

STATIC_T = """# astra:type=static target=@TARGET@
server {
    listen 80;
    listen [::]:80;
    server_name @DOMAIN@;
    root @TARGET@;
    index index.html index.htm;
    location / { try_files $uri $uri/ =404; }
}
"""
PROXY_T = """# astra:type=proxy target=@TARGET@
server {
    listen 80;
    listen [::]:80;
    server_name @DOMAIN@;
    location / {
        proxy_pass @TARGET@;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
"""
REDIRECT_T = """# astra:type=redirect target=@TARGET@
server {
    listen 80;
    listen [::]:80;
    server_name @DOMAIN@;
    return 301 @TARGET@$request_uri;
}
"""


def _nginx_dir():
    """Folder holding nginx.conf. Linux: /etc/nginx. Windows: <nginx folder>\\conf (found via PATH / bin_dirs)."""
    env = os.environ.get("ASTRA_NGINX_DIR") or config.cfg.get("nginx_dir")
    if env:
        return Path(env)
    if WIN:
        exe = plat.which("nginx")
        return Path(exe).parent / "conf" if exe else Path(os.environ.get("SystemDrive", "C:") + "\\nginx\\conf")
    return Path("/etc/nginx")


def _dirs():
    n = _nginx_dir()
    return n / "sites-available", n / "sites-enabled"


def _have():
    return bool(plat.which("nginx"))


def _builtin():
    """True when Astra's own web engine serves the sites (nginx missing, or site_engine = builtin)."""
    return config.cfg.get("site_engine") == "builtin" or not _have()


def _need_nginx():
    if not _have():
        raise PanelError("Nginx is not installed yet. Install it from Services > Software library (or the button on this page).", 404)


def _nginx(*args, timeout=30):
    _need_nginx()
    # Windows nginx finds conf/ and logs/ relative to its prefix, so run it from there
    return run(["nginx", *args], timeout=timeout, cwd=str(_nginx_dir().parent) if WIN else None)


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:   # no BOM, LF line endings (nginx dislikes a BOM)
        f.write(text)


def _enable(conf, link):
    """Linux: symlink (Debian layout). Windows: symlinks need a privilege, so enabling copies the file."""
    if WIN:
        shutil.copyfile(conf, link)
    else:
        link.symlink_to(conf)


def _test_reload():
    rc, out = _nginx("-t")
    if rc:
        raise PanelError("nginx -t failed: " + out[-600:])
    rc, out = _nginx("-s", "reload")
    if rc:
        raise PanelError("nginx reload failed: " + out.strip()[-400:] + (" (is nginx running? start it in the Services tab)" if WIN else ""))


def _domain(p):
    return need(str(p.get("domain", "")).strip().lower(), DOMAIN, "domain")


def _flag(v):
    return v in (True, "true", "1", "on", 1)


@EXT.route("list")
def list_(p):
    if _builtin():
        return sitehost.listing()
    avail, enabled = _dirs()
    rows = []
    for f in sorted(avail.glob(PREFIX + "*")):
        text = f.read_text(encoding="utf-8", errors="replace")
        m = META.match(text.split("\n", 1)[0])
        names = re.search(r"server_name\s+([^;]+);", text)
        rows.append({"domain": f.name[len(PREFIX):], "type": m[1] if m else "?", "target": m[2] if m else "",
                     "https": "ssl_certificate" in text, "aliases": " ".join(names[1].split()[1:]) if names else "",
                     "state": "enabled" if (enabled / f.name).exists() else "disabled"})
    return rows


@EXT.route("status")
def status(p):
    ips = plat.local_ips()
    if _builtin():
        st = sitehost.status()
        base = [["Web server", "Astra built-in" + (" (nginx is not installed)" if not _have() else "")],
                ["Running", ("Yes, port %s" % st["port"]) if st["running"] else (st["error"] or "Starts when you add a site")],
                ["Sites managed here", str(len(sitehost.listing()))], ["Open a site without DNS", "http://%s:%s/<domain>/" % ((ips or ["SERVER-IP"])[0], st["port"])]]
        return {"pairs": base + [["This server's addresses", ", ".join(ips) or "unknown"]]}
    if not _have():
        return {"pairs": [["Nginx", "Not installed"], ["This server's addresses", ", ".join(ips) or "unknown"]]}
    rc, out = run(["nginx", "-v"])
    running = False
    if WIN:
        rc2, o2 = run(["tasklist", "/FI", "IMAGENAME eq nginx.exe", "/NH"])
        running = "nginx.exe" in o2
    else:
        running = run(["systemctl", "is-active", "nginx"])[1].strip() == "active"
    n = len(list_({}))
    return {"pairs": [["Nginx", out.strip().replace("nginx version: ", "") or "installed"], ["Running", "Yes" if running else "No: start it in Services"],
                      ["Sites managed here", str(n)], ["This server's addresses", ", ".join(ips) or "unknown"],
                      ["Config folder", str(_nginx_dir())]]}


@EXT.route("install_nginx", write=True)
def install_nginx(p):
    title, steps, env = catalog.install_plan("nginx")
    j = jobs.start(title, steps, kind="install", env=env, ext="websites")
    return {"job": j.id, "title": title}


@EXT.route("config")
def config_(p):
    if _builtin():
        return {"text": sitehost.config_text(p.get("domain"))}
    f = _dirs()[0] / (PREFIX + _domain(p))
    if not f.exists():
        raise PanelError("unknown site", 404)
    return {"text": f.read_text(encoding="utf-8", errors="replace")}


@EXT.route("retarget", write=True)
def retarget(p):
    """Change the folder / upstream / redirect target of a site (keeps HTTPS blocks that certbot added)."""
    if _builtin():
        sitehost.retarget(p.get("domain"), str(p.get("target", "")).strip())
        return {"ok": True}
    domain = _domain(p)
    f = _dirs()[0] / (PREFIX + domain)
    if not f.exists():
        raise PanelError("unknown site", 404)
    text = f.read_text(encoding="utf-8")
    m = META.match(text.split("\n", 1)[0])
    if not m:
        raise PanelError("this site was not created by Astra; edit its file by hand")
    kind, old = m[1], m[2]
    new = str(p.get("target", "")).strip()
    if kind == "static":
        new = safe_path(new, config.cfg["web_roots"]).replace("\\", "/")
        if not PATH_OK.match(new):
            raise PanelError("path may only contain letters, digits and . _ / - (no spaces)")
        os.makedirs(new, exist_ok=True)
    elif kind == "proxy":
        need(new, UPSTREAM, "upstream URL (e.g. http://127.0.0.1:3000)")
    elif kind == "redirect":
        need(new, UPSTREAM, "address to send visitors to (e.g. https://example.org)")
    updated = text.replace(old, new)
    _write(f, updated)
    try:
        _test_reload()
    except Exception:
        _write(f, text)
        raise
    return {"ok": True}


@EXT.route("dnscheck")
def dnscheck(p):
    domain = _domain(p)
    ips = set(plat.local_ips())
    try:
        found = sorted({i[4][0] for i in socket.getaddrinfo(domain, None, socket.AF_INET)})
    except OSError:
        return {"text": f"{domain} does not resolve yet.\n\nAt your domain registrar add an A record:\n  Name: {domain}\n  Value: <this server's public IP address>\nDNS changes can take from a few minutes up to a day."}
    mine = [i for i in found if i in ips]
    if mine:
        return {"text": f"OK: {domain} points to {', '.join(found)}, which is an address of this machine."}
    return {"text": f"{domain} points to {', '.join(found)}.\nThis machine's local addresses are {', '.join(sorted(ips)) or 'unknown'}.\n"
                    "If this server is behind a router or cloud firewall that is normal (the public address differs from the local one). "
                    "If the domain should point here, update its A record at your registrar."}


@EXT.route("certs")
def certs(p):
    if WIN or not plat.which("certbot"):
        return []
    rc, out = run(["certbot", "certificates"], timeout=60)
    rows = []
    for blk in re.split(r"\n\s*Certificate Name: ", "\n" + out)[1:]:
        name = blk.split("\n", 1)[0].strip()
        dom = re.search(r"Domains: (.+)", blk)
        exp = re.search(r"Expiry Date: (\S+ \S+).*?\((VALID|INVALID)[: ]*(\d+)?", blk)
        rows.append({"name": name, "domains": dom[1].strip() if dom else "", "expires": exp[1] if exp else "?",
                     "days": int(exp[3]) if exp and exp[3] else 0, "state": "valid" if exp and exp[2] == "VALID" else "expired"})
    return rows


@EXT.route("renew", write=True)
def renew(p):
    if WIN or not plat.which("certbot"):
        raise PanelError("certbot is not installed", 404)
    j = jobs.start("Renew certificates", [["certbot", "renew"]], kind="task", ext="websites")
    return {"job": j.id}


@EXT.route("add", write=True)
def add(p):
    if _builtin():
        sitehost.add(p.get("domain"), p.get("type"), str(p.get("target") or "").strip(), _flag(p.get("www")))
        return {"ok": True, "message": "Site added. Open it at http://<this server>:%s/%s/ until the domain points here." % (sitehost.status()["port"], str(p.get("domain")).strip().lower())}
    _need_nginx()
    domain, kind = _domain(p), p.get("type")
    names = domain + (" www." + domain if _flag(p.get("www")) and domain.count(".") == 1 else "")
    if kind == "static":
        target = safe_path(str(p.get("target") or os.path.join(config.cfg["web_roots"][0], domain)), config.cfg["web_roots"])
        if WIN:
            target = target.replace("\\", "/")
        if not PATH_OK.match(target):
            raise PanelError("path may only contain letters, digits and . _ / - (no spaces)")
        os.makedirs(target, exist_ok=True)
        idx = Path(target) / "index.html"
        if not idx.exists():
            idx.write_text(f"<!doctype html><title>{domain}</title><h1>{domain}</h1>\n", encoding="utf-8")
        tpl = STATIC_T
    elif kind == "proxy":
        target = need(str(p.get("target", "")), UPSTREAM, "upstream URL (e.g. http://127.0.0.1:3000)")
        tpl = PROXY_T
    elif kind == "redirect":
        target = need(str(p.get("target", "")), UPSTREAM, "address to send visitors to (e.g. https://example.org)")
        tpl = REDIRECT_T
    else:
        raise PanelError("type must be static, proxy or redirect")
    avail, enabled = _dirs()
    avail.mkdir(parents=True, exist_ok=True)
    enabled.mkdir(parents=True, exist_ok=True)
    name = PREFIX + domain
    conf, link = avail / name, enabled / name
    if conf.exists():
        raise PanelError("site already exists", 409)
    _write(conf, tpl.replace("@DOMAIN@", names).replace("@TARGET@", target))
    try:
        _enable(conf, link)
        _test_reload()
    except Exception:
        conf.unlink(missing_ok=True)
        link.unlink(missing_ok=True)
        raise
    return {"ok": True}


@EXT.route("toggle", write=True)
def toggle(p):
    if _builtin():
        sitehost.toggle(p.get("domain"))
        return {"ok": True}
    avail, enabled = _dirs()
    name = PREFIX + _domain(p)
    conf, link = avail / name, enabled / name
    if not conf.exists():
        raise PanelError("unknown site", 404)
    was = link.exists()
    link.unlink(missing_ok=True) if was else _enable(conf, link)
    try:
        _test_reload()
    except Exception:
        link.unlink(missing_ok=True)
        if was:
            _enable(conf, link)
        raise
    return {"ok": True}


@EXT.route("delete", write=True)
def delete(p):
    if _builtin():
        sitehost.delete(p.get("domain"))
        return {"ok": True}
    avail, enabled = _dirs()
    name = PREFIX + _domain(p)
    (enabled / name).unlink(missing_ok=True)
    (avail / name).unlink(missing_ok=True)
    _test_reload()
    return {"ok": True}


@EXT.route("ssl", write=True)
def ssl(p):
    if _builtin():
        raise PanelError("HTTPS needs nginx (or a TLS proxy in front of Astra's built-in web server). Install Nginx from Services, then request the certificate.", 501)
    if WIN:
        raise PanelError("automatic certificates use certbot's nginx plugin, which is Linux-only. On Windows get a certificate "
                         "with win-acme (wacs.exe) or certbot certonly, then add ssl_certificate lines to the site by hand.", 501)
    if not plat.which("certbot"):
        raise PanelError("Certbot is not installed. Install it from Services > Software library.", 404)
    domain, email = _domain(p), need(p.get("email"), EMAIL, "email")
    if not (_dirs()[0] / (PREFIX + domain)).exists():
        raise PanelError("unknown site", 404)
    rc, out = run(["certbot", "--nginx", "-d", domain, "-m", email, "--agree-tos", "--no-eff-email",
                   "--redirect", "--non-interactive"], timeout=180)
    if rc:
        raise PanelError(out[-800:])
    return {"text": out[-1500:]}


@EXT.route("test")
def test(p):
    if _builtin():
        return {"text": "Astra's built-in web server is in use; there is no nginx configuration to test.\nInstall Nginx (Services > Software library) for HTTPS, WebSockets and heavy traffic."}
    text = _nginx("-t")[1]
    if WIN:  # Windows nginx has no sites-enabled convention; the include line has to be added once
        try:
            conf = (_nginx_dir() / "nginx.conf").read_text(encoding="utf-8", errors="replace")
        except OSError:
            conf = ""
        if "sites-enabled" not in conf:
            text += "\nNOTE: add `include sites-enabled/*;` inside the http { } block of nginx.conf, or Astra's sites are not loaded."
    return {"text": text}


def _sections():
    have = _have()
    help_ = {"type": "help", "title": "What is this page?", "text": "A website needs three things: a web server (Nginx) to answer visitors, your site's files (or an app running on a port), and a domain name pointing at this server. "
             "This page connects them.",
             "steps": [["Nginx is optional:", "without it Astra serves sites itself; install Nginx from Services for HTTPS and heavy traffic."], ["Add a site:", "give the domain, choose what it serves."],
                       ["Point the domain here:", "at your registrar create an A record to this server's IP. Use the Domain check tab to verify."], ["Turn on HTTPS:", "request a free certificate on the Certificates tab."]],
             "example": {"title": "Example", "text": "A Node app listens on port 3000. Add site: domain app.example.com, type Reverse proxy, target http://127.0.0.1:3000. Visitors reach it on ports 80/443 and your app stays private."}}
    note = None
    if not have:
        note = {"type": "notice", "level": "ok", "title": "Using Astra's built-in web server", "text": "Nginx is not installed, so Astra serves your sites itself on port %s: folders, reverse proxy and redirects all work. Install Nginx later if you need HTTPS certificates, WebSockets or heavy traffic." % config.cfg.get("site_port", 8080),
                "actions": [{"label": "Install Nginx", "route": "install_nginx", "icon": "download", "confirm": "Install Nginx on this server? The progress shows in the console."}]}
    site_actions = [{"label": "Disable", "route": "toggle", "params": {"domain": "$domain"}, "if": {"state": ["enabled"]}},
                    {"label": "Enable", "route": "toggle", "params": {"domain": "$domain"}, "if": {"state": ["disabled"]}},
                    {"label": "Change target", "route": "retarget", "params": {"domain": "$domain"}, "more": True,
                     "form": [{"name": "target", "label": "New folder, upstream URL or redirect address", "value": "$target", "required": True}]},
                    {"label": "View config", "route": "config", "method": "GET", "params": {"domain": "$domain"}, "more": True, "quiet": True},
                    {"label": "Delete", "route": "delete", "params": {"domain": "$domain"}, "danger": True,
                     "confirm": "Delete the site $domain? Its files on disk are kept."}]
    add_fields = [{"name": "domain", "label": "Domain name", "required": True, "placeholder": "example.com", "help": "Only the name, without https://"},
                  {"name": "type", "label": "What should it do?", "type": "select", "options": [{"value": "static", "label": "Serve files from a folder (a normal website)"}, {"value": "proxy", "label": "Reverse proxy to an app (Node, Python, Docker...)"}, {"value": "redirect", "label": "Redirect to another address"}]},
                  {"name": "target", "label": "Folder, app address or redirect address", "placeholder": os.path.join(plat.EXAMPLE_ROOT, "example.com") + "   |   http://127.0.0.1:3000   |   https://example.org",
                   "help": "Folder for a website (blank = a new folder under your web root), http://127.0.0.1:PORT for an app, or the full address for a redirect.", "wide": True},
                  {"name": "www", "label": "Also answer on www.", "type": "checkbox", "value": True}]
    return [help_] + ([note] if note else []) + [{"type": "kv", "title": "Web server", "source": "status", "refresh": 15},
            {"type": "tabs", "tabs": [
                {"id": "sites", "title": "Sites", "icon": "globe", "sections": [{"type": "table", "title": "Your sites", "source": "list", "refresh": 15,
                    "columns": [["Domain", "domain"], ["What it does", "type"], ["Target", "target", "mono"], ["HTTPS", "https", "bool"], ["State", "state", "state"]], "actions": site_actions,
                    "empty": {"icon": "globe", "title": "No sites yet", "text": "Add your first site: a folder of web pages, an app behind a reverse proxy, or a redirect.", "actions": [{"label": "Add a site", "go": "websites", "sub": "add", "primary": True, "icon": "plus"}]}}]},
                {"id": "add", "title": "Add a site", "icon": "plus", "sections": [{"type": "form", "title": "New site", "route": "add", "submit": "Create site", "icon": "plus", "fields": add_fields,
                    "note": "Nginx is tested before the change goes live; a bad config is rolled back automatically."}]},
                {"id": "certificates", "title": "Certificates", "icon": "lock", "sections": [
                    {"type": "table", "title": "HTTPS certificates", "source": "certs", "refresh": 60, "buttons": [{"label": "Renew all now", "route": "renew", "icon": "refresh", "confirm": "Ask Let's Encrypt to renew every certificate that is due?"}],
                     "columns": [["Name", "name"], ["Domains", "domains"], ["Expires", "expires"], ["Days left", "days", "num"], ["State", "state", "state"]],
                     "empty": {"icon": "lock", "title": "No certificates yet", "text": "Request one below once your domain points at this server. Certbot renews them automatically."}},
                    {"type": "form", "title": "Get a free certificate (Let's Encrypt)" if not WIN else "HTTPS certificate (not automated on Windows)", "route": "ssl", "submit": "Request certificate", "icon": "lock",
                     "fields": [{"name": "domain", "label": "Site domain", "required": True}, {"name": "email", "label": "E-mail for expiry notices", "required": True}],
                     "note": "The domain must already point at this server and port 80 must be reachable from the internet."}]},
                {"id": "domain", "title": "Domain check", "icon": "network", "sections": [
                    {"type": "form", "title": "Is my domain pointed here?", "route": "dnscheck", "method": "GET", "submit": "Check", "icon": "search", "reset": False,
                     "fields": [{"name": "domain", "label": "Domain name", "required": True, "placeholder": "example.com"}]}]},
                {"id": "nginx", "title": "Nginx", "icon": "terminal", "sections": [{"type": "text", "title": "Configuration test (nginx -t)", "source": "test"}]}]}]


EXT.sections = _sections
