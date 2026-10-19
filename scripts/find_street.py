"""One-off (temporary): find a street in ZTOE's lists and show its queues. Public data only."""

import sys
import time

from svitlo_notifier.api import GpvClient
from svitlo_notifier.bot import _queue_of, house_queues, listed_houses, match, name_of, similar

WANT = sys.argv[1]
client = GpvClient(timeout=90)
found = []


def look(city_id, city_name):
    streets = client.streets(city_id)
    hits = match(streets, WANT) or similar(streets, WANT, cutoff=0.75)
    for s in hits:
        found.append((city_name, s))
        print(f"FOUND  {city_name} (city {city_id}) -> {name_of(s)} (street {s['id']})")
    return bool(hits)


if not look("16657", "місто Житомир"):
    for rem in client.rems():
        time.sleep(2)
        for c in client.cities(str(rem["id"])):
            if name_of(c).startswith(("м.", "місто")) and str(c["id"]) != "16657":
                time.sleep(2)
                try:
                    look(str(c["id"]), f"{name_of(rem)} / {name_of(c)}")
                except Exception as exc:  # noqa: BLE001
                    print(f"skip {name_of(c)}: {exc}")
for city, s in found[:3]:
    time.sleep(2)
    rows = client.addresses(str(s["id"]))
    queues = sorted({q for r in rows if (q := _queue_of(r))})
    print(f"\n{city}, {name_of(s)}: {len(rows)} rows, queues: {', '.join(f'{a}.{b}' for a, b in queues) or 'NONE (0.0 only)'}")
    for h in listed_houses(rows):
        q = house_queues(rows, h)
        text = ", ".join(f"{'побутові' if k else 'непобутові'} {v[0]}.{v[1]}" for k, v in q.items()) or "no queue (0.0)"
        print(f"  house {h}: {text}")
if not found:
    print("NOT FOUND in any town list")
