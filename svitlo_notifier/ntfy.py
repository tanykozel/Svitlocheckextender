"""Phone push via ntfy (https://docs.ntfy.sh/publish/): no account, just a topic name."""

from __future__ import annotations

import urllib.parse
import urllib.request


class NtfyError(RuntimeError):
    pass


def send_push(topic: str, text: str, server: str = "https://ntfy.sh", timeout: float = 20.0) -> None:
    title = text[1 : text.index("]")] if text.startswith("[") and "]" in text else "Світло"
    # Options go in the query string: HTTP headers cannot carry Cyrillic titles.
    params = urllib.parse.urlencode({"title": title, "priority": "high", "tags": "bulb"})
    request = urllib.request.Request(
        f"{server.rstrip('/')}/{urllib.parse.quote(topic, safe='')}?{params}",
        data=text.encode("utf-8"),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout):
            pass
    except OSError as exc:
        raise NtfyError(f"ntfy publish failed: {type(exc).__name__}") from None
