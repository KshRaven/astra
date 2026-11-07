"""Command line interface: `astra --help`."""
import argparse, json, os, socket, sys, time
from . import __version__, audit, config, daemon, deploy, mfa, monitor, plat
from .errors import PanelError
from .extensions import Raw, load_extensions, registry

TTY = sys.stdout.isatty()
START_HINT = "systemctl start astra" if not plat.IS_WIN else 'schtasks /run /tn AstraPanel'


def _console():
    """Windows: UTF-8 output (bars use block characters) and ANSI colours on the console."""
    if not plat.IS_WIN:
        return
    for st in (sys.stdout, sys.stderr):
        if hasattr(st, "reconfigure"):
            st.reconfigure(encoding="utf-8", errors="replace")
    try:
        import ctypes
        k = ctypes.windll.kernel32
        h, m = k.GetStdHandle(-11), ctypes.c_ulong()
        if k.GetConsoleMode(h, ctypes.byref(m)):
            k.SetConsoleMode(h, m.value | 4)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
    except Exception:
        pass


def c(code, s):
    return f"\033[{code}m{s}\033[0m" if TTY else str(s)


def bar(v, width=24):
    n = int(width * min(max(v, 0), 100) / 100)
    col = "32" if v < 70 else "33" if v < 90 else "31"
    return c(col, "█" * n) + c("2", "░" * (width - n))


def size(n):
    n = float(n)
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or u == "TB":
            return f"{n:.1f} {u}" if u != "B" else f"{int(n)} B"
        n /= 1024


def table(rows):
    if not rows:
        return print(c("2", "(nothing here)"))
    keys = list(rows[0])
    cell = lambda v: str(v)[:60]
    widths = [max(len(k), *(len(cell(r.get(k, ""))) for r in rows)) for k in keys]
    print(c("1;36", "  ".join(k.upper().ljust(w) for k, w in zip(keys, widths))))
    for r in rows:
        print("  ".join(cell(r.get(k, "")).ljust(w) for k, w in zip(keys, widths)))


def show(res):
    if isinstance(res, Raw):
        print(f"(binary, {len(res.data)} bytes: {res.filename})")
    elif isinstance(res, list) and res and isinstance(res[0], dict):
        table(res)
    elif isinstance(res, dict) and "text" in res:
        print(res["text"])
    else:
        print(json.dumps(res, indent=2))


def _prepare_home():
    try:
        for d in (config.HOME, config.HOME / "extensions", config.LOGDIR):
            d.mkdir(parents=True, exist_ok=True)
            plat.secure(d)  # chmod 700 on Linux, restricted ACL on Windows
    except PermissionError:
        sys.exit(f"Cannot write to {config.HOME} as this user. Run it with sudo (sudo astra ...), "
                 "or use a private config instead:  ASTRA_HOME=~/.astra astra init")


def _show_login(user, pw=None):
    from .server import urls
    print(c("1", "\nSign in to the panel:"))
    for u in urls(config.cfg["host"], int(config.cfg["port"])):
        print(f"  {u}")
    print(f"  username: {user}")
    if pw:
        print(f"  password: {pw}   (shown once; change it with: astra passwd)")


def cmd_init(a):
    """Create the config folder and the admin account (like aaPanel: user + password, no tokens)."""
    _prepare_home()
    if config.has_admin() and not a.reset:
        print(f"Already initialised ({config.CONFIG}). Use --reset to set a new username/password.")
        return
    user = a.user or (config.cfg["admin"]["username"] if config.has_admin() else "admin")
    pw = a.password or config.new_password()
    try:
        config.set_admin(user, pw)
    except ValueError as e:
        sys.exit(str(e))
    config.save()
    print(f"Config: {config.CONFIG}")
    _show_login(user, None if a.password else pw)
    print(f"\nBring the website up with:  astra start     (foreground: astra web;  as a service: {START_HINT})")


def cmd_passwd(a):
    import getpass
    if not config.has_admin():
        sys.exit("No admin account yet. Run: astra init")
    pw = a.password
    if not pw:
        pw = getpass.getpass("New password: ")
        if pw != getpass.getpass("Repeat it: "):
            sys.exit("passwords do not match")
    try:
        config.set_admin(a.user, pw)
    except ValueError as e:
        sys.exit(str(e))
    config.save()
    audit.log("account_changed", ip="cli", user=config.cfg["admin"]["username"])
    print("Password updated for", config.cfg["admin"]["username"], "(open sessions end when the panel restarts).")


