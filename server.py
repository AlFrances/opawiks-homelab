#!/usr/bin/env python3
"""Runs the website and asks for a password before showing private folders.

Start the site:       python3 server.py
Change the password:  python3 server.py --set-password
"""
import getpass
import hashlib
import hmac
import html
import http.server
import os
import posixpath
import secrets
import sys
import threading
import time
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit

# Settings you can change
PORT = 8080
MAX_TRIES = 10
LOCK_SECONDS = 2 * 60
SESSION_SECONDS = 12 * 60 * 60  # Longest a login lasts if nobody leaves the private pages
USE_HTTPS = False  # Set to True once the site runs on https://

# Only these can be opened. Everything else (like this file) gives a 404.
PRIVATE_FOLDERS = {"roms", "photos", "movies"}
PUBLIC_FILES = {"main_page.html", "style.css", "main.js", "cv.pdf"}

SITE = Path(__file__).resolve().parent
HASH_FILE = SITE / "password.hash"
ITERATIONS = 600_000
COOKIE = "session"

data_lock = threading.Lock()
sessions = {}  # login token -> time it expires
failures = {}  # IP address -> {"count", "last_try", "locked_until"}


def hash_password(password, salt=None, iterations=ITERATIONS):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
    return f"{iterations}${salt}${digest}"


def check_password(password):
    saved = HASH_FILE.read_text().strip()
    iterations, salt, _ = saved.split("$")
    return hmac.compare_digest(hash_password(password, salt, int(iterations)), saved)


def seconds_locked(ip):
    """How long this IP address must still wait (0 means it can try)."""
    with data_lock:
        record = failures.get(ip)
        if not record:
            return 0
        now = time.time()
        if record["locked_until"] > now:
            return int(record["locked_until"] - now) + 1
        if now - record["last_try"] >= LOCK_SECONDS:
            del failures[ip]
        return 0


def use_try(ip):
    """Counts a try before checking it, so tries sent at the same time all count."""
    with data_lock:
        now = time.time()
        for address, record in list(failures.items()):
            if now - record["last_try"] >= LOCK_SECONDS and record["locked_until"] <= now:
                del failures[address]
        record = failures.setdefault(ip, {"count": 0, "last_try": now, "locked_until": 0})
        if record["locked_until"] > now:
            return False
        record["count"] += 1
        record["last_try"] = now
        if record["count"] >= MAX_TRIES:
            record["count"] = 0
            record["locked_until"] = now + LOCK_SECONDS
        return True


def tries_left(ip):
    with data_lock:
        record = failures.get(ip)
        return MAX_TRIES - record["count"] if record else MAX_TRIES


def login_succeeded(ip):
    with data_lock:
        failures.pop(ip, None)
        now = time.time()
        for token, expires in list(sessions.items()):
            if expires <= now:
                del sessions[token]
        token = secrets.token_urlsafe(32)
        sessions[token] = now + SESSION_SECONDS
        return token


def format_wait(seconds):
    minutes, rest = divmod(seconds, 60)
    return f"{minutes} min {rest:02d} s" if minutes else f"{rest} s"


def clean_path(raw_path):
    """Turns the address into a safe path, or None if it looks wrong."""
    path = unquote(urlsplit(raw_path).path)
    if "\\" in path or "\0" in path:
        return None
    wants_folder = path.endswith("/")
    parts = posixpath.normpath("/" + path).strip("/").split("/")
    parts = [part for part in parts if part]
    if any(part.startswith(".") for part in parts):
        return None
    cleaned = "/" + "/".join(parts)
    return cleaned + "/" if wants_folder and parts else cleaned


def is_private(path):
    return path.strip("/").split("/")[0] in PRIVATE_FOLDERS


