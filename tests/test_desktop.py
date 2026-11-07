"""Desktop tab: gating logic only. Nothing here installs packages or starts a session."""
import collections, types, unittest
from helpers import http, jhttp, start
from astra.errors import PanelError
from astra.extensions import desktop, registry


def boom(*a, **k):
    raise AssertionError("must not touch the system")


class Desktop(unittest.TestCase):
    def setUp(self):
        _, self.token = start()
        self.keep = (desktop._checks, desktop._installed, desktop._ram_mb, desktop._user, desktop.run, desktop.subprocess, desktop.threading)

    def tearDown(self):
        desktop._checks, desktop._installed, desktop._ram_mb, desktop._user, desktop.run, desktop.subprocess, desktop.threading = self.keep

    def test_listed_with_lazy_ui_and_no_dependency(self):
        meta = {e["name"]: e for e in jhttp("/api/extensions", bearer=self.token)[1]}
        self.assertEqual(meta["desktop"]["ui"], "desktop")
        self.assertTrue(meta["desktop"]["available"])
        self.assertIn("install_log", registry["desktop"].routes)

    def test_status_shape(self):
        desktop._installed = lambda: False
        st = jhttp("/api/ext/desktop/status", bearer=self.token)[1]
        self.assertFalse(st["installed"])
        self.assertEqual(len(st["checks"]), 4)
        self.assertIn("novnc", st["packages"])

    def test_install_refused_on_low_resources(self):
        desktop._installed = lambda: False
        desktop._checks = lambda: [{"label": "Free memory", "ok": False, "detail": "100 MB"}] * 3 + [{"label": "x", "ok": True, "detail": ""}]
        desktop.subprocess = types.SimpleNamespace(run=boom, Popen=boom)  # module-local stubs; the HTTP server keeps real threads
        desktop.threading = types.SimpleNamespace(Thread=boom)
        code, r = jhttp("/api/ext/desktop/install", "POST", {}, bearer=self.token)
        self.assertEqual(code, 400)
        self.assertIn("cannot install", r["error"])
        self.assertEqual(jhttp("/api/ext/desktop/install", bearer=self.token)[0], 405)  # write needs POST

    def test_start_requires_install_user_and_memory(self):
        desktop.run = boom
        desktop.subprocess = types.SimpleNamespace(run=boom, Popen=boom)
        desktop._installed = lambda: False
        with self.assertRaises(PanelError):
            desktop.start({})
        desktop._installed = lambda: True
        with self.assertRaises(PanelError) as c:  # no desktop.user configured
            desktop.start({})
        self.assertIn("unprivileged user", c.exception.message)
        desktop._user = lambda: collections.namedtuple("U", "pw_name pw_uid pw_gid pw_dir")("a", 1000, 1000, "/home/a")
        desktop._ram_mb = lambda: 100
        with self.assertRaises(PanelError) as c:
            desktop.start({})
        self.assertIn("memory", c.exception.message)

    def test_user_must_be_unprivileged(self):
        desktop.config.cfg["desktop"]["user"] = "root"
        try:
            with self.assertRaises(PanelError):
                desktop._user()
        finally:
            desktop.config.cfg["desktop"]["user"] = ""


if __name__ == "__main__":
    unittest.main()
