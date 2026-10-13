# Svitlo notifier (Svitlochek extender)

The official **Svitlochek** app (АТ «Житомиробленерго», `ua.com.ztoe.outages`) shows the
hourly outage schedule, but it does **not warn you before power goes off or comes back**.
This small service fills that gap: it reads the same public ZTOE schedule for your queue
(черга / підчерга) and sends a **phone push notification** a set number of minutes before each change.

No account with ZTOE is needed, and none is created.

## What you get

| Alert | Example |
|---|---|
| Power going off | `[Дім] 🔴 Світло вимкнуть через ~30 хв, о 08:00 (до 12:00 за графіком).` |
| Possible outage (yellow) | `[Дім] 🟡 Можливе відключення через ~30 хв, о 18:00 (до 20:00).` |
| Power coming back | `[Дім] 🟢 Світло мають увімкнути через ~30 хв, о 12:00.` |
| Schedule published / changed | `[Дім] 📅 Графік на 14.10 змінено: • 00:00–04:00` |

Every alert is sent once. A schedule change re-plans upcoming alerts automatically.

## Delivery channels (choose one or both)

1. **ntfy push**, the simplest option, with no account and no bot.
   Install the free *ntfy* app ([Android](https://play.google.com/store/apps/details?id=io.heckel.ntfy) /
   [iOS](https://apps.apple.com/app/ntfy/id1625396347)), tap **+**, and subscribe to a topic name you invent,
   for example `svitlo-dim-k7x29q`. Anyone who knows the topic can read it, so make the name hard to guess.
   Set `NTFY_TOPIC` to the same name.
2. **Telegram**. Your own bot sends the alerts, and Telegram shows them as normal push notifications.
   See [Create the Telegram bot](#create-the-telegram-bot).

## Create the Telegram bot

1. In Telegram, open [@BotFather](https://t.me/BotFather) (blue tick) and send `/newbot`.
2. Enter a display name, e.g. `Світло Дім`, then a username ending in `bot`, e.g. `svitlo_dim_tk_bot`.
3. BotFather replies with a **token** like `123456789:AA...`. Treat it like a password: never post or commit it.
   If it leaks, send `/revoke` to BotFather to get a new one.
4. Open your new bot (the `t.me/...` link BotFather gives you) and press **Start**.
   Telegram bots cannot message you first, so this step is required.
   *Family alerts:* create a group, add the bot to it, and send any message in the group.
5. Find your chat ID and send a test message.

   **In the browser (no install):** in the GitHub repo, open Settings → Secrets and variables → Actions,
   and add the secret `TELEGRAM_BOT_TOKEN`. Then go to Actions → **Telegram setup** → **Run workflow**.
   Open the finished run, and the "Check bot and chat" step lists your chat ID. Add it as the secret
   `TELEGRAM_CHAT_ID` and run the workflow again to get the test message.

   **On your computer** (Python 3.10+, in the repo folder; on Windows PowerShell use `$env:NAME='value'` instead of `export`):

   ```bash
   export TELEGRAM_BOT_TOKEN='123456789:AA...'
   python -m svitlo_notifier telegram-setup          # shows the bot name and your chat id
   export TELEGRAM_CHAT_ID='<id from the list>'      # group ids start with -100
   python -m svitlo_notifier telegram-setup          # sends "✅ Svitlo notifier підключено"
   ```

6. Optional polish in BotFather: `/setuserpic` for an avatar, and `/setdescription` for the text people see before pressing Start.

For GitHub Actions, store the two values as repository **secrets** `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
(Settings → Secrets and variables → Actions).

## Setup

Requires Python 3.10+ and nothing else (standard library only).

```bash
# 1. Find your queue: REM (district) -> city -> street -> house
python -m svitlo_notifier lookup
python -m svitlo_notifier lookup --rem <id>
python -m svitlo_notifier lookup --city <id>
python -m svitlo_notifier lookup --street <id>      # prints "черга 3.1  <houses>"

# 2. See what the schedule looks like now
python -m svitlo_notifier status --queue 3 --subqueue 1

# 3. Try alerts without sending anything
python -m svitlo_notifier check --queue 3 --subqueue 1 --dry-run --lead 120

# 4. Run for real every 5–10 minutes (cron, Task Scheduler, or GitHub Actions below)
NTFY_TOPIC=svitlo-dim-k7x29q SVITLO_QUEUE=3 SVITLO_SUBQUEUE=1 SVITLO_LABEL=Дім \
  python -m svitlo_notifier check
```

Settings (flag or environment variable):

| Setting | Env | Default |
|---|---|---|
| Queue / sub-queue | `SVITLO_QUEUE`, `SVITLO_SUBQUEUE` | required |
| Warning time | `SVITLO_LEAD_MINUTES` / `--lead` | 30 min |
| Label in messages | `SVITLO_LABEL` / `--label` | none |
| Skip yellow "possible" alerts | `--no-possible` | off |
| Skip "schedule changed" alerts | `--no-changes` | off |
| State file (what was already sent) | `SVITLO_STATE` / `--state` | `.state/state.json` |
| Self-hosted ntfy server | `NTFY_SERVER` | `https://ntfy.sh` |

## Where to run it

- **Home PC, Raspberry Pi or a VPS in Ukraine (recommended).** Add a cron line:
  `*/5 * * * * cd /path/to/repo && NTFY_TOPIC=... SVITLO_QUEUE=3 SVITLO_SUBQUEUE=1 python3 -m svitlo_notifier check`
  This is the most punctual option, and a Ukrainian IP is never blocked by the utility's site.
  Note: if the machine is at the same address that loses power, it can still warn you before an outage
  but not before power returns. Use a laptop on battery, a UPS, or a remote server.
- **GitHub Actions (free, nothing to host).** `.github/workflows/notify.yml` runs every 10 minutes.
  Add repository **secrets** `NTFY_TOPIC` (and/or `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`) and
  **variables** `SVITLO_QUEUE`, `SVITLO_SUBQUEUE`, optionally `SVITLO_LABEL` and `SVITLO_LEAD_MINUTES`.
  Caveats: GitHub can delay scheduled runs by several minutes at busy times, so keep the lead at 30 min or more.
  Some Ukrainian sites also block non-Ukrainian IPs. If the run log shows the ZTOE request failing, use the home option.

## Data source and limits

- The schedule comes from ZTOE's public but **undocumented** endpoints `https://www.ztoe.com.ua/gpv/api/`,
  the same ones the open-source [SvitloYE](https://github.com/dmitthedazed/SvitloYE) app (MIT) uses.
  ZTOE may change them without notice.
- Alerts follow the **planned** schedule. Emergency outages ordered by Ukrenergo can happen at any time
  and are not in the schedule.
- This is an unofficial tool. If anything differs, [ztoe.com.ua](https://www.ztoe.com.ua) is authoritative.

## Development

```bash
python -m unittest discover -s tests -v
```

The product spec (problem, user stories, acceptance criteria, risks) is in [docs/product-spec.md](docs/product-spec.md).
