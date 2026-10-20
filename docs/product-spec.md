# Product spec: «Світло Люся 💡», advance outage alerts for Zhytomyr oblast

| | |
|---|---|
| Product | Telegram bot, display name «Світло Житомир 💡 Графік відключень»; username **@Svitlo_Lyusia_zt_bot** (live since 13.10, 21:00) |
| Status | **v0.3 live** (GitHub Actions, public repo). Real-scenario UAT on 2026-10-13. v0.4 (always-on server, D4) in progress. |
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
| v0.4 (next) | Always-on server: instant replies, punctual alerts, durable storage (D4, see section 8) |

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
- /setting (Menu → «Коли попереджати») offers 15 / 30 / 60 minutes. It is not /settings, so Telegram's own Settings option is not taken over (current one ✓; default 30). With 60, the alert arrives ~50–60 minutes before.

**US-10 How long, and the full picture** (Must)
- Off alerts state the length and end time and link to the official schedule.
- Power-back alerts name the next outage («Наступного разу мене вимкнуть завтра о 06:00 - світло буде ~8 год.») or say there's none.
- /schedule shows today and tomorrow: windows with durations, «Разом без світла», and the official link.

**US-11 Address moved to another queue** (Must)
- The bot stores where the queue came from (street + house) and re-reads each street at most every 2 h (one request per street; owner 16.10, was 6 h).
- *Given* the house moved to another queue, *then* the bot switches and says once «⚠️ … було 3.1, тепер 4.2.»
- *Given* the house is gone, *then* it keeps the last queue and asks once to check via /change.
- *Given* a person followed a whole street (no house number) and ZTOE splits it into several queues, *then* the bot says once «⚠️ Житомиробленерго розділило твою вулицю (…) на кілька черг: 1.1, 1.2, 3.2. Напиши номер свого будинку…», keeps alerting on the last queue, and the person simply **types the house number in the chat** (no /change, no 4 steps). Until then every alert ends with «⚠️ Черга може бути неточною: напиши номер свого будинку…». (Owner, 16.10)
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
- **Context:** schedule days *published* and *changed* per day and per week across the subscribers' queues (all 12 queues before v0.4.1, D5), the hour of day when changes happen, and changes by queue.
- **Warning before a change:** for each change, how long before the first edited half-hour it came (after the fact / < 1 h / 1–3 h / 3–6 h / 6–12 h / > 12 h), the median, the share of last-minute changes, and how much outage changes added or removed. Also how long before midnight the next day's schedule appears. *Why:* it shows how much notice people really get from ZTOE, which is the core reason Люся exists.
- **Releases & deploys:** each run records its code version (commit) and branch. The dashboard shows the live version (release tag name when there is one), whether the first run after a deploy was OK, failures since the deploy, deploys per week, **change failure rate** (deploys followed within 1 hour by a crash or failed run; ZTOE/Telegram outages excluded) and **time to restore** (first bad run → next good run), and draws a line on the charts where a new version went live. Only runs from `main` count as production.
- **Funnel:** *subscribed* (address chosen) and *started the bot, no address yet*, with the share who chose an address. People who opened the bot are counted as keyed tags (not chat IDs) and recounted after a bot switch.
- **Active subscribers = reachable on the current bot.** Each subscription remembers the bot that last reached the person (they wrote to it, or it delivered an alert). After a bot switch the others are counted separately as "haven't pressed Start yet".
- **Reply time (SLA):** every answered message records how long it waited (Telegram's send time → the run that answered it). Target: 95% answered within 5 minutes. The dashboard shows median, p95, longest wait, messages queued at run start, and recommends the always-on platform (v0.4) when the target is missed. Section order: Subscribers → How the system works → Context → Releases & deploys.
- **Privacy:** only aggregate numbers are published (the `metrics` branch of a public repo). Chat ids, names and addresses never appear; a test checks this.
- A failed or crashed run is still recorded, so it shows up on the dashboard. Every chart has a table view and supports dark mode.

## 4a. Voice & tone: persona «Світло Люся 💡»
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
- Description: «Привіт! Я Світло Люся 💡 Попереджу тебе: 🔴 за 15, 30 або 60 хв до вимкнення світла і скажу, скільки його
  не буде; 🟢 коли світло повернеться; 📅 якщо графік зміниться. Дані з графіка Житомиробленерго. Без реєстрації: обери
  адресу за 4 кроки. Тисни «Start» 👇»

## 5. Non-functional requirements
| Item | Value |
|---|---|
| Schedule check / bot tick | every 10 min (GitHub cron); in practice GitHub sometimes skips runs for 30+ min (R4) |
| Warning before off/on | user choice 15 / **30** / 60 min |
| Bot reply | next tick (instant during *stay_minutes* sessions; instant for everyone in v0.4) |
| Duplicates | at most one alert per change per user |
| Address → queue re-check | every 2 h per subscriber, one request per street (owner, 16.10: streets get split into several queues when the power situation gets worse) |

- All times are Europe/Kyiv. One schedule request per distinct queue per run; identifying User-Agent.
- Secrets live only in GitHub secrets. Subscriber data is **encrypted at rest** (`SVITLO_STATE_KEY`, Fernet). Chat ids are never logged.
- Dependencies: Python standard library plus `cryptography` (pinned). Automated tests: 94.

## 5a. Data protection and security review (2026-10-14)
**Personal data held** (one record per subscriber, key = Telegram user ID; Telegram gives bots no phone numbers):
queue, address label, ZTOE street ID + house, warning time, alerts already sent, bot that last reached the person.
Not held: name, @username, phone, location, message texts.

| # | Check | Result | Action |
|---|---|---|---|
| S1 | Subscriber data at rest | ✅ Encrypted (Fernet = AES-128 + HMAC-SHA256; key derived with scrypt from the `SVITLO_STATE_KEY` secret) in the Actions cache, not in the repository | - |
| S2 | Fork pull requests in a public repo | ✅ They can read the cache but only get the encrypted file; secrets are never given to fork runs; owner approval required | Keep "Require approval for all external contributors" |
| S3 | Real personal data in the public code | ❌ **Found:** the owner's real chat ID, first name and an address were used as test data since 13.10 | Replaced with fake values (v0.3.6). Removed from the history on 14.10 (Q3) |
| S4 | Chat labels in public logs (`chat#…`) | ❌ **Found:** an unkeyed hash of a ~10-digit ID can be reversed by trying all IDs | Now an HMAC keyed with the secret: meaningless without the key |
| S5 | Old encrypted snapshots | ⚠️ Each run kept a new copy for up to 7 days, so /stop did not erase a person promptly | Only the 3 newest copies are kept (~30 min) |
| S6 | Supply chain (code downloaded on every run, with the bot's secrets) | ⚠️ Python packages pinned by version only; GitHub actions by movable tags | Packages pinned by sha256 hash (`requirements-bot.txt`), actions pinned to commit SHAs |
| S7 | Dashboard (public page) | ✅ Aggregate numbers only; tests check no IDs or addresses leak | Chart library now loaded with an integrity hash (SRI) |
| S8 | Secrets (`TELEGRAM_BOT_TOKEN`, `SVITLO_STATE_KEY`, `TELEGRAM_CHAT_ID`) | ✅ GitHub secrets, masked in logs; never in code | Rotate the token if it ever appears in a chat or screenshot |
| S9 | Workflow permissions | ✅ Least privilege per workflow: `contents: write` only to publish dashboard data / releases; `actions: write` only to delete old snapshots | - |

**Data subject requests:** `/stop` deletes the person's record (and, with S5, every stored copy within ~30 minutes). GitHub deletes everything automatically if the bot does not run for 7 days.

## 6. Success metrics
| Metric | Target | How it is measured (owner dashboard) |
|---|---|---|
| Alerts on time | ≥ 95% of scheduled changes alerted at least 15 minutes before the change | Section 3 «How the system works» → «Alerts on time». (Section 2 «Service levels (SLA)» is the promise to users: 95% of their messages answered within 5 min.) Each alert records its minutes of notice; a late alert (sent with an apology) and a change that passed with no alert both count as a miss. |
| Duplicate alerts | 0 per change | Prevented by design (one alert per event key) and covered by unit tests; no live counter yet. |
| People keep the bot | More join than leave | Qualitative proxy (decision 14.10): «Joined» and «Left» tiles (left = /stop or blocked the bot). Request counts are not used, because a subscriber who only reads alerts sends no requests. |

## 7. Risks, assumptions, decisions
| # | Item | Status | Mitigation / note |
|---|---|---|---|
| R1 | ZTOE endpoints are undocumented and may change | Open | Isolated in `api.py`; contract from SvitloYE (MIT). Ask ZTOE about an official feed. |
| R2/R3 | Live API reachable from GitHub runners | **Resolved** | Verified 2026-10-13: districts, villages, streets and the live schedule for queue 1.2. |
| R4 | GitHub's scheduler is best-effort: runs skipped for 30–45+ min | **Being fixed (v0.4)** | Always-on server (D4): replies by long polling, alerts checked every minute. |
| R5 | Emergency outages are not in the schedule | Limitation | Stated honestly in /help and /status. A home "power sensor" (SvitloBot-style) is a future epic. |
| R6 | Private repo would exceed free Actions minutes | **Resolved** | Repository made public (no secrets in code or history). |
| R7 | Subscribers live in the Actions cache (evicted after 7 days unused) | Being fixed (v0.4) | On the server: encrypted file on disk + daily encrypted backup kept 3 days. |
| R8 | Public repo: logs public; fork PRs could read the cache | **Mitigated** | Encryption, no chat ids in logs, approval required for outside PR workflows. |
| A1 | Slot colours: red = outage, yellow = possible, white/green = power | Partly verified | Live data shows white/red as expected; yellow not yet seen. |
| D1 | Final username @Svitlo_Lyusia_zt_bot | **Done 13.10** | New bot created; token switched; both subscriptions kept (hotfix v0.3.4 stops "chat not found" from unsubscribing people who haven't pressed Start yet). The old @svitlo_dim_tk_bot becomes the test bot. |
| D2 | Persona «Світло Люся» with a functional display name | Decided | Section 4a. |
| D3 | /start never asks to change the address | Decided | Change only via the menu (US-8). |
| D7 | Chats clean themselves: messages older than ~2 days are deleted (both Люся's and the user's) | **Decided 16.10 (owner)** | Telegram lets a bot delete private-chat messages only within 48 h, so "3 days" is not possible; 46 h leaves a safe margin. Message ids (not texts) are kept in the encrypted state for that; /stop forgets them. Said in /help and /privacy. Counted on the dashboard as `messages_cleaned`. |
| D8 | Discovery of free-text questions: what people type that the bot does not understand | **Decided 16.10 (owner)** | Before any AI assistant is considered, measure the need. Kept: the masked text (digits → #, links/e-mails/@names → …) and the day, **no chat id**, at most 300 texts for 30 days, inside the encrypted state. Public dashboard: topic counts only (`freetext:*`). Owner reads the texts on the server: `bash /opt/svitlo/deploy/discovery.sh`. Mentioned in /help. Review after 2–4 weeks: share of free text vs commands, top topics |
| D9 | How the future AI entry door is switched on for a pilot | **Decided 16.10 (owner); build in the AI phase** | Feature flag, off by default. A secret pilot code lives only in the server's root-only `bot.env` (`SVITLO_AI_CODE`), never in GitHub or chats. A person joins with `/pilot <code>` and leaves with `/pilot off`; /stop also removes them. Members are kept in the encrypted state. A wrong code gets the normal "unknown command" reply. Changing the code ends the pilot for everyone who joined with the old one. Rollout: owner → testers → everyone |
| D10 | Addresses without an outage queue (ZTOE «0.0») can be followed | **Decided 19.10 (owner)** | 0.0 is valid ZTOE data: ZTOE's own address search shows «В цей час не вимикається, за винятком випадків аварійних відключень» (e.g. all of вул. Левка Лук'яненка, м. Звягель; not a renaming issue). Rule: 0.0 is never assigned unless the address was matched - the street must be an exact name or confirmed by a tap, and the house must be listed by ZTOE (or its official spelling tapped); a whole street at 0.0 still asks for the house; an unknown house gets «Не знайшла будинок». A matched 0.0 house is followed without alerts; /schedule and /status say so; the 2-hourly re-check tells the person when ZTOE assigns a queue («…призначило чергу 3.1») and alerts start |
| D11 | Emergency outages (аварійні відключення) for subscribers' addresses | **Decided 20.10 (owner)** | Source: ZTOE's public «Чому немає світла?» service (api-ztoe-poweron.inneti.net, behind ztoe.com.ua/unhooking.php); the schedule data has no emergencies. Each address is linked to it once by name (РЕМ → town → street, kind «вул./пров» kept; twin entries handled); no exact match = no emergency alerts for that address, never a guess. Checked every 10 min (`SVITLO_EMERGENCY_EVERY_MINUTES`), one request per subscribed street. Only emergencies are used: outages «by queue» there are the regular schedule. Messages: «⚡🔴 Нове аварійне відключення на твоїй адресі (…): з 20.10 12:48 до 21.10 09:00.» and, if the interval changes, «⚡🔴 Аварійне відключення на твоїй адресі (…) змінено: з … до ….». No message when it ends. Only the person's house (a whole-street subscription hears about any house). Followed 0.0 addresses included |
| D6 | Privacy text for users (inside /help) | **On hold (owner, 16.10)** | Wording to be agreed later; no consent step; /stop is the way out. Already done: /stop deletes the address, settings and every trace of the chat (encrypted backups expire within 3 days). Data minimisation: labels show town and street only; the house number is kept (encrypted) only when a street has several queues, for the 6-hourly re-check. Hashing the house number was rejected: a few hundred possible numbers can be tried in a second. |
| D5 | Replies instant; as few requests to ZTOE as possible: only subscribers' queues, every 10 min (15 is acceptable) | **Decided 15.10 (owner)** | Schedules are kept in memory and refreshed in the background, one request at a time 2 s apart, with a skipped round after a ZTOE error; about 12 requests/hour for 2 queues (was ~144). Alerts are still checked every minute from that copy, so they keep the chosen warning time. A ZTOE schedule edit is noticed within ≤10 min. Trade-off: dashboard section 4 (Context) covers subscribers' queues only. |
| D4 | v0.4 hosting: own small server (EU VPS, ~€4–5/month) instead of Cloudflare Workers or an external trigger | **Decided 15.10 (owner)** | Same Python code, no rewrite; ~1 s replies; alerts every minute and never later than the chosen warning time (sent up to 1 min early). Trade-off accepted: the owner operates the server (automatic security updates, firewall, uptime check). Guide: deploy/README.md. |
| Q1 | bezsvitla.com.ua as an extra source? | Open | Third-party aggregator; ZTOE stays primary. |
| Q2 | Several addresses per person (home + parents)? | Open | Candidate after v0.4. |
| Q3 | Remove the owner's personal test data from the **old commits** of the public repository (history rewrite + force-push)? | ✅ Decided: yes (14.10) | History rewritten on 14.10. Old releases v0.3.2–v0.3.6 pointed to the old commits, so they were removed and their notes moved to CHANGELOG.md (GitHub does not let a workflow re-create a tag on a commit whose workflow files differ from main). Remaining step (owner): ask GitHub Support to purge cached views of the old commits. |

## 8. Roadmap
| When | Item |
|---|---|
| Now | Real-scenario UAT on the live schedule (queue 1.2: off 20:00, on 22:00, 2026-10-13); token switch to @Svitlo_Lyusia_zt_bot ✅ done |
| Next (v0.4) | **Always-on server** (D4): ≈1 s replies, alerts every minute, auto-deploy of `main`, encrypted state on disk. Fallback: GitHub Actions (rollback in deploy/README.md). |
| Later | Send Люся's sticker with each alert · several addresses per person (Q2) · sticker pack publishing · home power sensor epic |

## 9. Release history (2026-10-13)
| Version | Highlights |
|---|---|
| v0.1 | CLI alerts for one queue (ntfy/Telegram), lookup, tests, spec |
| v0.2 | Shared bot with address quiz; GitHub Actions ticks; stay-awake sessions |
| v0.3.1 | Owner dashboard (US-16): subscribers, failures with fix hints, request types, run gaps, schedule-change context |
| v0.3 | One address + change; 15/30/60 warnings; durations and /schedule; queue-move detection; latest request wins; unknown-input reply; typed answers at every step; persona Люся; encryption and log privacy; bot-switch safety; honest /status; natural Ukrainian time phrases |
