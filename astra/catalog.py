"""Install catalog: the software the panel knows how to install, remove and describe.

Every entry says what the thing is, whether you need it, and how to install it with the package manager of
this machine (apt, dnf, zypper, pacman, apk, winget). Installs run as background jobs (jobs.py) so the panel can
show live output and progress, and finish with a notification.
"""
import glob as _glob, re, subprocess
from . import config, plat
from .errors import PanelError

WIN = plat.IS_WIN
CATS = ["Web servers", "Languages", "Databases", "Containers", "Protection", "Tools"]


def _e(id, title, cat, summary, need, skip, pkgs, units=(), glob=None, bins=(), ports=(), size="", url="",
       win=None, win_note="", data=False, conflicts=(), post=None, icon="box"):
    return {"id": id, "title": title, "category": cat, "summary": summary, "need": need, "skip": skip, "pkgs": pkgs,
            "units": list(units), "glob": glob, "bins": list(bins), "ports": list(ports), "size": size, "url": url,
            "win": win, "win_note": win_note, "data": data, "conflicts": list(conflicts), "post": post, "icon": icon}


CATALOG = [
    _e("nginx", "Nginx", "Web servers",
       "Fast web server and reverse proxy. The panel's Websites tab writes its configuration for you.",
       "You want to host websites or put several apps behind one domain and HTTPS.",
       "You only use the panel for files, tasks and monitoring.",
       {"apt": ["nginx"], "dnf": ["nginx"], "zypper": ["nginx"], "pacman": ["nginx"], "apk": ["nginx"]},
       units=["nginx"], bins=["nginx"], ports=[80, 443], size="about 2 MB", url="https://nginx.org/en/docs/",
       win_note="Nginx has no installer for Windows. Download the zip from nginx.org, unzip it (for example to C:\\nginx) and add the folder to bin_dirs.",
       conflicts=["apache"], icon="globe"),
    _e("apache", "Apache HTTP Server", "Web servers",
       "The classic web server. Works with .htaccess files and many PHP applications.",
       "An application you run insists on Apache or .htaccess rules.",
       "You already use Nginx. Both want port 80, so run only one of them.",
       {"apt": ["apache2"], "dnf": ["httpd"], "zypper": ["apache2"], "pacman": ["apache"], "apk": ["apache2"]},
       units=["apache2", "httpd"], bins=["apache2", "httpd"], ports=[80, 443], size="about 10 MB",
       url="https://httpd.apache.org/docs/", conflicts=["nginx"], icon="globe"),
    _e("certbot", "Certbot (Let's Encrypt)", "Web servers",
       "Gets and renews free HTTPS certificates. Used by the HTTPS button in the Websites tab.",
       "You have a real domain name pointing at this server and want https:// on it.",
       "The server is only reachable inside your own network, or HTTPS is handled elsewhere.",
       {"apt": ["certbot", "python3-certbot-nginx"], "dnf": ["certbot", "python3-certbot-nginx"],
        "zypper": ["certbot", "python3-certbot-nginx"], "pacman": ["certbot", "certbot-nginx"], "apk": ["certbot", "certbot-nginx"]},
       bins=["certbot"], size="about 40 MB", url="https://certbot.eff.org/", icon="lock"),
    _e("php-fpm", "PHP (FPM)", "Languages",
       "Runs PHP applications such as WordPress, behind Nginx or Apache.",
       "You host PHP software (WordPress, Nextcloud, phpMyAdmin...).",
       "Your sites are static files or Node/Python apps.",
       {"apt": ["php-fpm"], "dnf": ["php-fpm"], "zypper": ["php-fpm"], "pacman": ["php-fpm"], "apk": ["php-fpm"]},
       units=["php-fpm"], glob="php*-fpm", bins=["php-fpm"], size="about 25 MB", url="https://www.php.net/manual/",
       icon="code"),
    _e("nodejs", "Node.js", "Languages",
       "JavaScript runtime with npm. Needed to run many modern web apps and build tools.",
       "You deploy a Node app (Express, Next.js, a bot...). Put it behind a proxy site in the Websites tab.",
       "You do not run JavaScript server software.",
       {"apt": ["nodejs", "npm"], "dnf": ["nodejs", "npm"], "zypper": ["nodejs", "npm"], "pacman": ["nodejs", "npm"], "apk": ["nodejs", "npm"]},
       bins=["node"], size="about 60 MB", url="https://nodejs.org/docs/", win="OpenJS.NodeJS.LTS", icon="code"),
    _e("git", "Git", "Tools",
       "Version control. Lets you deploy a site by pulling its repository onto the server.",
       "You deploy code from GitHub/GitLab or keep configuration under version control.",
       "You only upload files by hand.",
       {"apt": ["git"], "dnf": ["git"], "zypper": ["git"], "pacman": ["git"], "apk": ["git"]},
       bins=["git"], size="about 40 MB", url="https://git-scm.com/doc", win="Git.Git", icon="code"),
    _e("mariadb", "MariaDB", "Databases",
       "MySQL-compatible database server. The default choice for WordPress and most web apps.",
       "An application asks for MySQL or MariaDB.",
       "You do not run database-backed apps, or you prefer PostgreSQL. MariaDB and MySQL share port 3306: run one.",
       {"apt": ["mariadb-server"], "dnf": ["mariadb-server"], "zypper": ["mariadb"], "pacman": ["mariadb"], "apk": ["mariadb", "mariadb-client"]},
       units=["mariadb", "mysql"], bins=["mariadbd"], ports=[3306], size="about 120 MB", url="https://mariadb.com/kb/en/documentation/",
       win="MariaDB.Server", data=True, conflicts=["mysql"], icon="database"),
    _e("mysql", "MySQL", "Databases",
       "The original MySQL server (Oracle). Use it only if you specifically need MySQL rather than MariaDB.",
       "A vendor requires real MySQL.",
       "Almost always: MariaDB does the same job and is the usual choice.",
       {"apt": ["mysql-server"], "dnf": ["mysql-server"], "zypper": ["mysql"]},
       units=["mysql", "mysqld"], bins=["mysqld"], ports=[3306], size="about 200 MB", url="https://dev.mysql.com/doc/",
       data=True, conflicts=["mariadb"], icon="database"),
    _e("postgresql", "PostgreSQL", "Databases",
       "Advanced open-source database with strong standards support and extensions.",
       "An application asks for PostgreSQL, or you want a robust database for your own projects.",
       "You only need MySQL/MariaDB.",
       {"apt": ["postgresql"], "dnf": ["postgresql-server", "postgresql-contrib"], "zypper": ["postgresql-server"], "pacman": ["postgresql"], "apk": ["postgresql"]},
       units=["postgresql"], bins=["postgres"], ports=[5432], size="about 150 MB", url="https://www.postgresql.org/docs/",
       win="PostgreSQL.PostgreSQL.16", data=True, post="pg_init", icon="database"),
    _e("redis", "Redis", "Databases",
       "In-memory key-value store used for caching, sessions and queues.",
       "An app or framework asks for Redis (Laravel, Django cache, Sidekiq, Nextcloud...).",
       "Nothing you run mentions Redis.",
       {"apt": ["redis-server"], "dnf": ["redis"], "zypper": ["redis"], "pacman": ["redis"], "apk": ["redis"]},
       units=["redis-server", "redis"], bins=["redis-server"], ports=[6379], size="about 5 MB", url="https://redis.io/docs/",
       data=True, icon="database"),
    _e("memcached", "Memcached", "Databases",
       "Simple memory cache for speeding up dynamic websites.",
       "An app lists Memcached as its cache backend.",
       "You use Redis or no cache.",
       {"apt": ["memcached"], "dnf": ["memcached"], "zypper": ["memcached"], "pacman": ["memcached"], "apk": ["memcached"]},
       units=["memcached"], bins=["memcached"], ports=[11211], size="under 1 MB", url="https://memcached.org/", icon="database"),
    _e("sqlite", "SQLite tools", "Databases",
       "Command-line tools for SQLite, the single-file database many apps embed. No server needed.",
       "You want to inspect or repair an app's .db / .sqlite file.",
       "Apps use SQLite internally without you touching it.",
       {"apt": ["sqlite3"], "dnf": ["sqlite"], "zypper": ["sqlite3"], "pacman": ["sqlite"], "apk": ["sqlite"]},
       bins=["sqlite3"], size="under 2 MB", url="https://sqlite.org/docs.html", icon="database"),
    _e("docker", "Docker Engine", "Containers",
       "Runs apps in isolated containers. On Linux this is the headless engine: no desktop app, just the service.",
       "You deploy apps that ship as Docker images or a compose file.",
       "You run software directly on the server.",
       {"apt": ["docker.io"], "dnf": ["moby-engine"], "zypper": ["docker"], "pacman": ["docker"], "apk": ["docker"]},
       units=["docker"], bins=["docker"], size="about 250 MB", url="https://docs.docker.com/engine/", win="Docker.DockerDesktop",
       win_note="Windows has no headless Docker service: Docker Desktop (with WSL 2) is the supported way, and it must be started once after install.",
       data=True, icon="box"),
    _e("ufw", "UFW firewall", "Protection",
       "Simple firewall front-end. The Firewall tab manages its rules.",
       "The server is reachable from the internet (almost every server).",
       "Your cloud provider's firewall already filters traffic, or you use firewalld.",
       {"apt": ["ufw"], "dnf": ["ufw"], "zypper": ["ufw"], "pacman": ["ufw"], "apk": ["ufw"]},
       units=["ufw"], bins=["ufw"], size="about 1 MB", url="https://help.ubuntu.com/community/UFW",
       win_note="Windows uses its built-in Defender Firewall, already managed by the Firewall tab.", icon="shield"),
    _e("fail2ban", "Fail2ban", "Protection",
       "Watches logs and temporarily bans IP addresses that keep failing to log in (SSH and more).",
       "SSH or any login is reachable from the internet. It blocks password-guessing bots.",
       "Login is key-only behind a VPN, or the server is not exposed.",
       {"apt": ["fail2ban"], "dnf": ["fail2ban"], "zypper": ["fail2ban"], "pacman": ["fail2ban"], "apk": ["fail2ban"]},
       units=["fail2ban"], bins=["fail2ban-client"], size="about 5 MB", url="https://github.com/fail2ban/fail2ban/wiki", icon="shield"),
    _e("openssh", "OpenSSH server", "Protection",
       "Lets you sign in to this machine remotely with a terminal (SSH).",
       "You administer this machine from another computer.",
       "You only have physical or console access, or already use SSH.",
       {"apt": ["openssh-server"], "dnf": ["openssh-server"], "zypper": ["openssh"], "pacman": ["openssh"], "apk": ["openssh"]},
       units=["ssh", "sshd"], bins=["sshd"], ports=[22], size="about 2 MB", url="https://www.openssh.com/manual.html", icon="terminal"),
    _e("cron", "Cron scheduler", "Tools",
       "Runs commands on a schedule. The Tasks tab writes its jobs here.",
       "You want scheduled tasks (backups, clean-ups, renewals).",
       "You never schedule anything.",
       {"apt": ["cron"], "dnf": ["cronie"], "zypper": ["cronie"], "pacman": ["cronie"], "apk": ["dcron"]},
       units=["cron", "crond", "cronie"], bins=["crond", "cron"], size="under 1 MB", url="https://man7.org/linux/man-pages/man5/crontab.5.html",
       win_note="Windows uses Task Scheduler, which is always present.", icon="clock"),
    _e("supervisor", "Supervisor", "Tools",
       "Keeps your own programs (workers, bots, small servers) running and restarts them if they crash.",
       "You run long-lived scripts that are not packaged as services.",
       "Systemd units or Docker already supervise your programs.",
       {"apt": ["supervisor"], "dnf": ["supervisor"], "zypper": ["supervisor"], "pacman": ["supervisor"], "apk": ["supervisor"]},
       units=["supervisor", "supervisord"], bins=["supervisord"], size="about 3 MB", url="http://supervisord.org/", icon="server"),
]
BY_ID = {e["id"]: e for e in CATALOG}
_PM_FAMILY = {"yum": "dnf"}


