"""Background jobs and the console.

A job is a list of steps (commands or Python functions) run in a thread. Installs, updates and other panel tasks wait in
a queue and run `job_concurrency` at a time (default 1, because many servers have a single core and little RAM); console
commands always run immediately. Its output is kept in memory so the web
GUI can show live progress in the console drawer even when you switch pages. Used for installs/removals started by the
panel and for commands typed into the console. Standard library only.
"""
import codecs, collections, itertools, os, re, shutil, signal, subprocess, threading, time
from . import audit, config, notify, plat
from .errors import PanelError
from .shell import _resolve

MAX_JOBS, MAX_BUF = 30, 400_000
_jobs = collections.OrderedDict()
_lock = threading.Lock()
_ids = itertools.count(1)
PCT = re.compile(r"(?<![\d.])(\d{1,3})(?:\.\d+)?\s?%")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

try:
    import fcntl, pty, struct, termios
except ImportError:  # Windows
    pty = None


class Job:
    def __init__(self, title, steps, kind, env, cwd, interactive, ext):
        self.id = next(_ids)
        self.title, self.steps, self.kind, self.cwd, self.ext = title, steps, kind, cwd, ext
        self.env = {**os.environ, "PYTHONUNBUFFERED": "1", "TERM": "xterm-256color", **(env or {})}
        self.interactive = interactive
        self.state, self.rc, self.step, self.pct = "queued" if kind != "console" else "running", None, 0, None
        self.started, self.ended = time.time(), None
        self.buf, self.dropped = "", 0
        self.proc, self.fd, self.cancelled = None, None, False
        self.lock = threading.Lock()

    # -- output
    def emit(self, text):
        if not text:
            return
        with self.lock:
            self.buf += text
            if len(self.buf) > MAX_BUF:
                cut = len(self.buf) - MAX_BUF
                self.buf, self.dropped = self.buf[cut:], self.dropped + cut
        m = PCT.findall(ANSI.sub("", text))
        if m and 0 <= int(m[-1]) <= 100:
            self.pct = int(m[-1])

    def note(self, text, dim=True):
        self.emit(f"\x1b[2m{text}\x1b[0m\n" if dim else text + "\n")

    def summary(self):
        return {"id": self.id, "title": self.title, "kind": self.kind, "state": self.state, "rc": self.rc,
                "step": self.step, "steps": len(self.steps), "pct": self.pct, "started": int(self.started),
                "ended": int(self.ended) if self.ended else None, "cwd": self.cwd, "interactive": self.interactive,
                "queue_pos": self.queue_pos()}

    def queue_pos(self):
        if self.state != "queued":
            return 0
        q = [j.id for j in _jobs.values() if j.state == "queued"]
        return q.index(self.id) + 1 if self.id in q else 0

    def read(self, since):
        with self.lock:
            start = max(since - self.dropped, 0)
            return {**self.summary(), "text": self.buf[start:], "next": self.dropped + len(self.buf),
                    "truncated": since < self.dropped}

    # -- execution
    def _spawn(self, argv):
        kw = dict(cwd=self.cwd or None, env=self.env)
        if plat.IS_WIN:
            kw["creationflags"] = plat.NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kw["start_new_session"] = True
        if self.interactive and pty:
            master, slave = pty.openpty()
            try:
                fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 32, 140, 0, 0))
            except OSError:
                pass
            self.proc = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, close_fds=True, **kw)
            os.close(slave)
            self.fd = master
            dec = codecs.getincrementaldecoder("utf-8")("replace")
            while True:
                try:
                    data = os.read(master, 4096)
                except OSError:        # EIO: the child closed the terminal
                    break
                if not data:
                    break
                self.emit(dec.decode(data).replace("\r\n", "\n"))
            os.close(master)
            self.fd = None
            return self.proc.wait()
        self.proc = subprocess.Popen(argv, stdin=subprocess.PIPE if self.interactive else subprocess.DEVNULL,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0, **kw)
        dec = codecs.getincrementaldecoder("utf-8")("replace")
        while True:
            data = self.proc.stdout.read1(4096) if hasattr(self.proc.stdout, "read1") else self.proc.stdout.read(4096)
            if not data:
                break
            self.emit(dec.decode(data).replace("\r\n", "\n"))
        return self.proc.wait()

    def run(self):
        rc = 0
        self.state, self.started = "running", time.time()
        try:
            for i, step in enumerate(self.steps, 1):
                if self.cancelled:
                    break
                self.step = i
                optional = False
                if isinstance(step, dict):
                    step, optional = step["cmd"], step.get("optional", False)
                if callable(step):
                    try:
                        out = step()
                        if out:
                            self.emit(str(out).rstrip() + "\n")
                    except Exception as e:  # a failing helper step is a failed job, not a crashed thread
                        self.emit(f"\x1b[31m{getattr(e, 'message', e)}\x1b[0m\n")
                        rc = 1
                        break
                    continue
                argv = _resolve(list(step))
                if self.kind != "console":
                    self.note("$ " + " ".join(argv))
                try:
                    rc = self._spawn(argv)
                except FileNotFoundError:
                    self.emit(f"\x1b[31m{argv[0]}: command not found\x1b[0m\n")
                    rc = 127
                except OSError as e:
                    self.emit(f"\x1b[31m{e}\x1b[0m\n")
                    rc = 126
                if rc and optional:
                    self.note(f"(exit code {rc}, continuing)")
                    rc = 0
                elif rc:
                    break
        except Exception as e:
            self.emit(f"\x1b[31minternal error: {e}\x1b[0m\n")
            rc = 1
        self.rc, self.ended = rc, time.time()
        self.state = "cancelled" if self.cancelled else "done" if rc == 0 else "failed"
        if self.state == "done":
            self.pct = 100
        if self.kind != "console" or rc:
            self.note(f"-- {self.state} (exit code {rc}) --", dim=True)
        if self.kind != "console":
            sev = {"done": "ok", "failed": "critical", "cancelled": "info"}[self.state]
            notify.add("tasks", sev, f"{self.title}: {self.state}", "Open the console to see the output." if sev != "ok" else "",
                       key=f"job:{self.id}")
        _pump()

    def cancel(self):
        self.cancelled = True
        if self.state == "queued":      # never started: just drop it from the queue
            self.state, self.rc, self.ended = "cancelled", 130, time.time()
            self.note("-- cancelled before it started --")
            return
        p = self.proc
        if not p or p.poll() is not None:
            return
        try:
            if plat.IS_WIN:
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, creationflags=plat.NO_WINDOW)
            else:
                os.killpg(os.getpgid(p.pid), signal.SIGTERM)
        except (OSError, subprocess.SubprocessError):
            pass

    def send(self, text):
        if self.state != "running" or not self.interactive:
            raise PanelError("this job is not waiting for input", 409)
        data = text.encode()
        if self.fd is not None:
            os.write(self.fd, data)
        elif self.proc and self.proc.stdin:
            try:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
            except OSError:
                pass


