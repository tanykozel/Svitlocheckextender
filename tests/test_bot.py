import unittest
from datetime import datetime, timedelta

from svitlo_notifier.api import ApiError
from svitlo_notifier.bot import Bot, BotState, Subscription, house_numbers, match, normalize
from svitlo_notifier.schedule import KYIV
from svitlo_notifier.telegram import TelegramError
from tests.test_planner import TODAY


class FakeDirectory:
    def __init__(self):
        self.schedule_calls = []

    def rems(self):
        return [{"id": "16", "name": "Звягельський"}, {"id": "7", "name": "Житомирський"}]

    def cities(self, rem_id):
        return [{"id": "16823", "name": "м. Звягель", "rem_id": rem_id},
                {"id": "17012", "name": "с. Сусли", "rem_id": rem_id},
                {"id": "16951", "name": "с. Мокляки", "rem_id": rem_id},
                {"id": "17028", "name": "с. Хутір-Мокляки", "rem_id": rem_id}]

    def streets(self, city_id):
        if city_id == "16823":  # a big town: more streets than fit as buttons
            return [{"id": str(i), "name": f"вул. Вулиця {i}"} for i in range(40)] + [
                {"id": "500", "name": "вул. Центральна"}]
        return [{"id": "179892", "name": "вул. Центральна"}, {"id": "179889", "name": "вул. Садова"}]

    def addresses(self, street_id):
        if street_id == "179889":  # whole street in one queue
            return [{"id": "1", "name": "1 - побутові споживачі, 3 - побутові споживачі",
                     "cherga": 2, "pidcherga": 2}]
        return [{"id": "1", "name": "10 - побутові споживачі, 12А - побутові споживачі", "cherga": 3, "pidcherga": 1},
                {"id": "2", "name": "14 - побутові споживачі", "cherga": 5, "pidcherga": 2}]

    def schedule(self, queue, subqueue):
        self.schedule_calls.append((queue, subqueue))
        return TODAY


class BotTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.state = BotState()
        self.dir = FakeDirectory()
        self.bot = Bot(self.dir, lambda chat, text, buttons: self.sent.append((chat, text, buttons)), self.state)

    def last(self):
        return self.sent[-1]

    def updates(self, *items):
        out = []
        for i, item in enumerate(items, start=100 + len(self.sent)):
            if item.startswith("btn:"):
                out.append({"update_id": i, "callback_query": {
                    "id": f"q{i}", "data": item[4:], "message": {"chat": {"id": 42}}}})
            else:
                out.append({"update_id": i, "message": {"chat": {"id": 42}, "text": item}})
        return out

    def test_full_quiz_with_typed_village_street_and_house(self):
        self.bot.process_updates(self.updates("/start"))
        chat, text, buttons = self.last()
        self.assertEqual(chat, 42)
        self.assertIn("1/4", text)
        self.assertIn(("Звягельський", "r:16"), [b for row in buttons for b in row])

        self.bot.process_updates(self.updates("btn:r:16"))
        _, text, buttons = self.last()
        self.assertIn("2/4", text)
        labels = [b[0] for row in buttons for b in row]
        self.assertEqual(labels, ["м. Звягель"], "only towns are offered as buttons, villages are typed")

        self.bot.process_updates(self.updates("сусли"))
        _, text, buttons = self.last()
        self.assertIn("3/4. с. Сусли", text)
        self.assertEqual(len(buttons), 1)

        self.bot.process_updates(self.updates("btn:s:179892"))
        self.assertIn("4/4", self.last()[1])

        last_update = self.updates("12а")
        self.bot.process_updates(last_update)
        _, text, _ = self.last()
        self.assertIn("✅", text)
        self.assertIn("черга 3.1", text)
        sub = self.state.subs["42"]
        self.assertEqual((sub.queue, sub.subqueue, sub.label), (3, 1, "с. Сусли, вул. Центральна 12а"))
        self.assertNotIn("42", self.state.sessions)
        self.assertEqual(self.state.offset, last_update[-1]["update_id"] + 1, "offset confirms handled updates")

    def test_street_with_one_queue_skips_house_question(self):
        self.bot.process_updates(self.updates("/start", "btn:r:16", "Сусли", "btn:s:179889"))
        self.assertIn("черга 2.2", self.last()[1])

    def test_big_town_asks_to_type_street(self):
        self.bot.process_updates(self.updates("/start", "btn:r:16", "btn:c:16823"))
        self.assertIn("напиши назву вулиці", self.last()[1])
        self.bot.process_updates(self.updates("Центральна"))
        self.assertIn("4/4", self.last()[1])

    def test_ambiguous_and_unknown_answers(self):
        self.bot.process_updates(self.updates("/start", "btn:r:16", "мокл"))
        _, text, buttons = self.last()
        self.assertIn("кілька варіантів", text)
        self.assertEqual([b[1] for row in buttons for b in row], ["c:16951", "c:17028"])
        self.bot.process_updates(self.updates("btn:c:17028"))
        self.assertIn("3/4. с. Хутір-Мокляки", self.last()[1], "name remembered for the tapped option")
        self.bot.process_updates(self.updates("/start", "btn:r:16", "Атлантида"))
        self.assertIn("Не знайшла", self.last()[1])

    def test_exact_name_beats_partial(self):
        found = match(FakeDirectory().cities("16"), "Мокляки")
        self.assertEqual([c["id"] for c in found], ["16951"])

    def test_unknown_house_and_stop(self):
        self.bot.process_updates(self.updates("/start", "btn:r:16", "Сусли", "btn:s:179892", "99"))
        self.assertIn("Не знайшла будинок", self.last()[1])
        self.bot.process_updates(self.updates("10"))
        self.assertIn("42", self.state.subs)
        self.bot.process_updates(self.updates("/stop"))
        self.assertNotIn("42", self.state.subs)

    def test_api_failure_tells_user_and_continues(self):
        def broken(_rem):
            raise ApiError("down")
        self.dir.cities = broken
        self.bot.process_updates(self.updates("/start", "btn:r:16"))
        self.assertIn("щось пішло не так", self.last()[1])
        self.assertIsNotNone(self.state.offset)

    def test_alerts_fetch_each_queue_once_and_drop_blocked_chats(self):
        self.state.subs = {"1": Subscription(3, 1, "A"), "2": Subscription(3, 1, "B"),
                           "3": Subscription(3, 1, "C")}
        sends = []

        def send(chat, text, _buttons):
            if chat == 3:
                raise TelegramError("sendMessage rejected: Forbidden: bot was blocked by the user")
            sends.append((chat, text))

        bot = Bot(self.dir, send, self.state)
        now = datetime(2026, 10, 13, 7, 40, tzinfo=KYIV)
        sent = bot.send_alerts(now, is_gone=lambda e: "blocked" in str(e))
        self.assertEqual(sent, 2)
        self.assertEqual(self.dir.schedule_calls, [(3, 1)])
        self.assertEqual([c for c, _ in sends], [1, 2])
        self.assertTrue(sends[0][1].startswith("[A] 🔴"))
        self.assertNotIn("3", self.state.subs)
        self.assertEqual(bot.send_alerts(now), 0, "no duplicates on the next tick")

    def test_state_round_trip(self):
        self.bot.process_updates(self.updates("/start", "btn:r:16", "Сусли", "btn:s:179889"))
        restored = BotState.from_dict(self.state.to_dict())
        self.assertEqual(restored.subs["42"].queue, 2)
        self.assertEqual(restored.offset, self.state.offset)


