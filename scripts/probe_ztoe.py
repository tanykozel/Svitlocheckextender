"""One-off (temporary): do real subscriber-style addresses link to ZTOE's emergency service? Public data only."""

import time

from svitlo_notifier.api import GpvClient
from svitlo_notifier.bot import name_of
from svitlo_notifier.emergency import PowerOnClient, emergencies, link_address

gpv, power = GpvClient(timeout=90), PowerOnClient(timeout=90)
rems = {str(r["id"]): name_of(r) for r in gpv.rems()}
print("GPV districts:", sorted(rems.values())[:30])
print("Emergency-service districts:", sorted(o.get("name") for o in power.otgs())[:30])
cases = [("7", "місто Житомир", "вул. Сергія Параджанова"), ("7", "місто Житомир", "вул. Вітрука"),
         ("16", "м. Звягель", "вул. Левка Лук'яненка"), ("16", "с. Сусли", "вул. Гранітна"),
         ("7", "місто Житомир", "пров Сергія Остапенка")]
for rem_id, city, street in cases:
    time.sleep(2)
    try:
        link = link_address(power, rems.get(rem_id, ""), city, street)
    except Exception as exc:  # noqa: BLE001
        link = f"error {exc}"
    print(f"{rems.get(rem_id)} | {city} | {street} -> {link or 'NO MATCH'}")
    if link and "|" in link:
        time.sleep(2)
        found = emergencies(power.accidents(*link.split("|")))
        print("   current emergencies on this street:", [(e.start.isoformat(), e.houses[:5]) for e in found])
