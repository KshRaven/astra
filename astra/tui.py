"""Terminal app: run `astra` with no arguments. Needs curses (built in on Linux/macOS; `pip install .` adds it on Windows).

Keys   Tab / Left / Right  switch page      Up / Down  move      q or Esc  quit
Pages  Dashboard, Services (catalog: s start, x stop, r restart, i install, u remove), Processes,
       Notifications (r mark read), Panel (w start/stop the website, p new password)
Everything here also exists as a plain command (astra --help), so once you know it you can skip this screen."""
import curses, time
from . import config, daemon, monitor, plat
from .errors import PanelError
from .extensions import load_extensions, registry

VIEWS = ["Dashboard", "Services", "Processes", "Notifications", "Panel"]
SEV = {"critical": 3, "warning": 2, "info": 4, "ok": 1}


def main():
    load_extensions()
    curses.wrapper(_run)


def _run(scr):
    try:
        curses.curs_set(0)
    except curses.error:
        pass
    curses.use_default_colors()
    for i, col in enumerate((curses.COLOR_GREEN, curses.COLOR_YELLOW, curses.COLOR_RED, curses.COLOR_CYAN), 1):
        curses.init_pair(i, col, -1)
    scr.timeout(1000)
    mon, view, sel = monitor.Monitor(), 0, 0
    state = {"msg": ""}
    cache = {"svc": ([], 0), "note": ({"items": [], "attention": 0}, 0), "web": (False, 0)}
    svc_ext = registry.get("services")

    def put(y, x, text, attr=0):
        h, w = scr.getmaxyx()
        if 0 <= y < h - 1 and 0 <= x < w:
            try:
                scr.addstr(y, x, str(text)[: w - x - 1], attr)
            except curses.error:
                pass

    def bar(y, label, v, extra=""):
        pair = curses.color_pair(1 if v < 70 else 2 if v < 90 else 3)
        n = int(24 * min(v, 100) / 100)
        put(y, 0, f"{label:<8}")
        put(y, 8, "█" * n, pair)
        put(y, 8 + n, "░" * (24 - n), curses.A_DIM)
        put(y, 34, f"{v:5.1f}%  {extra}")

    def fresh(key, fn, every):
        val, t = cache[key]
        if time.time() - t > every:
            try:
                val = fn()
            except Exception as e:  # a broken tool must not kill the screen
                state["msg"] = str(getattr(e, "message", e))[:60]
            cache[key] = (val, time.time())
        return val

    def catalog_rows():
        from . import catalog
        return catalog.listing()

    def notes():
        from . import notify
        return notify.feed(30)

    def confirm(question):
        h, _ = scr.getmaxyx()
        scr.move(h - 1, 0)
        scr.clrtoeol()
        put(h - 1, 0, question + " (y/n) ", curses.A_REVERSE)
        scr.refresh()
        scr.timeout(-1)
        k = scr.getch()
        scr.timeout(1000)
        return k in (ord("y"), ord("Y"))

    def foreground(title, steps, env):
        """Run an install/removal with its output on the real terminal, then come back."""
        from . import cli
        curses.def_prog_mode()
        curses.endwin()
        try:
            cli._run_plan(title, steps, env)
        except SystemExit as e:
            print(e)
        input("\nPress Enter to return to astra... ")
        curses.reset_prog_mode()
        scr.refresh()
        cache["svc"] = ([], 0)

    while True:
        s = mon.sample()
        scr.erase()
        put(0, 0, " ".join(f"[{v}]" if i == view else f" {v} " for i, v in enumerate(VIEWS)), curses.A_BOLD | curses.color_pair(4))
        n = cache["note"][0]
        if n.get("attention"):
            put(0, scr.getmaxyx()[1] - 22, f"! {n['attention']} need attention ", curses.color_pair(2) | curses.A_BOLD)
        if view == 0:
            info, mem = monitor.system_info(), monitor.meminfo()
            put(2, 0, f"{info['hostname']}  {info['os']}  up {info['uptime'] // 3600}h", curses.A_BOLD)
            bar(4, "CPU", s["cpu"], f"load {s['load']:.2f}/{info['cpus']}" if s["load"] is not None else f"{info['cpus']} CPUs")
            bar(5, "Memory", s["mem"], f"{mem['used'] >> 20} / {mem['total'] >> 20} MB")
            for i, d in enumerate(monitor.disks()[:6]):
                bar(6 + i, "Disk", 100 * d["used"] / max(d["total"], 1), d["mount"])
            put(14, 0, f"Network  down {s['rx'] / 1024:.1f} KB/s   up {s['tx'] / 1024:.1f} KB/s")
            fresh("note", notes, 10)
            put(16, 0, "Website: " + ("running" if fresh("web", daemon.listening, 3) else "stopped (Panel page, key w)"))
        elif view == 1:
            rows = fresh("svc", catalog_rows, 4)
            if not rows:
                put(2, 0, "The software catalog is not available on this machine. " + state["msg"])
            else:
                sel = min(sel, len(rows) - 1)
                top = max(0, min(sel - 4, len(rows) - (scr.getmaxyx()[0] - 8)))
                shown = rows[top: top + max(scr.getmaxyx()[0] - 8, 1)]
                for i, r in enumerate(shown):
                    idx = top + i
                    if not r["installed"]:
                        mark, col, st = "+", curses.A_DIM, "not installed"
                    else:
                        ok = r["state"] == "active"
                        mark, col, st = ("●" if ok else "○"), curses.color_pair(1 if ok else 2), r["state"] if r["units"] else "installed"
                    put(2 + i, 0, f"{'>' if idx == sel else ' '} {mark} {r['title']:<26} {st:<14} {r['category']}",
                        col | (curses.A_REVERSE if idx == sel else 0))
                cur = rows[sel]
                h = scr.getmaxyx()[0]
                put(h - 5, 0, cur["summary"], curses.A_BOLD)
                put(h - 4, 0, "You need it if: " + cur["need"], curses.A_DIM)
                put(h - 3, 0, "s start  x stop  r restart  i install  u remove   " + state["msg"], curses.A_DIM)
        elif view == 2:
            for i, p in enumerate(monitor.processes(max(scr.getmaxyx()[0] - 4, 1))):
                put(2 + i, 0, f"{p['pid']:>7}  {p['name']:<24} {p['rss'] >> 20:>6} MB  {p.get('state', '')}")
        elif view == 3:
            data = fresh("note", notes, 5)
            items = data["items"]
            if not items:
                put(2, 0, "Nothing needs your attention." + (" " + state["msg"] if state["msg"] else ""), curses.color_pair(1))
            for i, it in enumerate(items[: max(scr.getmaxyx()[0] - 5, 1)]):
                put(2 + i, 0, f"{time.strftime('%d %b %H:%M', time.localtime(it['ts']))}  {it['sev']:<8} {it['title']}" + ("" if it["read"] else "  *"),
                    curses.color_pair(SEV.get(it["sev"], 4)) | (curses.A_DIM if it["read"] else 0))
            put(scr.getmaxyx()[0] - 3, 0, "r  mark all as read   (* = unread)   " + state["msg"], curses.A_DIM)
        else:
            from .server import urls
            up = fresh("web", daemon.listening, 3)
            put(2, 0, "Website: " + ("running" if up else "stopped"), curses.color_pair(1 if up else 2) | curses.A_BOLD)
            for i, u in enumerate(urls(config.cfg["host"], int(config.cfg["port"]))):
                put(4 + i, 2, u)
            put(8, 0, f"User: {config.cfg['admin']['username'] or '(not set: astra init)'}")
            put(10, 0, "w  " + ("stop" if up else "start") + " the website     p  set a new random password   " + state["msg"], curses.A_DIM)
        put(scr.getmaxyx()[0] - 1, 0, f" Tab/←→ page   ↑↓ move   q quit   {plat.OS_NAME} ", curses.A_REVERSE)
        scr.refresh()
        k = scr.getch()
        if k in (ord("q"), 27):
            return
        if k in (9, curses.KEY_RIGHT):
            view, sel, state["msg"] = (view + 1) % len(VIEWS), 0, ""
        elif k == curses.KEY_LEFT:
            view, sel, state["msg"] = (view - 1) % len(VIEWS), 0, ""
        elif view == 1 and cache["svc"][0]:
            rows = cache["svc"][0]
            cur = rows[sel]
            if k == curses.KEY_DOWN:
                sel = min(sel + 1, len(rows) - 1)
            elif k == curses.KEY_UP:
                sel = max(sel - 1, 0)
            elif k == ord("i") and not cur["installed"]:
                from . import catalog
                try:
                    plan = catalog.install_plan(cur["id"])
                    if confirm(f"Install {cur['title']} ({cur['size'] or 'size unknown'})?"):
                        foreground(*plan)
                except PanelError as e:
                    state["msg"] = e.message[:70]
            elif k == ord("u") and cur["installed"]:
                from . import catalog
                try:
                    plan = catalog.uninstall_plan(cur["id"])
                    if confirm(f"Remove {cur['title']}? (data is kept)"):
                        foreground(*plan)
                except PanelError as e:
                    state["msg"] = e.message[:70]
            elif k in (ord("s"), ord("x"), ord("r")) and cur["installed"] and cur["units"] and svc_ext:
                op = {ord("s"): "start", ord("x"): "stop", ord("r"): "restart"}[k]
                try:
                    svc_ext.routes["action"][0]({"name": cur["units"][0], "op": op})
                    state["msg"] = f"{op} {cur['units'][0]}: ok"
                except PanelError as e:
                    state["msg"] = e.message[:70]
                cache["svc"] = ([], 0)
        elif view == 3 and k == ord("r"):
            from . import notify
            notify.mark_read()
            cache["note"] = ({"items": [], "attention": 0}, 0)
        elif view == 4 and k == ord("w"):
            ok, msg = daemon.stop() if cache["web"][0] else daemon.start()
            state["msg"] = msg[:60]
            cache["web"] = (False, 0)
        elif view == 4 and k == ord("p") and config.has_admin():
            pw = config.new_password()
            config.set_admin(None, pw)
            config.save()
            state["msg"] = "new password: " + pw
