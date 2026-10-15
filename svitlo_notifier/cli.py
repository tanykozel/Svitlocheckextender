"""Command line entry point: `python -m svitlo_notifier <command>`."""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
import urllib.request
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from .api import ApiError, GpvClient
from .cache import ScheduleCache, start_refresher
from .metrics import merge_from_files
from .ntfy import NtfyError, send_push
from .planner import Settings, State, plan, summary
from .schedule import KYIV
from .secure import StateKeyError, chat_tag, load_json, save_json
from .bot import MENU, MENU_VERSION, WATCH_QUEUES, Bot, BotState, Subscription
from .telegram import (TelegramError, answer_callback, get_me, get_updates, recent_chats, remove_buttons,
                       send_message, set_commands)


def _env_int(name: str) -> int | None:
    value = os.environ.get(name, "").strip()
    return int(value) if value else None


def _state_key() -> str:
    return os.environ.get("SVITLO_STATE_KEY", "")


def _load_state(path: Path) -> State:
    try:
        raw = load_json(path, _state_key())
    except ValueError:
        print(f"warning: ignoring unreadable state file {path}", file=sys.stderr)
        return State()
    return State.from_dict(raw) if raw else State()


def _save_state(path: Path, state: State) -> None:
    _write_json(path, state.to_dict())


def _queue(args: argparse.Namespace) -> tuple[int, int]:
    queue = args.queue if args.queue is not None else _env_int("SVITLO_QUEUE")
    subqueue = args.subqueue if args.subqueue is not None else _env_int("SVITLO_SUBQUEUE")
    if queue is None or subqueue is None:
        sys.exit("error: set --queue/--subqueue or SVITLO_QUEUE/SVITLO_SUBQUEUE (find them with `lookup`)")
    return queue, subqueue


def cmd_lookup(args: argparse.Namespace) -> int:
    client = GpvClient()
    if args.street:
        rows = client.addresses(args.street)
        for row in rows:
            print(f"{row.get('id')}\tчерга {row.get('cherga')}.{row.get('pidcherga')}\t{row.get('name')}")
        return 0
    if args.city:
        rows = client.streets(args.city)
        hint = "--street"
    elif args.rem:
        rows = client.cities(args.rem)
        hint = "--city"
    else:
        rows = client.rems()
        hint = "--rem"
    for row in rows:
        print(f"{row.get('id')}\t{row.get('name')}")
    print(f"\nnext: python -m svitlo_notifier lookup {hint} <id>", file=sys.stderr)
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    queue, subqueue = _queue(args)
    raw = GpvClient().schedule(queue, subqueue)
    print(summary(raw, datetime.now(KYIV), args.label or f"черга {queue}.{subqueue}"))
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    queue, subqueue = _queue(args)
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    topic = os.environ.get("NTFY_TOPIC", "")
    ntfy_server = os.environ.get("NTFY_SERVER") or "https://ntfy.sh"
    telegram_on = bool(token and chat_id)
    if not args.dry_run and not (telegram_on or topic):
        sys.exit("error: set NTFY_TOPIC and/or TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID, or use --dry-run")

    settings = Settings(
        lead=timedelta(minutes=args.lead),
        notify_possible=not args.no_possible,
        notify_changes=not args.no_changes,
        label=args.label or "",
    )
    state_path = Path(args.state)
    raw = GpvClient().schedule(queue, subqueue)
    messages, new_state = plan(raw, datetime.now(KYIV), _load_state(state_path), settings)

    for text in messages:
        if args.dry_run:
            print(text)
            continue
        if topic:
            send_push(topic, text, ntfy_server)
        if telegram_on:
            send_message(token, chat_id, text)
    # Save only after every message went out, so a failed send is retried next run.
    _save_state(state_path, new_state)
    if not messages:
        print("nothing due")
    return 0


def _annotate(level: str, text: str) -> None:
    """Print, and on GitHub Actions also show the line on the run's Summary page."""
    print(text)
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::{level}::{text}")


