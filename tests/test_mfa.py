import base64, time, unittest
import helpers
from helpers import config, http, jhttp, server, start
from astra import mfa


class MFA(unittest.TestCase):
    def setUp(self):
        _, self.token = start()
        self.sent = []
        self._send = mfa.send_mail
        mfa.send_mail = lambda to, subj, body: self.sent.append(body)
        config.cfg["smtp"].update(host="smtp.test", **{"from": "panel@test"})

    def tearDown(self):
        mfa.send_mail = self._send
        mfa.reset_all()
        mfa.revoke(keep="")
        server.limiter.ok("127.0.0.1")

    def session(self):
        code, r = jhttp("/api/auth/login", "POST", {"username": "tester", "password": "test-password-1"})
        self.assertEqual(code, 200)
        return r["session"]

    def enrol_totp(self, s):
        r = jhttp("/api/mfa/totp/begin", "POST", bearer=s)[1]
        n = int(time.time()) // 30
        self.assertEqual(jhttp("/api/mfa/totp/confirm", "POST", {"code": mfa._hotp(r["secret"], n)}, bearer=s)[0], 200)
        return r["secret"], n

    def test_rfc6238_vector(self):  # RFC 4226 appendix D / RFC 6238 SHA-1 secret "12345678901234567890"
        key = base64.b32encode(b"12345678901234567890").decode()
        self.assertEqual(mfa._hotp(key, 1), "287082")
        self.assertEqual(mfa._hotp(key, 0), "755224")

    def test_totp_window_and_replay(self):
        key = base64.b32encode(b"x" * 20).decode()
        n = int(time.time()) // 30
        self.assertEqual(mfa.totp_check(key, mfa._hotp(key, n)), n)
        self.assertEqual(mfa.totp_check(key, mfa._hotp(key, n - 1)), n - 1)
        self.assertIsNone(mfa.totp_check(key, mfa._hotp(key, n - 3)))
        self.assertIsNone(mfa.totp_check(key, mfa._hotp(key, n), after=n))
        self.assertIsNone(mfa.totp_check(key, "abc123"))

    def test_login_without_mfa(self):
        s = self.session()
        self.assertEqual(http("/api/ping", bearer=s)[0], 200)
        self.assertEqual(jhttp("/api/auth/login", "POST", {"username": "tester", "password": "wrong"})[0], 401)
        self.assertEqual(jhttp("/api/auth/login", "POST", {"username": "nobody", "password": "test-password-1"})[0], 401)

    def test_totp_flow(self):
        s = self.session()
        secret, used = self.enrol_totp(s)
        code, r = jhttp("/api/auth/login", "POST", {"username": "tester", "password": "test-password-1"})
        self.assertEqual(r["mfa"], ["totp"])
        cid = r["challenge"]
        self.assertEqual(jhttp("/api/auth/verify", "POST", {"challenge": cid, "method": "totp", "code": "000000"})[0], 401)
        good = mfa._hotp(secret, used + 1)
        code, r = jhttp("/api/auth/verify", "POST", {"challenge": cid, "method": "totp", "code": good})
        self.assertEqual(code, 200)
        self.assertEqual(http("/api/ping", bearer=r["session"])[0], 200)
        cid2 = jhttp("/api/auth/login", "POST", {"username": "tester", "password": "test-password-1"})[1]["challenge"]
        self.assertEqual(jhttp("/api/auth/verify", "POST", {"challenge": cid2, "method": "totp", "code": good})[0], 401, "replay")

    def test_email_flow(self):
        s = self.session()
        self.assertEqual(jhttp("/api/mfa/email/begin", "POST", {"email": "not-an-email"}, bearer=s)[0], 400)
        self.assertEqual(jhttp("/api/mfa/email/begin", "POST", {"email": "me@example.com"}, bearer=s)[0], 200)
        code_setup = self.sent[-1].split("code is ")[1][:6]
        self.assertEqual(jhttp("/api/mfa/email/confirm", "POST", {"code": "000000"}, bearer=s)[0], 401)
        self.assertEqual(jhttp("/api/mfa/email/confirm", "POST", {"code": code_setup}, bearer=s)[0], 200)
        self.assertIn("m***@example.com", jhttp("/api/mfa/status", bearer=s)[1]["email_address"])
        r = jhttp("/api/auth/login", "POST", {"username": "tester", "password": "test-password-1"})[1]
        self.assertEqual(r["mfa"], ["email"])
        self.assertEqual(jhttp("/api/auth/verify", "POST", {"challenge": r["challenge"], "method": "email", "code": "123456"})[0], 400)  # no code requested yet
        self.assertEqual(jhttp("/api/auth/send", "POST", {"challenge": r["challenge"]})[0], 200)
        self.assertEqual(jhttp("/api/auth/send", "POST", {"challenge": r["challenge"]})[0], 429)  # cooldown
        code = self.sent[-1].split("code is ")[1][:6]
        self.assertIn("nothing to unsubscribe", self.sent[-1])
        code_, out = jhttp("/api/auth/verify", "POST", {"challenge": r["challenge"], "method": "email", "code": code})
        self.assertEqual(code_, 200)
        self.assertEqual(http("/api/ping", bearer=out["session"])[0], 200)

    def test_challenge_attempt_limit(self):
        s = self.session()
        self.enrol_totp(s)
        cid = jhttp("/api/auth/login", "POST", {"username": "tester", "password": "test-password-1"})[1]["challenge"]
        codes = [jhttp("/api/auth/verify", "POST", {"challenge": cid, "method": "totp", "code": "111111"})[0] for _ in range(7)]
        self.assertIn(429, codes)

    def test_password_change_revokes_other_sessions(self):
        a, b = self.session(), self.session()
        code, _ = jhttp("/api/account/update", "POST", {"current": "test-password-1", "new_password": "test-password-2"}, bearer=a)
        self.assertEqual(code, 200)
        self.assertEqual(http("/api/ping", bearer=a)[0], 200)
        self.assertEqual(http("/api/ping", bearer=b)[0], 401)
        self.assertEqual(jhttp("/api/account/update", "POST", {"current": "nope", "new_password": "x" * 12}, bearer=a)[0], 401)
        config.set_admin("tester", "test-password-1")  # restore for the other tests
        config.save()

    def test_logout(self):
        s = self.session()
        http("/api/auth/logout", "POST", bearer=s)
        self.assertEqual(http("/api/ping", bearer=s)[0], 401)

    def test_auth_body_limit_and_pre_auth_body(self):
        self.assertEqual(http("/api/auth/login", "POST", raw=b"{" + b" " * 5000 + b"}")[0], 413)
        self.assertEqual(http("/api/ext/files/upload", "POST", raw=b"{" + b" " * 9000 + b"}")[0], 401)

    def test_privacy_export_masks_and_delete_clears(self):
        s = self.session()
        self.enrol_totp(s)
        exp = jhttp("/api/privacy/export", bearer=s)[1]
        self.assertEqual(exp["config"]["mfa"]["totp_secret"], "<set>")
        self.assertEqual(exp["config"]["admin"]["password_hash"], "<set>")
        self.assertEqual(jhttp("/api/privacy/delete", "POST", {}, bearer=s)[0], 405)
        self.assertEqual(jhttp("/api/privacy/delete", "POST", {"confirm": "delete"}, bearer=s)[0], 200)
        self.assertFalse(mfa.required())
        self.assertEqual(config.cfg["mfa"]["totp_secret"], "")


if __name__ == "__main__":
    unittest.main()
