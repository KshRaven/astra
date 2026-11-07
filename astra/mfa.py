"""Sign-in sessions and multi-factor authentication. Standard library only.

Factors: TOTP (RFC 6238, works with Google Authenticator, Authy, 1Password...) and e-mail codes.
The username + password is always factor one. Sessions live in memory (a restart signs everyone out).
"""
import base64, hashlib, hmac, os, secrets, smtplib, socket, ssl, struct, sys, threading, time, urllib.parse
from email.message import EmailMessage
from . import config
from .errors import PanelError
from .shell import EMAIL

CHALLENGE_TTL, CODE_TTL, MAX_TRIES, RESEND_GAP = 300, 600, 5, 30
_lock = threading.Lock()
_sessions, _challenges, _pending = {}, {}, {}


def _h(s):
    return hashlib.sha256(s.encode()).hexdigest()


def _m():
    return config.cfg["mfa"]


def required():
    return bool(_m().get("totp_enabled") or _m().get("email_enabled"))


def methods():
    return [k for k in ("totp", "email") if _m().get(k + "_enabled")]


# ---------- sessions
def new_session():
    sid = secrets.token_urlsafe(32)
    ttl = float(config.cfg.get("session_ttl_hours", 8)) * 3600
    with _lock:
        now = time.time()
        for k in [k for k, v in _sessions.items() if v < now]:
            del _sessions[k]
        _sessions[_h(sid)] = now + ttl
    return sid


def session_ok(sid):
    with _lock:
        exp = _sessions.get(_h(sid or ""))
        if exp and exp < time.time():
            _sessions.pop(_h(sid), None)
            return False
        return bool(exp)


def revoke(sid=None, keep=None):
    """Drop one session, or all sessions except `keep`."""
    with _lock:
        if sid is not None:
            _sessions.pop(_h(sid), None)
        else:
            for k in [k for k in _sessions if k != _h(keep or "")]:
                del _sessions[k]


# ---------- TOTP
def _hotp(secret, counter):
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    d = hmac.new(key, struct.pack(">Q", counter), "sha1").digest()
    o = d[-1] & 15
    return f"{(struct.unpack('>I', d[o:o + 4])[0] & 0x7FFFFFFF) % 10 ** 6:06d}"


def totp_check(secret, code, after=0):
    """Return the matching 30 s counter (allows +-1 step of clock drift) or None. Counters <= `after` are rejected (replay)."""
    code = str(code or "").replace(" ", "")
    if not (code.isdigit() and len(code) == 6):
        return None
    now = int(time.time()) // 30
    for c in (now - 1, now, now + 1):
        if c > after and hmac.compare_digest(_hotp(secret, c), code):
            return c
    return None


# ---------- e-mail
def send_mail(to, subject, body):
    s = config.cfg["smtp"]
    if s.get("host") == "console" and os.environ.get("ASTRA_DEV") == "1":  # dev/test only
        print(f"[dev mail] to={to} subject={subject}\n{body}", file=sys.stderr, flush=True)
        return
    if not s.get("host") or not s.get("from"):
        raise PanelError("SMTP is not configured: set smtp.host and smtp.from (see README, 'Multi-factor sign-in')")
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = s["from"], to, subject
    msg.set_content(body)
    port, sec = int(s.get("port") or 587), s.get("security", "starttls")
    try:
        ctx = ssl.create_default_context()
        cli = smtplib.SMTP_SSL(s["host"], port, timeout=15, context=ctx) if sec == "ssl" else smtplib.SMTP(s["host"], port, timeout=15)
        with cli:
            if sec == "starttls":
                cli.starttls(context=ctx)
            if s.get("user"):
                cli.login(s["user"], s.get("password", ""))
            cli.send_message(msg)
    except (OSError, smtplib.SMTPException) as e:
        raise PanelError(f"could not send e-mail ({type(e).__name__})", 502)


def _mail_code(to, purpose):
    code = f"{secrets.randbelow(10 ** 6):06d}"
    send_mail(to, f"astra {purpose} code",
              f"Your astra {purpose} code is {code}\n\nIt expires in {CODE_TTL // 60} minutes and works once.\n"
              "If you did not ask for it, nobody should have your password: change it in Settings.\n"
              "This is a one-time security message, not a mailing list; there is nothing to unsubscribe from.\n")
    return {"hash": _h(code), "exp": time.time() + CODE_TTL, "tries": 0, "sent": time.time()}


