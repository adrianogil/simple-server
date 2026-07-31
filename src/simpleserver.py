#!/usr/bin/env python

"""Simple HTTP Server With Upload.

This module builds on BaseHTTPServer by implementing the standard GET
and HEAD requests in a fairly straightforward manner.

"""


__version__ = "0.2"
__all__ = ["SimpleHTTPRequestHandler"]
__author__ = "gil"
__home_page__ = "http://adrianogil.github.io"

import ntpath
import os
import posixpath
import urllib
import cgi
from datetime import timezone
from email.utils import parsedate_to_datetime
import html
import shutil
import mimetypes
import re
from io import BytesIO
import atexit
import json
import signal
import time
import secrets
from http import cookies

from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import threading
import sys, zipfile


def sizeof_fmt(num, suffix='B'):
    for unit in ['','Ki','Mi','Gi','Ti','Pi','Ei','Zi']:
        if abs(num) < 1024.0:
            return "%3.1f%s%s" % (num, unit, suffix)
        num /= 1024.0
    return "%.1f%s%s" % (num, 'Yi', suffix)


def resolve_contained_child(root, child_name, parent=None):
    """Resolve a child under root without following a parent or child outside it."""
    if not isinstance(child_name, str):
        raise ValueError("Invalid file or folder name")

    child_name = urllib.parse.unquote(child_name)
    drive = os.path.splitdrive(child_name)[0] or ntpath.splitdrive(child_name)[0]
    separators = {separator for separator in (os.sep, os.altsep, '/', '\\') if separator}
    if (
        not child_name
        or child_name in (os.curdir, os.pardir)
        or drive
        or '\x00' in child_name
        or os.path.isabs(child_name)
        or any(separator in child_name for separator in separators)
    ):
        raise ValueError("Invalid file or folder name")

    root = os.path.realpath(root)
    parent = os.path.realpath(parent if parent is not None else root)
    try:
        parent_is_contained = os.path.commonpath((root, parent)) == root
    except ValueError:
        parent_is_contained = False
    if not parent_is_contained:
        raise ValueError("File or folder must remain within the served directory")

    destination = os.path.join(parent, child_name)
    resolved_destination = os.path.realpath(destination)
    try:
        contained = os.path.commonpath((root, resolved_destination)) == root
    except ValueError:
        contained = False
    if not contained:
        raise ValueError("File or folder must remain within the served directory")

    return destination


def parse_http_date(value):
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def parse_byte_range(value, file_size):
    unit, separator, range_spec = value.partition('=')
    if not separator or unit.strip().lower() != 'bytes' or ',' in range_spec:
        return None

    match = re.fullmatch(r"(\d*)-(\d*)", range_spec.strip())
    if not match or not any(match.groups()) or file_size == 0:
        raise ValueError("Unsatisfiable byte range")

    first, last = match.groups()
    if first:
        start = int(first)
        end = int(last) if last else file_size - 1
        if start >= file_size or end < start:
            raise ValueError("Unsatisfiable byte range")
        return start, min(end, file_size - 1)

    suffix_length = int(last)
    if suffix_length <= 0:
        raise ValueError("Unsatisfiable byte range")
    return max(0, file_size - suffix_length), file_size - 1