def get(id):
    e = BY_ID.get(id)
    if not e:
        raise PanelError("unknown package", 404)
    return e


# ---------------------------------------------------------------- unit table (one systemctl call, not one per service)
def _run(args, timeout=15):
    try:
        r = subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=timeout,
                           stdin=subprocess.DEVNULL, creationflags=plat.NO_WINDOW)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return 127, ""


def unit_table():
    """{unit name (without .service): (active, enabled)} for every systemd service. Empty on Windows / no systemd."""
    if WIN or not plat.has_systemd() or not plat.which("systemctl"):
        return {}
    table = {}
    _, files = _run(["systemctl", "list-unit-files", "--type=service", "--no-legend", "--no-pager"])
    for line in files.splitlines():
        t = line.split()
        if len(t) >= 2 and t[0].endswith(".service"):
            table[t[0][:-8]] = ["inactive", t[1]]
    _, units = _run(["systemctl", "list-units", "--type=service", "--all", "--no-legend", "--no-pager", "--plain"])
    for line in units.splitlines():
        t = line.lstrip("●* ").split()
        if len(t) >= 4 and t[0].endswith(".service"):
            name = t[0][:-8]
            row = table.setdefault(name, ["inactive", "static"])
            row[0] = "active" if t[2] == "active" else "failed" if t[2] == "failed" else t[2]
    return {k: tuple(v) for k, v in table.items()}