class AddressAndSettingsTests(BotTests.__base__):
    """US-8 one address / change it, US-9 warning time, US-10 schedule view."""

    def setUp(self):
        self.sent = []
        self.state = BotState()
        self.dir = FakeDirectory()
        self.bot = Bot(self.dir, lambda chat, text, buttons: self.sent.append((chat, text, buttons)), self.state)
        self.n = 0

    def say(self, *items):
        out = []
        for item in items:
            self.n += 1
            if item.startswith("btn:"):
                out.append({"update_id": self.n, "callback_query": {
                    "id": str(self.n), "data": item[4:], "message": {"chat": {"id": 7}}}})
            else:
                out.append({"update_id": self.n, "message": {"chat": {"id": 7}, "text": item}})
        self.bot.process_updates(out)
        return self.sent[-1]

    def subscribe_sadova(self):
        return self.say("/start", "btn:r:16", "Сусли", "btn:s:179889")

    def test_start_when_subscribed_offers_change_or_keep(self):
        self.subscribe_sadova()
        _, text, buttons = self.say("/start")
        self.assertIn("Твоя адреса: с. Сусли, вул. Садова (черга 2.2)", text)
        self.assertIn("лише за однією адресою", text)
        self.assertEqual(buttons, [[("Змінити адресу", "a:change"), ("Залишити", "a:keep")]])
        self.assertIn("залишаю", self.say("btn:a:keep")[1])
        self.assertEqual(self.state.subs["7"].queue, 2)

    def test_change_address_replaces_old_one_and_keeps_lead(self):
        self.subscribe_sadova()
        self.say("/settings", "btn:l:60")
        self.state.subs["7"].alerts.sent["off@x"] = "2026-10-13T08:00:00+03:00"
        self.say("/change", "btn:r:16", "Сусли", "btn:s:179892")
        _, text, _ = self.say("14")
        self.assertIn("✅ Адресу змінено", text)
        self.assertEqual(len(self.state.subs), 1)
        sub = self.state.subs["7"]
        self.assertEqual((sub.queue, sub.subqueue, sub.lead_minutes), (5, 2, 60))
        self.assertEqual(sub.alerts.sent, {}, "alert history restarts for the new queue")

    def test_settings_lead_time_changes_when_alerts_fire(self):
        self.subscribe_sadova()
        _, text, buttons = self.say("/settings")
        self.assertIn("Зараз: 30 хв", text)
        self.assertEqual([b[1] for b in buttons[0]], ["l:15", "l:30", "l:60"])
        self.assertTrue(buttons[0][1][0].startswith("✓"))
        self.assertIn("за 60 хв", self.say("btn:l:60")[1])

        sent = []
        bot = Bot(self.dir, lambda chat, text, _b: sent.append(text), self.state)
        bot.send_alerts(datetime(2026, 10, 13, 7, 10, tzinfo=KYIV))  # 50 min before the 08:00 outage
        self.assertEqual(len(sent), 1)
        self.assertIn("За ~50 хв", sent[0])

    def test_unknown_lead_value_is_ignored(self):
        self.subscribe_sadova()
        self.say("btn:l:999")
        self.assertEqual(self.state.subs["7"].lead_minutes, 30)

    def test_schedule_command(self):
        self.assertIn("Спершу обери адресу", self.say("/schedule")[1])
        self.subscribe_sadova()
        _, text, _ = self.say("/schedule")
        self.assertIn("черга 2.2", text)
        self.assertIn("https://www.ztoe.com.ua/unhooking-search.php", text)


class HelperTests(unittest.TestCase):
    def test_normalize_and_house_numbers(self):
        self.assertEqual(normalize("  вул.  Кам’яна "), "кам'яна")
        self.assertEqual(normalize("с. Сусли"), "сусли")
        self.assertEqual(house_numbers("25 - побутові споживачі, 27А - побутові споживачі"), ["25", "27а"])
        self.assertEqual(house_numbers("5/1"), ["5/1"])


if __name__ == "__main__":
    unittest.main()


