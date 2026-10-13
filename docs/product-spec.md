# Product spec: advance outage alerts for Svitlochek users

| | |
|---|---|
| Status | v0.1 implemented (MVP); live API not yet verified from a Ukrainian network |
| Owner | Tetiana Kozel |
| Last updated | 2026-10-13 |

## 1. Problem statement

Households in Zhytomyr oblast check the official **Svitlochek** app (Zhytomyroblenergo) to see
their hourly outage schedule. The app shows the schedule **only when opened**. It does not notify
users that power will go off soon or come back, and it does not tell them when the schedule changes.
People therefore miss the window to charge devices, finish a wash or start cooking, and they keep
re-opening the app to check for changes.

**Hypothesis:** if users get a push notification ~30 minutes before each scheduled change, and
whenever the schedule is published or changed, they will stop polling the app manually and
will be ready for each outage more often.

## 2. Users

| Persona | Need |
|---|---|
| Household member (primary) | "Tell me 30 min before light goes off or comes back, without me opening an app." |
| Remote family member | Gets alerts for parents' address without living there (multiple labels/instances). |
| Small business / home office | Plans work around outages; cares about schedule **changes** most. |

## 3. Scope

**In scope (MVP):** one address (queue) per running instance; push via ntfy and/or Telegram;
alerts for off / possible off / on; "schedule published / changed" alerts; address-to-queue lookup;
no ZTOE account.

**In scope (v0.2):** friends subscribe themselves through an address quiz in the shared bot.

**Out of scope (not now):** a mobile app UI; instant (sub-second) bot replies; emergency (unscheduled) outage
detection; other oblenergos; payments or meter readings.

## 4. User stories and acceptance criteria

**US-1 Find my queue**
As a household member, I want to find my черга/підчерга by address so that alerts match my house.
- *Given* I run `lookup` and drill down district → city → street, *when* I list addresses,
  *then* each house shows its queue as `черга X.Y`.

**US-2 Warning before power goes off** (Must)
As a household member, I want a push N minutes before a scheduled outage so that I can prepare.
- *Given* lead = 30 min and an outage at 08:00, *when* the check runs at any time 07:30–07:59,
  *then* one push says power goes off at 08:00 and until when.
- *Given* the alert was already sent, *when* the check runs again, *then* no duplicate is sent.
- *Given* the check runs at 07:00 or after 08:00, *then* no alert for that outage is sent.

**US-3 Warning before power comes back** (Must)
- *Given* an outage ends at 12:00, *when* the check runs 11:30–11:59, *then* one push says power returns at 12:00.

**US-4 Possible outages** (Should)
- *Given* a yellow ("можливе") slot, *then* a 🟡 alert is sent, unless the user set `--no-possible`.
- *Given* outage → possible → available, *then* no "possible off" alert is sent mid-outage.

**US-5 Schedule published or changed** (Should)
- *Given* the first run, *then* the current schedule is stored as a baseline and no alert is sent.
- *Given* tomorrow's schedule appears, *then* one "📅 Графік на DD.MM опубліковано" push lists its outage windows.
- *Given* an existing day's schedule changes, *then* one "змінено" push lists the new windows,
  and upcoming off/on alerts follow the new times.

**US-6 Choose channel** (Must)
- *Given* `NTFY_TOPIC` is set, *then* alerts arrive as phone push via the ntfy app, with no account needed.
- *Given* Telegram bot credentials are set, *then* alerts also arrive in Telegram.
- *Given* neither is set, *then* the run stops with a clear configuration error.

**US-7 Friend joins through an address quiz** (Should, v0.2)
As a friend of the owner, I want to pick my address in the bot so that I get alerts without any setup.
- *Given* I send /start, *then* I get district buttons (step 1/4).
- *Given* I pick a district, *then* towns are offered as buttons and villages can be typed (2/4).
- *Given* I type a name, *then* an exact match is chosen; several partial matches are offered as buttons;
  none means "not found, try again".