_WIN_STATE = {"RUNNING": "active", "STOPPED": "inactive", "START_PENDING": "starting", "STOP_PENDING": "stopping",
              "PAUSED": "paused", "CONTINUE_PENDING": "starting", "PAUSE_PENDING": "stopping"}
_WIN_START = {"AUTO_START": "enabled", "BOOT_START": "enabled", "SYSTEM_START": "enabled", "DEMAND_START": "manual", "DISABLED": "disabled"}


def win_service(name):
    rc, out = _run(["sc", "query", name])
    if rc == 1060 or (rc != 0 and "1060" in out):
        return None
    m = re.search(r"\b(STOPPED|START_PENDING|STOP_PENDING|RUNNING|CONTINUE_PENDING|PAUSE_PENDING|PAUSED)\b", out)
    state = _WIN_STATE[m[1]] if m else "unknown"
    _, qc = _run(["sc", "qc", name])
    s = re.search(r"\b(AUTO_START|DEMAND_START|DISABLED|BOOT_START|SYSTEM_START)\b", qc)
    return state, _WIN_START[s[1]] if s else "unknown"


def service_status(name, table=None):
    """(state, enabled) of a service, or ('not-installed', '-')."""
    if WIN:
        r = win_service(name)
        return r if r else ("not-installed", "-")
    table = unit_table() if table is None else table
    if name in table:
        return table[name]
    return ("not-installed", "-") if (table or plat.has_systemd()) else ("unknown", "-")


