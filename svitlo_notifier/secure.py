"""Encrypted state files.

The bot's state (subscribers' chat ids and addresses) lives in the GitHub Actions cache. In a
public repository that cache must not hold readable personal data, so when SVITLO_STATE_KEY is
set every state file is stored encrypted (Fernet: AES-128-CBC + HMAC-SHA256, from the
`cryptography` package) as `<name>.enc`, and the plain file is removed.

The key is derived from any long passphrase with scrypt, so the secret can be ordinary text.
"""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

_SALT = b"svitlo-notifier/state/v1"


class StateKeyError(RuntimeError):
    pass


def _fernet(passphrase: str):
    try:
        from cryptography.fernet import Fernet
    except ImportError as exc:  # only needed when a key is configured
        raise StateKeyError("SVITLO_STATE_KEY is set but the 'cryptography' package is missing "
                            "(pip install cryptography)") from exc
    raw = hashlib.scrypt(passphrase.encode(), salt=_SALT, n=2**14, r=8, p=1, dklen=32)
    return Fernet(base64.urlsafe_b64encode(raw))


def _enc_path(path: Path) -> Path:
    return path.with_name(path.name + ".enc")


def load_json(path: Path, passphrase: str = "") -> dict | None:
    """Read state; None when there is none yet. Never silently ignores an unreadable encrypted file."""
    enc = _enc_path(path)
    if enc.exists():
        if not passphrase:
            raise StateKeyError(f"{enc} is encrypted but SVITLO_STATE_KEY is not set")
        from cryptography.fernet import InvalidToken

        try:
            data = _fernet(passphrase).decrypt(enc.read_bytes())
        except InvalidToken:
            raise StateKeyError(f"{enc} cannot be decrypted: SVITLO_STATE_KEY is wrong") from None
        return json.loads(data.decode("utf-8"))
    if path.exists():  # plain file: first run, or before encryption was switched on
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def save_json(path: Path, data: dict, passphrase: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    target = _enc_path(path) if passphrase else path
    if passphrase:
        body = _fernet(passphrase).encrypt(body)
    tmp = target.with_name(target.name + ".tmp")
    tmp.write_bytes(body)
    tmp.replace(target)
    if passphrase and path.exists():
        path.unlink()  # never leave a readable copy next to the encrypted one


def chat_tag(chat: str | int) -> str:
    """Short, stable, non-reversible label for logs, which are public in a public repository."""
    return "chat#" + hashlib.sha256(str(chat).encode()).hexdigest()[:8]