- *Given* a street with ≤ 30 options, *then* streets are buttons; otherwise I type it (3/4).
- *Given* the whole street is in one queue, *then* the house question is skipped; otherwise I type the number (4/4).
- *Then* the bot confirms "✅ Готово! <address>: черга X.Y", and I receive alerts for that queue.
- *Given* I send /stop or block the bot, *then* I stop receiving alerts.
- Replies arrive on the next tick (≤ ~10 min). *Given* a lookup error, *then* I'm asked to retry later.

**US-8 One address per person, and changing it** (Must, v0.3)
- *Given* I'm subscribed and send /start, *then* the bot only shows my address and points to «Змінити адресу» in the menu.
  It does **not** ask a question: changing the address is always the user's own choice (changed after live testing, 2026-10-13).
- *Given* I send /change (or tap "Змінити адресу") and finish the quiz, *then* the new address **replaces** the old one
  ("✅ Адресу змінено"), my warning time is kept, and alerts restart for the new queue.
- A chat never has more than one address.

**US-9 Warning time** (Should, v0.3)
- *Given* I send /settings, *then* I can pick 15, 30 or 60 minutes (current one marked ✓). The default is 30.
- *Given* 60 minutes, *then* the outage alert arrives ~50–60 minutes before the change.

**US-10 How long and the full picture** (Must, v0.3)
- *Given* an outage alert, *then* it states the length and end time ("Без світла ~4 год, до 12:00") and links to the
  official schedule.
- *Given* a power-back alert, *then* it names the next outage and how long power stays on, or says none is scheduled.
- *Given* I send /schedule, *then* I see today's and tomorrow's windows with durations, the total hours without power,
  and the official link.
- Schedule published/changed alerts include durations and the total.

**US-11 Address moved to another queue** (Must, v0.3)
As a subscriber, I want the bot to notice when Zhytomyroblenergo moves my address to another queue, so that my
alerts stay correct without me re-subscribing.
- The bot stores *where* my queue came from (street + house), not only the queue number.
- *Given* 6 hours have passed since the last check, *when* the bot ticks, *then* it re-reads my street
  (one request per street, shared by all subscribers on it).
- *Given* my house is now in another queue, *then* the bot switches to it, restarts alert history, and tells me once:
  "⚠️ … було 3.1, тепер 4.2".
- *Given* my house is no longer found, or my street (subscribed without a house) now has several queues, *then* the bot
  keeps the last known queue and tells me once to check the address with /change.
- *Given* ZTOE is unavailable, *then* nothing changes and the check is retried on the next tick.
- Out of scope: the owner's address set through repository variables is not re-checked (use the quiz instead).

**US-12 Most recent request wins** (Must, v0.3; found in live testing 2026-10-13)
As a user who taps again because the bot hasn't answered yet, I want only my latest request handled,
so that the chat isn't flooded with duplicate replies.
- *Given* several requests from me arrived between two runs, *then* everything before my last "start over"
  (/start, /change, /stop, "Змінити адресу") is ignored.
- *Given* back-to-back requests of the same kind (two /start, two district taps), *then* only the last one is answered.
- Typed answers are not merged (a wrong spelling followed by a correction still works).
- *Given* the bot sends new buttons, *then* the buttons on its previous message are removed, so old choices can't be tapped.
- Every tapped button stops loading, even when its request was ignored.

**US-13 Unknown input** (Should, v0.3; requested in live testing)
- *Given* I send text that is neither a known command nor an expected quiz answer, *then* Люся replies:
  «Я тебе не розумію 🙈 Обери команду з меню ☰ (кнопка «Menu» внизу) або надішли /help.»
- *Given* I'm in the middle of the quiz and send an unknown /command, *then* I get the same hint and the quiz keeps waiting.
- *Given* I send a sticker, photo, voice message or file, *then* I get the same hint instead of silence.
- Typed quiz answers are never treated as "unknown": **every** address step (district, town/village, street,
  house) accepts typed text as well as buttons. A miss replies «Не знайшла такий район / населений пункт /
  таку вулицю / будинок … 🤔 Перевір написання і спробуй ще раз.» and the step keeps waiting.
- District can be typed with or without «район», «р-н» or «РЕМ».

## 4a. Voice & tone: persona «Лампочка Люся 💡» (decided 2026-10-13)