def units_of(entry, table):
    """The unit names of this software that exist on this machine (resolves php*-fpm style globs)."""
    found = [u for u in entry["units"] if u in table]
    if entry["glob"]:
        import fnmatch
        found += sorted(u for u in table if fnmatch.fnmatch(u, entry["glob"]) and u not in found)
    return found


def installed(entry, table=None):
    if WIN:
        if any(plat.which(b) for b in entry["bins"]):
            return True
        return any(win_service(u) for u in entry["units"])
    table = unit_table() if table is None else table
    return bool(units_of(entry, table)) or any(plat.which(b) for b in entry["bins"])


def version(entry):
    for b in entry["bins"]:
        exe = plat.which(b)
        if exe:
            rc, out = _run([exe, "--version"], 6)
            if not out.strip():
                rc, out = _run([exe, "-v"], 6)
            m = re.search(r"\d+(?:\.\d+){1,3}", out)
            if m:
                return m[0]
    return ""


def listing():
    """One row per catalog entry with live state. Used by the Services tab and the TUI."""
    table, pm = unit_table(), plat.pkg_manager()
    rows = []
    for e in CATALOG:
        units = units_of(e, table)
        inst = installed(e, table)
        state = enabled = "-"
        if units:
            running = [table[u] for u in units]
            state = "active" if any(r[0] == "active" for r in running) else "failed" if any(r[0] == "failed" for r in running) else "inactive"
            enabled = running[0][1]
        elif inst and WIN:
            for u in e["units"]:
                s = win_service(u)
                if s:
                    state, enabled = s
                    break
        rows.append({"id": e["id"], "title": e["title"], "category": e["category"], "icon": e["icon"],
                     "summary": e["summary"], "need": e["need"], "skip": e["skip"], "ports": e["ports"],
                     "size": e["size"], "url": e["url"], "installed": inst, "state": state if inst else "not-installed",
                     "enabled": enabled, "units": units, "data": e["data"], "conflicts": e["conflicts"],
                     "can_install": bool(_pkgs(e, pm)) or bool(WIN and e["win"] and pm), "note": e["win_note"] if WIN else ""})
    return rows


