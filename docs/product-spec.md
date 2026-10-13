# Product spec: «Лампочка Люся 💡», advance outage alerts for Zhytomyr oblast

| | |
|---|---|
| Product | Telegram bot, display name «Світло Житомир 💡 Графік відключень»; target username **@svitlo_lusia_zt_bot** |
| Status | **v0.3 live** (GitHub Actions, public repo). Real-scenario UAT on 2026-10-13. v0.4 (Cloudflare) planned. |
| Owner | Tetiana Kozel |
| How it was built | Product decisions, requirements and testing by the owner; design and code produced with an AI assistant (Claude Code) |
| Last updated | 2026-10-13 |

## 1. Problem statement
Households in Zhytomyr oblast check the official **Svitlochek** app (Zhytomyroblenergo) for their hourly outage
schedule. The app shows the schedule **only when opened**. It does not warn that power will go off or come back
soon, and it doesn't say when the schedule changes. People miss the window to charge devices, finish a wash or
start cooking, and keep re-opening the app.

**Hypothesis:** if users get a push alert before each scheduled change (with how long it lasts), and whenever
the schedule is published or changed, they will stop checking the app manually and be ready more often.

## 2. Users
| Persona | Need |
|---|---|
| Household member (primary) | "Warn me before the light goes off or comes back, without opening an app." |
| Friend / neighbour of the owner | Joins through a shared link, with no setup and no registration. |
| Remote family member | Watches parents' address. *(Today: one address per person; see Q2.)* |
| Small business / home office | Plans work around outages; cares most about schedule **changes**. |

## 3. Scope
| Version | In scope |
|---|---|
| v0.1 MVP | One queue per instance; alerts off / possible off / on; schedule published/changed; ntfy and/or Telegram; queue lookup |
| v0.2 | Shared bot: friends subscribe themselves through an address quiz |
| v0.3 (current) | One address per person + change; warning time 15/30/60; outage length and `/schedule`; queue-move detection; most-recent-request-wins; unknown-input reply; typed answers at every step; persona Люся; encryption; bot-switch safety |
| v0.4 (next) | Move to Cloudflare Workers: instant replies, punctual alerts, durable storage (see section 8) |

**Out of scope (now):** mobile app UI; emergency (unscheduled) outage detection; other oblenergos; meter readings
or payments; several addresses per person (Q2).

## 4. User stories and acceptance criteria

**US-1 Find my queue** (Must). As a household member, I want to find my черга/підчерга by address so that alerts match my house.
- *Given* I drill down district → city → street (CLI `lookup` or Actions → Find my queue), *then* each house shows `черга X.Y`.

**US-2 Warning before power goes off** (Must)
- *Given* a 30-minute warning and an outage at 20:00, *when* a check runs at 19:30–19:59, *then* one alert says
  «🔴 За ~N хв, о 20:00, мене вимкнуть 😔 Без світла ~2 год, до 22:00 (за графіком).»
- *Given* the alert was already sent, *then* no duplicate. *Given* the check runs before 19:30 or after 20:00, *then* no alert.

**US-3 Warning before power comes back** (Must)
- *Given* an outage ends at 22:00, *when* a check runs 21:30–21:59, *then* one alert says «🟢 Я повертаюся! … о 22:00 …».

**US-4 Possible outages** (Should)
- *Given* a yellow slot, *then* a 🟡 alert is sent (CLI: unless `--no-possible`).
- *Given* outage → possible → available, *then* no "possible" alert is sent in the middle of an outage.

**US-5 Schedule published or changed** (Should)
- *Given* the first run, *then* the schedule is stored as a baseline and no alert is sent.
- *Given* tomorrow's schedule appears, *then* one «📅 З'явився графік на DD.MM:» alert lists windows, durations and the total.
- *Given* a day's schedule changes, *then* one «📅 Графік на DD.MM змінився:» alert, and upcoming alerts follow the new times.

**US-6 Delivery channels** (Must)
- The shared bot delivers via Telegram. The CLI `check` can also deliver via ntfy (no account); with neither configured it stops with a clear error.

**US-7 Join through the address quiz** (Must)
As a friend of the owner, I want to pick my address in the bot so that I get alerts without any setup.
- *Given* /start (Menu → «Обрати адресу») and no subscription, *then* Люся greets me and shows district buttons (1/4).
- Every step (district, town/village, street, house) accepts **buttons or typed text**. Districts may be typed with or
  without «район», «р-н» or «РЕМ». Towns are offered as buttons; villages are typed.
- An exact name wins; several partial matches are offered as buttons; too many asks to be more specific.
- *Given* a typed answer that isn't found, *then* «Не знайшла такий район / населений пункт / таку вулицю / будинок …
  🤔 Перевір написання і спробуй ще раз.», and the step keeps waiting.
- *Given* the whole street is one queue, *then* the house question is skipped.
- *Then* «✅ Готово! <address>: черга X.Y. Тепер я попереджатиму тебе за 30 хв…».
- *Given* /stop or blocking the bot, *then* alerts stop. *Given* a lookup error, *then* «Ой, щось пішло не так… Спробуй /start трохи пізніше.»