class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):

    """Simple HTTP request handler with GET/HEAD/POST commands.

    This serves files from the current directory and any of its
    subdirectories.  The MIME type for files is determined by
    calling the .guess_type() method. And can reveive file uploaded
    by client.

    The GET/HEAD/POST requests are identical except that the HEAD
    request omits the actual contents of the file.

    """

    server_version = "SimpleHTTPWithUpload/" + __version__
    server_password = None
    session_duration_seconds = 1800
    session_cookie_name = "SimpleServerSession"
    session_store = {}
    session_lock = threading.Lock()
    share_store = {}
    share_lock = threading.Lock()
    share_expiry_options = (900, 3600, 86400)
    max_share_links = 1000
    copy_buffer_size = 64 * 1024

    def log_request(self, code='-', size='-'):
        requestline = re.sub(
            r"(/__share__/)[^/?\s]+",
            r"\1<redacted>",
            self.requestline,
        )
        self.log_message('"%s" %s %s', requestline, str(code), str(size))

    def send_json_response(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def send_health_response(self, include_body=True):
        payload = {
            "status": "ok",
            "uptime": max(0.0, time.monotonic() - self.server.started_at),
            "version": __version__,
            "app": "simple-server",
        }
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if include_body:
            self.wfile.write(body)

    def make_file_etag(self, file_stat):
        return '"%x-%x-%x"' % (
            getattr(file_stat, 'st_ino', 0),
            file_stat.st_mtime_ns,
            file_stat.st_size,
        )

    def etag_matches(self, header_value, etag):
        for candidate in header_value.split(','):
            candidate = candidate.strip()
            if candidate == '*':
                return True
            if candidate.startswith('W/'):
                candidate = candidate[2:]
            if candidate == etag:
                return True
        return False

    def is_not_modified(self, etag, modified_at):
        if_none_match = self.headers.get('If-None-Match')
        if if_none_match is not None:
            return self.etag_matches(if_none_match, etag)

        if_modified_since = self.headers.get('If-Modified-Since')
        if if_modified_since is None:
            return False
        cached_at = parse_http_date(if_modified_since)
        return cached_at is not None and int(modified_at) <= int(cached_at)

    def if_range_matches(self, etag, modified_at):
        if_range = self.headers.get('If-Range')
        if if_range is None:
            return True
        if_range = if_range.strip()
        if if_range.startswith('"') or if_range.startswith('W/'):
            return if_range == etag
        cached_at = parse_http_date(if_range)
        return cached_at is not None and int(modified_at) <= int(cached_at)

    def send_file_validator_headers(self, file_stat, etag):
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("ETag", etag)
        self.send_header("Last-Modified", self.date_time_string(file_stat.st_mtime))
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Referrer-Policy", "no-referrer")

    def cleanup_expired_shares(self):
        now = time.time()
        with self.share_lock:
            expired = [
                token for token, entry in self.share_store.items()
                if entry["expires_at"] <= now
            ]
            for token in expired:
                self.share_store.pop(token, None)

    def handle_create_share(self):
        if self.headers.get_content_type() != "application/json":
            self.send_json_response(415, {"status": "error", "message": "Share requests must use JSON."})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
        except ValueError:
            self.send_json_response(400, {"status": "error", "message": "Invalid request length."})
            return
        if length <= 0 or length > 4096:
            self.send_json_response(400, {"status": "error", "message": "Invalid share request."})
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json_response(400, {"status": "error", "message": "Invalid JSON request."})
            return

        scope = payload.get("path")
        expires_in = payload.get("expires_in")
        parsed_scope = urllib.parse.urlsplit(scope) if isinstance(scope, str) else None
        if (
            parsed_scope is None
            or parsed_scope.scheme
            or parsed_scope.netloc
            or not parsed_scope.path.startswith('/')
            or type(expires_in) is not int
            or expires_in not in self.share_expiry_options
        ):
            self.send_json_response(400, {"status": "error", "message": "Invalid share scope or expiry."})
            return

        served_root = os.path.realpath(os.getcwd())
        target = os.path.realpath(self.translate_path(parsed_scope.path))
        try:
            contained = os.path.commonpath((served_root, target)) == served_root
        except ValueError:
            contained = False
        if not contained or not os.path.exists(target):
            self.send_json_response(404, {"status": "error", "message": "Share target not found."})
            return

        token = secrets.token_urlsafe(24)
        expires_at = time.time() + expires_in
        self.cleanup_expired_shares()
        with self.share_lock:
            if len(self.share_store) >= self.max_share_links:
                oldest = min(
                    self.share_store,
                    key=lambda item: self.share_store[item]["expires_at"],
                )
                self.share_store.pop(oldest, None)
            self.share_store[token] = {
                "path": target,
                "served_root": served_root,
                "expires_at": expires_at,
            }

        share_url = "/__share__/%s" % token
        if os.path.isdir(target):
            share_url += "/"
        self.send_json_response(201, {
            "status": "ok",
            "url": share_url,
            "expires_at": expires_at,
            "expires_in": expires_in,
        })

    def get_share_entry(self, token):
        now = time.time()
        with self.share_lock:
            entry = self.share_store.get(token)
            if entry is None:
                return None, False
            if entry["expires_at"] <= now:
                self.share_store.pop(token, None)
                return None, True
            return dict(entry), False

    def resolve_shared_target(self, entry, suffix):
        shared_root = os.path.realpath(entry["path"])
        served_root = entry["served_root"]
        try:
            if os.path.commonpath((served_root, shared_root)) != served_root:
                raise ValueError("Share target escaped the served directory")
        except ValueError:
            raise ValueError("Share target escaped the served directory")

        if not os.path.isdir(shared_root):
            if suffix.strip('/'):
                raise ValueError("File shares do not have child paths")
            return shared_root

        target = shared_root
        for part in suffix.split('/'):
            if part:
                target = resolve_contained_child(shared_root, part, target)
        return target

    def send_shared_head(self):
        request_path = urllib.parse.urlsplit(self.path).path
        remainder = request_path[len("/__share__/"):]
        token, separator, suffix = remainder.partition('/')
        entry, expired = self.get_share_entry(token)
        if entry is None:
            self.send_error(410 if expired else 404, "Share link expired" if expired else "Share link not found")
            return None
        try:
            target = self.resolve_shared_target(entry, suffix if separator else "")
        except ValueError:
            self.send_error(404, "Shared path not found")
            return None
        if not os.path.exists(target):
            self.send_error(404, "Shared path not found")
            return None

        if os.path.isdir(target):
            if not request_path.endswith('/'):
                self.send_response(301)
                self.send_header("Location", request_path + "/")
                self.send_header("Referrer-Policy", "no-referrer")
                self.end_headers()
                return None
            for index_name in "index.html", "index.htm":
                index_path = os.path.join(target, index_name)
                if os.path.exists(index_path):
                    return self.send_file_head(index_path)
            listing_root = "/__share__/%s/" % token
            display_path = "/" + urllib.parse.unquote(suffix)
            return self.list_directory(
                target,
                read_only=True,
                listing_root=listing_root,
                display_path=display_path,
            )
        return self.send_file_head(target)

    def handle_shared_request(self, include_body):
        f = self.send_shared_head()
        if f:
            if include_body:
                self.copyfile(f, self.wfile)
            f.close()

    def cleanup_expired_sessions(self):
        now = time.time()
        with self.session_lock:
            expired = [token for token, expires_at in self.session_store.items() if expires_at <= now]
            for token in expired:
                self.session_store.pop(token, None)

    def get_session_token(self):
        raw_cookie = self.headers.get("Cookie")
        if not raw_cookie:
            return None
        parsed = cookies.SimpleCookie()
        parsed.load(raw_cookie)
        if self.session_cookie_name not in parsed:
            return None
        return parsed[self.session_cookie_name].value

    def is_authenticated(self):
        if not self.server_password:
            return True
        self.cleanup_expired_sessions()
        token = self.get_session_token()
        if not token:
            return False
        with self.session_lock:
            expires_at = self.session_store.get(token)
        if not expires_at or expires_at <= time.time():
            return False
        return True

    def render_login_page(self, message="", next_path="/"):
        f = BytesIO()

        def customwrite(htmlstring):
            f.write(htmlstring.encode('utf-8'))

        customwrite("<!DOCTYPE html>\n")
        customwrite("<html lang=\"en\">\n")
        customwrite("<head>\n")
        customwrite("<meta charset=\"utf-8\">\n")
        customwrite("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n")
        customwrite("<script>\n")
        customwrite("(function(){\n")
        customwrite("var stored=localStorage.getItem('simple-server-theme');\n")
        customwrite("var theme=stored||'dark';\n")
        customwrite("document.documentElement.setAttribute('data-theme', theme);\n")
        customwrite("})();\n")
        customwrite("</script>\n")
        customwrite("<title>Server Login</title>\n")
        customwrite("<style>\n")
        customwrite(":root{color-scheme:dark;--bg:#0b1120;--text:#e2e8f0;--muted:#94a3b8;"
                    "--card:#0f172a;--border:#1e293b;--primary:#3b82f6;--shadow:0 10px 30px rgba(2,6,23,.6);}\n")
        customwrite(":root[data-theme='light']{color-scheme:light;--bg:#f5f7fb;--text:#1f2937;--muted:#64748b;"
                    "--card:#fff;--border:#e2e8f0;--primary:#2563eb;--shadow:0 10px 30px rgba(15,23,42,.08);}\n")
        customwrite("body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif;"
                    "background:var(--bg);color:var(--text);margin:0;padding:32px;}\n")
        customwrite(".card{max-width:420px;margin:0 auto;background:var(--card);border-radius:14px;"
                    "box-shadow:var(--shadow);padding:28px;border:1px solid var(--border);}\n")
        customwrite(".title{font-size:22px;margin:0 0 8px;}\n")
        customwrite(".subtitle{color:var(--muted);font-size:14px;margin:0 0 18px;}\n")
        customwrite(".message{color:#dc2626;font-size:14px;margin-bottom:12px;}\n")
        customwrite("label{display:block;font-size:14px;margin-bottom:6px;}\n")
        customwrite("input[type='password']{width:100%;padding:10px 12px;border-radius:8px;"
                    "border:1px solid var(--border);font-size:14px;background:transparent;color:var(--text);}\n")
        customwrite(".btn{margin-top:14px;background:var(--primary);color:#fff;border:none;border-radius:8px;"
                    "padding:10px 14px;font-size:14px;cursor:pointer;width:100%;}\n")
        customwrite("</style>\n")
        customwrite("</head>\n")
        customwrite("<body>\n")
        customwrite("<div class=\"card\">\n")
        customwrite("<h2 class=\"title\">Password required</h2>\n")
        customwrite("<p class=\"subtitle\">Enter the server password to continue.</p>\n")
        if message:
            customwrite("<div class=\"message\">%s</div>\n" % html.escape(message))
        customwrite("<form method=\"post\" action=\"/__login__\">\n")
        customwrite("<input type=\"hidden\" name=\"next\" value=\"%s\">\n" % html.escape(next_path))
        customwrite("<label for=\"password\">Password</label>\n")
        customwrite("<input id=\"password\" name=\"password\" type=\"password\" autofocus required>\n")
        customwrite("<button class=\"btn\" type=\"submit\">Sign in</button>\n")
        customwrite("</form>\n")
        customwrite("</div>\n")
        customwrite("<script>\n")
        customwrite("(function(){\n")
        customwrite("var button=document.getElementById('theme-toggle');\n")
        customwrite("var root=document.documentElement;\n")
        customwrite("function applyLabel(){\n")
        customwrite("if(!button){return;}\n")
        customwrite("var theme=root.getAttribute('data-theme')||'dark';\n")
        customwrite("button.textContent=theme==='dark'?'Light mode':'Dark mode';\n")
        customwrite("}\n")
        customwrite("if(button){\n")
        customwrite("button.addEventListener('click',function(){\n")
        customwrite("var next=(root.getAttribute('data-theme')==='dark')?'light':'dark';\n")
        customwrite("root.setAttribute('data-theme',next);\n")
        customwrite("localStorage.setItem('simple-server-theme',next);\n")
        customwrite("applyLabel();\n")
        customwrite("});\n")
        customwrite("}\n")
        customwrite("applyLabel();\n")
        customwrite("})();\n")
        customwrite("</script>\n")
        customwrite("</body>\n</html>\n")
        length = f.tell()
        f.seek(0)
        self.send_response(401)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        return f

    def handle_login(self):
        length = int(self.headers.get("Content-Length", 0))
        raw_body = self.rfile.read(length).decode("utf-8")
        form = urllib.parse.parse_qs(raw_body)
        password = form.get("password", [""])[0]
        next_path = form.get("next", ["/"])[0] or "/"
        if password != self.server_password:
            f = self.render_login_page("Incorrect password.", next_path)
            if f:
                self.copyfile(f, self.wfile)
                f.close()
            return
        token = secrets.token_urlsafe(32)
        expires_at = time.time() + self.session_duration_seconds
        with self.session_lock:
            self.session_store[token] = expires_at
        self.send_response(303)
        self.send_header("Location", next_path)
        cookie_value = (
            f"{self.session_cookie_name}={token}; HttpOnly; Path=/; Max-Age={self.session_duration_seconds}; SameSite=Lax"
        )
        self.send_header("Set-Cookie", cookie_value)
        self.end_headers()

    def handle_logout(self):
        token = self.get_session_token()
        if token:
            with self.session_lock:
                self.session_store.pop(token, None)
        self.send_response(303)
        self.send_header("Location", "/__login__")
        cookie_value = f"{self.session_cookie_name}=; HttpOnly; Path=/; Max-Age=0; SameSite=Lax"
        self.send_header("Set-Cookie", cookie_value)
        self.end_headers()

    def do_GET(self):
        """Serve a GET request."""
        request_path = urllib.parse.urlsplit(self.path).path
        if request_path == "/healthz":
            self.send_health_response()
            return
        if request_path.startswith("/__share__/"):
            self.handle_shared_request(include_body=True)
            return
        if self.path.startswith("/__logout__"):
            self.handle_logout()
            return
        if self.path.startswith("/__login__"):
            f = self.render_login_page(next_path="/")
            if f:
                self.copyfile(f, self.wfile)
                f.close()
            return
        if self.server_password and not self.is_authenticated():
            f = self.render_login_page(next_path=self.path)
            if f:
                self.copyfile(f, self.wfile)
                f.close()
            return
        f = self.send_head()
        if f:
            self.copyfile(f, self.wfile)
            f.close()

    def do_HEAD(self):
        """Serve a HEAD request."""
        request_path = urllib.parse.urlsplit(self.path).path
        if request_path == "/healthz":
            self.send_health_response(include_body=False)
            return
        if request_path.startswith("/__share__/"):
            self.handle_shared_request(include_body=False)
            return
        if self.server_password and not self.is_authenticated():
            self.send_response(401)
            self.end_headers()
            return
        f = self.send_head()
        if f:
            f.close()

    def do_POST(self):
        """Serve a POST request."""
        request_path = urllib.parse.urlsplit(self.path).path
        if request_path == "/__login__":
            if not self.server_password:
                self.send_error(404, "Login not configured")
                return
            self.handle_login()
            return
        if request_path.startswith("/__share__/"):
            self.send_error(405, "Shared links are read-only")
            return
        if request_path == "/__share__" and self.server_password and not self.is_authenticated():
            self.send_json_response(401, {"status": "error", "message": "Authentication required."})
            return
        if self.server_password and not self.is_authenticated():
            f = self.render_login_page(next_path=self.path)
            if f:
                self.copyfile(f, self.wfile)
                f.close()
            return
        if request_path == "/__share__":
            self.handle_create_share()
            return
        r, info = self.deal_post_data()
        print(r, info, "by: ", self.client_address)
        if "application/json" in self.headers.get("Accept", ""):
            body = json.dumps({
                "status": "ok" if r else "error",
                "message": info,
            }).encode("utf-8")
            self.send_response(200 if r else 400)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        f = BytesIO()

        def customwrite(htmlstring):
            f.write(htmlstring.encode('utf-8'))

        customwrite("<!DOCTYPE html>\n")
        customwrite("<html lang=\"en\">\n")
        customwrite("<head>\n")
        customwrite("<meta charset=\"utf-8\">\n")
        customwrite("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n")
        customwrite("<script>\n")
        customwrite("(function(){\n")
        customwrite("var stored=localStorage.getItem('simple-server-theme');\n")
        customwrite("var theme=stored||'dark';\n")
        customwrite("document.documentElement.setAttribute('data-theme', theme);\n")
        customwrite("})();\n")
        customwrite("</script>\n")
        customwrite("<title>Upload Result</title>\n")
        customwrite("<style>\n")
        customwrite(":root{color-scheme:dark;--bg:#0b1120;--text:#e2e8f0;--muted:#94a3b8;"
                    "--card:#0f172a;--border:#1e293b;--primary:#3b82f6;--shadow:0 10px 30px rgba(2,6,23,.6);}\n")
        customwrite(":root[data-theme='light']{color-scheme:light;--bg:#f5f7fb;--text:#1f2937;--muted:#64748b;"
                    "--card:#fff;--border:#e2e8f0;--primary:#2563eb;--shadow:0 10px 30px rgba(15,23,42,.08);}\n")
        customwrite("body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif;"
                    "background:var(--bg);color:var(--text);margin:0;padding:32px;}\n")
        customwrite(".card{max-width:720px;margin:0 auto;background:var(--card);border-radius:14px;"
                    "box-shadow:var(--shadow);padding:28px;border:1px solid var(--border);}\n")
        customwrite(".title{font-size:22px;margin:0 0 8px;}\n")
        customwrite(".status{font-weight:600;margin:12px 0;}\n")
        customwrite(".status.success{color:#059669;}\n")
        customwrite(".status.fail{color:#dc2626;}\n")
        customwrite(".actions a{display:inline-block;margin-top:12px;padding:8px 14px;"
                    "background:var(--primary);color:#fff;border-radius:8px;text-decoration:none;}\n")
        customwrite(".footer{margin-top:18px;font-size:12px;color:var(--muted);}\n")
        customwrite("</style>\n")
        customwrite("</head>\n")
        customwrite("<body>\n")
        customwrite("<div class=\"card\">\n")
        customwrite("<h2 class=\"title\">Upload Result</h2>\n")
        if r:
            customwrite("<div class=\"status success\">Success</div>\n")
        else:
            customwrite("<div class=\"status fail\">Failed</div>\n")
        customwrite("<p>%s</p>\n" % info)
        customwrite("<div class=\"actions\"><a href=\"%s\">Back to listing</a></div>\n" % self.headers['referer'])
        customwrite("<div class=\"footer\">Powered By: Gil, check new version at "
                    "<a href=\"https://github.com/adrianogil/simple-server\">here</a>.</div>\n")
        customwrite("</div>\n")
        customwrite("<script>\n")
        customwrite("(function(){\n")
        customwrite("var button=document.getElementById('theme-toggle');\n")
        customwrite("var root=document.documentElement;\n")
        customwrite("function applyLabel(){\n")
        customwrite("if(!button){return;}\n")
        customwrite("var theme=root.getAttribute('data-theme')||'dark';\n")
        customwrite("button.textContent=theme==='dark'?'Light mode':'Dark mode';\n")
        customwrite("}\n")
        customwrite("if(button){\n")
        customwrite("button.addEventListener('click',function(){\n")
        customwrite("var next=(root.getAttribute('data-theme')==='dark')?'light':'dark';\n")
        customwrite("root.setAttribute('data-theme',next);\n")
        customwrite("localStorage.setItem('simple-server-theme',next);\n")
        customwrite("applyLabel();\n")
        customwrite("});\n")
        customwrite("}\n")
        customwrite("applyLabel();\n")
        customwrite("})();\n")
        customwrite("</script>\n")
        customwrite("</body>\n</html>\n")
        length = f.tell()
        f.seek(0)
        self.send_response(200 if r else 400)
        self.send_header("Content-type", "text/html")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        if f:
            self.copyfile(f, self.wfile)
            f.close()

    def create_directory(self, path, folder_name, last_page):
        print("create_directory %s %s" % (path, folder_name))

        result = True

        try:
            new_folder = resolve_contained_child(os.getcwd(), folder_name, path)
        except ValueError as error:
            self.send_error(400, str(error))
            return None
        folder_name = os.path.basename(new_folder)

        if os.path.exists(new_folder):
            result = False
        else:
            os.mkdir(new_folder)

        """Serve a POST request."""
        f = BytesIO()

        def customwrite(htmlstring):
            f.write(htmlstring.encode('utf-8'))

        customwrite("<!DOCTYPE html>\n")
        customwrite("<html lang=\"en\">\n")
        customwrite("<head>\n")
        customwrite("<meta charset=\"utf-8\">\n")
        customwrite("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n")
        customwrite("<script>\n")
        customwrite("(function(){\n")
        customwrite("var stored=localStorage.getItem('simple-server-theme');\n")
        customwrite("var theme=stored||'dark';\n")
        customwrite("document.documentElement.setAttribute('data-theme', theme);\n")
        customwrite("})();\n")
        customwrite("</script>\n")
        customwrite("<title>Folder Created</title>\n")
        customwrite("<style>\n")
        customwrite(":root{color-scheme:dark;--bg:#0b1120;--text:#e2e8f0;--muted:#94a3b8;"
                    "--card:#0f172a;--border:#1e293b;--primary:#3b82f6;--shadow:0 10px 30px rgba(2,6,23,.6);}\n")
        customwrite(":root[data-theme='light']{color-scheme:light;--bg:#f5f7fb;--text:#1f2937;--muted:#64748b;"
                    "--card:#fff;--border:#e2e8f0;--primary:#2563eb;--shadow:0 10px 30px rgba(15,23,42,.08);}\n")
        customwrite("body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif;"
                    "background:var(--bg);color:var(--text);margin:0;padding:32px;}\n")
        customwrite(".card{max-width:720px;margin:0 auto;background:var(--card);border-radius:14px;"
                    "box-shadow:var(--shadow);padding:28px;border:1px solid var(--border);}\n")
        customwrite(".title{font-size:22px;margin:0 0 8px;}\n")
        customwrite(".status{font-weight:600;margin:12px 0;}\n")
        customwrite(".status.success{color:#059669;}\n")
        customwrite(".status.fail{color:#dc2626;}\n")
        customwrite(".actions a{display:inline-block;margin-top:12px;padding:8px 14px;"
                    "background:var(--primary);color:#fff;border-radius:8px;text-decoration:none;}\n")
        customwrite(".footer{margin-top:18px;font-size:12px;color:var(--muted);}\n")
        customwrite("</style>\n")
        customwrite("</head>\n")
        customwrite("<body>\n")
        customwrite("<div class=\"card\">\n")
        customwrite("<h2 class=\"title\">Folder \"%s\"</h2>\n" % html.escape(folder_name))
        if result:
            customwrite("<div class=\"status success\">Created successfully.</div>\n")
        else:
            customwrite("<div class=\"status fail\">Folder already exists.</div>\n")
        customwrite("<div class=\"actions\"><a href=\"%s\">Back to listing</a></div>\n" % last_page)
        customwrite("<div class=\"footer\">Powered By: Gil, check new version at "
                    "<a href=\"https://github.com/adrianogil/simple-server\">here</a>.</div>\n")
        customwrite("</div>\n")
        customwrite("<script>\n")
        customwrite("(function(){\n")
        customwrite("var button=document.getElementById('theme-toggle');\n")
        customwrite("var root=document.documentElement;\n")
        customwrite("function applyLabel(){\n")
        customwrite("if(!button){return;}\n")
        customwrite("var theme=root.getAttribute('data-theme')||'dark';\n")
        customwrite("button.textContent=theme==='dark'?'Light mode':'Dark mode';\n")
        customwrite("}\n")
        customwrite("if(button){\n")
        customwrite("button.addEventListener('click',function(){\n")
        customwrite("var next=(root.getAttribute('data-theme')==='dark')?'light':'dark';\n")
        customwrite("root.setAttribute('data-theme',next);\n")
        customwrite("localStorage.setItem('simple-server-theme',next);\n")
        customwrite("applyLabel();\n")
        customwrite("});\n")
        customwrite("}\n")
        customwrite("applyLabel();\n")
        customwrite("})();\n")
        customwrite("</script>\n")
        customwrite("</body>\n</html>\n")
        length = f.tell()
        f.seek(0)
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        if f:
            self.copyfile(f, self.wfile)
            f.close()

    def delete_file(self, path, file_name, last_page):
        print("delete_file %s %s" % (path, file_name))

        result = True

        try:
            file_path = resolve_contained_child(os.getcwd(), file_name, path)
        except ValueError as error:
            self.send_error(400, str(error))
            return None
        file_name = os.path.basename(file_path)

        if os.path.exists(file_path):
            os.remove(file_path)

        """Serve a POST request."""
        f = BytesIO()

        def customwrite(htmlstring):
            f.write(htmlstring.encode('utf-8'))

        customwrite("<!DOCTYPE html>\n")
        customwrite("<html lang=\"en\">\n")
        customwrite("<head>\n")
        customwrite("<meta charset=\"utf-8\">\n")
        customwrite("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n")
        customwrite("<script>\n")
        customwrite("(function(){\n")
        customwrite("var stored=localStorage.getItem('simple-server-theme');\n")
        customwrite("var theme=stored||'dark';\n")
        customwrite("document.documentElement.setAttribute('data-theme', theme);\n")
        customwrite("})();\n")
        customwrite("</script>\n")
        customwrite("<title>File Removed</title>\n")
        customwrite("<style>\n")
        customwrite(":root{color-scheme:dark;--bg:#0b1120;--text:#e2e8f0;--muted:#94a3b8;"
                    "--card:#0f172a;--border:#1e293b;--primary:#3b82f6;--shadow:0 10px 30px rgba(2,6,23,.6);}\n")
        customwrite(":root[data-theme='light']{color-scheme:light;--bg:#f5f7fb;--text:#1f2937;--muted:#64748b;"
                    "--card:#fff;--border:#e2e8f0;--primary:#2563eb;--shadow:0 10px 30px rgba(15,23,42,.08);}\n")
        customwrite("body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif;"
                    "background:var(--bg);color:var(--text);margin:0;padding:32px;}\n")
        customwrite(".card{max-width:720px;margin:0 auto;background:var(--card);border-radius:14px;"
                    "box-shadow:var(--shadow);padding:28px;border:1px solid var(--border);}\n")
        customwrite(".title{font-size:22px;margin:0 0 8px;}\n")
        customwrite(".status{font-weight:600;margin:12px 0;}\n")
        customwrite(".status.success{color:#059669;}\n")
        customwrite(".status.fail{color:#dc2626;}\n")
        customwrite(".actions a{display:inline-block;margin-top:12px;padding:8px 14px;"
                    "background:var(--primary);color:#fff;border-radius:8px;text-decoration:none;}\n")
        customwrite(".footer{margin-top:18px;font-size:12px;color:var(--muted);}\n")
        customwrite("</style>\n")
        customwrite("</head>\n")
        customwrite("<body>\n")
        customwrite("<div class=\"card\">\n")
        customwrite("<h2 class=\"title\">Removed \"%s\"</h2>\n" % html.escape(file_name))
        if result:
            customwrite("<div class=\"status success\">File deleted successfully.</div>\n")
        else:
            customwrite("<div class=\"status fail\">Failed to delete file.</div>\n")
        customwrite("<div class=\"actions\"><a href=\"%s\">Back to listing</a></div>\n" % last_page)
        customwrite("<div class=\"footer\">Powered By: Gil, check new version at "
                    "<a href=\"https://github.com/adrianogil/simple-server\">here</a>.</div>\n")
        customwrite("</div>\n")
        customwrite("<script>\n")
        customwrite("(function(){\n")
        customwrite("var button=document.getElementById('theme-toggle');\n")
        customwrite("var root=document.documentElement;\n")
        customwrite("function applyLabel(){\n")
        customwrite("if(!button){return;}\n")
        customwrite("var theme=root.getAttribute('data-theme')||'dark';\n")
        customwrite("button.textContent=theme==='dark'?'Light mode':'Dark mode';\n")
        customwrite("}\n")
        customwrite("if(button){\n")
        customwrite("button.addEventListener('click',function(){\n")
        customwrite("var next=(root.getAttribute('data-theme')==='dark')?'light':'dark';\n")
        customwrite("root.setAttribute('data-theme',next);\n")
        customwrite("localStorage.setItem('simple-server-theme',next);\n")
        customwrite("applyLabel();\n")
        customwrite("});\n")
        customwrite("}\n")
        customwrite("applyLabel();\n")
        customwrite("})();\n")
        customwrite("</script>\n")
        customwrite("</body>\n</html>\n")
        length = f.tell()
        f.seek(0)
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.send_header("Content-Length", str(length))
        self.end_headers()
        if f:
            self.copyfile(f, self.wfile)
            f.close()

    def deal_post_data(self):
        ctype, pdict = cgi.parse_header(self.headers['Content-Type'])
        pdict['boundary'] = bytes(pdict['boundary'], "utf-8")
        pdict['CONTENT-LENGTH'] = int(self.headers['Content-Length'])
        if ctype == 'multipart/form-data':
            form = cgi.FieldStorage( fp=self.rfile, headers=self.headers, environ={'REQUEST_METHOD':'POST', 'CONTENT_TYPE':self.headers['Content-Type'], })
            print (type(form))
            if getattr(form, "bytes_read", pdict['CONTENT-LENGTH']) < pdict['CONTENT-LENGTH']:
                return (False, "Upload cancelled or incomplete.")
            try:
                records = form["file"] if isinstance(form["file"], list) else [form["file"]]
                uploads = [
                    (record, resolve_contained_child(os.getcwd(), record.filename))
                    for record in records
                ]
                for record, destination in uploads:
                    with open(destination, "wb") as uploaded_file:
                        uploaded_file.write(record.file.read())
            except ValueError:
                return (False, "Upload rejected: invalid filename or destination.")
            except IOError:
                return (False, "Can't create file to write, do you have permission to write?")
        return (True, "Files uploaded")

    def send_head(self):
        """Common code for GET and HEAD commands.

        This sends the response code and MIME headers.

        Return value is either a file object (which has to be copied
        to the outputfile by the caller unless the command was HEAD,
        and must be closed by the caller under all circumstances), or
        None, in which case the caller has nothing further to do.

        """
        self._range_remaining = None
        path = self.translate_path(self.path)
        print("send_head - path: " + str(self.path))
        f = None
        if '?deletefile=' in self.path:
            index = self.path.index('?deletefile=')
            file_to_be_deleted = self.path[index + 12:]
            print("Let's delete file: " + file_to_be_deleted)
            return self.delete_file(path, file_to_be_deleted, self.path[:index])
        elif '?createfolder=' in self.path:
            index = self.path.index('?createfolder=')
            folder_name = self.path[index + 14:]
            return self.create_directory(path, folder_name, self.path[:index])
        elif self.path.endswith('?download'):
            tmp_file = "tmp.zip"
            self.path = self.path.replace("?download","")

            # Improve zipped path
            zip = zipfile.ZipFile(tmp_file, 'w')
            for root, dirs, files in os.walk(path):
                for file in files:
                    if os.path.join(root, file) != os.path.join(root, tmp_file):
                        zip.write(os.path.join(root, file))
            zip.close()
            path = self.translate_path(tmp_file)
        elif os.path.isdir(path):
            if not self.path.endswith('/'):
                # redirect browser - doing basically what apache does
                self.send_response(301)
                self.send_header("Location", self.path + "/")
                self.end_headers()
                return None
            for index in "index.html", "index.htm":
                index = os.path.join(path, index)
                if os.path.exists(index):
                    path = index
                    break
            else:
                return self.list_directory(path)
        return self.send_file_head(path)

    def send_file_head(self, path):
        self._range_remaining = None
        ctype = self.guess_type(path)
        try:
            # Always read in binary mode. Opening files in text mode may cause
            # newline translations, making the actual size of the content
            # transmitted *less* than the content-length!
            f = open(path, 'rb')
        except IOError:
            self.send_error(404, "File not found")
            return None
        fs = os.fstat(f.fileno())
        etag = self.make_file_etag(fs)
        if self.is_not_modified(etag, fs.st_mtime):
            self.send_response(304)
            self.send_file_validator_headers(fs, etag)
            self.end_headers()
            f.close()
            return None

        byte_range = None
        range_header = self.headers.get("Range")
        if range_header and self.if_range_matches(etag, fs.st_mtime):
            try:
                byte_range = parse_byte_range(range_header, fs.st_size)
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", "bytes */%s" % fs.st_size)
                self.send_header("Content-Length", "0")
                self.send_file_validator_headers(fs, etag)
                self.end_headers()
                f.close()
                return None

        if byte_range is None:
            self.send_response(200)
            content_length = fs.st_size
        else:
            start, end = byte_range
            content_length = end - start + 1
            self._range_remaining = content_length
            f.seek(start)
            self.send_response(206)
            self.send_header(
                "Content-Range",
                "bytes %s-%s/%s" % (start, end, fs.st_size),
            )
        self.send_header("Content-type", ctype)
        self.send_header("Content-Length", str(content_length))
        self.send_file_validator_headers(fs, etag)
        self.end_headers()
        return f

    def list_directory(self, path, read_only=False, listing_root="/", display_path=None):
        """Helper to produce a directory listing (absent index.html).

        Return value is either a file object, or None (indicating an
        error).  In either case, the headers are sent, making the
        interface the same as for send_head().

        """
        try:
            list = os.listdir(path)
        except os.error:
            self.send_error(404, "No permission to list directory")
            return None
        list.sort(key=lambda a: a.lower())
        f = BytesIO()
        displaypath = html.escape(
            display_path if display_path is not None else urllib.parse.unquote(self.path)
        )

        js_action_create_folder = "window.open('%s' + document.getElementById('folderName').value,'_self')" % (
                self.path.strip() + "?createfolder=",
            )

        def customwrite(htmlstring):
            f.write(htmlstring.encode('utf-8'))

        customwrite("<!DOCTYPE html>\n")
        customwrite("<html lang=\"en\">\n")
        customwrite("<head>\n")
        customwrite("<meta charset=\"utf-8\">\n")
        customwrite("<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n")
        customwrite("<script>\n")
        customwrite("(function(){\n")
        customwrite("var stored=localStorage.getItem('simple-server-theme');\n")
        customwrite("var theme=stored||'dark';\n")
        customwrite("document.documentElement.setAttribute('data-theme', theme);\n")
        customwrite("})();\n")
        customwrite("</script>\n")
        customwrite("<title>Directory listing for %s</title>\n" % displaypath)
        customwrite("<style>\n")
        customwrite(":root{color-scheme:dark;--bg:#0b1120;--text:#e2e8f0;--muted:#94a3b8;"
                    "--card:#0f172a;--border:#1e293b;--surface:#111827;--primary:#3b82f6;"
                    "--secondary:#334155;--link:#60a5fa;--danger:#f87171;"
                    "--shadow:0 12px 30px rgba(2,6,23,.6);}\n")
        customwrite(":root[data-theme='light']{color-scheme:light;--bg:#f5f7fb;--text:#0f172a;--muted:#64748b;"
                    "--card:#fff;--border:#e2e8f0;--surface:#f8fafc;--primary:#2563eb;"
                    "--secondary:#0f172a;--link:#1d4ed8;--danger:#ef4444;"
                    "--shadow:0 12px 30px rgba(15,23,42,.08);}\n")
        customwrite("body{font-family:system-ui,-apple-system,Segoe UI,Roboto,Ubuntu,Arial,sans-serif;"
                    "background:var(--bg);color:var(--text);margin:0;padding:32px;}\n")
        customwrite(".container{max-width:960px;margin:0 auto;}\n")
        customwrite(".card{background:var(--card);border-radius:16px;padding:24px;"
                    "box-shadow:var(--shadow);border:1px solid var(--border);}\n")
        customwrite(".header{display:flex;flex-direction:column;gap:6px;margin-bottom:18px;}\n")
        customwrite(".header h2{margin:0;font-size:24px;}\n")
        customwrite(".header .path{color:var(--muted);font-size:14px;}\n")
        customwrite(".actions{display:flex;flex-wrap:wrap;gap:12px;margin-bottom:18px;}\n")
        customwrite(".actions form{display:flex;align-items:center;gap:8px;"
                    "background:var(--surface);padding:10px 12px;border-radius:12px;"
                    "border:1px solid var(--border);}\n")
        customwrite("input[type='text'],input[type='file'],select{font-size:14px;}\n")
        customwrite(".btn{background:var(--primary);color:#fff;border:none;border-radius:8px;"
                    "padding:8px 12px;font-size:14px;cursor:pointer;}\n")
        customwrite(".btn.secondary{background:var(--secondary);}\n")
        customwrite(".upload-panel{margin-bottom:18px;}\n")
        customwrite(".upload-form{display:block;}\n")
        customwrite(".upload-dropzone{display:flex;align-items:center;justify-content:center;"
                    "flex-direction:column;gap:5px;min-height:110px;padding:18px;border:2px dashed var(--border);"
                    "border-radius:12px;background:var(--surface);cursor:pointer;text-align:center;transition:.15s ease;}\n")
        customwrite(".upload-dropzone:hover,.upload-dropzone:focus,.upload-dropzone.dragover{"
                    "border-color:var(--primary);box-shadow:0 0 0 3px rgba(59,130,246,.18);outline:none;}\n")
        customwrite(".upload-dropzone input{position:absolute;width:1px;height:1px;overflow:hidden;"
                    "clip:rect(0 0 0 0);white-space:nowrap;}\n")
        customwrite(".upload-hint{color:var(--muted);font-size:13px;}\n")
        customwrite(".upload-controls{display:flex;gap:10px;margin-top:10px;}\n")
        customwrite(".upload-queue{display:flex;flex-direction:column;gap:10px;list-style:none;margin:12px 0 0;padding:0;}\n")
        customwrite(".upload-item{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:7px 12px;"
                    "padding:12px;border:1px solid var(--border);border-radius:10px;background:var(--surface);}\n")
        customwrite(".upload-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-weight:600;}\n")
        customwrite(".upload-progress{grid-column:1;width:100%;height:9px;accent-color:var(--primary);}\n")
        customwrite(".upload-state{grid-column:1;color:var(--muted);font-size:12px;}\n")
        customwrite(".upload-item.success .upload-state{color:#10b981;}\n")
        customwrite(".upload-item.failed .upload-state,.upload-item.cancelled .upload-state{color:var(--danger);}\n")
        customwrite(".cancel-upload{grid-column:2;grid-row:1/4;align-self:center;background:transparent;"
                    "color:var(--danger);border:1px solid var(--danger);border-radius:8px;padding:6px 9px;cursor:pointer;}\n")
        customwrite(".cancel-upload:disabled{cursor:default;opacity:.55;}\n")
        customwrite(".share-settings{display:flex;align-items:center;gap:8px;background:var(--surface);"
                    "padding:10px 12px;border:1px solid var(--border);border-radius:12px;}\n")
        customwrite(".share-settings select,.share-link{background:var(--card);color:var(--text);"
                    "border:1px solid var(--border);border-radius:7px;padding:7px;}\n")
        customwrite(".share-button{background:transparent;color:var(--link);border:1px solid var(--link);"
                    "border-radius:8px;padding:4px 8px;font-size:12px;cursor:pointer;}\n")
        customwrite(".share-button:disabled{cursor:wait;opacity:.6;}\n")
        customwrite(".share-result{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:8px;"
                    "margin-bottom:18px;padding:12px;background:var(--surface);border:1px solid var(--border);"
                    "border-radius:12px;}\n")
        customwrite(".share-result[hidden]{display:none;}\n")
        customwrite(".share-link{min-width:0;}\n")
        customwrite(".share-status{grid-column:1/-1;color:var(--muted);font-size:12px;}\n")
        customwrite(".list{list-style:none;margin:0;padding:0;}\n")
        customwrite(".list li{display:flex;align-items:center;justify-content:space-between;"
                    "padding:10px 12px;border-bottom:1px solid var(--border);}\n")
        customwrite(".list li:last-child{border-bottom:none;}\n")
        customwrite(".file-link{color:var(--link);text-decoration:none;font-weight:500;}\n")
        customwrite(".file-meta{display:flex;align-items:center;gap:12px;color:var(--muted);font-size:12px;}\n")
        customwrite(".delete{background:var(--danger);color:#fff;border-radius:8px;text-decoration:none;"
                    "padding:4px 8px;font-size:12px;}\n")
        customwrite(".footer{margin-top:20px;font-size:12px;color:var(--muted);}\n")
        customwrite("</style>\n")
        customwrite("</head>\n")
        customwrite("<body>\n")
        customwrite("<div class=\"container\">\n")
        customwrite("<div class=\"card\">\n")
        customwrite("<div class=\"header\">\n")
        customwrite("<h2>%s</h2>\n" % ("Shared directory" if read_only else "Directory listing"))
        customwrite("<div class=\"path\">%s</div>\n" % displaypath)
        customwrite("</div>\n")
        if not read_only:
            customwrite("<div class=\"upload-panel\">\n")
            customwrite("<form id=\"upload-form\" class=\"upload-form\" ENCTYPE=\"multipart/form-data\" method=\"post\">\n")
            customwrite("<label id=\"upload-dropzone\" class=\"upload-dropzone\" for=\"upload-input\" tabindex=\"0\">\n")
            customwrite("<strong>Drop files here or choose files</strong>\n")
            customwrite("<span class=\"upload-hint\">Files upload individually so each transfer can be tracked or cancelled.</span>\n")
            customwrite("<input id=\"upload-input\" name=\"file\" type=\"file\" multiple>\n")
            customwrite("</label>\n")
            customwrite("<div class=\"upload-controls\">\n")
            customwrite("<button id=\"upload-submit\" class=\"btn\" type=\"submit\">Upload selected</button>\n")
            customwrite("<button id=\"refresh-list\" class=\"btn secondary\" type=\"button\" hidden>Refresh listing</button>\n")
            customwrite("</div>\n")
            customwrite("</form>\n")
            customwrite("<ul id=\"upload-queue\" class=\"upload-queue\" aria-live=\"polite\"></ul>\n")
            customwrite("</div>\n")
        customwrite("<div class=\"actions\">\n")
        if not read_only:
            customwrite("<form ENCTYPE=\"multipart/form-data\">")
            customwrite("<label for=\"folderName\"><small>Create folder:</small></label>")
            customwrite("<input type=\"text\" id=\"folderName\" placeholder=\"New folder\">")
            customwrite("<button class=\"btn secondary\" type=\"button\" onclick=\"" + js_action_create_folder + "\">Create</button>")
            customwrite("</form>\n")
            customwrite("<a class=\"btn\" href='%s'>Download zip</a>\n" % (self.path + "?download",))
            customwrite("<div class=\"share-settings\">")
            customwrite("<label for=\"share-expiry\"><small>Share expires:</small></label>")
            customwrite("<select id=\"share-expiry\">")
            customwrite("<option value=\"900\">15 minutes</option>")
            customwrite("<option value=\"3600\" selected>1 hour</option>")
            customwrite("<option value=\"86400\">24 hours</option>")
            customwrite("</select></div>\n")
        customwrite("<button class=\"btn secondary\" type=\"button\" id=\"theme-toggle\">Light mode</button>\n")
        if self.server_password and not read_only:
            customwrite("<a class=\"btn secondary\" href='/__logout__'>Logout</a>\n")
        customwrite("</div>\n")
        if not read_only:
            customwrite("<div id=\"share-result\" class=\"share-result\" hidden>\n")
            customwrite("<input id=\"share-link\" class=\"share-link\" type=\"text\" readonly aria-label=\"Generated share link\">\n")
            customwrite("<button id=\"copy-share\" class=\"btn secondary\" type=\"button\">Copy</button>\n")
            customwrite("<span id=\"share-status\" class=\"share-status\" aria-live=\"polite\"></span>\n")
            customwrite("</div>\n")
        customwrite("<ul class=\"list\">\n")
        if self.path != listing_root:
            customwrite('<li><a href="%s">..</a>\n' % (urllib.parse.quote(self.path + ".."),))
        for name in list:
            fullname = os.path.join(path, name)
            displayname = linkname = name
            # Append / for directories or @ for symbolic links

            size_display = ""

            if os.path.isdir(fullname):
                displayname = name + "/"
                linkname = name + "/"
            else:
                size_value = os.path.getsize(fullname)
                size_value = sizeof_fmt(size_value)

                size_display = "<span>(%s)</span>" % (size_value,)

            if os.path.islink(fullname):
                displayname = name + "@"
                # Note: a link to a directory displays with @ and links with /
            customwrite("<li>")
            customwrite("<a class=\"file-link\" href=\"%s\">%s</a>" % (
                urllib.parse.quote(linkname),
                html.escape(displayname),
            ))
            customwrite("<div class=\"file-meta\">%s" % size_display)
            if not read_only:
                scope_path = urllib.parse.quote(
                    urllib.parse.unquote(self.path) + linkname,
                    safe='/',
                )
                customwrite("<button class=\"share-button\" type=\"button\" data-scope=\"%s\">Share</button>" % (
                    html.escape(scope_path, quote=True),
                ))
                customwrite("<a class=\"delete\" href=\"%s\">Delete</a>" % (
                    "?deletefile=" + html.escape(displayname),
                ))
            customwrite("</div></li>\n")
        customwrite("</ul>\n")
        customwrite("<div class=\"footer\">Powered By: Gil, check new version ")
        customwrite("<a href=\"https://github.com/adrianogil/simple-server\">")
        customwrite("here</a>.</div>\n")
        customwrite("</div>\n</div>\n")
        customwrite("<script>\n")
        customwrite("(function(){\n")
        customwrite("var button=document.getElementById('theme-toggle');\n")
        customwrite("var root=document.documentElement;\n")
        customwrite("function applyLabel(){\n")
        customwrite("if(!button){return;}\n")
        customwrite("var theme=root.getAttribute('data-theme')||'dark';\n")
        customwrite("button.textContent=theme==='dark'?'Light mode':'Dark mode';\n")
        customwrite("}\n")
        customwrite("if(button){\n")
        customwrite("button.addEventListener('click',function(){\n")
        customwrite("var next=(root.getAttribute('data-theme')==='dark')?'light':'dark';\n")
        customwrite("root.setAttribute('data-theme',next);\n")
        customwrite("localStorage.setItem('simple-server-theme',next);\n")
        customwrite("applyLabel();\n")
        customwrite("});\n")
        customwrite("}\n")
        customwrite("applyLabel();\n")
        customwrite("var uploadForm=document.getElementById('upload-form');\n")
        customwrite("var uploadInput=document.getElementById('upload-input');\n")
        customwrite("var uploadSubmit=document.getElementById('upload-submit');\n")
        customwrite("var dropzone=document.getElementById('upload-dropzone');\n")
        customwrite("var queue=document.getElementById('upload-queue');\n")
        customwrite("var refresh=document.getElementById('refresh-list');\n")
        customwrite("if(uploadForm){\n")
        customwrite("function uploadFile(file){\n")
        customwrite("var item=document.createElement('li');item.className='upload-item';\n")
        customwrite("var name=document.createElement('span');name.className='upload-name';name.textContent=file.name;\n")
        customwrite("var progress=document.createElement('progress');progress.className='upload-progress';"
                    "progress.max=100;progress.value=0;\n")
        customwrite("var state=document.createElement('span');state.className='upload-state';state.textContent='Starting…';\n")
        customwrite("var cancel=document.createElement('button');cancel.type='button';cancel.className='cancel-upload';"
                    "cancel.textContent='Cancel';\n")
        customwrite("item.appendChild(name);item.appendChild(progress);item.appendChild(state);item.appendChild(cancel);"
                    "queue.appendChild(item);\n")
        customwrite("var data=new FormData();data.append('file',file,file.name);\n")
        customwrite("var xhr=new XMLHttpRequest();xhr.open('POST',window.location.pathname,true);"
                    "xhr.setRequestHeader('Accept','application/json');\n")
        customwrite("xhr.upload.addEventListener('progress',function(event){if(!event.lengthComputable){return;}"
                    "var percent=Math.round((event.loaded/event.total)*100);progress.value=percent;"
                    "state.textContent=percent<100?percent+'%':'Processing…';});\n")
        customwrite("xhr.addEventListener('load',function(){cancel.disabled=true;"
                    "if(xhr.status>=200&&xhr.status<300){progress.value=100;item.classList.add('success');"
                    "state.textContent='Complete';cancel.textContent='Done';refresh.hidden=false;return;}"
                    "item.classList.add('failed');cancel.textContent='Failed';"
                    "try{state.textContent=JSON.parse(xhr.responseText).message||'Upload failed';}"
                    "catch(error){state.textContent='Upload failed ('+xhr.status+')';}});\n")
        customwrite("xhr.addEventListener('error',function(){cancel.disabled=true;cancel.textContent='Failed';"
                    "item.classList.add('failed');state.textContent='Network error';});\n")
        customwrite("xhr.addEventListener('abort',function(){cancel.disabled=true;cancel.textContent='Cancelled';"
                    "item.classList.add('cancelled');state.textContent='Cancelled';});\n")
        customwrite("cancel.addEventListener('click',function(){xhr.abort();});xhr.send(data);\n")
        customwrite("}\n")
        customwrite("function uploadFiles(files){Array.prototype.forEach.call(files,uploadFile);}\n")
        customwrite("uploadSubmit.hidden=true;\n")
        customwrite("uploadInput.addEventListener('change',function(){uploadFiles(uploadInput.files);uploadInput.value='';});\n")
        customwrite("uploadForm.addEventListener('submit',function(event){event.preventDefault();"
                    "uploadFiles(uploadInput.files);uploadInput.value='';});\n")
        customwrite("['dragenter','dragover'].forEach(function(type){dropzone.addEventListener(type,function(event){"
                    "event.preventDefault();dropzone.classList.add('dragover');});});\n")
        customwrite("['dragleave','drop'].forEach(function(type){dropzone.addEventListener(type,function(event){"
                    "event.preventDefault();dropzone.classList.remove('dragover');});});\n")
        customwrite("dropzone.addEventListener('drop',function(event){uploadFiles(event.dataTransfer.files);});\n")
        customwrite("dropzone.addEventListener('keydown',function(event){if(event.key==='Enter'||event.key===' '){"
                    "event.preventDefault();uploadInput.click();}});\n")
        customwrite("refresh.addEventListener('click',function(){window.location.reload();});\n")
        customwrite("}\n")
        customwrite("var shareResult=document.getElementById('share-result');\n")
        customwrite("if(shareResult){\n")
        customwrite("var shareExpiry=document.getElementById('share-expiry');\n")
        customwrite("var shareLink=document.getElementById('share-link');\n")
        customwrite("var shareStatus=document.getElementById('share-status');\n")
        customwrite("var copyShare=document.getElementById('copy-share');\n")
        customwrite("Array.prototype.forEach.call(document.querySelectorAll('.share-button'),function(control){\n")
        customwrite("control.addEventListener('click',function(){control.disabled=true;shareStatus.textContent='Creating link…';"
                    "fetch('/__share__',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},"
                    "body:JSON.stringify({path:control.dataset.scope,expires_in:Number(shareExpiry.value)})})"
                    ".then(function(response){return response.json().then(function(data){if(!response.ok){"
                    "throw new Error(data.message||'Could not create link');}return data;});})"
                    ".then(function(data){shareLink.value=window.location.origin+data.url;shareResult.hidden=false;"
                    "shareStatus.textContent='Expires '+new Date(data.expires_at*1000).toLocaleString();shareLink.select();})"
                    ".catch(function(error){shareResult.hidden=false;shareLink.value='';shareStatus.textContent=error.message;})"
                    ".then(function(){control.disabled=false;});});\n")
        customwrite("});\n")
        customwrite("function fallbackCopy(){shareLink.select();document.execCommand('copy');"
                    "shareStatus.textContent='Link copied';}\n")
        customwrite("copyShare.addEventListener('click',function(){if(!shareLink.value){return;}"
                    "if(navigator.clipboard&&window.isSecureContext){navigator.clipboard.writeText(shareLink.value)"
                    ".then(function(){shareStatus.textContent='Link copied';}).catch(fallbackCopy);return;}"
                    "fallbackCopy();});\n")
        customwrite("}\n")
        customwrite("})();\n")
        customwrite("</script>\n")
        customwrite("</body>\n</html>\n")
        length = f.tell()
        f.seek(0)
        self.send_response(200)
        encoding = sys.getfilesystemencoding()
        self.send_header("Content-type", "text/html; charset=%s" % encoding)
        self.send_header("Content-Length", str(length))
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        return f

    def translate_path(self, path):
        """Translate a /-separated PATH to the local filename syntax.

        Components that mean special things to the local file system
        (e.g. drive or directory names) are ignored.  (XXX They should
        probably be diagnosed.)

        """
        # abandon query parameters
        path = path.split('?',1)[0]
        path = path.split('#',1)[0]
        path = posixpath.normpath(urllib.parse.unquote(path))
        words = path.split('/')
        words = filter(None, words)
        path = os.getcwd()
        for word in words:
            drive, word = os.path.splitdrive(word)
            head, word = os.path.split(word)
            if word in (os.curdir, os.pardir): continue
            path = os.path.join(path, word)
        return path

    def copyfile(self, source, outputfile):
        """Copy all data between two file objects.

        The SOURCE argument is a file object open for reading
        (or anything with a read() method) and the DESTINATION
        argument is a file object open for writing (or
        anything with a write() method).

        The only reason for overriding this would be to change
        the block size or perhaps to replace newlines by CRLF
        -- note however that this the default server uses this
        to copy binary data as well.

        """
        remaining = getattr(self, '_range_remaining', None)
        if remaining is None:
            shutil.copyfileobj(source, outputfile)
            return
        while remaining > 0:
            chunk = source.read(min(self.copy_buffer_size, remaining))
            if not chunk:
                break
            outputfile.write(chunk)
            remaining -= len(chunk)

    def guess_type(self, path):
        """Guess the type of a file.

        Argument is a PATH (a filename).

        Return value is a string of the form type/subtype,
        usable for a MIME Content-type header.

        The default implementation looks the file's extension
        up in the table self.extensions_map, using application/octet-stream
        as a default; however it would be permissible (if
        slow) to look inside the data to make a better guess.

        """

        base, ext = posixpath.splitext(path)
        if ext in self.extensions_map:
            return self.extensions_map[ext]
        ext = ext.lower()
        if ext in self.extensions_map:
            return self.extensions_map[ext]
        else:
            return self.extensions_map['']

    if not mimetypes.inited:
        mimetypes.init() # try to read system mime.types
    extensions_map = mimetypes.types_map.copy()
    extensions_map.update({
        '': 'application/octet-stream', # Default
        '.py': 'text/plain',
        '.c': 'text/plain',
        '.h': 'text/plain',
        })

try:
    # Python 2.x
    from SocketServer import ThreadingMixIn
    from http.server import HTTPServer
except ImportError:
    # Python 3.x
    from socketserver import ThreadingMixIn
    from http.server import HTTPServer

class ThreadingSimpleServer(ThreadingMixIn, HTTPServer):
    def __init__(self, server_address, request_handler_class, bind_and_activate=True):
        super().__init__(server_address, request_handler_class, bind_and_activate)
        self.started_at = time.monotonic()

REGISTRY_DIR = os.path.join(os.path.expanduser("~"), ".simple-server")
REGISTRY_PATH = os.path.join(REGISTRY_DIR, "servers.json")


def load_registry():
    if not os.path.exists(REGISTRY_PATH):
        return []
    with open(REGISTRY_PATH, "r", encoding="utf-8") as handle:
        try:
            return json.load(handle)
        except json.JSONDecodeError:
            return []


def save_registry(entries):
    os.makedirs(REGISTRY_DIR, exist_ok=True)
    with open(REGISTRY_PATH, "w", encoding="utf-8") as handle:
        json.dump(entries, handle, indent=2)


def process_alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def list_servers():
    entries = load_registry()
    active = []
    for entry in entries:
        pid = entry.get("pid")
        if pid and process_alive(pid):
            active.append(entry)
    if active != entries:
        save_registry(active)
    if not active:
        print("No running servers found.")
        return
    print("PID\tADDRESS\tPORT\tSTARTED\tCWD")
    for entry in active:
        started = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(entry.get("started_at", 0)))
        print(
            f"{entry.get('pid')}\t{entry.get('interface')}\t{entry.get('port')}\t"
            f"{started}\t{entry.get('cwd')}"
        )