| Rule | Example |
|---|---|
| Люся speaks in the first person, as the light itself (feminine forms) | «мене вимкнуть», «знайшла», «я повертаюся» |
| Informal «ти», but never assumes the user's gender | «Адресу ще не обрано» rather than «ти не обрав/обрала» |
| Facts first (time, duration), warmth after | «За ~30 хв, о 14:00, мене вимкнуть 😔 Без світла ~4 год…» |
| Caring, never sarcastic: outages are stressful | «Заряди телефон і павербанк 🔋» |
| Honest about limits | No promises about emergency outages; the source (Житомиробленерго) is always named |
| 1–2 emoji per message, meaningful ones | 🔴 off, 🟢 on, 🟡 possible, 📅 schedule, ⚠️ change |

Display name: «Світло Житомир 💡 Графік відключень» (keywords for search); username @svitlo_lusia_zt_bot. The persona introduces herself inside the chat. Avatar: `assets/lyusya-avatar.png`.

## 5. Non-functional requirements

**Check and notification cadence (decided):**

| Item | Value |
|---|---|
| Schedule check / bot tick | every 10 min (GitHub Actions cron; GitHub may start runs a few minutes late) |
| Warning before off/on | user choice 15 / **30** / 60 min |
| "Schedule published/changed" alert | on the next tick after ZTOE updates (≤ ~10 min) |
| Bot reply to a message or tap | on the next tick (≤ ~10 min) |
| Duplicates | at most one alert per change per user |
| Address → queue re-check | every 6 h per subscriber (US-11) |


- Timezone: all times are Europe/Kyiv, regardless of where the job runs.
- Runs unattended every 5–10 min; one run takes < 5 s; standard library only.
- Secrets (bot token, topic) live in env vars / repository secrets, never in code or logs.
- Polite to ZTOE: 1 request per run, identifying User-Agent.

## 6. Success metrics

- ≥ 95% of scheduled transitions produce an alert at least 15 minutes before the change.
- 0 duplicate alerts per transition.
- Qualitative: the user no longer opens Svitlochek just to check for changes.

## 7. Risks, assumptions, open questions

| # | Item | Type | Mitigation / next step |
|---|---|---|---|
| R1 | ZTOE endpoints are undocumented and may change | Risk | Isolated in `api.py`; contract taken from SvitloYE (MIT). Ask ZTOE about an official feed. |
| R2 | Live API not yet tested: the build environment cannot reach ztoe.com.ua | Risk | First run `status` from a Ukrainian network and compare with Svitlochek. |
| R3 | ztoe.com.ua may block non-Ukrainian IPs (GitHub Actions) | Risk | Run on a home PC / Raspberry Pi / UA VPS. |
| R4 | GitHub scheduled runs can be delayed | Risk | Lead ≥ 30 min; state ensures late runs still alert once. |
| R5 | Emergency outages are not in the schedule | Limitation | Out of scope. A future option is a "power sensor" approach like SvitloBot. |
| A1 | Slot colours: red = outage, yellow = possible, white/green = power | Assumption | Verify against the live API (R2). |
| Q1 | Is bezsvitla.com.ua a better or extra source? | Open | Third-party aggregator; could not be reviewed from the build environment. Keep ZTOE as the primary source. |
| D1 | Final bot: @svitlo_lusia_zt_bot (decided 2026-10-13). Switching tokens keeps subscriptions | Decision | Bot change is detected automatically (message counter + menu reset). |
| Q2 | Several addresses per person (home + parents)? | Open | v0.3 candidate. |
| R6 | Private repo: ~4,300 Actions min/month vs 2,000 free | Risk | Make the repo public (code has no secrets), or move the bot to an always-on free host. |
| R8 | Public repo: logs are public and fork PRs could read the cache | Mitigated | State encrypted with SVITLO_STATE_KEY; chat ids never logged; fork PR workflows need owner approval. |
| R7 | Subscribers live in the Actions cache (evicted after 7 days unused) | Risk | Acceptable for a few friends. Move to a durable store if usage grows. |
| R5b | Live API verified from GitHub runners on 2026-10-13 (districts, villages, streets) | Resolved | R2/R3 closed. |
