"""JSON state file. Written atomically (temp file + rename) so a crash never corrupts it."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

STATE_VERSION = 1


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ms_to_iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_state(mode: str, account_size: float) -> dict:
    return {
        "version": STATE_VERSION,
        "created_at": utcnow_iso(),
        "mode": mode,
        "account_size": account_size,
        "failed": False,
        "failed_reason": None,
        "failed_at": None,
        "consecutive_losses": 0,
        "realized_pnl": 0.0,           # net of fees and funding, closed trades only
        "open_trades": [],             # status "pending" (order sent, not confirmed) or "open"
        "closed_trades": [],
        "last_entry_close_ts": {},     # symbol -> close time (ms) of the bar of its last entry
        "last_processed_bar_close_ts": None,
        "day_start_equity": {},        # "YYYY-MM-DD" -> simulated equity at 00:00 UTC
        "equity_history": [],          # one row per run
        "last_daily_summary": None,
        "unmanaged_positions": [],     # positions on the exchange the bot did not open
    }


def load_state(path: Path, mode: str, account_size: float) -> dict:
    if not path.exists():
        return new_state(mode, account_size)
    with open(path) as f:
        state = json.load(f)
    base = new_state(mode, account_size)
    for k, v in base.items():
        state.setdefault(k, v)
    return state


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".state-", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(state, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