# ---------------------------------------------------------------- install / uninstall plans (executed by jobs.py)
def _pkgs(e, pm):
    return e["pkgs"].get(_PM_FAMILY.get(pm, pm)) or []


def _need_admin(what):
    if not plat.IS_ROOT:
        raise PanelError(f"{what} needs {'an elevated Administrator' if WIN else 'root'}: start the panel with "
                         f"{'an Administrator terminal' if WIN else 'sudo'}.", 403)


def _allow(units):
    """Put the service units into the panel's managed list so they show up under Services."""
    def step():
        added = [u for u in units if u not in config.cfg["services"]]
        if added:
            config.cfg["services"].extend(added)
            config.save()
        return f"Added to the managed services list: {', '.join(added)}" if added else ""
    return step


def _unmanage(units):
    def step():
        keep = [u for u in config.cfg["services"] if u not in units]
        if keep != config.cfg["services"]:
            config.cfg["services"][:] = keep
            config.save()
        return ""
    return step


def _enable_now(e, other_active):
    def step():
        table = unit_table()
        units = units_of(e, table)
        if not units:
            return "No service unit appeared after the install (nothing to start)."
        u = units[0]
        if other_active:
            rc, out = _run(["systemctl", "enable", u], 30)
            return f"{u} enabled for boot but NOT started: {other_active} is using the same port. Stop it first, then start {u}."
        rc, out = _run(["systemctl", "enable", "--now", u], 60)
        _allow(units)()
        return out.strip() or f"{u} enabled and started"
    return step


def install_plan(id):
    """(title, steps, env). A step is an argv list, {'cmd': argv, 'optional': True}, or a function returning text."""
    e = get(id)
    pm = plat.pkg_manager()
    if not pm:
        raise PanelError("no supported package manager found (apt, dnf, zypper, pacman, apk, winget)", 501)
    _need_admin("Installing software")
    if WIN:
        if not e["win"]:
            raise PanelError(e["win_note"] or f"{e['title']} cannot be installed automatically on Windows.", 501)
        if pm == "winget":
            return f"Install {e['title']}", [["winget", "install", "--id", e["win"], "-e", "--silent",
                                              "--accept-package-agreements", "--accept-source-agreements"]], {}
        return f"Install {e['title']}", [["choco", "install", e["win"].split(".")[-1].lower(), "-y"]], {}
    pkgs = _pkgs(e, pm)
    if not pkgs:
        raise PanelError(f"{e['title']} has no known package for {pm}. Install it by hand.", 501)
    env = {"DEBIAN_FRONTEND": "noninteractive", "NEEDRESTART_MODE": "a", "LC_ALL": "C"}
    steps = []
    if pm == "apt":
        steps += [["apt-get", "update"], ["apt-get", "install", "-y", "-o", "Dpkg::Options::=--force-confold", *pkgs]]
    elif pm == "dnf":
        steps += [[plat.which("dnf") and "dnf" or "yum", "install", "-y", *pkgs]]
    elif pm == "zypper":
        steps += [["zypper", "--non-interactive", "install", *pkgs]]
    elif pm == "pacman":
        steps += [["pacman", "-Sy", "--noconfirm", "--needed", *pkgs]]
    elif pm == "apk":
        steps += [["apk", "add", *pkgs]]
    if e["post"] == "pg_init" and pm == "dnf":
        steps.append({"cmd": ["postgresql-setup", "--initdb"], "optional": True})
    if e["units"] or e["glob"]:
        table = unit_table()
        other = next((BY_ID[c]["title"] for c in e["conflicts"] if units_of(BY_ID[c], table)
                      and any(table[u][0] == "active" for u in units_of(BY_ID[c], table))), "")
        steps.append(_enable_now(e, other))
    return f"Install {e['title']}", steps, env


