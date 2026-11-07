import os, time
from pathlib import Path
from .. import audit, config, plat
from ..errors import PanelError
from ..shell import ps, ps_json, run
from . import Extension

WIN = plat.IS_WIN
EXT = Extension("security", "Security", "🔒", order=90, description="Hardening checks, open ports, audit log")
# SIDs that mean "everybody": Everyone, BUILTIN\Users, Authenticated Users (language independent)
OPEN_SIDS = {"S-1-1-0": "Everyone", "S-1-5-32-545": "Users", "S-1-5-11": "Authenticated Users"}


def _ssh_files():
    if WIN:  # Windows OpenSSH Server keeps one file here
        return [Path(os.environ.get("ProgramData", "C:\\ProgramData")) / "ssh" / "sshd_config"]
    return sorted(Path("/etc/ssh/sshd_config.d").glob("*.conf")) + [Path("/etc/ssh/sshd_config")]


def _sshd():
    vals = {}
    for f in _ssh_files():  # OpenSSH: first value wins
        try:
            lines = f.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            parts = line.strip().split(None, 1)
            if len(parts) == 2 and not parts[0].startswith("#"):
                vals.setdefault(parts[0].lower(), parts[1].strip().lower())
    return vals


def _rdp():
    import winreg
    base = r"SYSTEM\CurrentControlSet\Control\Terminal Server"
    with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base) as k:
        enabled = winreg.QueryValueEx(k, "fDenyTSConnections")[0] == 0
    nla = None
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, base + r"\WinStations\RDP-Tcp") as k:
            nla = winreg.QueryValueEx(k, "UserAuthentication")[0] == 1
    except OSError:
        pass
    return enabled, nla


def _win_open_acl(path):
    """Names of 'everybody' groups that appear in the folder's ACL (language independent via SIDs)."""
    q = str(path).replace("'", "''")
    sids = ps("(Get-Acl -LiteralPath '" + q + "').Access | ForEach-Object { "
              "$_.IdentityReference.Translate([Security.Principal.SecurityIdentifier]).Value }").split()
    return [OPEN_SIDS[s] for s in sids if s in OPEN_SIDS]


def _win_checks(add):
    try:
        prof = ps("Get-NetFirewallProfile | ForEach-Object { '{0}={1}' -f $_.Name, $_.Enabled }").split()
        add("Windows Firewall", "ok" if prof and not [x for x in prof if x.lower().endswith("=false")] else "fail", ", ".join(prof) or "unknown")
    except PanelError as e:
        add("Windows Firewall", "warn", e.message[:120])
    try:
        rt = ps("(Get-MpComputerStatus).RealTimeProtectionEnabled").strip()
        add("Defender real-time protection", "ok" if rt.lower() == "true" else "warn", rt)
    except PanelError:
        add("Defender real-time protection", "warn", "unavailable (third-party antivirus, or Defender is not installed)")
    try:
        enabled, nla = _rdp()
        add("Remote Desktop (RDP)", "warn" if enabled else "ok",
            "enabled: keep it behind a VPN/SSH tunnel or a firewall allow-list" if enabled else "disabled")
        if enabled:
            add("RDP network-level authentication", "ok" if nla else "fail", "required" if nla else "not required")
    except OSError as e:
        add("Remote Desktop (RDP)", "warn", f"cannot read registry: {e.strerror}")
    try:
        open_to = _win_open_acl(config.HOME)
        add("Config folder access", "fail" if open_to else "ok",
            ("readable by " + ", ".join(open_to)) if open_to else "SYSTEM, Administrators and the panel user only")
    except PanelError:
        add("Config folder access", "warn", "could not read the ACL")


def _linux_checks(add):
    try:
        ufw = run(["ufw", "status"])[1]
        add("Firewall (ufw)", "ok" if "Status: active" in ufw else "fail", ufw.splitlines()[0] if ufw else "unknown")
    except Exception:
        add("Firewall (ufw)", "warn", "ufw not installed")
    state = run(["systemctl", "is-active", "fail2ban"])[1].strip() if plat.which("systemctl") else "n/a"
    add("fail2ban", "ok" if state == "active" else "warn", state)


