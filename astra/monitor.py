"""System metrics + a sampling thread. Linux reads /proc; Windows uses the Win32 API through ctypes
(plus tasklist/netstat for processes and network). No dependencies."""
import collections, csv, os, platform, shutil, socket, subprocess, sys, threading, time
from . import audit, config, plat

ROOT_DISK = (os.environ.get("SystemDrive", "C:") + "\\") if plat.IS_WIN else "/"

if plat.IS_WIN:
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _k32.GetTickCount64.restype = ctypes.c_ulonglong
    _k32.GetDriveTypeW.argtypes = [wintypes.LPCWSTR]

    class _FT(ctypes.Structure):
        _fields_ = [("lo", wintypes.DWORD), ("hi", wintypes.DWORD)]

    class _MEM(ctypes.Structure):
        _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    def _ft(f):
        return (f.hi << 32) | f.lo


def _read(path):
    with open(path) as f:
        return f.read()


def _cmd(args, timeout=10):
    """Run a Windows console tool and return stdout ('' on any failure)."""
    try:
        return subprocess.run(args, capture_output=True, text=True, errors="replace", timeout=timeout,
                              stdin=subprocess.DEVNULL, creationflags=plat.NO_WINDOW).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _cpu():
    if plat.IS_WIN:
        idle, kern, user = _FT(), _FT(), _FT()
        if not _k32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kern), ctypes.byref(user)):
            raise OSError("GetSystemTimes failed")
        return _ft(idle), _ft(kern) + _ft(user)  # kernel time already includes idle time
    v = [int(x) for x in _read("/proc/stat").splitlines()[0].split()[1:]]
    return v[3] + v[4], sum(v)  # (idle+iowait, total)


def _net():
    if plat.IS_WIN:  # `netstat -e`: first line with two trailing numbers is "Bytes  received  sent"
        for line in _cmd(["netstat", "-e"]).splitlines():
            t = line.split()
            if len(t) >= 3 and t[-1].isdigit() and t[-2].isdigit() and not t[0].isdigit():
                return int(t[-2]), int(t[-1])
        return 0, 0
    rx = tx = 0
    for line in _read("/proc/net/dev").splitlines()[2:]:
        name, _, data = line.partition(":")
        if name.strip() != "lo":
            c = data.split()
            rx, tx = rx + int(c[0]), tx + int(c[8])
    return rx, tx


def meminfo():
    if plat.IS_WIN:
        m = _MEM()
        m.dwLength = ctypes.sizeof(_MEM)
        _k32.GlobalMemoryStatusEx(ctypes.byref(m))
        total, avail = m.ullTotalPhys, m.ullAvailPhys
        # "page file" is the commit limit (RAM + paging files): the part beyond RAM is the swap estimate
        sw = max(m.ullTotalPageFile - total, 0)
        sw_used = min(max((m.ullTotalPageFile - m.ullAvailPageFile) - (total - avail), 0), sw)
        return {"total": total, "used": total - avail, "swap_total": sw, "swap_used": sw_used}
    d = {}
    for line in _read("/proc/meminfo").splitlines():
        k, _, v = line.partition(":")
        d[k] = int(v.split()[0]) * 1024
    sw = d.get("SwapTotal", 0)
    return {"total": d["MemTotal"], "used": d["MemTotal"] - d["MemAvailable"],
            "swap_total": sw, "swap_used": sw - d.get("SwapFree", 0)}


def disks():
    out = []
    if plat.IS_WIN:
        mask = _k32.GetLogicalDrives()
        for i in range(26):
            root = f"{chr(65 + i)}:\\"
            if mask >> i & 1 and _k32.GetDriveTypeW(root) == 3:  # DRIVE_FIXED
                try:
                    u = shutil.disk_usage(root)
                except OSError:
                    continue
                out.append({"mount": root, "total": u.total, "used": u.used})
        return out
    seen = set()
    for line in _read("/proc/mounts").splitlines():
        dev, mp = line.split()[:2]
        if not dev.startswith("/dev/") or dev.startswith("/dev/loop") or dev in seen:
            continue
        seen.add(dev)
        try:
            u = shutil.disk_usage(mp)
        except OSError:
            continue
        out.append({"mount": mp, "total": u.total, "used": u.used})
    return out


def loadavg():
    """1/5/15 minute load average, or None where the OS has no such thing (Windows)."""
    try:
        return list(os.getloadavg())
    except (AttributeError, OSError):
        return None


