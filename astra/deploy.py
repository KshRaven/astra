"""Launch astra persistently (starts at boot, restarts if it stops) and publish it under a domain name.

  astra service install | remove | status     boot-time service: systemd on Linux, Task Scheduler (SYSTEM) on Windows
  astra domain set panel.example.com          reverse-proxy the panel under a domain (nginx if present, else the built-in site server)
  astra domain remove | show

The panel is also always reachable under a path prefix (default /astra/, setting `base_path`), e.g. http://localhost:8800/astra/
or, behind any reverse proxy, http://localhost/astra/. Standard library only.
"""
import os, re, shutil, subprocess, sys
from . import config, plat
from .errors import PanelError

TASK = "AstraPanel"
UNIT = "/etc/systemd/system/astra.service"
DOMAIN_RX = re.compile(r"^(?=.{1,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$|^localhost$")


def _run(args, timeout=30):
    try:
        r = subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=timeout,
                           stdin=subprocess.DEVNULL, creationflags=plat.NO_WINDOW)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError) as e:
        return 127, str(e)


def _command():
    exe = sys.executable
    if os.environ.get("ASTRA_HOME"):
        return exe, {"ASTRA_HOME": os.environ["ASTRA_HOME"]}
    return exe, {}


def service_status():
    if plat.IS_WIN:
        rc, out = _run(["schtasks", "/query", "/tn", TASK, "/fo", "LIST"])
        if rc:
            return {"installed": False, "running": False, "kind": "Task Scheduler task " + TASK}
        return {"installed": True, "running": bool(re.search(r"Running", out)), "kind": "Task Scheduler task " + TASK}
    if not plat.has_systemd():
        return {"installed": False, "running": False, "kind": "systemd (not available here)"}
    en = _run(["systemctl", "is-enabled", "astra"])[1].strip()
    act = _run(["systemctl", "is-active", "astra"])[1].strip()
    return {"installed": os.path.exists(UNIT) or en in ("enabled", "disabled"), "running": act == "active", "kind": "systemd unit astra.service"}


def service_install():
    if not plat.IS_ROOT:
        raise PanelError("installing the boot service needs " + ("an Administrator terminal" if plat.IS_WIN else "root (sudo)"), 403)
    exe, env = _command()
    if plat.IS_WIN:
        inner = f'"{exe}" -m astra web'
        if env:
            inner = f'set "ASTRA_HOME={env["ASTRA_HOME"]}" && ' + inner
        log = str(config.LOGDIR / "server.log")
        config.LOGDIR.mkdir(parents=True, exist_ok=True)
        tr = f'cmd /s /c "{inner} >> "{log}" 2>&1"'
        rc, out = _run(["schtasks", "/create", "/tn", TASK, "/tr", tr, "/sc", "onstart", "/ru", "SYSTEM", "/rl", "HIGHEST", "/f"])
        if rc:
            raise PanelError(out.strip()[-400:] or "schtasks failed", 400)
        _run(["schtasks", "/run", "/tn", TASK])
        return {"ok": True, "message": f"Installed. The panel now starts at boot (task {TASK}) and runs in the background."}
    if not plat.has_systemd():
        raise PanelError("this machine has no systemd; use `astra start` for a background process", 501)
    lines = ["[Unit]", "Description=astra server control panel", "After=network-online.target", "Wants=network-online.target", "",
             "[Service]", "Type=simple", "Environment=PYTHONUNBUFFERED=1"]
    lines += [f"Environment={k}={v}" for k, v in env.items()]
    lines += [f"ExecStart={exe} -m astra web", "Restart=on-failure", "RestartSec=3", "", "[Install]", "WantedBy=multi-user.target", ""]
    with open(UNIT, "w") as f:
        f.write("\n".join(lines))
    _run(["systemctl", "daemon-reload"])
    rc, out = _run(["systemctl", "enable", "--now", "astra"], 60)
    if rc:
        raise PanelError(out.strip()[-400:] or "systemctl failed", 400)
    return {"ok": True, "message": "Installed and started astra.service. It starts at boot and restarts if it stops."}


