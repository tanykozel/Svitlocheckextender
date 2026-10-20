"""Emergency outages (аварійні відключення) from ZTOE's «Чому немає світла?» service.

The schedule data (gpv/api) has no emergencies. ZTOE publishes them in a separate public service,
https://api-ztoe-poweron.inneti.net/api (found 20.10 behind ztoe.com.ua/unhooking.php). It has its own ids, so a
subscriber's address is linked to it by name: district office (РЕМ) -> town -> street. A name that does not match
exactly is never guessed: that address simply gets no emergency alerts.

Load on ZTOE: one request per subscribed street per check (owner, 20.10: every 10 minutes), never per person.
"""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .api import ApiError, USER_AGENT
from .schedule import KYIV

BASE_URL = "https://api-ztoe-poweron.inneti.net/api/"
_PREFIX = re.compile(r"^(м\.|місто|с\.|село|смт\.?|селище|сщ\.|вул\.|вулиця|пров\.|провулок|просп\.|пл\.|бульв?\.?)\s*")


class PowerOnClient:
    def __init__(self, base_url: str = BASE_URL, timeout: float = 30.0) -> None:
        self.base_url = base_url
        self.timeout = timeout

    def _get(self, path: str, **params: Any) -> Any:
        params = {k: v for k, v in params.items() if v != ""}  # an unknown district is left out, not sent empty
        url = urllib.parse.urljoin(self.base_url, path) + "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/ld+json"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, ValueError) as exc:
            raise ApiError(f"GET {path} failed: {exc}") from exc

    @staticmethod
    def _members(data: Any) -> list[dict]:
        return data.get("hydra:member", []) if isinstance(data, dict) else list(data or [])

    def otgs(self) -> list[dict]:
        return self._members(self._get("pw_otgs", pagination="false"))

    def cities(self, otg_id: int | str = "") -> list[dict]:
        return self._members(self._get("pw_cities", **{"pagination": "false", "otg.id": otg_id}))

    def streets(self, city_id: int | str) -> list[dict]:
        return self._members(self._get("pw_streets", **{"pagination": "false", "city.id": city_id}))

    def accidents(self, otg_id: int | str, city_id: int | str, street_id: int | str) -> list[dict]:
        """Current outages on one street (a street rarely has more than a page)."""
        items: list[dict] = []
        for page in (1, 2, 3):
            data = self._get("pw_accidents", **{"page": page, "otg.id": otg_id, "city.id": city_id,
                                                 "street.id": street_id})
            items += self._members(data)
            if not (isinstance(data, dict) and data.get("hydra:view", {}).get("hydra:next")):
                break
        return items


def plain(name: str) -> str:
    """«місто Житомир» = «Житомир», «вул. Лук'яненка» = «вул. Лукʼяненка»: compared without prefixes and case."""
    name = name.lower().replace("’", "'").replace("ʼ", "'").replace("`", "'")
    name = re.sub(r"\s+", " ", name).strip()
    return _PREFIX.sub("", name).strip()


def link_address(client: PowerOnClient, rem_name: str, city_name: str, street_name: str) -> str:
    """'otg|city|street' ids in the emergency service, or '' when there is no exact, unambiguous match."""
    otg_id: Any = ""
    if rem_name:
        rem = plain(rem_name).replace(" рем", "")
        otgs = [o for o in client.otgs() if plain(str(o.get("name", ""))).replace(" рем", "") == rem]
        if len(otgs) != 1:
            return ""
        otg_id = otgs[0]["id"]
    cities = [c for c in client.cities(otg_id) if plain(str(c.get("name", ""))) == plain(city_name)]
    if len(cities) != 1:
        return ""  # unknown, or the same village name in several districts: never guess
    city = cities[0]
    streets = [s for s in client.streets(city["id"]) if plain(str(s.get("name", ""))) == plain(street_name)]
    if len(streets) != 1:
        return ""
    return f"{otg_id}|{city['id']}|{streets[0]['id']}"


@dataclass(frozen=True)
class Emergency:
    id: str
    start: datetime
    until: datetime | None
    houses: tuple[str, ...]

    def fingerprint(self) -> str:
        return f"{self.start.isoformat()}|{self.until.isoformat() if self.until else ''}"


def _when(raw: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(raw)).astimezone(KYIV)
    except ValueError:
        return None


def emergencies(records: list[dict]) -> list[Emergency]:
    """Emergency records only. Outages «by queue» (switchSubReason 2, e.g. «3.1») are the regular schedule,
    which the bot already alerts about. Mirrors the «аварійні» filter of ZTOE's own page."""
    found = []
    for r in records:
        emergency = r.get("typeOff") == 2 or (r.get("typeOff") == 1 and r.get("switchSubReason") == 0)
        start = _when(r.get("dateEvent"))
        if not emergency or start is None:
            continue
        houses = tuple(h.strip() for h in str(r.get("buildingNames", "")).split(",") if h.strip())
        found.append(Emergency(str(r.get("id")), start, _when(r.get("datePlanIn")), houses))
    return found


def interval(e: Emergency) -> str:
    start = e.start.strftime("%d.%m %H:%M")
    until = e.until.strftime("%d.%m %H:%M") if e.until else "невідомо"
    return f"з {start} до {until} (очікуване ввімкнення)"


def new_text(label: str, e: Emergency) -> str:
    return f"⚡ Аварійне відключення на твоїй адресі ({label}): {interval(e)}."


def changed_text(label: str, e: Emergency) -> str:
    return f"⚡ Аварійне відключення на твоїй адресі ({label}) змінено: {interval(e)}."