def _win_os():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion") as k:
            name = winreg.QueryValueEx(k, "ProductName")[0]
            build = int(winreg.QueryValueEx(k, "CurrentBuildNumber")[0])
        return name.replace("Windows 10", "Windows 11") if build >= 22000 else name  # the registry still says 10 on 11
    except Exception:
        return "Windows " + platform.release()


def system_info():
    if plat.IS_WIN:
        name, kernel, up = _win_os(), platform.version(), int(_k32.GetTickCount64() // 1000)
    else:
        name = "Linux"
        try:
            for line in _read("/etc/os-release").splitlines():
                k, _, v = line.partition("=")
                if k == "PRETTY_NAME":
                    name = v.strip('"')
        except OSError:
            pass
        kernel, up = platform.release(), int(float(_read("/proc/uptime").split()[0]))
    return {"hostname": socket.gethostname(), "os": name, "platform": plat.OS_NAME, "kernel": kernel,
            "arch": platform.machine(), "cpus": os.cpu_count(), "uptime": up}


def processes(limit=30):
    out = []
    if plat.IS_WIN:  # tasklist CSV: name, pid, session name, session #, "12,345 K"
        for rec in csv.reader(_cmd(["tasklist", "/fo", "csv", "/nh"], 20).splitlines()):
            try:
                out.append({"pid": int(rec[1]), "name": rec[0], "state": "-",
                            "rss": int("".join(c for c in rec[4] if c.isdigit()) or 0) * 1024, "uid": rec[2]})
            except (ValueError, IndexError):
                continue
        out.sort(key=lambda p: -p["rss"])
        return out[:limit]
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        try:
            st = {}
            for line in _read(f"/proc/{pid}/status").splitlines():
                k, _, v = line.partition(":")
                st[k] = v.strip()
            out.append({"pid": int(pid), "name": st.get("Name", ""), "state": st.get("State", "?")[:1],
                        "rss": int(st.get("VmRSS", "0 kB").split()[0]) * 1024,
                        "uid": st.get("Uid", "0").split()[0]})
        except (OSError, ValueError, IndexError):
            continue
    out.sort(key=lambda p: -p["rss"])
    return out[:limit]


class Monitor(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True, name="monitor")
        self.hist = collections.deque(maxlen=int(config.cfg["history_len"]))
        self.alerts = collections.deque(maxlen=50)
        self.lock, self._last = threading.Lock(), {}
        self._cpu, self._net, self._t = _cpu(), _net(), time.time()

    def sample(self):
        now = time.time()
        idle, total = _cpu()
        rx, tx = _net()
        di, dt = idle - self._cpu[0], total - self._cpu[1]
        el = max(now - self._t, 0.001)
        m, du, la = meminfo(), shutil.disk_usage(ROOT_DISK), loadavg()
        s = {"t": int(now), "cpu": round(100 * (1 - di / dt), 1) if dt > 0 else 0.0,
             "mem": round(100 * m["used"] / m["total"], 1), "disk": round(100 * du.used / du.total, 1),
             "rx": max(0, (rx - self._net[0]) / el), "tx": max(0, (tx - self._net[1]) / el),
             "load": la[0] if la else None}
        self._cpu, self._net, self._t = (idle, total), (rx, tx), now
        with self.lock:
            self.hist.append(s)
        self._check(s)
        return s

    def _check(self, s):
        for key, lim in (config.cfg.get("alerts") or {}).items():
            if lim and key in s and s[key] >= lim and time.time() - self._last.get(key, 0) > 300:
                self._last[key] = time.time()
                a = {"t": s["t"], "metric": key, "value": s[key], "limit": lim}
                self.alerts.appendleft(a)
                audit.log("alert", **{k: v for k, v in a.items() if k != "t"})

    def history(self):
        with self.lock:
            return list(self.hist)

    def run(self):
        tick = 0
        while True:
            time.sleep(config.cfg["sample_interval"])
            try:
                config.reload_if_changed()  # `astra config set` from another process (no SIGHUP on Windows)
                self.sample()
                tick += 1
                if tick % max(1, 30 // max(int(config.cfg["sample_interval"]), 1)) == 0:   # ~every 30 s
                    from . import catalog
                    catalog.watch_tick()   # notify when a managed service stops, crashes or comes back
            except Exception as e:  # keep sampling no matter what
                print("monitor:", e, file=sys.stderr)
