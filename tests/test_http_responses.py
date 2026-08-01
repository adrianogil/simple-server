import http.client
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = PROJECT_ROOT / "src"
sys.path.insert(0, str(SRC_DIR))

original_argv = sys.argv
try:
    sys.argv = [str(SRC_DIR / "simpleserver.py")]
    import simpleserver
finally:
    sys.argv = original_argv


class QuietRequestHandler(simpleserver.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        pass


class LocalServer:
    def __init__(self, directory, password=None):
        self.directory = directory
        self.password = password

    def __enter__(self):
        self.original_cwd = os.getcwd()
        self.original_password = QuietRequestHandler.server_password
        try:
            os.chdir(self.directory)
            QuietRequestHandler.server_password = self.password
            QuietRequestHandler.session_store.clear()
            QuietRequestHandler.share_store.clear()

            self.server = simpleserver.ThreadingSimpleServer(
                ("127.0.0.1", 0),
                QuietRequestHandler,
            )
            self.server.daemon_threads = True
            self.thread = threading.Thread(
                target=self.server.serve_forever,
                name="simple-server-smoke-test",
            )
            self.thread.start()
            return self.server.server_address
        except BaseException:
            if hasattr(self, "server"):
                self.server.server_close()
            QuietRequestHandler.session_store.clear()
            QuietRequestHandler.share_store.clear()
            QuietRequestHandler.server_password = self.original_password
            os.chdir(self.original_cwd)
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        QuietRequestHandler.session_store.clear()
        QuietRequestHandler.share_store.clear()
        QuietRequestHandler.server_password = self.original_password
        os.chdir(self.original_cwd)
        if self.thread.is_alive():
            raise RuntimeError("local test server did not shut down")


def request(server_address, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection(*server_address, timeout=5)
    try:
        connection.request(method, path, body=body, headers=headers or {})
        response = connection.getresponse()
        response_body = response.read()
        return response.status, response.headers, response_body
    finally:
        connection.close()


def multipart_upload(filename, content):
    boundary = "simple-server-test-boundary"
    body = (
        "--%s\r\n"
        "Content-Disposition: form-data; name=\"file\"; filename=\"%s\"\r\n"
        "Content-Type: application/octet-stream\r\n"
        "\r\n" % (boundary, filename)
    ).encode("utf-8")
    body += content
    body += ("\r\n--%s--\r\n" % boundary).encode("ascii")
    headers = {
        "Content-Type": "multipart/form-data; boundary=%s" % boundary,
        "Content-Length": str(len(body)),
        "Referer": "/",
    }
    return body, headers


def create_share(server_address, path, expires_in=3600, cookie=None):
    body = json.dumps({"path": path, "expires_in": expires_in}).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Content-Length": str(len(body)),
    }
    if cookie:
        headers["Cookie"] = cookie
    return request(
        server_address,
        "POST",
        "/__share__",
        body=body,
        headers=headers,
    )


class HttpResponseSmokeTests(unittest.TestCase):
    def test_share_tokens_are_redacted_from_access_logs(self):
        handler = object.__new__(simpleserver.SimpleHTTPRequestHandler)
        handler.requestline = "GET /__share__/secret-token/child.txt HTTP/1.1"
        messages = []
        handler.log_message = lambda message, *args: messages.append(message % args)

        handler.log_request(200, 12)

        self.assertEqual(len(messages), 1)
        self.assertNotIn("secret-token", messages[0])
        self.assertIn("/__share__/<redacted>/child.txt", messages[0])

    def test_incomplete_upload_is_rejected_before_writing_a_file(self):
        body, headers = multipart_upload(
            "cancelled.txt",
            b"partial upload content",
        )
        handler = object.__new__(QuietRequestHandler)
        handler.headers = dict(headers)
        handler.headers["Content-Length"] = str(len(body) + 100)
        handler.rfile = BytesIO(body)

        with tempfile.TemporaryDirectory() as directory:
            original_cwd = os.getcwd()
            try:
                os.chdir(directory)
                result, message = handler.deal_post_data()
            finally:
                os.chdir(original_cwd)

            self.assertFalse(result)
            self.assertEqual(message, "Upload cancelled or incomplete.")
            self.assertFalse(Path(directory, "cancelled.txt").exists())

    def test_health_endpoint_returns_json_for_get_and_head(self):
        with tempfile.TemporaryDirectory() as directory:
            with LocalServer(directory, password="test-secret") as address:
                status, headers, body = request(address, "GET", "/healthz")
                payload = json.loads(body)

                self.assertEqual(status, 200)
                self.assertEqual(headers.get_content_type(), "application/json")
                self.assertEqual(headers.get_content_charset(), "utf-8")
                self.assertEqual(headers["Content-Length"], str(len(body)))
                self.assertEqual(payload["status"], "ok")
                self.assertEqual(payload["app"], "simple-server")
                self.assertEqual(payload["version"], simpleserver.__version__)
                self.assertGreaterEqual(payload["uptime"], 0)

                status, headers, body = request(address, "HEAD", "/healthz")
                self.assertEqual(status, 200)
                self.assertEqual(headers.get_content_type(), "application/json")
                self.assertGreater(int(headers["Content-Length"]), 0)
                self.assertEqual(body, b"")

    def test_connection_page_lists_urls_with_inline_qr_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            local_server = LocalServer(directory)
            with local_server as address:
                port = address[1]
                local_server.server.connection_urls = [
                    "http://192.168.1.50:%s/" % port,
                    "http://127.0.0.1:%s/" % port,
                ]

                status, headers, body = request(address, "GET", "/__connect__")
                self.assertEqual(status, 200)
                self.assertEqual(headers.get_content_type(), "text/html")
                self.assertEqual(headers.get_content_charset(), "utf-8")
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertEqual(headers["Referrer-Policy"], "no-referrer")
                self.assertIn(b"Connect a device", body)
                self.assertIn(b"http://192.168.1.50:", body)
                self.assertEqual(body.count(b'class="qr-code"'), 2)
                self.assertNotIn(b"Local-only mode", body)
                self.assertNotIn(b"<script src=", body)

                status, headers, body = request(address, "HEAD", "/__connect__")
                self.assertEqual(status, 200)
                self.assertGreater(int(headers["Content-Length"]), 0)
                self.assertEqual(body, b"")

    def test_connection_page_warns_for_local_only_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            with LocalServer(directory) as address:
                status, headers, body = request(address, "GET", "/__connect__")

                self.assertEqual(status, 200)
                self.assertIn(b"Local-only mode", body)
                self.assertIn(b"Restart without <code>--local</code>", body)

    def test_connection_page_requires_configured_password(self):
        with tempfile.TemporaryDirectory() as directory:
            with LocalServer(directory, password="test-secret") as address:
                status, headers, body = request(address, "GET", "/__connect__")

                self.assertEqual(status, 401)
                self.assertIn(b"Password required", body)

    def test_static_file_get_and_head_responses(self):
        content = b"hello from simple-server\n"
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "hello.txt").write_bytes(content)

            with LocalServer(directory) as address:
                status, headers, body = request(address, "GET", "/hello.txt")
                self.assertEqual(status, 200)
                self.assertEqual(body, content)
                self.assertEqual(headers.get_content_type(), "text/plain")
                self.assertEqual(headers["Content-Length"], str(len(content)))
                self.assertIsNotNone(headers["Last-Modified"])
                self.assertIsNotNone(headers["ETag"])
                self.assertEqual(headers["Accept-Ranges"], "bytes")
                self.assertEqual(headers["Cache-Control"], "no-cache")

                status, headers, body = request(address, "HEAD", "/hello.txt")
                self.assertEqual(status, 200)
                self.assertEqual(body, b"")
                self.assertEqual(headers.get_content_type(), "text/plain")
                self.assertEqual(headers["Content-Length"], str(len(content)))

    def test_static_file_range_responses(self):
        content = b"0123456789"
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "media.bin").write_bytes(content)

            with LocalServer(directory) as address:
                status, headers, body = request(
                    address,
                    "GET",
                    "/media.bin",
                    headers={"Range": "bytes=2-5"},
                )
                self.assertEqual(status, 206)
                self.assertEqual(body, b"2345")
                self.assertEqual(headers["Content-Range"], "bytes 2-5/10")
                self.assertEqual(headers["Content-Length"], "4")
                etag = headers["ETag"]

                status, headers, body = request(
                    address,
                    "GET",
                    "/media.bin",
                    headers={"Range": "bytes=7-"},
                )
                self.assertEqual(status, 206)
                self.assertEqual(body, b"789")
                self.assertEqual(headers["Content-Range"], "bytes 7-9/10")

                status, headers, body = request(
                    address,
                    "GET",
                    "/media.bin",
                    headers={"Range": "bytes=-3"},
                )
                self.assertEqual(status, 206)
                self.assertEqual(body, b"789")

                status, headers, body = request(
                    address,
                    "HEAD",
                    "/media.bin",
                    headers={"Range": "bytes=2-5"},
                )
                self.assertEqual(status, 206)
                self.assertEqual(body, b"")
                self.assertEqual(headers["Content-Length"], "4")

                status, headers, body = request(
                    address,
                    "GET",
                    "/media.bin",
                    headers={"Range": "bytes=50-60"},
                )
                self.assertEqual(status, 416)
                self.assertEqual(body, b"")
                self.assertEqual(headers["Content-Range"], "bytes */10")

                status, headers, body = request(
                    address,
                    "GET",
                    "/media.bin",
                    headers={"Range": "bytes=2-5", "If-Range": etag},
                )
                self.assertEqual(status, 206)
                self.assertEqual(body, b"2345")

                status, headers, body = request(
                    address,
                    "GET",
                    "/media.bin",
                    headers={"Range": "bytes=2-5", "If-Range": '"stale"'},
                )
                self.assertEqual(status, 200)
                self.assertEqual(body, content)

    def test_static_file_cache_revalidation(self):
        content = b"cacheable content"
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "cache.txt").write_bytes(content)

            with LocalServer(directory) as address:
                status, headers, body = request(address, "GET", "/cache.txt")
                self.assertEqual(status, 200)
                etag = headers["ETag"]
                last_modified = headers["Last-Modified"]

                status, headers, body = request(
                    address,
                    "GET",
                    "/cache.txt",
                    headers={"If-None-Match": etag},
                )
                self.assertEqual(status, 304)
                self.assertEqual(body, b"")
                self.assertEqual(headers["ETag"], etag)

                status, headers, body = request(
                    address,
                    "GET",
                    "/cache.txt",
                    headers={"If-Modified-Since": last_modified},
                )
                self.assertEqual(status, 304)
                self.assertEqual(body, b"")

                status, headers, body = request(
                    address,
                    "GET",
                    "/cache.txt",
                    headers={
                        "If-None-Match": '"stale"',
                        "If-Modified-Since": last_modified,
                    },
                )
                self.assertEqual(status, 200)
                self.assertEqual(body, content)

    def test_expiring_file_share_is_scoped_and_does_not_require_password(self):
        password = "main-password-must-stay-secret"
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "shared.txt").write_bytes(b"shared content")
            Path(directory, "private.txt").write_bytes(b"private content")

            with LocalServer(directory, password=password) as address:
                status, headers, body = create_share(address, "/shared.txt")
                self.assertEqual(status, 401)
                self.assertEqual(headers.get_content_type(), "application/json")
                self.assertEqual(json.loads(body)["message"], "Authentication required.")

                login_body = ("password=%s&next=%%2F" % password).encode("utf-8")
                status, headers, body = request(
                    address,
                    "POST",
                    "/__login__",
                    body=login_body,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Content-Length": str(len(login_body)),
                    },
                )
                self.assertEqual(status, 303)
                session_cookie = headers["Set-Cookie"].split(";", 1)[0]

                status, headers, body = create_share(
                    address,
                    "/shared.txt",
                    expires_in=900,
                    cookie=session_cookie,
                )
                payload = json.loads(body)
                self.assertEqual(status, 201)
                self.assertEqual(headers["Cache-Control"], "no-store")
                self.assertEqual(payload["expires_in"], 900)
                self.assertNotIn(password.encode("utf-8"), body)
                share_url = payload["url"]
                token = share_url.split('/')[2]

                status, headers, body = request(address, "GET", share_url)
                self.assertEqual(status, 200)
                self.assertEqual(body, b"shared content")
                self.assertEqual(headers["Referrer-Policy"], "no-referrer")

                status, headers, body = request(
                    address,
                    "GET",
                    share_url,
                    headers={"Range": "bytes=0-5"},
                )
                self.assertEqual(status, 206)
                self.assertEqual(body, b"shared")

                status, headers, body = request(
                    address,
                    "GET",
                    share_url + "/private.txt",
                )
                self.assertEqual(status, 404)

                status, headers, body = request(address, "POST", share_url)
                self.assertEqual(status, 405)

                QuietRequestHandler.share_store[token]["expires_at"] = 0
                status, headers, body = request(address, "GET", share_url)
                self.assertEqual(status, 410)

    def test_directory_share_is_read_only_and_cannot_escape_its_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            shared_directory = Path(directory, "shared-folder")
            shared_directory.mkdir()
            Path(shared_directory, "child.txt").write_bytes(b"child content")
            Path(directory, "private.txt").write_bytes(b"private content")

            with LocalServer(directory) as address:
                status, headers, body = create_share(
                    address,
                    "/shared-folder/",
                    expires_in=60,
                )
                self.assertEqual(status, 400)

                status, headers, body = create_share(
                    address,
                    "/shared-folder/",
                    expires_in=86400,
                )
                self.assertEqual(status, 201)
                share_url = json.loads(body)["url"]
                self.assertTrue(share_url.endswith('/'))

                status, headers, body = request(address, "GET", share_url)
                self.assertEqual(status, 200)
                self.assertIn(b"Shared directory", body)
                self.assertIn(b"child.txt", body)
                self.assertNotIn(b'id="upload-dropzone"', body)
                self.assertNotIn(b'class="delete"', body)
                self.assertNotIn(b'class="share-button"', body)
                self.assertEqual(headers["Referrer-Policy"], "no-referrer")

                status, headers, body = request(
                    address,
                    "GET",
                    share_url + "child.txt",
                )
                self.assertEqual(status, 200)
                self.assertEqual(body, b"child content")

                status, headers, body = request(
                    address,
                    "GET",
                    share_url + "%2E%2E/private.txt",
                )
                self.assertEqual(status, 404)

    def test_directory_listing_and_missing_file_responses(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "visible file.txt").write_text(
                "listed content",
                encoding="utf-8",
            )

            with LocalServer(directory) as address:
                status, headers, body = request(address, "GET", "/")
                self.assertEqual(status, 200)
                self.assertEqual(headers.get_content_type(), "text/html")
                self.assertIn("charset=", headers["Content-Type"])
                self.assertIn(b"<h2>Directory listing</h2>", body)
                self.assertIn(b"visible%20file.txt", body)
                self.assertIn(b'id="upload-dropzone"', body)
                self.assertIn(b'id="upload-input" name="file" type="file" multiple', body)
                self.assertIn(b"xhr.upload.addEventListener('progress'", body)
                self.assertIn(b"cancel.addEventListener('click'", body)
                self.assertIn(b"dropzone.addEventListener('drop'", body)
                self.assertIn(b'id="share-expiry"', body)
                self.assertIn(b'class="share-button"', body)
                self.assertIn(b"fetch('/__share__'", body)
                self.assertIn(b'href=\'/__connect__\'>Connect devices', body)

                status, headers, body = request(address, "GET", "/missing.txt")
                self.assertEqual(status, 404)
                self.assertEqual(headers.get_content_type(), "text/html")
                self.assertIn(b"File not found", body)

    def test_mutations_cannot_escape_served_directory(self):
        with tempfile.TemporaryDirectory() as parent:
            served = Path(parent, "served")
            served.mkdir()
            outside = Path(parent, "outside.txt")
            outside.write_bytes(b"must remain unchanged")
            outside_directory = Path(parent, "outside-directory")
            outside_directory.mkdir()
            outside_via_symlink = outside_directory / "outside-via-symlink.txt"
            outside_via_symlink.write_bytes(b"also unchanged")
            escape_link = served / "escape"
            upload_escape_link = served / "upload-escape.txt"
            symlinks_available = True
            try:
                escape_link.symlink_to(outside_directory, target_is_directory=True)
                upload_escape_link.symlink_to(outside)
            except OSError:
                symlinks_available = False

            with LocalServer(str(served)) as address:
                status, headers, body = request(
                    address,
                    "GET",
                    "/?deletefile=..%2Foutside.txt",
                )
                self.assertEqual(status, 400)
                self.assertEqual(outside.read_bytes(), b"must remain unchanged")

                status, headers, body = request(
                    address,
                    "GET",
                    "/?createfolder=..%2Fescaped-folder",
                )
                self.assertEqual(status, 400)
                self.assertFalse(Path(parent, "escaped-folder").exists())

                if symlinks_available:
                    status, headers, body = request(
                        address,
                        "GET",
                        "/escape/?deletefile=outside-via-symlink.txt",
                    )
                    self.assertEqual(status, 400)
                    self.assertEqual(outside_via_symlink.read_bytes(), b"also unchanged")

                    status, headers, body = request(
                        address,
                        "GET",
                        "/escape/?createfolder=escaped-via-symlink",
                    )
                    self.assertEqual(status, 400)
                    self.assertFalse((outside_directory / "escaped-via-symlink").exists())

                    upload_body, upload_headers = multipart_upload(
                        "upload-escape.txt",
                        b"must not follow the symlink",
                    )
                    status, headers, body = request(
                        address,
                        "POST",
                        "/",
                        body=upload_body,
                        headers=upload_headers,
                    )
                    self.assertEqual(status, 400)
                    self.assertEqual(outside.read_bytes(), b"must remain unchanged")

                upload_body, upload_headers = multipart_upload(
                    "../escaped-upload.txt",
                    b"must not be written",
                )
                upload_headers["Accept"] = "application/json"
                status, headers, body = request(
                    address,
                    "POST",
                    "/",
                    body=upload_body,
                    headers=upload_headers,
                )
                self.assertEqual(status, 400)
                self.assertEqual(headers.get_content_type(), "application/json")
                self.assertEqual(json.loads(body)["status"], "error")
                self.assertIn(b"Upload rejected", body)
                self.assertFalse(Path(parent, "escaped-upload.txt").exists())

    def test_mutations_accept_plain_names_within_served_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            served = Path(directory)
            delete_target = served / "delete-me.txt"
            delete_target.write_text("delete me", encoding="utf-8")

            with LocalServer(directory) as address:
                status, headers, body = request(
                    address,
                    "GET",
                    "/?deletefile=delete-me.txt",
                )
                self.assertEqual(status, 200)
                self.assertFalse(delete_target.exists())

                status, headers, body = request(
                    address,
                    "GET",
                    "/?createfolder=new-folder",
                )
                self.assertEqual(status, 200)
                self.assertTrue(Path(directory, "new-folder").is_dir())

                upload_body, upload_headers = multipart_upload(
                    "uploaded.txt",
                    b"uploaded safely",
                )
                upload_headers["Accept"] = "application/json"
                status, headers, body = request(
                    address,
                    "POST",
                    "/",
                    body=upload_body,
                    headers=upload_headers,
                )
                self.assertEqual(status, 200)
                self.assertEqual(headers.get_content_type(), "application/json")
                self.assertEqual(
                    json.loads(body),
                    {"status": "ok", "message": "Files uploaded"},
                )
                self.assertEqual(
                    Path(directory, "uploaded.txt").read_bytes(),
                    b"uploaded safely",
                )

    def test_password_login_allows_access_to_static_file(self):
        content = b"protected content\n"
        with tempfile.TemporaryDirectory() as directory:
            Path(directory, "protected.txt").write_bytes(content)

            with LocalServer(directory, password="test-secret") as address:
                status, headers, body = request(
                    address,
                    "GET",
                    "/protected.txt",
                )
                self.assertEqual(status, 401)
                self.assertEqual(headers.get_content_type(), "text/html")
                self.assertIn(b"Password required", body)

                login_body = b"password=test-secret&next=%2Fprotected.txt"
                status, headers, body = request(
                    address,
                    "POST",
                    "/__login__",
                    body=login_body,
                    headers={
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Content-Length": str(len(login_body)),
                    },
                )
                self.assertEqual(status, 303)
                self.assertEqual(body, b"")
                self.assertEqual(headers["Location"], "/protected.txt")
                self.assertIn("HttpOnly", headers["Set-Cookie"])
                self.assertIn("SameSite=Lax", headers["Set-Cookie"])

                session_cookie = headers["Set-Cookie"].split(";", 1)[0]
                status, headers, body = request(
                    address,
                    "GET",
                    "/protected.txt",
                    headers={"Cookie": session_cookie},
                )
                self.assertEqual(status, 200)
                self.assertEqual(headers.get_content_type(), "text/plain")
                self.assertEqual(body, content)


if __name__ == "__main__":
    unittest.main()
