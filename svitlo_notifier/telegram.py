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


def send_message(
    token: str,
    chat_id: str | int,
    text: str,
    timeout: float = 20.0,
    buttons: list[list[tuple[str, str]]] | None = None,
) -> int | None:
    """Send text; `buttons` are rows of (label, callback_data) shown under the message. Returns the message id."""
    payload = {"chat_id": chat_id, "text": text, "disable_web_page_preview": True}
    if buttons:
        payload["reply_markup"] = {
            "inline_keyboard": [
                [{"text": label, "callback_data": data} for label, data in row] for row in buttons
            ]
        }
    result = _call(token, "sendMessage", payload, timeout)
    return result.get("message_id") if isinstance(result, dict) else None


def delete_message(token: str, chat_id: int, message_id: int) -> bool:
    """Delete a message in a private chat (the bot's own or the user's). Telegram allows it only while the
    message is less than 48 hours old. Best effort."""
    try:
        return bool(_call(token, "deleteMessage", {"chat_id": chat_id, "message_id": message_id}))
    except TelegramError:
        return False


def remove_buttons(token: str, chat_id: int, message_id: int) -> None:
    """Take the buttons off an older message so they can't be tapped any more. Best effort."""
    try:
        _call(token, "editMessageReplyMarkup",
              {"chat_id": chat_id, "message_id": message_id, "reply_markup": {"inline_keyboard": []}})
    except TelegramError:
        pass


def get_updates(token: str, offset: int | None = None, wait: int = 0) -> list[dict]:
    """Pending messages and button taps. Telegram keeps them for 24 hours until confirmed by `offset`.

    With `wait` > 0 Telegram holds the request open up to that many seconds and returns as soon as
    something arrives (long polling), so replies feel instant.
    """
    payload: dict = {"timeout": wait, "allowed_updates": ["message", "callback_query"]}
    if offset is not None:
        payload["offset"] = offset
    return _call(token, "getUpdates", payload, timeout=wait + 15)


def answer_callback(token: str, callback_id: str) -> None:
    """Stop the button's loading spinner. Taps older than a few minutes can't be answered; that's fine."""
    try:
        _call(token, "answerCallbackQuery", {"callback_query_id": callback_id})
    except TelegramError:
        pass


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


def set_commands(token: str, commands: list[tuple[str, str]]) -> None:
    """Fill the bot's "Menu" button next to the message box (https://core.telegram.org/bots/api#setmycommands)."""
    _call(token, "setMyCommands", {"commands": [{"command": c, "description": d} for c, d in commands]})