@EXT.route("checks")
def checks(p):
    rows = []
    add = lambda c, s, d: rows.append({"check": c, "status": s, "detail": d})
    ssh = _sshd()
    if not WIN:
        root = ssh.get("permitrootlogin", "prohibit-password")
        add("SSH root login", "fail" if root == "yes" else "ok", f"PermitRootLogin {root}")
    if ssh or not WIN:  # on Windows only report SSH when OpenSSH Server is actually configured
        pw = ssh.get("passwordauthentication", "yes")
        add("SSH password login", "warn" if pw == "yes" else "ok", f"PasswordAuthentication {pw} (keys are safer)")
    (_win_checks if WIN else _linux_checks)(add)
    tls = bool(config.cfg["tls_cert"] and config.cfg["tls_key"])
    loop = config.cfg["host"] in ("127.0.0.1", "::1", "localhost")
    add("Panel exposure", "ok" if (loop or tls) else "fail", f"{config.cfg['host']}:{config.cfg['port']} {'TLS' if tls else 'plain HTTP'}")
    if not WIN:
        mode = config.CONFIG.stat().st_mode & 0o777 if config.CONFIG.exists() else 0o600
        add("Config permissions", "ok" if mode & 0o077 == 0 else "fail", oct(mode))
    fails = sum(1 for e in audit.tail(500) if e.get("event") == "auth_fail" and time.time() - e["ts"] < 86400)
    add("Failed panel logins (24h)", "ok" if fails == 0 else "warn", str(fails))
    if not WIN:  # TODO.md: Windows Update status
        try:
            rc, out = run(["apt", "list", "--upgradable"], timeout=30)
            n = max(len(out.splitlines()) - 1, 0) if rc == 0 else None
            if n is not None:
                add("Pending updates", "ok" if n == 0 else "warn", f"{n} packages")
        except Exception:
            pass
    return rows


def _win_ports():
    rows = ps_json("$r=@(Get-NetTCPConnection -State Listen | ForEach-Object { [pscustomobject]@{a=[string]$_.LocalAddress;p=[int]$_.LocalPort;"
                   "n=(Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue).ProcessName} }); "
                   "ConvertTo-Json -InputObject $r -Compress", 40)
    out = []
    for r in sorted(rows, key=lambda r: (r.get("p", 0), r.get("a", ""))):
        a = r.get("a", "")
        out.append({"address": f"[{a}]:{r.get('p')}" if ":" in a else f"{a}:{r.get('p')}",
                    "exposure": "local" if a.startswith("127.") or a == "::1" else "public", "process": r.get("n") or ""})
    return out


@EXT.route("ports")
def ports(p):
    if WIN:
        return _win_ports()
    rows = []
    for line in run(["ss", "-tlnpH"])[1].splitlines():
        f = line.split(None, 5)
        if len(f) >= 5:
            local = f[3]
            rows.append({"address": local, "exposure": "local" if local.startswith(("127.", "[::1]")) else "public",
                         "process": f[5] if len(f) > 5 else ""})
    return rows


@EXT.route("events")
def events(p):
    return [{"time": e["ts"], "event": e["event"], "ip": e.get("ip", ""),
             "detail": f"{e.get('ext', '')} {e.get('route', '')} {e.get('params', '')}".strip()} for e in audit.tail(100)]


EXT.sections = [
    {"type": "table", "title": "Hardening checks", "source": "checks",
     "columns": [["Check", "check"], ["Status", "status", "state"], ["Detail", "detail"]]},
    {"type": "table", "title": "Listening TCP ports", "source": "ports",
     "columns": [["Address", "address"], ["Exposure", "exposure", "state"], ["Process", "process"]]},
    {"type": "table", "title": "Panel audit log (latest 100)", "source": "events",
     "columns": [["Time", "time", "time"], ["Event", "event"], ["From", "ip"], ["Detail", "detail"]]},
]