def limit():
    try:
        return max(1, min(8, int(config.cfg.get("job_concurrency", 1))))
    except (TypeError, ValueError):
        return 1


def _pump():
    """Start queued jobs while there is room (called when a job is added or finishes)."""
    with _lock:
        busy = sum(1 for j in _jobs.values() if j.kind != "console" and j.state == "running" and j.ended is None)
        for j in list(_jobs.values()):
            if busy >= limit():
                break
            if j.state == "queued":
                j.state, j.started = "running", time.time()   # claim the slot now, the thread starts a moment later
                busy += 1
                threading.Thread(target=j.run, daemon=True, name=f"job-{j.id}").start()


def start(title, steps, kind="task", env=None, cwd=None, interactive=False, ext=None):
    with _lock:
        if kind != "console" and any(j.title == title and j.state in ("queued", "running") for j in _jobs.values()):
            raise PanelError(f"'{title}' is already waiting or running (see Tasks)", 409)
        job = Job(title, steps, kind, env, cwd, interactive, ext)
        _jobs[job.id] = job
        while len(_jobs) > MAX_JOBS:
            old = next((k for k, j in _jobs.items() if j.state not in ("queued", "running")), None)
            if old is None:
                break
            del _jobs[old]
    if kind == "console":
        threading.Thread(target=job.run, daemon=True, name=f"job-{job.id}").start()
    else:
        _pump()
    return job


