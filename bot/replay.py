"""Replay the signal logic over historical 4h candles and list the trades it would have taken.

Uses exactly the live signal code (detect_signal / signal_filter_reason /
levels_at with usable_from), one position per symbol, the 6-bar cooldown, the
open-risk cap and the loss-streak rule. Exits are simulated on 4h bars:
stop first if a bar touches both stop and target (conservative), otherwise
target, otherwise market close after 60 bars. No fees, funding or slippage;
the prop-firm daily/drawdown guards are not simulated.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from .config import BAR_MS, TIME_EXIT_BARS, ModeParams
from .indicators import add_indicators, btc_trend_at, btc_trend_by_day, daily_candles, levels_at, swing_levels
from .risk import effective_risk_pct, update_loss_streak
from .signals import detect_signal, signal_filter_reason


@dataclass
class ReplayTrade:
    symbol: str
    side: str
    entry_close_ts: int
    entry: float
    stop: float
    target: float
    level: float
    risk_pct: float
    exit_ts: int | None = None
    exit: float | None = None
    reason: str | None = None
    r: float | None = None
    bars: int = 0


def replay(frames: dict[str, pd.DataFrame], mode: ModeParams, start_ms: int, end_ms: int | None = None):
    """Returns (trades, skipped) for signal bars closing in [start_ms, end_ms]."""
    ind = {s: add_indicators(df) for s, df in frames.items()}
    as_of = max(int(df["ts"].iloc[-1]) + BAR_MS for df in frames.values())
    end_ms = end_ms or as_of
    levels = {s: swing_levels(daily_candles(df, as_of)) for s, df in frames.items()}
    trend = btc_trend_by_day(daily_candles(frames["BTC"], as_of)) if "BTC" in frames else {}
    by_close = {s: d.set_index("close_ts") for s, d in ind.items()}
    closes = sorted({int(c) for d in ind.values() for c in d["close_ts"] if start_ms <= c <= end_ms})

    open_t: dict[str, ReplayTrade] = {}
    done: list[ReplayTrade] = []
    skipped: list[tuple] = []
    last_entry: dict[str, int] = {}
    streak = 0
    for c in closes:
        # exits on this bar for trades entered earlier
        for sym, t in list(open_t.items()):
            d = by_close[sym]
            if c not in d.index or c <= t.entry_close_ts:
                continue
            t.bars = int((c - t.entry_close_ts) // BAR_MS)
            hi, lo, cl = float(d.at[c, "high"]), float(d.at[c, "low"]), float(d.at[c, "close"])
            long = t.side == "long"
            if (lo <= t.stop) if long else (hi >= t.stop):
                t.exit, t.reason = t.stop, "stop"
            elif (hi >= t.target) if long else (lo <= t.target):
                t.exit, t.reason = t.target, "target"
            elif t.bars >= TIME_EXIT_BARS:
                t.exit, t.reason = cl, "time"
            if t.exit is not None:
                risk = abs(t.entry - t.stop)
                t.r = ((t.exit - t.entry) if long else (t.entry - t.exit)) / risk
                t.exit_ts = c
                streak = update_loss_streak(streak, t.r)
                done.append(open_t.pop(sym))
        # entries
        for sym, d in ind.items():
            rows = d.index[d["close_ts"] == c]
            if not len(rows):
                continue
            i = int(rows[0])
            sig = detect_signal(sym, d, i, levels_at(levels[sym], c))
            if sig is None:
                continue
            tr = btc_trend_at(trend, c)
            reason = signal_filter_reason(sig, mode, tr, last_entry.get(sym))
            risk_pct = effective_risk_pct(mode, streak)
            if reason is None and sym in open_t:
                reason = "position already open on this symbol"
            if reason is None and sum(t.risk_pct for t in open_t.values()) + risk_pct > mode.max_open_risk + 1e-9:
                reason = "max open risk"
            if reason:
                skipped.append((c, sym, sig.side, reason))
                continue
            open_t[sym] = ReplayTrade(sym, sig.side, c, sig.close, sig.stop, sig.target(mode.target_r), sig.level,
                                      risk_pct)
            last_entry[sym] = c
    return done + list(open_t.values()), skipped


def summarize(trades: list[ReplayTrade]) -> dict:
    closed = [t for t in trades if t.r is not None]
    n = len(closed)
    wins = sum(1 for t in closed if t.r > 0)
    total = sum(t.r for t in closed)
    return {"closed": n, "open": len(trades) - n, "win_rate": wins / n if n else 0.0,
            "avg_r": total / n if n else 0.0, "total_r": total}