def cmd_telegram_setup(args: argparse.Namespace) -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        _annotate("error", "TELEGRAM_BOT_TOKEN is not set: add the token from @BotFather as a secret")
        return 1
    bot = get_me(token)
    username = bot.get("username")
    print(f"bot: @{username} - token works")

    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if chat_id:
        send_message(token, chat_id, "✅ Привіт! Це Світло Люся 💡 Я на зв'язку - сюди приходитимуть сповіщення про світло.")
        _annotate("notice", f"Test message sent to {chat_tag(chat_id)}. Telegram is ready.")
        return 0

    chats = recent_chats(token)
    if not chats:
        # Not a failure: the user just has to write to the bot first.
        _annotate("warning", f"Token works, but nobody has written to the bot yet. Open https://t.me/{username}, "
                             "press Start (or send any message), then run this again.")
        return 0
    # Run logs are public in a public repository, so the chat id is sent to the chat itself, not logged.
    for chat in chats:
        send_message(token, chat["id"], f"Ваш TELEGRAM_CHAT_ID: {chat['id']}\n"
                                        "Збережіть його як секрет у GitHub і запустіть Telegram setup ще раз.")
    _annotate("notice", f"Found {len(chats)} chat(s); each received its TELEGRAM_CHAT_ID in Telegram.")
    print("next: save that id as TELEGRAM_CHAT_ID and run telegram-setup again to send a test message")
    return 0


def _telegram_gone(exc: Exception) -> bool:
    """True only when the person really left: blocked the bot, deleted the account, removed the bot.

    "chat not found" and "can't initiate conversation" are NOT gone: after a switch to a new bot token,
    people who have not pressed Start in the new bot yet get exactly these errors. They keep their
    subscription and start receiving alerts as soon as they press Start.
    """
    text = str(exc).lower()
    return isinstance(exc, TelegramError) and any(
        marker in text for marker in ("blocked by the user", "user is deactivated", "kicked")
    )


def cmd_bot(args: argparse.Namespace) -> int:
    started = time.monotonic()
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        _annotate("warning", "TELEGRAM_BOT_TOKEN is not set; the bot is idle")
        return 0
    path = Path(args.state)
    try:
        raw = load_json(path, _state_key())
    except StateKeyError as exc:
        # Refuse to start empty: saving would overwrite every subscription.
        _annotate("error", str(exc))
        return 1
    except ValueError:
        print(f"warning: unreadable bot state {path}; starting empty", file=sys.stderr)
        raw = None
    state = BotState.from_dict(raw) if raw else BotState()
    if not _state_key() and os.environ.get("GITHUB_ACTIONS") == "true":
        _annotate("warning", "SVITLO_STATE_KEY is not set: subscriber data is stored unencrypted in the Actions cache")

    # The owner's address from repository variables counts as a subscription too.
    owner, queue, subqueue = (os.environ.get("TELEGRAM_CHAT_ID", ""), _env_int("SVITLO_QUEUE"),
                              _env_int("SVITLO_SUBQUEUE"))
    if owner and queue is not None and subqueue is not None and owner not in state.subs:
        state.subs[owner] = Subscription(queue, subqueue, os.environ.get("SVITLO_LABEL", ""),
                                         lead_minutes=_env_int("SVITLO_LEAD_MINUTES") or 30)

    try:
        me = get_me(token)
    except TelegramError as exc:
        _annotate("error", f"Telegram rejected the bot token: {exc}")
        return 1
    print(f"bot: @{me.get('username')}")
    if state.switch_bot(int(me["id"])):
        _annotate("notice", f"New bot detected (@{me.get('username')}): message counter and menu reset, "
                            f"{len(state.subs)} subscription(s) kept")

    if state.menu_version < MENU_VERSION:
        try:
            set_commands(token, MENU)
            state.menu_version = MENU_VERSION
        except TelegramError as exc:
            print(f"warning: could not set the bot menu: {exc}")

    # Always-on: schedules come from memory, refreshed in the background, so replies never wait for ZTOE.
    directory = ScheduleCache(GpvClient()) if args.forever else GpvClient()
    bot = Bot(directory, lambda chat, text, buttons: send_message(token, chat, text, buttons=buttons), state,
              unbutton=lambda chat, message: remove_buttons(token, chat, message))

    def read_and_answer(wait: int) -> int:
        try:
            updates = get_updates(token, state.offset, wait=wait)
            bot.note_queue(updates)  # requests that waited for this run to start
            bot.process_updates(updates, answer=lambda callback_id: answer_callback(token, callback_id))
        except TelegramError as exc:
            bot.stats["failure:telegram_read"] += 1
            print(f"warning: could not read messages: {exc}")
            return 0
        # Save before alerts so answered messages are never processed twice.
        _write_json(path, state.to_dict())
        return len(updates)

    moved = sent = 0
    if args.forever:
        bot.alert_early = timedelta(seconds=ALERT_EVERY)  # alerts are checked every minute
    elif os.environ.get("SVITLO_ALERT_EARLY_MINUTES"):
        bot.alert_early = timedelta(minutes=float(os.environ["SVITLO_ALERT_EARLY_MINUTES"]))

    def alerts() -> None:
        nonlocal moved, sent
        now = datetime.now(KYIV)
        moved += bot.refresh_queues(now)
        sent += bot.send_alerts(now, is_gone=_telegram_gone)
        bot.watch_all_queues(now)
        _write_json(path, state.to_dict())

    if args.forever:
        return _serve(args, bot, me, read_and_answer, alerts)

    handled = read_and_answer(0)
    alerts()
    # "Stay awake": keep listening with long polling so replies arrive within a second or two,
    # and keep checking alerts every minute so they go out on time during the session.
    deadline = time.monotonic() + args.stay_minutes * 60
    next_alerts = time.monotonic() + ALERT_EVERY
    while time.monotonic() < deadline - 5:
        handled += read_and_answer(int(min(25, max(1, deadline - time.monotonic() - 5))))
        if time.monotonic() >= next_alerts:
            alerts()
            next_alerts = time.monotonic() + ALERT_EVERY
    if args.stay_minutes:
        alerts()
    print(f"processed {handled} message(s)")
    print(f"subscribers: {len(state.subs)}, queues changed: {moved}, alerts sent: {sent}")
    if args.metrics:
        _write_metrics(Path(args.metrics), bot, me, handled, time.monotonic() - started)
    return 0