class QueueChangeTests(unittest.TestCase):
    """US-11: ZTOE moves an address to another queue -> the bot follows and tells the user."""

    def setUp(self):
        self.sent = []
        self.state = BotState()
        self.dir = FakeDirectory()
        self.calls = []
        original = self.dir.addresses
        self.rows = {"179892": original("179892"), "179889": original("179889")}
        self.dir.addresses = lambda street: (self.calls.append(street), self.rows[street])[1]
        self.bot = Bot(self.dir, lambda chat, text, buttons: self.sent.append((chat, text)), self.state)
        self.t0 = datetime(2026, 10, 13, 9, 0, tzinfo=KYIV)

    def sub(self, chat, street, house, queue=(3, 1)):
        s = Subscription(*queue, f"Сусли {chat}", street_id=street, house=house,
                         checked_at=self.t0.isoformat())
        s.alerts.sent["off@x"] = "2026-10-13T08:00:00+03:00"
        self.state.subs[str(chat)] = s
        return s

    def test_queue_moved_is_followed_and_reported_once(self):
        sub = self.sub(1, "179892", "12а")
        self.rows["179892"] = [{"id": "1", "name": "10 - побутові споживачі, 12А - побутові споживачі",
                                "cherga": 4, "pidcherga": 2}]
        self.assertEqual(self.bot.refresh_queues(self.t0 + timedelta(hours=7)), 1)
        self.assertEqual((sub.queue, sub.subqueue), (4, 2))
        self.assertEqual(sub.alerts.sent, {})
        self.assertIn("було 3.1, тепер 4.2", self.sent[-1][1])
        self.assertEqual(self.bot.refresh_queues(self.t0 + timedelta(hours=14)), 0)
        self.assertEqual(len(self.sent), 1, "no repeat message when nothing changed")

    def test_checked_at_most_every_6_hours_and_once_per_street(self):
        self.sub(1, "179892", "12а")
        self.sub(2, "179892", "14", queue=(5, 2))
        self.bot.refresh_queues(self.t0 + timedelta(hours=1))
        self.assertEqual(self.calls, [], "too soon to re-check")
        self.bot.refresh_queues(self.t0 + timedelta(hours=6))
        self.assertEqual(self.calls, ["179892"], "one request serves both subscribers")
        self.assertEqual(self.sent, [])

    def test_missing_house_and_split_street_warn_once_and_keep_old_queue(self):
        house_sub = self.sub(1, "179892", "12а")
        street_sub = self.sub(2, "179889", "", queue=(2, 2))
        self.rows["179892"] = [{"id": "1", "name": "10 - побутові споживачі", "cherga": 3, "pidcherga": 1}]
        self.rows["179889"] = [{"id": "1", "name": "1", "cherga": 2, "pidcherga": 2},
                               {"id": "2", "name": "3", "cherga": 6, "pidcherga": 1}]
        self.bot.refresh_queues(self.t0 + timedelta(hours=7))
        texts = dict(self.sent)
        self.assertIn("Не можу знайти твою адресу", texts[1])
        self.assertIn("кілька різних черг", texts[2])
        self.assertEqual((house_sub.queue, street_sub.queue), (3, 2), "keep alerting on the last known queue")
        self.bot.refresh_queues(self.t0 + timedelta(hours=14))
        self.assertEqual(len(self.sent), 2, "each problem is reported only once")

    def test_owner_subscription_without_street_is_not_rechecked(self):
        self.state.subs["9"] = Subscription(3, 1, "owner")
        self.bot.refresh_queues(self.t0 + timedelta(days=1))
        self.assertEqual(self.calls, [])

    def test_api_error_retries_next_tick(self):
        sub = self.sub(1, "179892", "12а")

        def down(_street):
            raise ApiError("down")
        self.dir.addresses = down
        self.bot.refresh_queues(self.t0 + timedelta(hours=7))
        self.assertEqual(sub.checked_at, self.t0.isoformat())

    def test_quiz_stores_where_the_queue_came_from(self):
        bot = Bot(FakeDirectory(), lambda *_: None, self.state)
        bot.process_updates([{"update_id": 1, "message": {"chat": {"id": 5}, "text": "/start"}},
                             {"update_id": 2, "callback_query": {"id": "a", "data": "r:16",
                                                                 "message": {"chat": {"id": 5}}}},
                             {"update_id": 3, "message": {"chat": {"id": 5}, "text": "Сусли"}},
                             {"update_id": 4, "callback_query": {"id": "b", "data": "s:179892",
                                                                 "message": {"chat": {"id": 5}}}},
                             {"update_id": 5, "message": {"chat": {"id": 5}, "text": "12 А"}}])
        sub = self.state.subs["5"]
        self.assertEqual((sub.street_id, sub.house, sub.queue), ("179892", "12а", 3))
        restored = BotState.from_dict(self.state.to_dict()).subs["5"]
        self.assertEqual((restored.street_id, restored.house), ("179892", "12а"))