def cmd_user(a):
    print(config.cfg["admin"]["username"] or "(not set: run astra init)")


def _ensure_admin():
    """First run straight after `pip install .`: create the config folder and the admin account, show the sign-in once."""
    if config.has_admin():
        return False
    _prepare_home()
    pw = config.new_password()
    config.set_admin("admin", pw)
    config.save()
    print(c("1", "First run: the admin account was created."))
    _show_login("admin", pw)
    print()
    return True


def cmd_serve(a):
    from .server import serve
    _ensure_admin()
    if getattr(a, "host", None):
        config.cfg["host"] = a.host
    if getattr(a, "port", None):
        config.cfg["port"] = a.port
    if getattr(a, "open", False):
        import threading, webbrowser
        from .server import urls
        threading.Timer(1.5, lambda: webbrowser.open(urls("127.0.0.1" if config.cfg["host"] in ("0.0.0.0", "::") else config.cfg["host"], int(config.cfg["port"]))[0])).start()
    serve()


def cmd_start(a):
    """Run the web panel in the background (no systemd or service needed)."""
    from .server import urls
    _ensure_admin()
    ok, msg = daemon.start()
    print(("" if ok else c("31", "error: ")) + f"web panel: {msg}")
    if ok:
        for u in urls(config.cfg["host"], int(config.cfg["port"])):
            print("  open", u)
        print(f"  user: {config.cfg['admin']['username']}   (forgot the password? astra passwd)")
    sys.exit(0 if ok else 1)


def cmd_stop(a):
    ok, msg = daemon.stop()
    print(("" if ok else c("31", "error: ")) + f"web panel: {msg}")
    sys.exit(0 if ok else 1)


def cmd_restart(a):
    daemon.stop()
    cmd_start(a)


def cmd_service(a):
    """astra service install|remove|status: keep the panel running at boot (systemd / Task Scheduler)."""
    try:
        if a.action == "install":
            print(deploy.service_install()["message"])
        elif a.action == "remove":
            print(deploy.service_remove()["message"])
        else:
            st = deploy.service_status()
            print(f"{st['kind']}: " + ("installed, " + ("running" if st["running"] else "not running") if st["installed"] else "not installed (astra service install)"))
    except PanelError as e:
        sys.exit(c("31", "error: ") + e.message)


def cmd_domain(a):
    """astra domain set panel.example.com | remove | show"""
    try:
        if a.action == "set":
            if not a.name:
                sys.exit("give a domain: astra domain set panel.example.com")
            print(deploy.set_domain(a.name)["message"])
            if a.persist:
                print(deploy.service_install()["message"])
        elif a.action == "remove":
            deploy.clear_domain()
            print("domain removed")
        else:
            d = deploy.domain_info()
            print(f"domain: {d['domain'] or '(none)'}")
            for u in d["urls"]:
                print("  ", u)
    except PanelError as e:
        sys.exit(c("31", "error: ") + e.message)


def cmd_url(a):
    from .server import urls
    for u in urls(config.cfg["host"], int(config.cfg["port"])):
        print(u)


def _run_plan(title, steps, env):
    """Run an install/uninstall plan from catalog.py in the foreground with the output on screen."""
    import subprocess
    from .shell import _resolve
    print(c("1;36", title))
    full_env = {**os.environ, **env}
    for step in steps:
        optional = False
        if isinstance(step, dict):
            step, optional = step["cmd"], step.get("optional", False)
        if callable(step):
            out = step()
            if out:
                print(out)
            continue
        argv = _resolve(list(step))
        print(c("2", "$ " + " ".join(argv)), flush=True)
        try:
            rc = subprocess.run(argv, env=full_env, creationflags=plat.NO_WINDOW).returncode
        except OSError as e:
            sys.exit(c("31", "error: ") + str(e))
        if rc and not optional:
            sys.exit(c("31", f"failed (exit code {rc})"))
    print(c("32", "done"))


def _plan_args(a, uninstall):
    from . import catalog
    try:
        e = catalog.get(a.name)
        return (catalog.uninstall_plan if uninstall else catalog.install_plan)(e["id"])
    except PanelError as err:
        sys.exit(c("31", "error: ") + err.message)


def cmd_install(a):
    """astra install nginx   (see `astra catalog` for the list)"""
    audit.log("action", ip="cli", ext="services", route="install", params={"name": a.name})
    _run_plan(*_plan_args(a, False))