**US-8 One address per person, and changing it** (Must)
- *Given* I'm subscribed and send /start, *then* Люся **only** reminds me: «Я вже стежу за твоєю адресою: … (черга X.Y) 💡
  Щоб змінити її, обери «Змінити адресу» в меню ☰.» There's **no question and no buttons**; changing the address is the
  user's own choice. *(Changed after live testing; older Змінити/Залишити buttons are removed.)*
- *Given* /change (Menu → «Змінити адресу») and a finished quiz, *then* the new address **replaces** the old one
  («✅ Адресу змінено»), the warning time is kept, and alert history restarts for the new queue.

**US-9 Warning time** (Should)
- /settings offers 15 / 30 / 60 minutes (current one ✓; default 30). With 60, the alert arrives ~50–60 minutes before.

**US-10 How long, and the full picture** (Must)
- Off alerts state the length and end time and link to the official schedule.
- Power-back alerts name the next outage («Наступного разу мене вимкнуть завтра о 06:00 - світло буде ~8 год.») or say there's none.
- /schedule shows today and tomorrow: windows with durations, «Разом без світла», and the official link.

**US-11 Address moved to another queue** (Must)
- The bot stores where the queue came from (street + house) and re-reads each street at most every 6 h (one request per street).
- *Given* the house moved to another queue, *then* the bot switches and says once «⚠️ … було 3.1, тепер 4.2.»
- *Given* the house is gone, or the street splits into several queues, *then* it keeps the last queue and asks once to check via /change.
- *Given* ZTOE is down, *then* nothing changes and it retries on the next tick. (Owner variables are not re-checked.)

**US-12 Most recent request wins** (Must; found in live testing)
- Of the requests that arrive between two runs, everything before the last "start over" (/start, /change, /stop) is dropped;
  back-to-back requests of the same kind keep only the last. Typed answers are never merged.
- New buttons remove the previous message's buttons; every tapped button stops loading.

**US-13 Unknown input** (Should; requested in live testing)
- Text that is neither a command nor an expected quiz answer, any unknown /command (even mid-quiz), and stickers, photos,
  voice or files: «Я тебе не розумію 🙈 Обери команду з меню ☰ (кнопка «Menu» внизу) або надішли /help.»
- *Given* /start arrives together with random text, *then* each gets its own reply.

**US-14 Honest status** (Must)
- /status (Menu → «Стан за графіком») says «Зараз за графіком: …» and «(Аварійні відключення я не бачу - лише графік.)».

**US-15 Owner tools** (Should)
- Hidden `/test`: one example of each alert for my address, marked «🧪 ТЕСТ», never marking real alerts as sent.
- Run workflow with *stay_minutes* (≤ 30): ~1-second replies, and alerts checked every minute during the session.
- Bot switch: a new token is detected automatically; message counter and menu reset, subscriptions kept.

**US-16 Owner dashboard** (Should)
*As the owner, I want one page with subscribers, system health and schedule-change context, so that I can see growth, notice failures and fix them, and understand how volatile the schedule is.*
- **Subscribers:** active count, change in 7 days, joined / left, people mid-quiz, a trend line, a split by queue and by warning time.
- **Health:** bot status (running / late / failed), number of runs and failed runs, failures by type, each with a plain "what to do" hint, links to the logs of failed runs, minutes between runs against the 10-minute target (R4), and requests by type.
- **Context:** schedule days *published* and *changed* per day and per week across all 12 queues, the hour of day when changes happen, and changes by queue.
- **Warning before a change:** for each change, how long before the first edited half-hour it came (after the fact / < 1 h / 1–3 h / 3–6 h / 6–12 h / > 12 h), the median, the share of last-minute changes, and how much outage changes added or removed. Also how long before midnight the next day's schedule appears. *Why:* it shows how much notice people really get from ZTOE, which is the core reason Люся exists.
- **Privacy:** only aggregate numbers are published (the `metrics` branch of a public repo). Chat ids, names and addresses never appear; a test checks this.
- A failed or crashed run is still recorded, so it shows up on the dashboard. Every chart has a table view and supports dark mode.

## 4a. Voice & tone: persona «Лампочка Люся 💡»
| Rule | Example |
|---|---|
| Speaks in the first person, as the light itself (feminine forms) | «мене вимкнуть», «знайшла», «я повертаюся» |
| Informal «ти», but never assumes the user's gender | «Адресу ще не обрано» rather than «ти не обрав/обрала» |
| Facts first (time, duration), warmth after | «За ~30 хв, о 20:00, мене вимкнуть 😔 Без світла ~2 год…» |
| Caring, never sarcastic: outages are stressful | «Заряди телефон і павербанк 🔋» |
| Honest about limits | No promises about emergency outages; the source (Житомиробленерго) is always named |
| Natural Ukrainian time phrases | «о 20:00», «завтра о 06:00», «до 02:00 завтра» |
| 1–2 meaningful emoji per message | 🔴 off · 🟢 on · 🟡 possible · 📅 schedule · ⚠️ change · 🧪 test |