def get(jid):
    j = _jobs.get(int(jid)) if str(jid).isdigit() else None
    if not j:
        raise PanelError("unknown job", 404)
    return j


def listing():
    with _lock:
        return [j.summary() for j in reversed(_jobs.values())]


def running():
    return sum(1 for j in _jobs.values() if j.state == "running")


def pending():
    """Panel tasks (not console commands) that are running or waiting."""
    return sum(1 for j in _jobs.values() if j.kind != "console" and j.state in ("queued", "running"))


def clear_finished():
    with _lock:
        for k in [k for k, j in _jobs.items() if j.state not in ("queued", "running")]:
            del _jobs[k]


# ---------------------------------------------------------------- console
def shell_argv(cmd):
    if plat.IS_WIN:
        return ["cmd.exe", "/c", cmd]
    sh = shutil.which("bash") or "/bin/sh"
    return [sh, "-c", cmd]


def _resolve_dir(cwd, target):
    base = cwd or str(config.HOME if config.HOME.exists() else os.path.expanduser("~"))
    tgt = os.path.expanduser(target.strip().strip('"\'') or "~")
    path = os.path.normpath(os.path.join(base, tgt))
    if not os.path.isdir(path):
        raise PanelError(f"cd: no such directory: {path}")
    return path


def default_cwd():
    return os.path.expanduser("~") if os.path.isdir(os.path.expanduser("~")) else os.getcwd()


def info():
    return {"enabled": bool(config.cfg.get("console_enabled", True)), "cwd": default_cwd(), "user": _user(),
            "shell": shell_argv("")[0], "os": plat.OS_NAME, "root": plat.IS_ROOT, "pty": bool(pty)}


def _user():
    try:
        import getpass
        return getpass.getuser()
    except Exception:
        return ""


def run_command(cmd, cwd, ip="?"):
    if not config.cfg.get("console_enabled", True):
        raise PanelError("the console is turned off (Settings > Console)", 403)
    cmd = str(cmd or "").strip()
    if not cmd or len(cmd) > 4000 or "\0" in cmd:
        raise PanelError("type a command")
    cwd = cwd if cwd and os.path.isdir(cwd) else default_cwd()
    m = re.fullmatch(r"cd(?:\s+(.*))?", cmd)
    if m:
        return {"cwd": _resolve_dir(cwd, m[1] or "~")}
    audit.log("console", ip=ip, command=cmd[:300], cwd=cwd)
    job = start(cmd[:60], [shell_argv(cmd)], kind="console", cwd=cwd, interactive=True)
    return {"job": job.id}


def route(parts, method, params, ip):
    """/api/jobs, /api/jobs/<id>[/cancel|/input], /api/console/info, /api/console/run"""
    head = parts[0]
    if head == "console":
        if parts[1:] == ["info"]:
            return info()
        if parts[1:] == ["run"] and method == "POST":
            return run_command(params.get("cmd"), params.get("cwd"), ip)
        raise PanelError("not found", 404)
    if len(parts) == 1:
        return {"jobs": listing(), "running": running(), "pending": pending(), "limit": limit()}
    if parts[1] == "clear" and method == "POST":
        clear_finished()
        return {"ok": True}
    if parts[1] == "limit" and method == "POST":
        try:
            n = int(params.get("n"))
        except (TypeError, ValueError):
            raise PanelError("n must be a number from 1 to 8")
        config.cfg["job_concurrency"] = max(1, min(8, n))
        config.save()
        _pump()
        return {"ok": True, "limit": limit()}
    job = get(parts[1])
    if len(parts) == 2:
        try:
            since = int(params.get("since") or 0)
        except ValueError:
            since = 0
        return job.read(since)
    if parts[2] == "cancel" and method == "POST":
        job.cancel()
        return {"ok": True}
    if parts[2] == "input" and method == "POST":
        job.send(str(params.get("text", "")))
        return {"ok": True}
    raise PanelError("not found", 404)
