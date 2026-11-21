"""Append-only CSV logs: logs/signals.csv and logs/trades.csv."""
from __future__ import annotations

import csv
from pathlib import Path

from .state import utcnow_iso

SIGNAL_FIELDS = ["run_time", "bar_close", "symbol", "side", "level", "close", "atr", "stop", "target", "stop_pct",
                 "vol_z", "vol_rank", "btc_trend", "mode", "action", "reason", "risk_pct", "risk_amount",
                 "contracts", "leverage", "note", "dry_run"]

TRADE_FIELDS = ["time", "event", "trade_id", "symbol", "side", "order_id", "price", "contracts", "notional",
                "stop", "target", "pnl", "fee", "funding", "net_pnl", "r_multiple", "equity", "details", "dry_run"]


class Journal:
    def __init__(self, log_dir: Path, dry_run: bool = False):
        self.dir = Path(log_dir)
        self.dry_run = dry_run
        self.dir.mkdir(parents=True, exist_ok=True)

    def _append(self, name: str, fields: list[str], row: dict) -> None:
        path = self.dir / name
        new = not path.exists()
        with open(path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            if new:
                w.writeheader()
            w.writerow({k: _fmt(row.get(k)) for k in fields})

    def signal(self, **row) -> None:
        row.setdefault("run_time", utcnow_iso())
        row["dry_run"] = self.dry_run
        self._append("signals.csv", SIGNAL_FIELDS, row)

    def trade(self, event: str, **row) -> None:
        row.setdefault("time", utcnow_iso())
        row["event"] = event
        row["dry_run"] = self.dry_run
        self._append("trades.csv", TRADE_FIELDS, row)


def _fmt(v):
    if isinstance(v, float):
        return f"{v:.10g}"
    return "" if v is None else v