ALERT_EVERY = 60  # seconds between alert checks while the bot stays awake


def _serve(args: argparse.Namespace, bot: Bot, me: dict, read_and_answer, alerts) -> int:
    """Always-on mode for a server: replies within ~1 s, alerts checked every minute.

    The ZTOE website is read only by a background thread, every --ztoe-every minutes; the replies and the
    minute-by-minute alert check use the copy in memory, so a person never waits for ZTOE.
    Dashboard numbers are written as one record per window into --metrics-dir; a separate timer
    publishes them, so a GitHub outage never stops the bot.
    """
    stop = []
    previous = {sig: signal.signal(sig, lambda *_a: stop.append(True)) for sig in (signal.SIGTERM, signal.SIGINT)}
    refresher_stop = threading.Event()
    cache = bot.dir if isinstance(bot.dir, ScheduleCache) else None
    if cache is not None:
        def needed() -> set[tuple[int, int]]:
            return {(s.queue, s.subqueue) for s in list(bot.state.subs.values())} | set(WATCH_QUEUES)
        start_refresher(cache, needed, args.ztoe_every * 60, refresher_stop)
    window_start = time.monotonic()
    next_alerts = time.monotonic()
    handled = windows = 0
    print(f"serving @{me.get('username')}: replies by long polling, alerts every {ALERT_EVERY} s, "
          f"ZTOE read every {args.ztoe_every:g} min", flush=True)
    while not stop:
        failed_before = bot.stats["failure:telegram_read"]
        # Never wait past the next alert check, so checks stay one minute apart.
        handled += read_and_answer(int(min(25, max(1, next_alerts - time.monotonic()))))
        if bot.stats["failure:telegram_read"] > failed_before:
            time.sleep(5)  # Telegram unreachable (or another copy of the bot is polling): don't spin
        if time.monotonic() >= next_alerts:
            try:
                alerts()
                if cache is not None and (errors := cache.take_errors()):
                    bot.stats["failure:ztoe"] += errors  # background reads that failed; the last copy stays in use
                _ping(os.environ.get("SVITLO_HEALTHCHECK_URL", ""))
            except Exception as exc:  # noqa: BLE001 - keep serving; the next check retries
                bot.stats["failure:run_crashed"] += 1
                print(f"warning: alert check failed: {type(exc).__name__}: {exc}", flush=True)
            next_alerts = time.monotonic() + ALERT_EVERY
        if args.metrics_dir and (stop or time.monotonic() - window_start >= args.metrics_every * 60):
            folder = Path(args.metrics_dir)
            folder.mkdir(parents=True, exist_ok=True)
            windows += 1  # in the name too, so two windows in the same second never overwrite each other
            _write_metrics(folder / f"run-{int(time.time())}-{windows:06d}.json", bot, me, handled,
                           time.monotonic() - window_start)
            bot.reset_window()
            window_start, handled = time.monotonic(), 0
    refresher_stop.set()
    for sig, handler in previous.items():
        signal.signal(sig, handler)
    print("stopped", flush=True)
    return 0