def service_remove():
    if not plat.IS_ROOT:
        raise PanelError("removing the boot service needs " + ("an Administrator terminal" if plat.IS_WIN else "root (sudo)"), 403)
    if plat.IS_WIN:
        _run(["schtasks", "/end", "/tn", TASK])
        rc, out = _run(["schtasks", "/delete", "/tn", TASK, "/f"])
        if rc and "cannot find" not in out.lower() and "does not exist" not in out.lower():
            raise PanelError(out.strip()[-300:], 400)
        return {"ok": True, "message": "Boot task removed. A running panel keeps running until stopped (astra stop)."}
    _run(["systemctl", "disable", "--now", "astra"], 60)
    try:
        os.remove(UNIT)
    except OSError:
        pass
    _run(["systemctl", "daemon-reload"])
    return {"ok": True, "message": "astra.service removed."}


def service_control(op):
    """start/stop the boot service (used by `astra stop` when the panel was not started by astra itself)."""
    if plat.IS_WIN:
        rc, out = _run(["schtasks", "/end" if op == "stop" else "/run", "/tn", TASK])
    else:
        rc, out = _run(["systemctl", op, "astra"], 60)
    return rc == 0, out.strip()


# ---------------------------------------------------------------- domain
def domain_info():
    d = config.cfg.get("domain", "")
    return {"domain": d, "base_path": config.cfg.get("base_path", "/astra"), "port": config.cfg["port"],
            "urls": ([f"http://{d}/"] if d else []) + [f"http://localhost:{config.cfg['port']}{config.cfg.get('base_path', '/astra')}/"]}


def _websites():
    from .extensions import load_extensions, registry
    if "websites" not in registry:
        load_extensions()
    ext = registry.get("websites")
    if not ext:
        raise PanelError("the Websites extension is disabled", 404)
    return ext


def set_domain(domain):
    domain = str(domain or "").strip().lower()
    if not DOMAIN_RX.match(domain):
        raise PanelError("that does not look like a domain name (example: panel.example.com)")
    ext = _websites()
    old = config.cfg.get("domain", "")
    if old and old != domain:
        clear_domain()
    upstream = f"http://127.0.0.1:{int(config.cfg['port'])}"
    try:
        ext.routes["add"][0]({"domain": domain, "type": "proxy", "target": upstream, "www": False})
    except PanelError as e:
        if e.status != 409:      # 409 = the site already exists, which is fine
            raise
    config.cfg["domain"] = domain
    config.save()
    return {"ok": True, "domain": domain,
            "message": f"{domain} now forwards to the panel. Point its DNS A record at this server; the site server listens on port "
                       f"{config.cfg.get('site_port', 8080)} unless nginx handles port 80."}


def clear_domain():
    d = config.cfg.get("domain", "")
    if d:
        try:
            _websites().routes["delete"][0]({"domain": d})
        except PanelError:
            pass
    config.cfg["domain"] = ""
    config.save()
    return {"ok": True}


def route(parts, method, params):
    """/api/panel/service[/install|remove|status], /api/panel/domain[/set|clear]"""
    if parts[0] == "service":
        step = parts[1] if len(parts) > 1 else "status"
        if step == "status":
            return service_status()
        if method != "POST":
            raise PanelError("POST required", 405)
        return {"install": service_install, "remove": service_remove}.get(step, lambda: (_ for _ in ()).throw(PanelError("not found", 404)))()
    if parts[0] == "domain":
        step = parts[1] if len(parts) > 1 else "show"
        if step == "show":
            return domain_info()
        if method != "POST":
            raise PanelError("POST required", 405)
        if step == "set":
            return set_domain(params.get("domain"))
        if step == "clear":
            return clear_domain()
    raise PanelError("not found", 404)