**Naming and brand:** a functional display name for search («Світло Житомир 💡 Графік відключень»); the persona
introduces herself inside the chat. Avatars and a 7-sticker set are in `assets/`.

**BotFather texts:**
- About: «Я Люся 💡 Попереджаю про вимкнення і ввімкнення світла на Житомирщині, заздалегідь і з графіком.»
- Description: «Привіт! Я Лампочка Люся 💡 Попереджу тебе: 🔴 за 15, 30 або 60 хв до вимкнення світла і скажу, скільки його
  не буде; 🟢 коли світло повернеться; 📅 якщо графік зміниться. Дані з графіка Житомиробленерго. Без реєстрації: обери
  адресу за 4 кроки. Тисни «Start» 👇»

## 5. Non-functional requirements
| Item | Value |
|---|---|
| Schedule check / bot tick | every 10 min (GitHub cron); in practice GitHub sometimes skips runs for 30+ min (R4) |
| Warning before off/on | user choice 15 / **30** / 60 min |
| Bot reply | next tick (instant during *stay_minutes* sessions; instant for everyone in v0.4) |
| Duplicates | at most one alert per change per user |
| Address → queue re-check | every 6 h per subscriber |

- All times are Europe/Kyiv. One schedule request per distinct queue per run; identifying User-Agent.
- Secrets live only in GitHub secrets. Subscriber data is **encrypted at rest** (`SVITLO_STATE_KEY`, Fernet). Chat ids are never logged.
- Dependencies: Python standard library plus `cryptography` (pinned). Automated tests: 84.

## 6. Success metrics
- ≥ 95% of scheduled changes produce an alert at least 15 minutes before the change.
- 0 duplicate alerts per change.
- Qualitative: users stop opening Svitlochek just to check for changes; friends recommend the bot.

## 7. Risks, assumptions, decisions
| # | Item | Status | Mitigation / note |
|---|---|---|---|
| R1 | ZTOE endpoints are undocumented and may change | Open | Isolated in `api.py`; contract from SvitloYE (MIT). Ask ZTOE about an official feed. |
| R2/R3 | Live API reachable from GitHub runners | **Resolved** | Verified 2026-10-13: districts, villages, streets and the live schedule for queue 1.2. |
| R4 | GitHub's scheduler is best-effort: runs skipped for 30–45+ min | **Open (high)** | Short term: *stay_minutes* sessions and an external trigger (cron-job.org, $0). Long term: v0.4 Cloudflare. |
| R5 | Emergency outages are not in the schedule | Limitation | Stated honestly in /help and /status. A home "power sensor" (SvitloBot-style) is a future epic. |
| R6 | Private repo would exceed free Actions minutes | **Resolved** | Repository made public (no secrets in code or history). |
| R7 | Subscribers live in the Actions cache (evicted after 7 days unused) | Open (low) | Fine while the bot runs; v0.4 moves to durable storage. |
| R8 | Public repo: logs public; fork PRs could read the cache | **Mitigated** | Encryption, no chat ids in logs, approval required for outside PR workflows. |
| A1 | Slot colours: red = outage, yellow = possible, white/green = power | Partly verified | Live data shows white/red as expected; yellow not yet seen. |
| D1 | Final username @svitlo_lusia_zt_bot | Decided, **switch pending** | The running token still belongs to the first bot (renamed). Switching = put the new bot's token in `TELEGRAM_BOT_TOKEN`; subscriptions are kept automatically. |
| D2 | Persona «Лампочка Люся» with a functional display name | Decided | Section 4a. |
| D3 | /start never asks to change the address | Decided | Change only via the menu (US-8). |
| Q1 | bezsvitla.com.ua as an extra source? | Open | Third-party aggregator; ZTOE stays primary. |
| Q2 | Several addresses per person (home + parents)? | Open | Candidate after v0.4. |

## 8. Roadmap
| When | Item |
|---|---|
| Now | Real-scenario UAT on the live schedule (queue 1.2: off 20:00, on 22:00, 2026-10-13); token switch to @svitlo_lusia_zt_bot |
| Next (v0.4) | **Cloudflare Workers**: Telegram webhook (≈1 s replies), cron every minute (punctual alerts), D1/KV storage. $0 on the free plan. |
| Later | Send Люся's sticker with each alert · several addresses per person (Q2) · sticker pack publishing · home power sensor epic |

## 9. Release history (2026-10-13)
| Version | Highlights |
|---|---|
| v0.1 | CLI alerts for one queue (ntfy/Telegram), lookup, tests, spec |
| v0.2 | Shared bot with address quiz; GitHub Actions ticks; stay-awake sessions |
| v0.3.1 | Owner dashboard (US-16): subscribers, failures with fix hints, request types, run gaps, schedule-change context |
| v0.3 | One address + change; 15/30/60 warnings; durations and /schedule; queue-move detection; latest request wins; unknown-input reply; typed answers at every step; persona Люся; encryption and log privacy; bot-switch safety; honest /status; natural Ukrainian time phrases |
