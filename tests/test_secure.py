import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from svitlo_notifier.secure import StateKeyError, chat_tag, load_json, save_json


class SecureStateTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "bot.json"
        self.data = {"subs": {"670870052": {"label": "с. Сусли, вул. Гранітна 12"}}}

    def tearDown(self):
        self.dir.cleanup()

    def test_round_trip_and_nothing_readable_on_disk(self):
        save_json(self.path, self.data, "a long passphrase")
        self.assertFalse(self.path.exists())
        blob = (Path(self.dir.name) / "bot.json.enc").read_bytes()
        self.assertNotIn(b"670870052", blob)
        self.assertNotIn("Сусли".encode(), blob)
        self.assertEqual(load_json(self.path, "a long passphrase"), self.data)

    def test_plain_state_is_migrated_and_removed(self):
        self.path.write_text(json.dumps(self.data), encoding="utf-8")
        self.assertEqual(load_json(self.path, "k"), self.data)
        save_json(self.path, self.data, "k")
        self.assertFalse(self.path.exists(), "plain copy deleted once encrypted")

    def test_wrong_or_missing_key_refuses_instead_of_starting_empty(self):
        save_json(self.path, self.data, "right")
        with self.assertRaises(StateKeyError):
            load_json(self.path, "wrong")
        with self.assertRaises(StateKeyError):
            load_json(self.path, "")

    def test_no_key_keeps_plain_files(self):
        save_json(self.path, self.data)
        self.assertEqual(json.loads(self.path.read_text(encoding="utf-8")), self.data)
        self.assertIsNone(load_json(Path(self.dir.name) / "none.json"))

    def test_chat_tag_hides_the_id(self):
        self.assertNotIn("670870052", chat_tag(670870052))
        self.assertEqual(chat_tag(670870052), chat_tag("670870052"))

    def test_bot_command_will_not_overwrite_state_with_a_wrong_key(self):
        import io
        from contextlib import redirect_stdout

        from svitlo_notifier import cli
        save_json(self.path, self.data, "right")
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "T", "SVITLO_STATE_KEY": "wrong"}, clear=True), \
             redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(["bot", "--state", str(self.path)]), 1)
        self.assertEqual(load_json(self.path, "right"), self.data, "subscribers untouched")