def _check_code(slot, code):
    slot["tries"] += 1
    if slot["tries"] > MAX_TRIES or slot["exp"] < time.time():
        raise PanelError("code expired or too many attempts; request a new one", 401)
    if not hmac.compare_digest(_h(str(code or "").strip()), slot["hash"]):
        raise PanelError("wrong code", 401)


# ---------- login (step 1: username + password, step 2: factor)
def login(username, password):
    if not config.check_login(username, password):
        raise PanelError("wrong username or password", 401)
    if not required():
        return {"session": new_session()}
    cid = secrets.token_urlsafe(24)
    with _lock:
        now = time.time()
        for k in [k for k, v in _challenges.items() if v["exp"] < now]:
            del _challenges[k]
        _challenges[cid] = {"exp": now + CHALLENGE_TTL, "tries": 0, "email": None}
    return {"mfa": methods(), "challenge": cid}


def _challenge(cid):
    c = _challenges.get(cid or "")
    if not c or c["exp"] < time.time():
        raise PanelError("sign-in expired, start again", 401)
    return c


def send_login_code(cid):
    with _lock:
        c = _challenge(cid)
        if not _m().get("email_enabled"):
            raise PanelError("e-mail codes are not enabled")
        if c["email"] and time.time() - c["email"]["sent"] < RESEND_GAP:
            raise PanelError(f"wait {RESEND_GAP} seconds before requesting another code", 429)
        to, c["email"] = _m()["email"], {"sent": time.time(), "hash": "", "exp": 0, "tries": 99}  # reserve the slot
    slot = _mail_code(to, "sign-in")  # network call outside the lock
    with _lock:
        c["email"] = slot
    return {"sent": True}


def verify_login(cid, method, code):
    with _lock:
        c = _challenge(cid)
        c["tries"] += 1
        if c["tries"] > MAX_TRIES:
            _challenges.pop(cid, None)
            raise PanelError("too many attempts, start again", 429)
        if method == "totp" and _m().get("totp_enabled"):
            n = totp_check(_m()["totp_secret"], code, _m().get("totp_last", 0))
            if n is None:
                raise PanelError("wrong code", 401)
            _m()["totp_last"] = n
            config.save()
        elif method == "email" and _m().get("email_enabled"):
            if not c["email"]:
                raise PanelError("request an e-mail code first")
            _check_code(c["email"], code)
        else:
            raise PanelError("unknown method")
        _challenges.pop(cid, None)
    return {"session": new_session()}


# ---------- enrolment (needs a signed-in session)
def status():
    s, e = config.cfg["smtp"], _m().get("email", "")
    masked = e[0] + "***@" + e.split("@")[1] if "@" in e else ""
    return {"totp": bool(_m().get("totp_enabled")), "email": bool(_m().get("email_enabled")),
            "email_address": masked, "smtp_configured": bool(s.get("host") and s.get("from"))}


def totp_begin():
    secret = base64.b32encode(secrets.token_bytes(20)).decode()
    _pending["totp"] = secret
    label = urllib.parse.quote("astra:" + socket.gethostname())
    return {"secret": secret, "uri": f"otpauth://totp/{label}?secret={secret}&issuer=astra&digits=6&period=30"}


def totp_confirm(code):
    secret = _pending.get("totp")
    n = secret and totp_check(secret, code)
    if not n:
        raise PanelError("wrong code (or setup not started)", 401)
    _m().update(totp_secret=secret, totp_enabled=True, totp_last=n)
    config.save()
    _pending.pop("totp", None)
    return {"ok": True}


def email_begin(addr):
    if not isinstance(addr, str) or not EMAIL.match(addr):
        raise PanelError("invalid e-mail address")
    _pending["email"] = {**_mail_code(addr, "setup"), "addr": addr}
    return {"sent": True}


def email_confirm(code):
    slot = _pending.get("email")
    if not slot:
        raise PanelError("setup not started")
    _check_code(slot, code)
    _m().update(email=slot["addr"], email_enabled=True)
    config.save()
    _pending.pop("email", None)
    return {"ok": True}


def disable(method):
    if method == "totp":
        _m().update(totp_secret="", totp_enabled=False, totp_last=0)
    elif method == "email":
        _m().update(email="", email_enabled=False)
    else:
        raise PanelError("unknown method")
    config.save()
    return {"ok": True}


def reset_all():
    """Used by `astra mfa reset` (needs local root access to the config)."""
    _m().update(totp_secret="", totp_enabled=False, totp_last=0, email="", email_enabled=False)
    config.save()