class LatestRequestWinsTests(unittest.TestCase):
    """US-12: repeated taps between runs -> only the most recent request is answered."""

    def setUp(self):
        self.sent = []
        self.removed = []
        self.state = BotState()
        self.ids = iter(range(1000, 2000))

        def send(chat, text, buttons):
            self.sent.append((chat, text, buttons))
            return next(self.ids)

        self.bot = Bot(FakeDirectory(), send, self.state, unbutton=lambda c, m: self.removed.append((c, m)))
        self.n = 0

    def batch(self, *items, chat=42):
        out = []
        for item in items:
            self.n += 1
            if item.startswith("btn:"):
                out.append({"update_id": self.n, "callback_query": {
                    "id": str(self.n), "data": item[4:], "message": {"chat": {"id": chat}}}})
            else:
                out.append({"update_id": self.n, "message": {"chat": {"id": chat}, "text": item}})
        return out

    def test_three_starts_and_a_tap_give_one_answer_per_step(self):
        answered = []
        self.bot.process_updates(self.batch("/start", "/start", "/start", "btn:r:16"), answer=answered.append)
        texts = [t for _, t, _ in self.sent]
        self.assertEqual(sum("1/4" in t for t in texts), 1, "one district list, not three")
        self.assertIn("2/4", texts[-1])
        self.assertEqual(answered, ["4"], "the tap's spinner is stopped")
        self.assertEqual(self.state.offset, 5)

    def test_two_district_taps_follow_the_last_one(self):
        self.bot.process_updates(self.batch("/start"))
        self.bot.process_updates(self.batch("btn:r:7", "btn:r:16"))
        self.assertEqual(sum("2/4" in t for _, t, _ in self.sent), 1)
        self.assertEqual(self.state.sessions["42"]["rem"], "16")

    def test_start_over_drops_everything_before_it(self):
        self.bot.process_updates(self.batch("/start", "btn:r:16", "сусли", "/start"))
        texts = [t for _, t, _ in self.sent]
        self.assertEqual(len(texts), 2, "greeting + one district list only")
        self.assertIn("1/4", texts[-1])
        self.assertEqual(self.state.sessions["42"], {"step": "rem"})

    def test_typed_answers_are_not_merged(self):
        self.bot.process_updates(self.batch("/start", "btn:r:16", "атлантида", "сусли"))
        self.assertIn("3/4. с. Сусли", self.sent[-1][1])

    def test_other_chats_are_not_affected(self):
        updates = self.batch("/start", chat=1) + self.batch("/start", chat=2)
        self.bot.process_updates(updates)
        self.assertEqual({c for c, t, _ in self.sent if "1/4" in t}, {1, 2})

    def test_old_buttons_are_removed_when_new_ones_arrive(self):
        self.bot.process_updates(self.batch("/start"))
        first_keyboard = self.state.keyboards["42"]
        self.bot.process_updates(self.batch("btn:r:16"))
        self.assertEqual(self.removed, [(42, first_keyboard)])
        self.assertNotEqual(self.state.keyboards["42"], first_keyboard)
        restored = BotState.from_dict(self.state.to_dict())
        self.assertEqual(restored.keyboards, self.state.keyboards)


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.state = BotState()
        self.bot = Bot(FakeDirectory(), lambda chat, text, buttons: self.sent.append(text), self.state)

    def test_test_command_sends_every_alert_type_marked_as_test(self):
        self.state.subs["1"] = Subscription(3, 1, "с. Сусли, вул. Садова", lead_minutes=60)
        self.bot.handle_text(1, "/test")
        intro, *samples = self.sent
        self.assertIn("4 приклади", intro)
        self.assertIn("за 60 хв", intro)
        self.assertEqual(len(samples), 4)
        self.assertTrue(all(t.startswith("🧪 ТЕСТ") for t in samples))
        self.assertIn("🔴 За ~60 хв", samples[0])
        self.assertIn("Без світла ~", samples[0])
        self.assertIn("🟢 Я повертаюся! За ~60 хв", samples[1])
        self.assertIn("📅 Графік на", samples[2])
        self.assertIn("було 3.1, тепер X.Y", samples[3])
        self.assertEqual(self.state.subs["1"].alerts.sent, {}, "a test never marks real alerts as sent")

    def test_test_command_needs_an_address(self):
        self.bot.handle_text(1, "/test")
        self.assertIn("Спершу обери адресу", self.sent[-1])


class MenuTests(unittest.TestCase):
    def test_test_command_is_hidden_from_menu_and_help_but_still_works(self):
        from svitlo_notifier.bot import HELP, MENU
        self.assertNotIn("test", [command for command, _ in MENU])
        self.assertNotIn("/test", HELP)
        sent = []
        state = BotState(subs={"1": Subscription(3, 1, "A")})
        Bot(FakeDirectory(), lambda chat, text, buttons: sent.append(text), state).handle_text(1, "/test")
        self.assertTrue(any(t.startswith("🧪 ТЕСТ") for t in sent))


