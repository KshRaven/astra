import json, os, sys, tempfile, threading, unittest, urllib.error, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import helpers  # noqa: E402  (sets ASTRA_HOME to a throwaway folder before astra is imported)
TMP = helpers.TMP

from astra import config, server  # noqa: E402
from astra.errors import PanelError  # noqa: E402
from astra.extensions import load_extensions, registry  # noqa: E402
from astra.shell import NAME, DOMAIN, need, safe_path  # noqa: E402


class Panel(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = os.path.join(TMP, "www")
        os.makedirs(cls.root)
        config.cfg["file_roots"] = [cls.root]
        config.cfg["backup_dir"] = os.path.join(TMP, "bk")
        config.set_admin("tester", "test-password-1")
        config.save()
        from astra import mfa
        cls.token = mfa.login("tester", "test-password-1")["session"]
        load_extensions()
        cls.srv = server.make_server("127.0.0.1", 0)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def http(self, path, method="GET", body=None, token=True):
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                                     data=json.dumps(body).encode() if body is not None else None)
        if token:
            req.add_header("Authorization", "Bearer " + self.token)
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read(), r.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    # --- validation helpers
    def test_validators(self):
        self.assertTrue(need("nginx", NAME, "x"))
        for bad in ("-rf", "a b", "a;b", "", "../x"):
            with self.assertRaises(PanelError):
                need(bad, NAME, "x")
        self.assertTrue(DOMAIN.match("example.com"))
        self.assertFalse(DOMAIN.match("evil.com;rm -rf /"))

    def test_safe_path(self):
        self.assertEqual(safe_path(self.root, [self.root]), os.path.realpath(self.root))
        for bad in (self.root + "/../etc", "/etc/passwd", self.root + "x"):
            with self.assertRaises(PanelError):
                safe_path(bad, [self.root])
        os.symlink("/etc", os.path.join(self.root, "escape"))
        with self.assertRaises(PanelError):
            safe_path(os.path.join(self.root, "escape", "passwd"), [self.root])

    # --- server
    def test_static_and_headers(self):
        code, body, hdr = self.http("/", token=False)
        self.assertEqual(code, 200)
        self.assertIn(b"astra", body)
        self.assertIn("default-src 'self'", hdr["Content-Security-Policy"])

    def test_auth(self):
        self.assertEqual(self.http("/api/dashboard", token=False)[0], 401)
        code, body, _ = self.http("/api/dashboard")
        self.assertEqual(code, 200)
        self.assertIn("hostname", json.loads(body))

    def test_write_requires_post(self):
        self.assertEqual(self.http(f"/api/ext/files/mkdir?path={self.root}&name=x")[0], 405)

    def test_files_roundtrip_and_sandbox(self):
        f = os.path.join(self.root, "a.txt")
        code, _, _ = self.http("/api/ext/files/write", "POST", {"path": f, "content": "héllo"})
        self.assertEqual(code, 200)
        code, body, _ = self.http("/api/ext/files/read?path=" + f)
        self.assertEqual(json.loads(body)["content"], "héllo")
        self.assertEqual(self.http("/api/ext/files/read?path=/etc/passwd")[0], 403)
        code, body, hdr = self.http("/api/ext/files/download?path=" + f)
        self.assertEqual(body.decode(), "héllo")
        self.assertIn("attachment", hdr["Content-Disposition"])
        self.assertEqual(self.http("/api/ext/files/delete", "POST", {"path": self.root})[0], 403)
        self.assertEqual(self.http("/api/ext/files/delete", "POST", {"path": f})[0], 200)

    def test_symlink_delete_keeps_target(self):
        outside = os.path.join(TMP, "outside.txt")
        open(outside, "w").write("keep")
        link = os.path.join(self.root, "lnk")
        os.symlink(outside, link)
        self.http("/api/ext/files/delete", "POST", {"path": link})
        self.assertTrue(os.path.exists(outside))
        self.assertFalse(os.path.lexists(link))

    def test_extensions_listed(self):
        names = {e["name"] for e in json.loads(self.http("/api/extensions")[1])}
        self.assertTrue({"services", "websites", "files", "cron", "firewall", "docker", "databases",
                         "logs", "processes", "security", "backups", "desktop"} <= names)

    def test_backup_cycle(self):
        d = os.path.join(self.root, "proj")
        os.makedirs(d)
        open(os.path.join(d, "f.txt"), "w").write("x")
        self.assertEqual(self.http("/api/ext/backups/create", "POST", {"path": d})[0], 200)
        rows = json.loads(self.http("/api/ext/backups/list")[1])
        self.assertTrue(rows and rows[0]["name"].endswith(".tar.gz"))
        self.assertEqual(self.http("/api/ext/backups/delete", "POST", {"name": "../x"})[0], 400)

    def test_cron_validation(self):
        os.environ["ASTRA_CRON_FILE"] = os.path.join(TMP, "crontab")
        from astra.extensions import cron
        cron.CRON_FILE = type(cron.CRON_FILE)(os.environ["ASTRA_CRON_FILE"])
        fn = registry["cron"].routes["add"][0]
        with self.assertRaises(PanelError):
            fn({"name": "x", "schedule": "* * * *", "command": "ls"})
        with self.assertRaises(PanelError):
            fn({"name": "x", "schedule": "* * * * *", "command": "ls\nrm -rf /"})
        fn({"name": "ok", "schedule": "*/5 * * * *", "command": "echo 100%"})
        self.assertIn("echo 100\\%", cron.CRON_FILE.read_text())

    def test_zz_rate_limit(self):
        for _ in range(5):
            self.http("/api/dashboard", token=False)
        self.assertEqual(self.http("/api/dashboard")[0], 429)
        server.limiter.ok("127.0.0.1")


if __name__ == "__main__":
    unittest.main()
