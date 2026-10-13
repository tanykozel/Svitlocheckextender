"""Client for the ZTOE "GPV" JSON endpoints that back the outage-schedule apps.

The endpoints are public (no account, no key) but undocumented. The contract
below mirrors what the open-source SvitloYE app (MIT) relies on:
https://github.com/dmitthedazed/SvitloYE
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from typing import Any

BASE_URL = "https://www.ztoe.com.ua/gpv/api/"
USER_AGENT = "svitlo-notifier/0.1 (+https://github.com/tanykozel/svitlocheckextender)"


class ApiError(RuntimeError):
    pass


class GpvClient:
    def __init__(self, base_url: str = BASE_URL, timeout: float = 20.0) -> None:
        self.base_url = base_url
        self.timeout = timeout

    def _get(self, endpoint: str, **params: Any) -> Any:
        url = urllib.parse.urljoin(self.base_url, endpoint)
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8-sig")
        except OSError as exc:
            raise ApiError(f"GET {url} failed: {exc}") from exc
        try:
            return json.loads(body) if body.strip() else []
        except json.JSONDecodeError as exc:
            raise ApiError(f"GET {url} returned non-JSON: {body[:200]!r}") from exc

    # Address lookup chain: REM (district office) -> city -> street -> address.
    def rems(self) -> list[dict]:
        return self._get("api-rem.php")

    def cities(self, rem_id: str) -> list[dict]:
        return self._get("api-city.php", rem_id=rem_id)

    def streets(self, city_id: str) -> list[dict]:
        return self._get("api-street.php", city_id=city_id)

    def addresses(self, street_id: str) -> list[dict]:
        """Each address carries its queue: {"id", "name", "cherga", "pidcherga"}."""
        return self._get("api-address.php", street_id=street_id)

    def schedule(self, queue: int, subqueue: int) -> list[dict]:
        """Slots like {"date": "dd.MM.yyyy", "span": "HH:mm-HH:mm", "color": "red", "text": ...}."""
        return self._get("api-schedule.php", cherga_id=queue, pidcherga_id=subqueue)