def list_servers_porcelain():
    entries = load_registry()
    active = []
    for entry in entries:
        pid = entry.get("pid")
        if pid and process_alive(pid):
            active.append(entry)
    if active != entries:
        save_registry(active)
    if not active:
        print("No running servers found.")
        return
    for entry in active:
        print(f"{entry.get('port')}\t{entry.get('cwd')}")


def register_server(interface, port, cwd):
    entry = {
        "pid": os.getpid(),
        "interface": interface,
        "port": port,
        "cwd": cwd,
        "started_at": time.time(),
    }
    entries = load_registry()
    entries = [item for item in entries if item.get("pid") != entry["pid"]]
    entries.append(entry)
    save_registry(entries)


def deregister_server():
    entries = load_registry()
    pid = os.getpid()
    entries = [item for item in entries if item.get("pid") != pid]
    save_registry(entries)


def handle_exit(signum, frame):
    deregister_server()
    raise KeyboardInterrupt


def parse_args(argv):
    password = None
    local_only = False
    remaining = []
    index = 0
    while index < len(argv):
        arg = argv[index]
        if arg == "--local":
            local_only = True
            index += 1
            continue
        if arg in ("--password", "-pwd"):
            if index + 1 >= len(argv):
                raise ValueError("Missing value for --password/-pwd option.")
            password = argv[index + 1]
            index += 2
            continue
        remaining.append(arg)
        index += 1
    return remaining, password, local_only


def resolve_bind_address(args, local_only=False):
    if args:
        address = args[0]
        if ':' in address:
            interface, port_text = address.rsplit(':', 1)
            port = int(port_text)
        else:
            interface = '0.0.0.0'
            port = int(address)
    else:
        port = 8000
        interface = '0.0.0.0'

    if local_only:
        interface = '127.0.0.1'

    return interface, port


args, server_password, local_only = parse_args(sys.argv[1:])

if args and args[0] == "list":
    if len(args) > 1 and args[1] == "--porcelain":
        list_servers_porcelain()
    else:
        list_servers()
    sys.exit(0)

interface, port = resolve_bind_address(args, local_only)

if len(args) > 1:
    os.chdir(args[1])

SimpleHTTPRequestHandler.server_password = server_password

print('Started HTTP server on ' +  interface + ':' + str(port))


def run_server():
    server = ThreadingSimpleServer((interface, port), SimpleHTTPRequestHandler)
    register_server(interface, port, os.getcwd())
    atexit.register(deregister_server)
    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)
    try:
        while 1:
            sys.stdout.flush()
            server.handle_request()
    except KeyboardInterrupt:
        deregister_server()
        print('Finished.')

if __name__ == '__main__':
    run_server()
