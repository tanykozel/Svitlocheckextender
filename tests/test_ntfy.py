import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

from svitlo_notifier.ntfy import NtfyError, send_push


class Recorder(BaseHTTPRequestHandler):
    calls: list = []
    status = 200

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"])).decode()
        Recorder.calls.append((self.path, body))
        self.send_response(Recorder.status)
        self.end_headers()

    def log_message(self, *args):
        pass


class NtfyTests(unittest.TestCase):
    def setUp(self):
        Recorder.calls, Recorder.status = [], 200
        self.server = HTTPServer(("127.0.0.1", 0), Recorder)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_posts_text_with_label_as_title(self):
        send_push("my-home-svitlo", "[Дім] 🔴 Світло вимкнуть", self.url)
        path, body = Recorder.calls[0]
        parsed = urllib.parse.urlsplit(path)
        self.assertEqual(parsed.path, "/my-home-svitlo")
        self.assertEqual(urllib.parse.parse_qs(parsed.query)["title"], ["Дім"])
        self.assertEqual(urllib.parse.parse_qs(parsed.query)["priority"], ["high"])
        self.assertEqual(body, "[Дім] 🔴 Світло вимкнуть")

    def test_http_error_raises(self):
        Recorder.status = 500
        with self.assertRaises(NtfyError):
            send_push("t", "x", self.url)


if __name__ == "__main__":
    unittest.main()
