import threading, time


class Limiter:
    """Blocks an IP for `window` seconds after `max_fail` bad tokens."""

    def __init__(self, max_fail=5, window=300):
        self.max_fail, self.window, self.fails, self.lock = max_fail, window, {}, threading.Lock()

    def _recent(self, ip):
        now = time.time()
        self.fails[ip] = [t for t in self.fails.get(ip, []) if now - t < self.window]
        return self.fails[ip]

    def blocked(self, ip):
        with self.lock:
            return len(self._recent(ip)) >= self.max_fail

    def fail(self, ip):
        with self.lock:
            self._recent(ip).append(time.time())

    def ok(self, ip):
        with self.lock:
            self.fails.pop(ip, None)
