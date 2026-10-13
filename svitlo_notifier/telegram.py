"""Minimal Telegram Bot API sender (https://core.telegram.org/bots/api#sendmessage)."""

from __future__ import annotations

import json
import urllib.request


class TelegramError(RuntimeError):
    pass


def send_message(token: str, chat_id: str, text: str, timeout: float = 20.0) -> None:
    payload = json.dumps(
        {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    ).encode()
    request = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            result = json.loads(response.read().decode())
    except OSError as exc:
        # Do not echo the URL: it contains the bot token.
        raise TelegramError(f"sendMessage failed: {type(exc).__name__}") from None
    if not result.get("ok"):
        raise TelegramError(f"sendMessage rejected: {result.get('description')}")
