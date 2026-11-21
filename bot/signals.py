"""Entry signal on a just-closed 4h bar, and the per-signal filters.

Pure functions only; shared by the live runner and the replay script.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from .config import (BAR_MS, BREAK_ATR, COOLDOWN_BARS, MAX_STOP_PCT, MIN_STOP_PCT, STOP_ATR, VOL_Z_MIN,
                     ModeParams)


@dataclass
class Signal:
    symbol: str
    bar_ts: int          # open time of the signal bar (ms)
    bar_close_ts: int    # close time of the signal bar (ms)
    side: str            # "long" | "short"
    level: float
    close: float
    prev_close: float
    atr: float
    stop: float
    stop_pct: float
    vol_z: float
    vol_rank: float

    def target(self, target_r: float) -> float:
        r = abs(self.close - self.stop)
        return self.close + target_r * r if self.side == "long" else self.close - target_r * r

    def as_dict(self) -> dict:
        return asdict(self)


def _nan(x) -> bool:
    return x is None or (isinstance(x, float) and math.isnan(x))


def detect_signal(symbol: str, df: pd.DataFrame, i: int, level_prices: np.ndarray) -> Signal | None:
    """Breakout signal on bar `i` of an indicator frame (see indicators.add_indicators)."""
    if i < 1 or len(level_prices) == 0:
        return None
    row = df.iloc[i]
    atr, vz = float(row["atr"]), float(row["vol_z"])
    if _nan(atr) or _nan(vz) or not vz > VOL_Z_MIN:
        return None
    close, prev = float(row["close"]), float(df["close"].iloc[i - 1])
    longs = level_prices[(close > level_prices + BREAK_ATR * atr) & (prev <= level_prices)]
    shorts = level_prices[(close < level_prices - BREAK_ATR * atr) & (prev >= level_prices)]
    if len(longs):
        side, level = "long", float(longs.max())
        stop = level - STOP_ATR * atr
    elif len(shorts):
        side, level = "short", float(shorts.min())
        stop = level + STOP_ATR * atr
    else:
        return None
    return Signal(
        symbol=symbol, bar_ts=int(row["ts"]), bar_close_ts=int(row["ts"]) + BAR_MS, side=side, level=level,
        close=close, prev_close=prev, atr=atr, stop=stop, stop_pct=abs(close - stop) / close, vol_z=vz,
        vol_rank=float(row["vol_rank"]) if not _nan(float(row["vol_rank"])) else float("nan"),
    )


def signal_filter_reason(sig: Signal, mode: ModeParams, btc_trend: int, last_entry_close_ts: int | None) -> str | None:
    """Reason to skip this signal before any account checks, or None if it passes."""
    if sig.stop_pct < MIN_STOP_PCT:
        return f"stop distance {sig.stop_pct:.4%} < {MIN_STOP_PCT:.1%}"
    if sig.stop_pct > MAX_STOP_PCT:
        return f"stop distance {sig.stop_pct:.4%} > {MAX_STOP_PCT:.0%}"
    if last_entry_close_ts is not None and sig.bar_close_ts - last_entry_close_ts < COOLDOWN_BARS * BAR_MS:
        return f"cooldown: previous entry {(sig.bar_close_ts - last_entry_close_ts) // BAR_MS} bars ago"
    if mode.btc_trend_filter:
        want = 1 if sig.side == "long" else -1
        if btc_trend == 0:
            return "BTC trend unknown (not enough daily history)"
        if btc_trend != want:
            return f"BTC trend {btc_trend:+d} does not match {sig.side}"
    if mode.vol_rank_max is not None:
        if _nan(sig.vol_rank):
            return "volatility rank unavailable (<300 bars)"
        if sig.vol_rank > mode.vol_rank_max:
            return f"volatility rank {sig.vol_rank:.3f} > {mode.vol_rank_max:.2f}"
    return None