def cmd_uninstall(a):
    if not a.yes and input(f"Remove {a.name}? Its data is kept. Type 'yes': ") != "yes":
        sys.exit("cancelled")
    audit.log("action", ip="cli", ext="services", route="uninstall", params={"name": a.name})
    _run_plan(*_plan_args(a, True))


def cmd_catalog(a):
    from . import catalog
    rows = [{"id": r["id"], "state": "not installed" if not r["installed"] else r["state"], "category": r["category"],
             "what": r["summary"][:70]} for r in catalog.listing()]
    table(rows)
    print(c("2", "\nInstall with: astra install <id>      Remove with: astra uninstall <id>"))


def cmd_notes(a):
    from . import notify
    f = notify.feed(a.n, unread=not a.all)
    if not f["items"]:
        return print(c("32", "Nothing needs your attention."))
    for i in f["items"]:
        col = {"critical": "31", "warning": "33", "ok": "32"}.get(i["sev"], "0")
        print(c(col, f"{time.strftime('%d %b %H:%M', time.localtime(i['ts']))}  {i['sev']:<8} [{i['cat']}] {i['title']}"))
    if a.read:
        notify.mark_read()


def cmd_status(a):
    m = monitor.Monitor()
    time.sleep(0.6)
    s, mem, info = m.sample(), monitor.meminfo(), monitor.system_info()
    print(c("1", f"{info['hostname']}") + f"  {info['os']}  {'build' if plat.IS_WIN else 'kernel'} {info['kernel']}  up {info['uptime'] // 3600}h")
    la = monitor.loadavg()
    print(f"CPU    {bar(s['cpu'])} {s['cpu']:5.1f}%  " + (f"load {la[0]:.2f}/{info['cpus']}" if la else f"{info['cpus']} CPUs"))
    print(f"Memory {bar(s['mem'])} {s['mem']:5.1f}%  {size(mem['used'])} / {size(mem['total'])}")
    for d in monitor.disks():
        p = 100 * d["used"] / d["total"] if d["total"] else 0
        print(f"Disk   {bar(p)} {p:5.1f}%  {d['mount']}  {size(d['used'])} / {size(d['total'])}")
    from .server import urls
    up = daemon.listening()
    print(f"Web    {c('32', 'running') if up else c('33', 'stopped')}  " + (urls(config.cfg['host'], int(config.cfg['port']))[0] if up else "start it with: astra start"))


def cmd_ext(a):
    load_extensions()
    rows = [{"name": e.name, "available": "yes" if e.available else "missing: " + ",".join(e.missing),
             "routes": ",".join(e.routes), "about": e.description} for e in registry.values()]
    table(sorted(rows, key=lambda r: r["name"]))


def cmd_call(a):
    """Run any extension route locally: astra call docker containers"""
    load_extensions()
    ext = registry.get(a.ext)
    if not ext:
        sys.exit(f"unknown extension '{a.ext}'. Try: astra ext")
    if a.route not in ext.routes:
        sys.exit(f"unknown route. Available: {', '.join(ext.routes)}")
    params = dict(kv.split("=", 1) for kv in a.params if "=" in kv)
    fn, write = ext.routes[a.route]
    try:
        if write:
            audit.log("action", ip="cli", ext=a.ext, route=a.route, params=audit.redact(params))
        show(fn(params))
    except PanelError as e:
        sys.exit(c("31", "error: ") + e.message)


def cmd_svc(a):
    a.ext, a.route, a.params = "services", "action", [f"name={a.name}", f"op={a.op}"]
    cmd_call(a)


def cmd_services(a):
    a.ext, a.route, a.params = "services", "list", []
    cmd_call(a)


def cmd_config(a):
    shown = config.public()
    if a.action == "set":
        protected = ("admin", "mfa")  # changed with `astra passwd`, `astra mfa` or the Settings page
        if a.key in protected or a.key not in config.DEFAULTS:
            sys.exit(f"unknown or protected key. Valid: {', '.join(k for k in config.DEFAULTS if k not in protected)}")
        try:
            config.cfg[a.key] = json.loads(a.value)
        except ValueError:
            config.cfg[a.key] = a.value
        config.save()
        print(f"{a.key} updated. A running panel picks it up within a few seconds (restart it for host/port/tls changes).")
    else:
        print(json.dumps(shown, indent=2))


def cmd_logs(a):
    for r in reversed(audit.tail(a.n)):
        print(time.strftime("%F %T", time.localtime(r.pop("ts"))), r.pop("event"), json.dumps(r))


