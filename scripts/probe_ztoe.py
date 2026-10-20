"""One-off (temporary): how the emergency service writes the unmatched names. Public data only."""

import time

from svitlo_notifier.emergency import PowerOnClient, plain

power = PowerOnClient(timeout=90)
otg = next(o for o in power.otgs() if "Звягель" in str(o.get("name")))
cities = power.cities(otg["id"])
print("Звягельський РЕМ cities matching звяг/сусл/новоград:",
      [c["name"] for c in cities if any(w in plain(c["name"]) for w in ("звяг", "сусл", "новоград"))])
for c in cities:
    if any(w in plain(c["name"]) for w in ("звяг", "сусл", "новоград")):
        time.sleep(2)
        streets = power.streets(c["id"])
        print(f"  {c['name']}: {len(streets)} streets; matches:",
              [s["name"] for s in streets if any(w in plain(s["name"]) for w in ("лук", "гранітн"))])
time.sleep(2)
zh = next(c for c in power.cities(next(o for o in power.otgs() if "Житомирський" in str(o.get("name")))["id"])
          if plain(c["name"]) == "житомир")
time.sleep(2)
print("Житомир streets with остапенк:", [s["name"] for s in power.streets(zh["id"]) if "остапенк" in plain(s["name"])])
