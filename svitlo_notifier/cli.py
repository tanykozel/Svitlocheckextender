"""Command line entry point: `python -m svitlo_notifier <command>`."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from .api import ApiError, GpvClient
from .metrics import merge_from_files
from .ntfy import NtfyError, send_push
from .planner import Settings, State, plan, summary
from .schedule import KYIV
from .secure import StateKeyError, chat_tag, load_json, save_json
from .bot import MENU, MENU_VERSION, Bot, BotState, Subscription
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
    text = str(exc).lower()
    return isinstance(exc, TelegramError) and any(
        marker in text for marker in ("blocked by the user", "chat not found", "user is deactivated", "kicked")
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

    bot = Bot(GpvClient(), lambda chat, text, buttons: send_message(token, chat, text, buttons=buttons), state,
              unbutton=lambda chat, message: remove_buttons(token, chat, message))

    def read_and_answer(wait: int) -> int:
        try:
            updates = get_updates(token, state.offset, wait=wait)
            bot.process_updates(updates, answer=lambda callback_id: answer_callback(token, callback_id))
        except TelegramError as exc:
            bot.stats["failure:telegram_read"] += 1
            print(f"warning: could not read messages: {exc}")
            return 0
        # Save before alerts so answered messages are never processed twice.
        _write_json(path, state.to_dict())
        return len(updates)

    moved = sent = 0

    def alerts() -> None:
        nonlocal moved, sent
        now = datetime.now(KYIV)
        moved += bot.refresh_queues(now)
        sent += bot.send_alerts(now, is_gone=_telegram_gone)
        bot.watch_all_queues(now)
        _write_json(path, state.to_dict())

    handled = read_and_answer(0)
    alerts()
    # "Stay awake": keep listening with long polling so replies arrive within a second or two,
    # and keep checking alerts every minute so they go out on time during the session.
    deadline = time.monotonic() + args.stay_minutes * 60
    next_alerts = time.monotonic() + 60
    while time.monotonic() < deadline - 5:
        handled += read_and_answer(int(min(25, max(1, deadline - time.monotonic() - 5))))
        if time.monotonic() >= next_alerts:
            alerts()
            next_alerts = time.monotonic() + 60
    if args.stay_minutes:
        alerts()
    print(f"processed {handled} message(s)")
    print(f"subscribers: {len(state.subs)}, queues changed: {moved}, alerts sent: {sent}")
    if args.metrics:
        _write_metrics(Path(args.metrics), bot, me, handled, time.monotonic() - started)
    return 0


def metrics_record(bot: Bot, me: dict, processed: int, seconds: float) -> dict:
    """One run's numbers for the owner dashboard. Aggregates only: no chat ids, names or addresses."""
    groups: dict[str, dict[str, int]] = {"request": {}, "outcome": {}, "failure": {}, "schedule": {}}
    for key, count in sorted(bot.stats.items()):
        group, _, name = key.partition(":")
        groups.setdefault(group, {})[name] = count
    subs = bot.state.subs.values()
    by_queue, by_lead = Counter(f"{s.queue}.{s.subqueue}" for s in subs), Counter(str(s.lead_minutes) for s in subs)
    return {
        "ts": datetime.now(KYIV).isoformat(timespec="seconds"),
        "bot": me.get("username", ""),
        "seconds": round(seconds, 1),
        "subscribers": len(bot.state.subs),
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
                             {"run_id": args.run_id, "event": args.event, "outcome": args.outcome, "url": args.url})
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
    bot.set_defaults(func=cmd_bot)

    dash = sub.add_parser("metrics-merge", help="add a bot run's numbers to the dashboard data files")
    dash.add_argument("--record", default=".metrics/run.json", help="the file `bot --metrics` wrote")
    dash.add_argument("--into", required=True, help="folder with history.json, daily.json, events.json")
    dash.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    dash.add_argument("--event", default=os.environ.get("GITHUB_EVENT_NAME", ""))
    dash.add_argument("--outcome", default="success", help="success / failure / cancelled")
    dash.add_argument("--url", default="")
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