def _ping(url: str) -> None:
    """Tell an uptime monitor (e.g. healthchecks.io) that the bot is alive; never fails the bot."""
    if not url:
        return
    try:
        urllib.request.urlopen(url, timeout=10).close()
    except OSError as exc:
        print(f"warning: health ping failed: {exc}", flush=True)


def metrics_record(bot: Bot, me: dict, processed: int, seconds: float) -> dict:
    """One run's numbers for the owner dashboard. Aggregates only: no chat ids, names or addresses."""
    groups: dict[str, dict[str, int]] = {"request": {}, "outcome": {}, "failure": {}, "schedule": {}}
    for key, count in sorted(bot.stats.items()):
        group, _, name = key.partition(":")
        groups.setdefault(group, {})[name] = count
    # Active = reachable on the current bot. After a bot switch, people who haven't pressed Start in the
    # new bot yet are "waiting" until they write to it or it delivers a message to them.
    subs = [s for s in bot.state.subs.values() if s.bot_id == bot.state.bot_id]
    waiting = len(bot.state.subs) - len(subs)
    by_queue, by_lead = Counter(f"{s.queue}.{s.subqueue}" for s in subs), Counter(str(s.lead_minutes) for s in subs)
    waits = sorted(bot.reply_waits)
    return {
        "ts": datetime.now(KYIV).isoformat(timespec="seconds"),
        "bot": me.get("username", ""),
        "seconds": round(seconds, 1),
        "subscribers": len(subs),
        "subscribers_waiting": waiting,
        # Funnel: opened the bot (any message) -> chose an address. Counted with keyed tags, not chat ids.
        # Everyone with an address has started the bot, even if they haven't written since "seen" began.
        "started": len(set(bot.state.seen) | {chat_tag(c) for c in bot.state.subs}),
        "started_no_address": len(set(bot.state.seen) - {chat_tag(c) for c in bot.state.subs}),
        "queued_at_start": bot.queued_at_start,
        "queued_by_kind": dict(sorted(bot.queued_by_kind.items())),
        "waits_by_kind": {k: sorted(v)[-50:] for k, v in sorted(bot.waits_by_kind.items())},
        "alert_notices": bot.alert_notices[-500:],  # [minutes of notice, chosen warning time]; < 0 = late
        "reply_waits": waits[-200:],
        "quizzes": len(bot.state.sessions),
        "address_problems": sum(1 for s in subs if s.problem),
        "by_queue": dict(sorted(by_queue.items())),
        "by_lead": dict(sorted(by_lead.items())),
        "processed": processed,
        "requests": groups["request"],
        "outcomes": groups["outcome"],
        "failures": groups["failure"],
        "schedule_events": bot.schedule_events,
    }


def _write_metrics(path: Path, bot: Bot, me: dict, processed: int, seconds: float) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(metrics_record(bot, me, processed, seconds), ensure_ascii=False, indent=1),
                    encoding="utf-8")


def _write_json(path: Path, data: dict) -> None:
    save_json(path, data, _state_key())


