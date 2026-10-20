"""Emergency outages (owner, 20.10): ZTOE's «Чому немає світла?» service, real record shapes from 20.10."""

import unittest
from datetime import datetime, timedelta

from svitlo_notifier.api import ApiError
from svitlo_notifier.bot import Bot, BotState, Subscription
from svitlo_notifier.emergency import emergencies, link_address, plain
from svitlo_notifier.schedule import KYIV
from tests.test_bot import FakeDirectory


def record(rid, houses, start="2026-10-20T09:48:32+00:00", until="2026-10-21T06:00:00+00:00",
           type_off=1, sub_reason=0, koment=""):
    """Shaped like api-ztoe-poweron /api/pw_accidents members (public data)."""
    return {"@type": "PwAccident", "id": rid, "code_otg": "16",
            "city": {"id": 390, "name": "Улянівка"},
            "street": {"id": 17323, "name": "вул. Молодіжна"},
            "dateEvent": start, "datePlanIn": until, "koment": koment, "switchSubReason": sub_reason,
            "otg": {"id": 16, "code": "16", "name": "Романівський РЕМ"},
            "buildingNames": houses, "typeOff": type_off}


class FakePowerOn:
    def __init__(self):
        self.records = []
        self.calls = []
        self.down = False

    def otgs(self):
        return [{"id": 16, "name": "Романівський РЕМ"}, {"id": 1, "name": "Андрушівський РЕМ"}]

    def cities(self, otg_id=""):
        cities = {16: [{"id": 390, "name": "Улянівка"}], 1: [{"id": 1, "name": "Андрушівка"}]}
        if otg_id == "":
            return cities[16] + cities[1] + [{"id": 999, "name": "Андрушівка"}]  # a twin name elsewhere
        return cities[int(otg_id)]

    def streets(self, city_id):
        return [{"id": 17323, "name": "вул. Молодіжна"}, {"id": 17327, "name": "вул. Хутірська"},
                {"id": 5, "name": "вул. Левка Лук'яненка"}]

    def accidents(self, otg_id, city_id, street_id):
        self.calls.append(street_id)
        if self.down:
            raise ApiError("down")
        return self.records


class ParsingTests(unittest.TestCase):
    def test_only_emergencies_are_kept(self):
        found = emergencies([record(1, "1, 2"), record(2, "3", sub_reason=2, koment="3.1"),
                             record(3, "4", type_off=2, sub_reason=None)])
        self.assertEqual([e.id for e in found], ["1", "3"], "«by queue» outages are the regular schedule")
        self.assertEqual(found[0].start.strftime("%d.%m %H:%M"), "20.10 12:48", "shown in Kyiv time")
        self.assertEqual(found[0].houses, ("1", "2"))

    def test_names_compare_without_prefixes_and_apostrophe_kinds(self):
        self.assertEqual(plain("місто Житомир"), plain("Житомир"))
        self.assertEqual(plain("вул. Левка Лукʼяненка"), plain("вул. Левка Лук'яненка"))

    def test_link_is_exact_or_nothing(self):
        client = FakePowerOn()
        self.assertEqual(link_address(client, "Романівський", "с. Улянівка", "вул. Молодіжна"), "16|390|17323")
        self.assertEqual(link_address(client, "", "Улянівка", "вул. Молодіжна"), "|390|17323")
        self.assertEqual(link_address(client, "", "Андрушівка", "вул. Молодіжна"), "", "twin town: never guess")
        self.assertEqual(link_address(client, "Романівський", "Улянівка", "вул. Невідома"), "")

    def test_twin_town_entry_and_twin_street_entries_from_real_data(self):
        # 20.10: «Звягель» twice (458 streets / 1 street), «Лук`яненка» and «Лук'яненка» as two entries
        client = FakePowerOn()
        client.otgs = lambda: [{"id": 9, "name": "Звягельський РЕМ"}]
        client.cities = lambda otg_id="": [{"id": 100, "name": "Звягель"}, {"id": 101, "name": "Звягель"}]
        client.streets = lambda city_id: ([{"id": 7, "name": "вул. Левка Лук`яненка"},
                                           {"id": 8, "name": "вул. Левка Лук'яненка"},
                                           {"id": 9, "name": "вул. Гранітна"}] if city_id == 100 else
                                          [{"id": 50, "name": "вул. Інша"}])
        self.assertEqual(link_address(client, "Звягельський", "м. Звягель", "вул. Левка Лук'яненка"), "9|100|7,8")

    def test_street_kind_must_match_when_two_kinds_share_a_name(self):
        client = FakePowerOn()
        client.streets = lambda city_id: [{"id": 1, "name": "вул. Сергія Остапенка"},
                                          {"id": 2, "name": "пров. Сергія Остапенка"}]
        self.assertEqual(link_address(client, "Романівський", "Улянівка", "пров Сергія Остапенка"), "16|390|2")
        self.assertEqual(link_address(client, "Романівський", "Улянівка", "вул. Сергія Остапенка"), "16|390|1")


class AlertTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.power = FakePowerOn()
        self.state = BotState()
        self.bot = Bot(FakeDirectory(), lambda chat, text, buttons: self.sent.append((chat, text)), self.state,
                       emergency=self.power)
        self.now = datetime(2026, 10, 20, 13, 0, tzinfo=KYIV)
        self.state.subs["7"] = Subscription(3, 1, "с. Улянівка, вул. Молодіжна", street_id="1", house="12",
                                            rem="Романівський")

    def check(self, minutes=0):
        return self.bot.check_emergencies(self.now + timedelta(minutes=minutes))

    def test_new_emergency_is_announced_once_with_its_interval(self):
        self.power.records = [record(317818499, "1, 11, 12, 13")]
        self.assertEqual(self.check(), 1)
        self.assertEqual(self.sent[-1][1], "⚡🔴 Нове аварійне відключення на твоїй адресі (с. Улянівка, вул. Молодіжна): "
                                            "з 20.10 12:48 до 21.10 09:00.")
        self.assertEqual(self.check(10), 0, "the same emergency is not repeated")

    def test_changed_interval_shows_the_whole_new_interval(self):
        self.power.records = [record(317818499, "12")]
        self.check()
        self.power.records = [record(317818499, "12", until="2026-10-21T08:00:00+00:00")]
        self.check(10)
        self.assertIn("змінено: з 20.10 12:48 до 21.10 11:00.", self.sent[-1][1])

    def test_end_is_not_announced(self):
        self.power.records = [record(317818499, "12")]
        self.check()
        self.power.records = []
        self.check(10)
        self.assertEqual(len(self.sent), 1, "no «завершено» message (owner, 20.10)")
        self.check(24 * 60)  # past its end (21.10 09:00): forgotten
        self.assertEqual(self.state.subs["7"].em_sent, {})

    def test_same_emergency_under_a_new_id_is_not_new_again(self):
        # Owner's report 20.10 (с. Дубрівка, whole street): «Нове…» at 22:47, 22:58 and 23:08 for one emergency
        for minutes, rid in ((0, 1), (10, 2), (20, 3)):
            self.power.records = [record(rid, "12")]
            self.check(minutes)
        self.assertEqual(len(self.sent), 1)

    def test_emergency_missing_from_one_reply_is_not_new_again(self):
        self.power.records = [record(1, "12")]
        self.check()
        self.power.records = []
        self.check(10)
        self.power.records = [record(1, "12")]
        self.check(20)
        self.assertEqual(len(self.sent), 1)

    def test_new_id_with_a_new_end_is_a_change(self):
        self.power.records = [record(1, "12")]
        self.check()
        self.power.records = [record(2, "12", until="2026-10-21T08:00:00+00:00")]
        self.check(10)
        self.assertEqual(len(self.sent), 2)
        self.assertIn("змінено: з 20.10 12:48 до 21.10 11:00.", self.sent[-1][1])
        self.check(20)
        self.assertEqual(len(self.sent), 2)

    def test_whole_street_hears_once_about_identical_records(self):
        self.state.subs["7"].house = ""
        self.power.records = [record(1, "1, 3"), record(2, "5, 7")]  # same interval, other houses
        self.check()
        self.check(10)
        self.assertEqual(len(self.sent), 1)

    def test_a_really_new_emergency_is_still_announced(self):
        self.power.records = [record(1, "12")]
        self.check()
        self.power.records = [record(1, "12"), record(2, "12", start="2026-10-20T11:00:00+00:00")]
        self.check(10)
        self.assertEqual(len(self.sent), 2)
        self.assertIn("Нове", self.sent[-1][1])

    def test_other_houses_and_queue_outages_are_ignored(self):
        self.power.records = [record(1, "1, 13"), record(2, "12", sub_reason=2, koment="3.1")]
        self.check()
        self.assertEqual(self.sent, [])

    def test_whole_street_subscription_hears_about_any_house(self):
        self.state.subs["7"].house = ""
        self.power.records = [record(1, "1, 13")]
        self.check()
        self.assertEqual(len(self.sent), 1)

    def test_every_10_minutes_and_one_request_per_street(self):
        self.state.subs["8"] = Subscription(3, 1, "с. Улянівка, вул. Молодіжна", street_id="1", house="1",
                                            rem="Романівський")
        self.check()
        self.check(5)
        self.assertEqual(self.power.calls, ["17323"], "two people, one street, one request; 5 min later: none")
        self.check(10)
        self.assertEqual(len(self.power.calls), 2)

    def test_unmatched_address_is_skipped_and_retried_daily(self):
        self.state.subs["7"].label = "с. Улянівка, вул. Невідома"
        self.check()
        self.assertEqual((self.state.subs["7"].em_link, self.power.calls), ("-", []))
        self.check(10)
        self.assertEqual(self.power.calls, [], "not retried before a day passes")

    def test_service_down_is_counted_and_nothing_is_lost(self):
        self.power.down = True
        self.check()
        self.assertEqual(self.bot.stats["failure:ztoe_emergency"], 1)
        self.power.down, self.power.records = False, [record(1, "12")]
        self.check(10)
        self.assertEqual(len(self.sent), 1)

    def test_kept_across_restarts(self):
        self.power.records = [record(1, "12")]
        self.check()
        restored = BotState.from_dict(self.state.to_dict())
        self.assertEqual(restored.subs["7"].em_sent, self.state.subs["7"].em_sent)
        self.assertEqual(restored.subs["7"].em_link, "16|390|17323")
        self.assertEqual(restored.emergency_at, self.state.emergency_at)

    def test_disabled_without_the_service(self):
        bot = Bot(FakeDirectory(), lambda *_: None, self.state)
        self.assertEqual(bot.check_emergencies(self.now), 0)


if __name__ == "__main__":
    unittest.main()
