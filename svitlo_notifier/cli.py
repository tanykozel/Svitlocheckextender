"""Command line entry point: `python -m svitlo_notifier <command>`."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from .api import ApiError, GpvClient
from .ntfy import NtfyError, send_push
from .planner import Settings, State, plan, summary
from .schedule import KYIV
from .telegram import TelegramError, send_message


def _env_int(name: str) -> int | None:
    value = os.environ.get(name, "").strip()
    return int(value) if value else None


def _load_state(path: Path) -> State:
    try:
        return State.from_dict(json.loads(path.read_text(encoding="utf-8")))
    except FileNotFoundError:
        return State()
    except (OSError, ValueError):
        print(f"warning: ignoring unreadable state file {path}", file=sys.stderr)
        return State()


def _save_state(path: Path, state: State) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="svitlo_notifier", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    lookup = sub.add_parser("lookup", help="find your queue: REM -> city -> street -> address")
    lookup.add_argument("--rem")
    lookup.add_argument("--city")
    lookup.add_argument("--street")
    lookup.set_defaults(func=cmd_lookup)

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