class BotNameTests(unittest.TestCase):
    """Renaming the bot (@svitlo_dim_tk_bot -> @svitlo_lusia_zt_bot) must not change behaviour."""

    def test_commands_work_with_any_bot_name_suffix(self):
        from svitlo_notifier.bot import latest_requests
        for text in ("/start", "/start@svitlo_lusia_zt_bot", "/start@svitlo_dim_tk_bot", "/START@Svitlo_Lusia_ZT_bot"):
            sent = []
            Bot(FakeDirectory(), lambda chat, t, b: sent.append(t), BotState()).handle_text(1, text)
            self.assertTrue(any("1/4" in t for t in sent), text)
        updates = [{"update_id": 1, "message": {"chat": {"id": 1}, "text": "/start@svitlo_lusia_zt_bot"}},
                   {"update_id": 2, "message": {"chat": {"id": 1}, "text": "/start"}}]
        self.assertEqual(len(latest_requests(updates)), 1, "both spellings count as the same /start")


class NotUnderstoodTests(unittest.TestCase):
    """US-13: anything that isn't a known command or a quiz answer gets one friendly hint."""

    def setUp(self):
        self.sent = []
        self.state = BotState()
        self.bot = Bot(FakeDirectory(), lambda chat, text, buttons: self.sent.append(text), self.state)

    def test_random_text_outside_the_quiz(self):
        self.bot.handle_text(1, "привіт, коли буде світло?")
        self.assertIn("Я тебе не розумію", self.sent[-1])
        self.assertIn("меню", self.sent[-1])

    def test_unknown_command_even_mid_quiz_is_not_taken_as_an_answer(self):
        self.bot.handle_text(1, "/start")
        self.bot.handle_button(1, "r:16")
        self.bot.handle_text(1, "/hello")
        self.assertIn("Я тебе не розумію", self.sent[-1])
        self.assertEqual(self.state.sessions["1"]["step"], "city", "the quiz is still waiting for the village")
        self.bot.handle_text(1, "сусли")
        self.assertIn("3/4", self.sent[-1], "a normal answer still works afterwards")

    def test_typed_quiz_answers_are_still_answers(self):
        self.bot.handle_text(1, "/start")
        self.bot.handle_button(1, "r:16")
        self.bot.handle_text(1, "сусли")
        self.assertNotIn("Я тебе не розумію", self.sent[-1])

    def test_sticker_photo_or_voice_gets_the_hint(self):
        self.bot.process_updates([{"update_id": 1, "message": {"chat": {"id": 9}, "sticker": {"file_id": "x"}}},
                                  {"update_id": 2, "message": {"chat": {"id": 8}, "voice": {"file_id": "y"}}}])
        self.assertEqual([t for t in self.sent if "не розумію" in t].__len__(), 2)


class TypedAddressTests(unittest.TestCase):
    """Every address step accepts typed text; a miss asks to check the spelling."""

    def setUp(self):
        self.sent = []
        self.state = BotState()
        self.bot = Bot(FakeDirectory(), lambda chat, text, buttons: self.sent.append(text), self.state)
        self.bot.handle_text(1, "/start")

    def test_district_can_be_typed(self):
        for typed in ("Звягельський", "звягельський район", "Звягельський РЕМ", "звяг"):
            self.bot.handle_text(1, "/start")
            self.bot.handle_text(1, typed)
            self.assertIn("2/4", self.sent[-1], typed)
            self.assertEqual(self.state.sessions["1"]["rem"], "16")

    def test_each_step_says_check_spelling_when_not_found(self):
        self.bot.handle_text(1, "Атлантидський")
        self.assertIn("Не знайшла такий район", self.sent[-1])
        self.assertIn("Перевір написання", self.sent[-1])
        self.bot.handle_text(1, "Звягельський")
        self.bot.handle_text(1, "Атлантида")
        self.assertIn("Не знайшла такий населений пункт", self.sent[-1])
        self.bot.handle_text(1, "Сусли")
        self.bot.handle_text(1, "Неіснуюча")
        self.assertIn("Не знайшла таку вулицю", self.sent[-1])
        self.bot.handle_text(1, "Центральна")
        self.bot.handle_text(1, "999")
        self.assertIn("Не знайшла будинок «999»", self.sent[-1])
        self.assertNotIn("не розумію", " ".join(self.sent), "address answers are never 'not understood'")