def cmd_mfa(a):
    if a.action == "reset":
        mfa.reset_all()
        print("All second factors removed. Sign-in needs only the password again. Re-enable in Settings.")
    elif a.action == "test-email":
        to = a.to or config.cfg["mfa"].get("email")
        if not to:
            sys.exit("give an address: astra mfa test-email you@example.com")
        try:
            mfa.send_mail(to, "astra test", "SMTP works. You can enable e-mail sign-in codes in Settings.")
        except PanelError as e:
            sys.exit(c("31", "error: ") + e.message)
        print("sent to", to)
    else:
        st = mfa.status()
        print(f"authenticator app: {'on' if st['totp'] else 'off'}\ne-mail codes:      {'on (' + st['email_address'] + ')' if st['email'] else 'off'}\nSMTP configured:   {'yes' if st['smtp_configured'] else 'no'}")


def cmd_privacy(a):
    if a.action == "export":
        print(json.dumps({"config": config.public(), "audit_events": audit.tail(5000)}, indent=2))
    else:
        if not a.yes and input("Delete the audit log, authenticator secret and MFA e-mail? Type 'delete': ") != "delete":
            sys.exit("cancelled")
        n = audit.erase()
        mfa.reset_all()
        audit.log("privacy_delete", files=n)
        print(f"Deleted {n} audit file(s) and cleared MFA data. Restart/reload the panel to drop open sessions.")


def cmd_tui(a):
    _ensure_admin()
    try:
        from .tui import main as tui
    except ImportError:
        sys.exit("The terminal app needs curses. Windows: pip install windows-curses (pip install . does this for you). Or use: astra status / astra web")
    tui()


def cmd_doctor(a):
    bad = 0

    def line(ok, msg):
        nonlocal bad
        bad += ok is False
        print({True: c("32", "[ ok ]"), False: c("31", "[FAIL]"), None: c("33", "[warn]")}[ok], msg)

    line(sys.version_info >= (3, 9), f"Python {sys.version.split()[0]} (need 3.9+) on {monitor.system_info()['os']}")
    line(config.CONFIG.exists(), f"config file {config.CONFIG}")
    if config.CONFIG.exists():
        priv = plat.perms_private(config.CONFIG)
        line(True if priv is None else priv, "config permissions are private (0600)" if priv is not None else "config folder ACL is set by `astra init` (inspect with: icacls " + str(config.HOME) + ")")
    line(config.has_admin(), "admin account is set" if config.has_admin() else "no admin account yet: run astra init")
    line(True if mfa.required() else None, "multi-factor sign-in is on (" + ", ".join(mfa.methods()) + ")" if mfa.required() else "multi-factor sign-in is off (enable it in Settings)")
    tls = bool(config.cfg["tls_cert"] and config.cfg["tls_key"])
    loop = config.cfg["host"] in ("127.0.0.1", "::1", "localhost")
    line(True if (loop or tls) else None, f"bind {config.cfg['host']}:{config.cfg['port']} ({'TLS' if tls else 'plain HTTP: passwords are not encrypted; use HTTPS or host=127.0.0.1'})")
    who = "Administrator" if plat.IS_WIN else "root"
    line(None if not config.IS_ROOT else True, f"running as {who} (needed to manage services, firewall, scheduled tasks)" if config.IS_ROOT else f"not {who}: service/firewall/nginx actions will fail")
    with socket.socket() as s:
        s.settimeout(0.5)
        up = s.connect_ex((("127.0.0.1" if loop else config.cfg["host"]), int(config.cfg["port"]))) == 0
    line(True, "server is " + ("listening" if up else "not running"))
    load_extensions()
    for e in sorted(registry.values(), key=lambda e: e.name):
        line(True if e.available else None, f"extension {e.name}" + ("" if e.available else f" (missing: {', '.join(e.missing)})"))
    sys.exit(1 if bad else 0)


