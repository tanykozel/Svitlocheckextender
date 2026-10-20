"""One-off (temporary): do real subscriber-style addresses link to ZTOE's emergency service? Public data only."""

import time

from svitlo_notifier.emergency import PowerOnClient, emergencies, link_address

power = PowerOnClient(timeout=90)
cases = [("Житомирський", "місто Житомир", "вул. Сергія Параджанова"), ("Житомирський", "місто Житомир", "вул. Вітрука"),
         ("Звягельський", "м. Звягель", "вул. Левка Лук'яненка"), ("Звягельський", "с. Сусли", "вул. Гранітна"),
         ("Житомирський", "місто Житомир", "пров Сергія Остапенка"), ("Малинський", "місто Малин", "вул. Левка Лук'яненка")]
for rem, city, street in cases:
    time.sleep(2)
    link = link_address(power, rem, city, street)
    print(f"{rem} | {city} | {street} -> {link or 'NO MATCH'}")
    if link:
        time.sleep(2)
        print("   emergencies now:", [(e.start.strftime("%d.%m %H:%M"), e.houses[:6]) for e in emergencies(power.accidents(*link.split("|")))])
