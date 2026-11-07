"""Shared test server. All test files share one throwaway config dir and one in-process server."""
import json, os, sys, tempfile, threading, urllib.error, urllib.request

if "ASTRA_HOME" not in os.environ or not os.environ["ASTRA_HOME"].startswith(tempfile.gettempdir()):
    os.environ["ASTRA_HOME"] = tempfile.mkdtemp()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from astra import config, server  # noqa: E402
from astra.extensions import load_extensions  # noqa: E402

TMP = str(config.HOME)
_state = {}


def start():
    """Start (once) and return (port, session). The session id works as a Bearer token for API calls."""
    if not _state:
        config.set_admin("tester", "test-password-1")
        config.save()
        from astra import mfa
        _state["token"] = mfa.login("tester", "test-password-1")["session"]
        load_extensions()
        srv = server.make_server("127.0.0.1", 0)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        _state["port"] = srv.server_address[1]
    return _state["port"], _state["token"]


def http(path, method="GET", body=None, bearer=None, raw=None, headers=None):
    port, _ = start()
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method=method, data=data)
    if bearer:
        req.add_header("Authorization", "Bearer " + bearer)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def jhttp(*a, **k):
    code, body, hdr = http(*a, **k)
    try:
        return code, json.loads(body)
    except ValueError:
        return code, body