def cmd_metrics_merge(args: argparse.Namespace) -> int:
    folder = Path(args.into)
    folder.mkdir(parents=True, exist_ok=True)
    entry = merge_from_files(folder, Path(args.record),
                             {"run_id": args.run_id, "event": args.event, "outcome": args.outcome, "url": args.url,
                              "sha": args.sha[:7], "ref": args.ref})
    print(f"dashboard: run {entry.get('run_id', '?')} {entry.get('outcome')}, "
          f"subscribers {entry.get('subscribers', '?')}, failures {sum(entry.get('failures', {}).values())}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="svitlo_notifier", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    lookup = sub.add_parser("lookup", help="find your queue: REM -> city -> street -> address")
    lookup.add_argument("--rem")
    lookup.add_argument("--city")
    lookup.add_argument("--street")
    lookup.set_defaults(func=cmd_lookup)

    bot = sub.add_parser("bot", help="answer bot messages (address quiz) and send alerts to all subscribers")
    bot.add_argument("--state", default=os.environ.get("SVITLO_BOT_STATE", ".state/bot.json"))
    bot.add_argument("--stay-minutes", type=float, default=float(os.environ.get("SVITLO_STAY_MINUTES") or 0),
                     help="keep listening this long for instant replies (for live testing); default 0")
    bot.add_argument("--metrics", default=os.environ.get("SVITLO_METRICS", ""),
                     help="write this run's dashboard numbers (no personal data) to this JSON file")
    bot.add_argument("--forever", action="store_true", default=os.environ.get("SVITLO_FOREVER") == "true",
                     help="always-on server mode: never stop, alerts every minute")
    bot.add_argument("--metrics-dir", default=os.environ.get("SVITLO_METRICS_DIR", ""),
                     help="with --forever: write one dashboard record per window into this folder")
    bot.add_argument("--metrics-every", type=float, default=10, help="with --forever: window length in minutes")
    bot.add_argument("--ztoe-every", type=float, default=float(os.environ.get("SVITLO_ZTOE_EVERY_MINUTES") or 10),
                     help="with --forever: read the ZTOE schedules every N minutes in the background (default 10)")
    bot.set_defaults(func=cmd_bot)

    dash = sub.add_parser("metrics-merge", help="add a bot run's numbers to the dashboard data files")
    dash.add_argument("--record", default=".metrics/run.json", help="the file `bot --metrics` wrote")
    dash.add_argument("--into", required=True, help="folder with history.json, daily.json, events.json")
    dash.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    dash.add_argument("--event", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    dash.add_argument("--outcome", default="success", help="success / failure / cancelled")
    dash.add_argument("--url", default="")
    dash.add_argument("--sha", default=os.environ.get("GITHUB_SHA", ""), help="the code version (commit) that ran")
    dash.add_argument("--ref", default=os.environ.get("GITHUB_REF_NAME", ""), help="the branch it ran from")
    dash.set_defaults(func=cmd_metrics_merge)

    tg = sub.add_parser("telegram-setup", help="check the bot token, find your chat id, send a test message")
    tg.set_defaults(func=cmd_telegram_setup)

    for name, func, help_text in (
        ("status", cmd_status, "print current state and next changes"),
        ("check", cmd_check, "send alerts that are due (run every 5-10 minutes)"),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--queue", type=int, help="черга (env SVITLO_QUEUE)")
        p.add_argument("--subqueue", type=int, help="підчерга (env SVITLO_SUBQUEUE)")
        p.add_argument("--label", default=os.environ.get("SVITLO_LABEL"), help="name shown in messages")
        p.set_defaults(func=func)

    check = sub.choices["check"]
    check.add_argument("--lead", type=int, default=_env_int("SVITLO_LEAD_MINUTES") or 30,
                       help="minutes of warning before a change (default 30)")
    check.add_argument("--state", default=os.environ.get("SVITLO_STATE", ".state/state.json"))
    check.add_argument("--no-possible", action="store_true", help="skip 'possible outage' (yellow) alerts")
    check.add_argument("--no-changes", action="store_true", help="skip 'schedule changed/published' alerts")
    check.add_argument("--dry-run", action="store_true", help="print instead of sending")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ApiError, NtfyError, TelegramError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