def main(argv=None):
    p = argparse.ArgumentParser(prog="astra", description="Server control panel. Run `astra` with no arguments for the terminal app; `astra start` brings the website up in the background. Every screen has a command: install, catalog, svc, notes, call ...")
    p.add_argument("-V", "--version", action="version", version=__version__)
    sp = p.add_subparsers(dest="cmd", metavar="command")
    s = sp.add_parser("init", help="create the config and the admin account"); s.add_argument("--user"); s.add_argument("--password"); s.add_argument("--reset", action="store_true"); s.set_defaults(f=cmd_init)
    s = sp.add_parser("web", aliases=["serve"], help="run the web panel (first run creates the admin account)"); s.add_argument("--host"); s.add_argument("--port", type=int); s.add_argument("--open", action="store_true", help="open a browser"); s.set_defaults(f=cmd_serve)
    sp.add_parser("start", help="run the web panel in the background").set_defaults(f=cmd_start)
    sp.add_parser("stop", help="stop the background web panel").set_defaults(f=cmd_stop)
    sp.add_parser("restart", help="restart the background web panel").set_defaults(f=cmd_restart)
    sp.add_parser("url", help="print the address(es) to open in a browser").set_defaults(f=cmd_url)
    s = sp.add_parser("service", help="start the panel at boot (install|remove|status)"); s.add_argument("action", nargs="?", default="status", choices=["install", "remove", "status"]); s.set_defaults(f=cmd_service)
    s = sp.add_parser("domain", help="publish the panel under a domain name (set|remove|show)"); s.add_argument("action", nargs="?", default="show", choices=["set", "remove", "show"]); s.add_argument("name", nargs="?"); s.add_argument("--persist", action="store_true", help="also install the boot service"); s.set_defaults(f=cmd_domain)
    s = sp.add_parser("install", help="install software from the catalog, e.g. astra install nginx"); s.add_argument("name"); s.set_defaults(f=cmd_install)
    s = sp.add_parser("uninstall", help="remove software (its data is kept)"); s.add_argument("name"); s.add_argument("--yes", action="store_true"); s.set_defaults(f=cmd_uninstall)
    sp.add_parser("catalog", help="list installable software and what is installed").set_defaults(f=cmd_catalog)
    s = sp.add_parser("notes", aliases=["notifications"], help="what needs your attention (security, services, installs)"); s.add_argument("-n", type=int, default=30); s.add_argument("--all", action="store_true", help="include already-read items"); s.add_argument("--read", action="store_true", help="mark them read"); s.set_defaults(f=cmd_notes)
    s = sp.add_parser("passwd", help="change the admin password (or user name with --user)"); s.add_argument("--user"); s.add_argument("--password"); s.set_defaults(f=cmd_passwd)
    sp.add_parser("user", help="show the admin user name").set_defaults(f=cmd_user)
    sp.add_parser("status", help="CPU / memory / disk summary").set_defaults(f=cmd_status)
    sp.add_parser("tui", help="full-screen terminal app (same as running astra alone)").set_defaults(f=cmd_tui)
    sp.add_parser("doctor", help="diagnose setup problems").set_defaults(f=cmd_doctor)
    sp.add_parser("ext", help="list extensions").set_defaults(f=cmd_ext)
    sp.add_parser("services", help="list managed services").set_defaults(f=cmd_services)
    s = sp.add_parser("svc", help="service action"); s.add_argument("name"); s.add_argument("op", choices=["start", "stop", "restart", "reload", "enable", "disable"]); s.set_defaults(f=cmd_svc)
    s = sp.add_parser("call", help="run any extension route (k=v params)"); s.add_argument("ext"); s.add_argument("route"); s.add_argument("params", nargs="*"); s.set_defaults(f=cmd_call)
    s = sp.add_parser("config", help="show/set config"); s.add_argument("action", nargs="?", default="show", choices=["show", "set"]); s.add_argument("key", nargs="?"); s.add_argument("value", nargs="?"); s.set_defaults(f=cmd_config)
    s = sp.add_parser("mfa", help="multi-factor status / reset / test e-mail"); s.add_argument("action", nargs="?", default="status", choices=["status", "reset", "test-email"]); s.add_argument("to", nargs="?"); s.set_defaults(f=cmd_mfa)
    s = sp.add_parser("privacy", help="export or delete stored personal data"); s.add_argument("action", choices=["export", "delete"]); s.add_argument("--yes", action="store_true"); s.set_defaults(f=cmd_privacy)
    s = sp.add_parser("logs", help="show audit log"); s.add_argument("-n", type=int, default=50); s.set_defaults(f=cmd_logs)
    _console()
    a = p.parse_args(argv)
    if not a.cmd:  # plain `astra`: the terminal app (falls back to help where curses is missing)
        if _ensure_admin() and TTY:
            input("Note the password above, then press Enter to open the terminal app... ")
        try:
            from .tui import main as tui
        except ImportError:
            return p.print_help()
        return tui()
    try:
        a.f(a)
    except KeyboardInterrupt:
        sys.exit(130)
