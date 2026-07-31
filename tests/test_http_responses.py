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
            QuietRequestHandler.server_password = self.original_password
            os.chdir(self.original_cwd)
            raise

    def __exit__(self, exc_type, exc_value, traceback):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        QuietRequestHandler.session_store.clear()
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


class HttpResponseSmokeTests(unittest.TestCase):
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

                status, headers, body = request(address, "HEAD", "/hello.txt")
                self.assertEqual(status, 200)
                self.assertEqual(body, b"")
                self.assertEqual(headers.get_content_type(), "text/plain")
                self.assertEqual(headers["Content-Length"], str(len(content)))

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