def uninstall_plan(id):
    e = get(id)
    pm = plat.pkg_manager()
    if not pm:
        raise PanelError("no supported package manager found", 501)
    _need_admin("Removing software")
    table = unit_table()
    units = units_of(e, table)
    if WIN:
        if not e["win"]:
            raise PanelError(f"{e['title']} was not installed by the panel on Windows. Remove it from Settings > Apps.", 501)
        cmd = ["winget", "uninstall", "--id", e["win"], "-e", "--silent"] if pm == "winget" else ["choco", "uninstall", e["win"].split(".")[-1].lower(), "-y"]
        return f"Remove {e['title']}", [cmd], {}
    pkgs = _pkgs(e, pm)
    if not pkgs:
        raise PanelError(f"{e['title']} has no known package for {pm}.", 501)
    env = {"DEBIAN_FRONTEND": "noninteractive", "LC_ALL": "C"}
    steps = [{"cmd": ["systemctl", "disable", "--now", u], "optional": True} for u in units]
    if pm == "apt":
        steps.append(["apt-get", "remove", "-y", *pkgs])      # remove, never purge: data and configs are kept
    elif pm == "dnf":
        steps.append(["dnf", "remove", "-y", *pkgs])
    elif pm == "zypper":
        steps.append(["zypper", "--non-interactive", "remove", *pkgs])
    elif pm == "pacman":
        steps.append(["pacman", "-R", "--noconfirm", *pkgs])
    elif pm == "apk":
        steps.append(["apk", "del", *pkgs])
    steps.append(_unmanage(units))
    return f"Remove {e['title']}", steps, env


def detail(id):
    e = get(id)
    table = unit_table()
    row = next(r for r in listing() if r["id"] == id)
    pm = plat.pkg_manager() or "none"
    pk = _pkgs(e, pm) if not WIN else [e["win"]] if e["win"] else []
    pairs = [["What it is", e["summary"]], ["You need it if", e["need"]], ["You can skip it if", e["skip"]]]
    if e["ports"]:
        pairs.append(["Ports", ", ".join(map(str, e["ports"]))])
    if e["size"]:
        pairs.append(["Download size", e["size"]])
    pairs.append(["Installs with", f"{pm}: {' '.join(pk)}" if pk else f"{pm}: (no package known)"])
    if row["installed"]:
        pairs.append(["Installed version", version(e) or "unknown"])
        pairs.append(["Service", ", ".join(f"{u} ({table[u][0]}, boot: {table[u][1]})" for u in row["units"]) or "no service"])
    if e["data"]:
        pairs.append(["Your data", "Removing the software keeps its data folders. Delete them by hand only if you are sure."])
    if e["url"]:
        pairs.append(["Documentation", e["url"]])
    if row["note"]:
        pairs.append(["Note", row["note"]])
    return {"title": e["title"], "kv": pairs}


# ---------------------------------------------------------------- change watcher (feeds notifications)
_seen = {}


def watch_tick():
    """Compare managed services with the last look; notify when one stops, fails or comes back."""
    from . import notify
    table = unit_table() if not WIN else None
    for name in list(config.cfg.get("services", [])):
        state = service_status(name, table)[0]
        if state == "not-installed":
            _seen.pop(name, None)
            continue
        prev = _seen.get(name)
        _seen[name] = state
        if prev is None or prev == state:
            continue
        if prev == "active" and state in ("failed", "inactive"):
            notify.add("services", "critical" if state == "failed" else "warning",
                       f"{name} {'crashed' if state == 'failed' else 'stopped'}", "Open Services to start it again.", key=f"svc:{name}")
        elif state == "active" and prev != "active":
            notify.resolve(f"svc:{name}", f"{name} is running again")
