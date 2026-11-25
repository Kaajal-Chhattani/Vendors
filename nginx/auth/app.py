"""Login page + auth_request backend for the Temporal UI (stdlib only).

nginx calls GET /_tauth/check for every request; 204 lets it through, 401 sends the browser to
/_tauth/login. Credentials are checked against Django (chat.views.TemporalAuthView), so Django
stays the only place users and passwords live."""
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request
from html import escape
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

COOKIE = "temporal_session"
SESSION_SECONDS = 8 * 3600
RECHECK_SECONDS = 300  # how often an existing session is re-validated against Django
SECRET = os.environ["TEMPORAL_AUTH_SECRET"].encode()
DJANGO_URL = os.environ["DJANGO_AUTH_URL"]
DJANGO_SECRET = os.environ["TEMPORAL_AUTH_DJANGO_SECRET"]
LOGIN_HTML = open(os.path.join(os.path.dirname(__file__), "login.html"), encoding="utf-8").read()
_active_cache = {}  # username -> (checked_at, is_active)


def sign(value):
    return hmac.new(SECRET, value.encode(), hashlib.sha256).hexdigest()


def make_token(username):
    body = base64.urlsafe_b64encode(f"{username}|{int(time.time()) + SESSION_SECONDS}".encode()).decode()
    return f"{body}.{sign(body)}"


def read_token(token):
    """Username for a valid, unexpired token, else None."""
    try:
        body, signature = token.rsplit(".", 1)
        if not hmac.compare_digest(signature, sign(body)):
            return None
        username, expires = base64.urlsafe_b64decode(body.encode()).decode().rsplit("|", 1)
        return username if int(expires) > time.time() else None
    except Exception:
        return None


def ask_django(username, password=None):
    """True/False from Django; None when Django cannot be reached."""
    payload = {"username": username}
    if password is not None:
        payload["password"] = password
    request = urllib.request.Request(
        DJANGO_URL, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "X-Temporal-Auth-Secret": DJANGO_SECRET, "Host": "localhost"},  # Django ALLOWED_HOSTS
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return bool(json.load(response).get("ok"))
    except urllib.error.HTTPError:
        return False
    except Exception as error:
        print("Django auth check failed:", error, flush=True)
        return None


def still_active(username):
    checked_at, active = _active_cache.get(username, (0, True))
    if time.time() - checked_at < RECHECK_SECONDS:
        return active
    result = ask_django(username)
    if result is None:  # Django is down: keep the session rather than lock everyone out
        return active
    _active_cache[username] = (time.time(), result)
    return result


def safe_next(value):
    return value if value and value.startswith("/") and not value.startswith("//") and not value.startswith("/_tauth/") else "/"


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print(self.address_string(), fmt % args, flush=True)

    def session_user(self):
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get(COOKIE)
        user = read_token(morsel.value) if morsel else None
        return user if user and still_active(user) else None

    def respond(self, status, body=b"", headers=None):
        self.send_response(status)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def login_page(self, next_url, error="", status=200):
        page = LOGIN_HTML.replace("{{next}}", escape(next_url, quote=True)).replace(
            "{{error}}", f'<div class="error">{escape(error)}</div>' if error else "")
        self.respond(status, page.encode(), {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"})

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/_tauth/check":
            self.respond(204 if self.session_user() else 401)
        elif url.path == "/_tauth/login":
            next_url = safe_next(parse_qs(url.query).get("next", ["/"])[0])
            if self.session_user():
                self.respond(302, headers={"Location": next_url})
            else:
                self.login_page(next_url)
        elif url.path == "/_tauth/logout":
            self.respond(302, headers={"Location": "/_tauth/login", "Set-Cookie": f"{COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"})
        else:
            self.respond(404)

    def do_POST(self):
        if urlparse(self.path).path != "/_tauth/login":
            return self.respond(404)
        form = parse_qs(self.rfile.read(int(self.headers.get("Content-Length", 0))).decode())
        username = form.get("username", [""])[0].strip()
        password = form.get("password", [""])[0]
        next_url = safe_next(form.get("next", ["/"])[0])
        result = ask_django(username, password) if username and password else False
        if result is None:
            return self.login_page(next_url, "Login is temporarily unavailable. Please try again.", 503)
        if not result:
            return self.login_page(next_url, "Incorrect username or password.", 401)
        _active_cache[username] = (time.time(), True)
        self.respond(302, headers={
            "Location": next_url,
            "Set-Cookie": f"{COOKIE}={make_token(username)}; Path=/; Max-Age={SESSION_SECONDS}; HttpOnly; SameSite=Lax",
        })


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", int(os.environ.get("PORT", "8000"))), Handler).serve_forever()
