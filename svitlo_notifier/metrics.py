"""Dashboard data: merge one run's numbers into the files the dashboard page reads.

Files (kept on the `metrics` branch, all aggregate numbers, no chat ids or addresses):
- history.json - one entry per run, the latest ~4 weeks (subscribers, requests, failures, run gaps)
- daily.json   - per-day totals kept forever (what history drops is still counted here)
- events.json  - every "schedule published / changed" event per queue (how often ZTOE changes plans)
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from .schedule import KYIV

MAX_RUNS = 4500  # ~4 weeks at one run per ~10 minutes
MAX_EVENTS = 20000


def _read(path: Path, empty):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty


def _write(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def merge_run(directory: Path, record: dict | None, run: dict) -> dict:
    """Add a run to the dashboard files in `directory`. `record` is None when the bot crashed before writing it.

    `run` carries what only the workflow knows: run_id, event (schedule / workflow_dispatch), outcome
    (success / failure / cancelled) and url.
    """
    entry = dict(record or {"ts": datetime.now(KYIV).isoformat(timespec="seconds")})
    events = entry.pop("schedule_events", [])
    entry.update({k: v for k, v in run.items() if v not in (None, "")})
    if record is None:
        entry.setdefault("failures", {})["run_crashed"] = 1

    history = _read(directory / "history.json", [])
    history.append(entry)
    _write(directory / "history.json", history[-MAX_RUNS:])

    all_events = _read(directory / "events.json", [])
    all_events.extend(events)
    _write(directory / "events.json", all_events[-MAX_EVENTS:])

    daily = _read(directory / "daily.json", {})
    day = daily.setdefault(entry["ts"][:10], {"runs": 0, "failed_runs": 0, "requests": 0, "alerts": 0,
                                              "failures": {}, "subscribers_max": 0})
    day["runs"] += 1
    day["failed_runs"] += int(entry.get("outcome", "success") != "success")
    day["requests"] += sum(v for k, v in entry.get("requests", {}).items() if k != "superseded")
    day["alerts"] += entry.get("outcomes", {}).get("alert_sent", 0)
    for name, count in entry.get("failures", {}).items():
        day["failures"][name] = day["failures"].get(name, 0) + count
    if "subscribers" in entry:
        day["subscribers_max"] = max(day["subscribers_max"], entry["subscribers"])
        day["subscribers_last"] = entry["subscribers"]
    _write(directory / "daily.json", daily)
    return entry


def merge_from_files(directory: Path, record_path: Path, run: dict) -> dict:
    record = _read(record_path, None)
    return merge_run(directory, record if isinstance(record, dict) else None, run)
