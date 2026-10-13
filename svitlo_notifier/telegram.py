"""Minimal Telegram Bot API client (https://core.telegram.org/bots/api)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

API_BASE = "https://api.telegram.org"


class TelegramError(RuntimeError):
    pass


def _call(token: str, method: str, payload: dict | None = None, timeout: float = 20.0):
    request = urllib.request.Request(
        f"{API_BASE}/bot{token}/{method}",
        data=json.dumps(payload or {}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        # Telegram explains rejections (bad token, unknown chat) in the JSON body.
        try:
            result = json.loads(exc.read().decode())
        except ValueError:
            raise TelegramError(f"{method} failed: HTTP {exc.code}") from None
    except OSError as exc:
        # Do not echo the URL: it contains the bot token.
        raise TelegramError(f"{method} failed: {type(exc).__name__}") from None
    if not result.get("ok"):
        raise TelegramError(f"{method} rejected: {result.get('description')}")
    return result["result"]


def send_message(token: str, chat_id: str, text: str, timeout: float = 20.0) -> None:
    _call(
        token,
        "sendMessage",
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": True},
        timeout,
    )


def get_me(token: str) -> dict:
    return _call(token, "getMe")


def recent_chats(token: str) -> list[dict]:
    """Chats that recently messaged the bot or added it, newest last, without duplicates."""
    chats: dict[int, dict] = {}
    for update in _call(token, "getUpdates", {"allowed_updates": ["message", "my_chat_member", "channel_post"]}):
        for key in ("message", "channel_post", "my_chat_member"):
            chat = (update.get(key) or {}).get("chat")
            if chat:
                chats.pop(chat["id"], None)
                chats[chat["id"]] = chat
    return list(chats.values())