def safe_next(value):
    """After login, only go back to a private page on this site."""
    path = clean_path(value or "")
    return quote(path) if path and is_private(path) else "/roms/"


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SITE), **kwargs)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        if self.private_response:
            self.send_header("Cache-Control", "no-store")
        if self.clear_cookie:
            self.send_header("Set-Cookie", self.cookie_text("", 0))
        super().end_headers()

    private_response = False
    clear_cookie = False

    def list_directory(self, path):
        self.send_error(404)  # Never show a folder's raw file list.

    def client_ip(self):
        return self.client_address[0]

    def session_token(self):
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except Exception:
            return None
        return cookie[COOKIE].value if COOKIE in cookie else None

    def logged_in(self):
        token = self.session_token()
        with data_lock:
            return bool(token) and sessions.get(token, 0) > time.time()

    def end_session(self):
        """Logs this visitor out, so coming back asks for the password again."""
        with data_lock:
            sessions.pop(self.session_token(), None)
        self.clear_cookie = bool(self.session_token())

    def redirect(self, location, cookie=None):
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Content-Length", "0")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def cookie_text(self, value, max_age=None):
        # With no Max-Age, the browser forgets the login when it closes.
        age = "" if max_age is None else f"; Max-Age={max_age}"
        secure = "; Secure" if USE_HTTPS else ""
        return f"{COOKIE}={value}; Path=/{age}; HttpOnly; SameSite=Lax{secure}"

    def send_login(self, status=200, message="", next_path="/roms/"):
        wait = seconds_locked(self.client_ip())
        if wait:
            status = 429
            message = f"Too many tries. Try again in {format_wait(wait)}."
        page = (SITE / "login.html").read_text(encoding="utf-8")
        page = page.replace("{{message}}", html.escape(message))
        page = page.replace("{{next}}", html.escape(next_path, quote=True))
        page = page.replace("{{disabled}}", "disabled" if wait else "")
        page = page.replace("{{refresh}}", f'<meta http-equiv="refresh" content="{wait}">' if wait else "")
        body = page.encode()
        self.private_response = True
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if wait:
            self.send_header("Retry-After", str(wait))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def handle_read(self):
        path = clean_path(self.path)
        if path is None:
            self.send_error(404)
            return False
        if path == "/login":
            query = parse_qs(urlsplit(self.path).query).get("next", [""])[0]
            # Reaching this page while logged in means the visitor went back, so log out.
            if self.command == "GET":
                self.end_session()
            self.send_login(next_path=safe_next(query))
            return False
        if path == "/":
            path = "/main_page.html"
        if path == "/main_page.html":
            # Leaving for the main page ends the login. no-store makes sure the
            # browser always asks the server, so this can't be skipped by its cache.
            self.private_response = True
            if self.command == "GET":
                self.end_session()
        if is_private(path):
            if not self.logged_in():
                self.redirect("/login?next=" + quote(path, safe=""))
                return False
            self.private_response = True
        elif path.lstrip("/") not in PUBLIC_FILES:
            self.send_error(404)
            return False
        self.path = quote(path)
        return True

    def do_GET(self):
        if self.handle_read():
            super().do_GET()

    def do_HEAD(self):
        if self.handle_read():
            super().do_HEAD()

    def do_POST(self):
        path = clean_path(self.path)
        if path == "/logout":
            self.end_session()
            self.redirect("/")
        elif path == "/login":
            self.handle_login()
        else:
            self.send_error(404)

    def handle_login(self):
        try:
            length = int(self.headers.get("Content-Length", ""))
        except ValueError:
            length = -1
        if not 0 <= length <= 4096:
            self.send_error(400)
            return
        form = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
        password = form.get("password", [""])[0]
        next_path = safe_next(form.get("next", [""])[0])
        ip = self.client_ip()

        if not use_try(ip):
            self.send_login(next_path=next_path)
        elif password and check_password(password):
            self.redirect(next_path, self.cookie_text(login_succeeded(ip)))
        else:
            left = tries_left(ip)
            self.send_login(401, f"Wrong password. {left} {'try' if left == 1 else 'tries'} left.", next_path)


def set_password():
    password = getpass.getpass("New password: ")
    if not password or password != getpass.getpass("Repeat it: "):
        sys.exit("The passwords don't match, so nothing changed.")
    HASH_FILE.write_text(hash_password(password) + "\n")
    os.chmod(HASH_FILE, 0o600)
    print("Password changed. Restart the server to log everyone out.")


def main():
    if not HASH_FILE.is_file():
        sys.exit("No password yet. Run: python3 server.py --set-password")
    server = http.server.ThreadingHTTPServer(("", PORT), Handler)
    print(f"Site running at http://localhost:{PORT} (press Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    if "--set-password" in sys.argv:
        set_password()
    else:
        main()