import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from svitlo_notifier import telegram


class FakeTelegram(BaseHTTPRequestHandler):
    calls: list = []

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        method = self.path.rsplit("/", 1)[-1]
        FakeTelegram.calls.append((self.path, payload))
        if "/botBAD/" in self.path:
            status, body = 401, {"ok": False, "description": "Unauthorized"}
        elif method == "getUpdates":
            status, body = 200, {"ok": True, "result": [
                {"message": {"chat": {"id": 1, "type": "private", "first_name": "Tetiana"}}},
                {"my_chat_member": {"chat": {"id": -100, "type": "group", "title": "Сім'я"}}},
                {"message": {"chat": {"id": 1, "type": "private", "first_name": "Tetiana"}}},
            ]}
        else:
            status, body = 200, {"ok": True, "result": {"username": "svitlo_bot"}}
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


class TelegramTests(unittest.TestCase):
    def setUp(self):
        FakeTelegram.calls = []
        self.server = HTTPServer(("127.0.0.1", 0), FakeTelegram)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        patcher = mock.patch.object(telegram, "API_BASE", f"http://127.0.0.1:{self.server.server_port}")
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def test_send_message(self):
        telegram.send_message("T", "42", "hello")
        path, payload = FakeTelegram.calls[0]
        self.assertEqual(path, "/botT/sendMessage")
        self.assertEqual(payload["chat_id"], "42")
        self.assertEqual(payload["text"], "hello")

    def test_recent_chats_deduplicated_newest_last(self):
        chats = telegram.recent_chats("T")
        self.assertEqual([c["id"] for c in chats], [-100, 1])

    def test_bad_token_reports_telegram_reason_without_token(self):
        with self.assertRaises(telegram.TelegramError) as ctx:
            telegram.get_me("BAD")
        self.assertIn("Unauthorized", str(ctx.exception))
        self.assertNotIn("BAD", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
