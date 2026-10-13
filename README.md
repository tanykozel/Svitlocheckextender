# «Лампочка Люся 💡»: outage alerts for Zhytomyr oblast

**Telegram bot: [@svitlo_lusia_zt_bot](https://t.me/svitlo_lusia_zt_bot)** · display name «Світло Житомир 💡 Графік відключень»

*Built with AI assistance:* product decisions, requirements and testing by Tetiana Kozel; design and code produced with an AI assistant (Claude Code).

The official **Svitlochek** app (АТ «Житомиробленерго», `ua.com.ztoe.outages`) shows the hourly outage
schedule, but it does **not warn you before the power goes off or comes back**. Люся fills that gap: she reads
the same public ZTOE schedule for your queue (черга / підчерга) and sends a **Telegram push alert** before every
change, tells you **how long** each outage lasts, and lets you know when the **schedule changes**.

- No account with ZTOE, no registration: choose an address in 4 steps.
- Unofficial tool. The schedule is planned; **emergency outages are not in it**, so Люся cannot warn about them.
- Product spec (user stories, acceptance criteria, risks): [docs/product-spec.md](docs/product-spec.md).

---

## For users

### Getting started
1. Open **https://t.me/svitlo_lusia_zt_bot** and press **Start**.
2. Answer 4 questions with buttons **or** by typing: **district → town/village → street → house number**.
   For example, type «звягельський», then «сусли». If the street is all in one queue, the house question is skipped.
3. Люся confirms: «✅ Готово! с. Сусли, вул. Центральна 5: черга 1.2. Тепер я попереджатиму тебе за 30 хв…»

If something isn't found, Люся asks you to check the spelling and waits for a corrected answer.

### Menu (☰ button next to the message box)
| Menu item | Command | What it does |
|---|---|---|
| Обрати адресу | `/start` | start the address quiz. If you're already subscribed, Люся only reminds you of your address. |
| Графік на сьогодні й завтра | `/schedule` | outage windows, their length, total hours without power, and the official link |
| Стан за графіком | `/status` | what the **schedule** says now and the next changes (not the real power state) |
| Коли попереджати | `/settings` | warn 15, **30** (default) or 60 minutes before each change |
| Змінити адресу | `/change` | choose another address. It **replaces** the current one: one address per person. |
| Відписатися | `/stop` | stop all alerts |
| Про Люсю і допомога | `/help` | short help |

Anything else (random text, stickers, photos, unknown commands) gets:
«Я тебе не розумію 🙈 Обери команду з меню ☰ (кнопка «Menu» внизу) або надішли /help.»

### What the alerts look like
These are the exact texts the code produces:

```text
🔴 За ~30 хв, о 20:00, мене вимкнуть 😔
Без світла ~2 год, до 22:00 (за графіком).
Заряди телефон і павербанк 🔋
Повний графік: /schedule або https://www.ztoe.com.ua/unhooking-search.php

🟢 Я повертаюся! За ~30 хв, о 22:00, світло мають увімкнути 💡
Наступного разу мене вимкнуть завтра о 06:00 - світло буде ~8 год.

📅 З'явився графік на 14.10:
• 06:00–10:00 (4 год)
Разом без світла: 4 год

⚠️ Житомиробленерго змінило чергу для твоєї адреси (…): було 3.1, тепер 4.2.
Я вже стежу за новою чергою 👀
```

There's also a 🟡 "possible outage" alert for yellow slots. Every alert is sent **once**.

### Good to know
- **Replies are not instant** (yet). The bot runs in short "ticks" on GitHub Actions, so a reply can take
  ~10–30 minutes. Telegram keeps your messages until then, and if you tap several times, only your **latest**
  request is answered. Instant replies are planned for v0.4 (Cloudflare).
- **One address per person.** If ZTOE moves your address to another queue, Люся notices within ~6 hours,
  switches over and tells you.

---

## For the owner

### Bot setup (one time)
1. **Create the bot** in [@BotFather](https://t.me/BotFather): `/newbot`, display name `Світло Житомир 💡 Графік відключень`,
   username `svitlo_lusia_zt_bot`. Keep the **token** secret. If it leaks, send `/revoke`.
2. **Profile in BotFather:** `/setuserpic` with an avatar from [assets/](assets) (`lyusya-phone.png`,
   `lyusya-vinok.png` or `lyusya-avatar.png`), then `/setabouttext` and `/setdescription` (texts in Люся's voice;
   see the spec, section 4a). The command menu is registered **automatically** by the bot.
3. **GitHub → Settings → Secrets and variables → Actions:**

   | Kind | Name | Value |
   |---|---|---|
   | Secret | `TELEGRAM_BOT_TOKEN` | the token from BotFather |
   | Secret | `TELEGRAM_CHAT_ID` | your chat id (run **Actions → Telegram setup**: the bot sends you your id in Telegram) |
   | Secret | `SVITLO_STATE_KEY` | a long random passphrase (30+ characters). It encrypts subscriber data. Keep a copy. |
   | Variable | `BOT_ENABLED` | `true`, to switch on the 10-minute schedule |

4. **Security for a public repository:** Settings → Actions → General → *Approval for running fork pull request
   workflows* → **Require approval for all external contributors**. Never approve PRs from strangers.

**Switching to another bot later:** put the new token in `TELEGRAM_BOT_TOKEN`. On the next run the bot detects
the change (the run log shows `bot: @username` and "New bot detected"), resets its message counter and menu, and
**keeps all subscriptions**. People only need to press **Start** in the new bot.

### How it runs
| Workflow (Actions tab) | What it does |
|---|---|
| **Outage alerts** | Every ~10 min, plus **Run workflow** on demand: reads messages, answers them, sends due alerts. *stay_minutes* (max 30) keeps the bot awake with ~1-second replies and alerts checked every minute, which is handy for live testing. |
| **Find my queue** | District → city → street → house lookup, or the live schedule for a queue (fill *queue* / *subqueue*). |
| **Telegram setup** | Checks the token; sends each chat its id in Telegram, or a test message if `TELEGRAM_CHAT_ID` is set. |
| **Tests** | Runs the automated tests on every push. |

- **Cadence:** schedule check every 10 min; address → queue re-check every 6 h. GitHub's scheduler is "best effort"
  and in practice sometimes skips runs for 30+ minutes. See risk R4 in the spec and the v0.4 Cloudflare plan.
- **Cost:** $0. The repository is public, so GitHub Actions minutes are free and unlimited.
- **Privacy:** subscriber data lives in the Actions cache, **encrypted** with `SVITLO_STATE_KEY` (Fernet, AES + HMAC).
  Chat ids are never printed in the public run logs. With a wrong or missing key the bot stops instead of wiping
  subscriptions. If the bot is off for more than 7 days, GitHub deletes the cache and people press Start again.
- **Owner tool:** `/test` (hidden from the menu and help) sends one example of each alert for your address, marked 🧪 ТЕСТ.

### Owner dashboard
**https://tanykozel.github.io/Svitlocheckextender/dashboard/** has three sections:
1. **Subscribers:** active count, 7-day change, joined/left, a trend line, and splits by queue and warning time.
2. **How the system works:** bot status, runs and failed runs (with log links), failures by type with a
   "what to do" hint, minutes between runs (GitHub scheduler gaps), and requests by type.
3. **Context:** how often ZTOE publishes or changes a day's schedule (per day/week, by hour, by queue). Люся
   checks all 12 queues every ~30 minutes for this.

How it works: after every run, the workflow adds the run's numbers to `history.json`, `daily.json` and `events.json`
on the `metrics` branch. They are **aggregate numbers only**, never chat ids or addresses. The page reads them from
there. One-time setup: **Settings → Pages → Deploy from a branch → the default branch (`claude/svitlocheck-subscribe-connect-jzvsxz`) / `/docs`**. Data appears after the
first bot run with this version.

### Brand assets
| File | What |
|---|---|
| `assets/lyusya-phone.png`, `assets/lyusya-vinok.png`, `assets/lyusya-avatar.png` | Люся avatars (640×640, round-crop safe) |
| `assets/stickers/*.png` | 7 Telegram stickers (512×512): Світло є!, Мене вимкнули, Увага!, Я повернулась!, Графік, Заряджай!, Дякую! Publish them via [@Stickers](https://t.me/Stickers) → `/newpack`. |
| `assets/demo/svitlo-demo.mp4` | 49-second demo video, built from the real bot texts |

Each image and the video have a script next to them that regenerates them.

---

## Advanced: single address without the bot (ntfy or Telegram)

The `check` command watches one queue and sends alerts via **ntfy** (free phone push app, no account) and/or a
Telegram chat. Python 3.10+; install `cryptography` only if you use `SVITLO_STATE_KEY`.

```bash
python -m svitlo_notifier lookup                       # REM (district) -> --rem/--city/--street ids -> queue
python -m svitlo_notifier status --queue 1 --subqueue 2
python -m svitlo_notifier check --queue 1 --subqueue 2 --dry-run --lead 120
NTFY_TOPIC=your-hard-to-guess-topic SVITLO_QUEUE=1 SVITLO_SUBQUEUE=2 python -m svitlo_notifier check   # every 5–10 min
```

| Setting | Env / flag | Default |
|---|---|---|
| Queue / sub-queue | `SVITLO_QUEUE`, `SVITLO_SUBQUEUE` | required |
| Warning time | `SVITLO_LEAD_MINUTES` / `--lead` | 30 min |
| Label in messages | `SVITLO_LABEL` / `--label` | none |
| Skip yellow / "schedule changed" alerts | `--no-possible` / `--no-changes` | off |
| ntfy | `NTFY_TOPIC`, `NTFY_SERVER` | `https://ntfy.sh` |

## Data source and limits
- Schedule from ZTOE's public but **undocumented** endpoints `https://www.ztoe.com.ua/gpv/api/`, the same ones the
  open-source [SvitloYE](https://github.com/dmitthedazed/SvitloYE) app (MIT) uses. They may change without notice.
- Alerts follow the **planned** schedule; emergency outages ordered by Ukrenergo are not in it.
- Unofficial. If anything differs, [ztoe.com.ua](https://www.ztoe.com.ua) is authoritative.

## Development
```bash
pip install cryptography==43.0.3
python -m unittest discover -s tests -v      # 83 tests
```
