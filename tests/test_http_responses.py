import http.client
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


class HttpResponseSmokeTests(unittest.TestCase):
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

                status, headers, body = request(address, "GET", "/missing.txt")
                self.assertEqual(status, 404)
                self.assertEqual(headers.get_content_type(), "text/html")
                self.assertIn(b"File not found", body)

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
