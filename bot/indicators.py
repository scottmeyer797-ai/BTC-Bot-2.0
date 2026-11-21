"""Indicators on 4h candles, daily candles, swing levels and BTC trend.

All functions are pure (no I/O) and take only confirmed (closed) candles.
Timestamps are UTC milliseconds; `ts` is a candle's OPEN time.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .config import (ATR_PERIOD, BAR_MS, BTC_SMA_DAYS, LEVEL_LOOKBACK_DAYS, SWING_SIDE_DAYS, VOL_RANK_MIN_BARS,
                     VOL_RANK_WINDOW, VOL_Z_PERIOD)

DAY_MS = 24 * 60 * 60 * 1000


def day_floor(ms: int) -> int:
    return (int(ms) // DAY_MS) * DAY_MS


def _pct_rank_last(w: np.ndarray) -> float:
    v = w[~np.isnan(w)]
    return float((v <= w[-1]).mean())


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Adds close_ts, atr, vol_z and vol_rank columns to a 4h candle frame (oldest first)."""
    df = df.reset_index(drop=True).copy()
    df["close_ts"] = df["ts"] + BAR_MS
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        df["high"] - df["low"],
        (df["high"] - prev_close).abs(),
        (df["low"] - prev_close).abs(),
    ], axis=1).max(axis=1)
    df["atr"] = tr.rolling(ATR_PERIOD).mean()
    vol = df["volume"]
    mean = vol.rolling(VOL_Z_PERIOD).mean()
    std = vol.rolling(VOL_Z_PERIOD).std()
    df["vol_z"] = (vol - mean) / std.replace(0, np.nan)
    natr = df["atr"] / df["close"]
    df["vol_rank"] = natr.rolling(VOL_RANK_WINDOW, min_periods=VOL_RANK_MIN_BARS).apply(_pct_rank_last, raw=True)
    df.loc[natr.isna(), "vol_rank"] = np.nan
    return df


def daily_candles(df4h: pd.DataFrame, as_of_ms: int) -> pd.DataFrame:
    """UTC daily candles built from 4h candles, keeping only days fully closed by `as_of_ms`."""
    d = df4h[["ts", "open", "high", "low", "close", "volume"]].copy()
    d["day"] = (d["ts"] // DAY_MS) * DAY_MS
    g = d.sort_values("ts").groupby("day", sort=True)
    out = pd.DataFrame({
        "open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
        "close": g["close"].last(), "volume": g["volume"].sum(), "bars": g["ts"].count(),
    }).reset_index()
    return out[out["day"] + DAY_MS <= as_of_ms].reset_index(drop=True)


def swing_levels(daily: pd.DataFrame) -> pd.DataFrame:
    """Swing highs/lows on daily candles.

    A swing high is a day whose high is strictly higher than the highs of the
    5 days before and the 5 days after it (lows likewise). It becomes usable
    only when the 5th later day has closed: usable_from = day + 6 days.
    """
    n, k = len(daily), SWING_SIDE_DAYS
    highs, lows, days = daily["high"].to_numpy(), daily["low"].to_numpy(), daily["day"].to_numpy()
    rows = []
    for j in range(k, n - k):
        nb_h = np.concatenate([highs[j - k:j], highs[j + 1:j + k + 1]])
        nb_l = np.concatenate([lows[j - k:j], lows[j + 1:j + k + 1]])
        usable = int(days[j + k]) + DAY_MS
        if highs[j] > nb_h.max():
            rows.append((int(days[j]), float(highs[j]), "high", usable))
        if lows[j] < nb_l.min():
            rows.append((int(days[j]), float(lows[j]), "low", usable))
    return pd.DataFrame(rows, columns=["day", "price", "kind", "usable_from"])


def levels_at(levels: pd.DataFrame, t_ms: int) -> np.ndarray:
    """Level prices usable at time `t_ms` (a bar close): confirmed and swing day within 365 days."""
    if levels.empty:
        return np.array([])
    oldest = day_floor(t_ms) - LEVEL_LOOKBACK_DAYS * DAY_MS
    m = (levels["usable_from"] <= t_ms) & (levels["day"] >= oldest)
    return levels.loc[m, "price"].to_numpy()


def btc_trend_by_day(btc_daily: pd.DataFrame) -> dict[int, int]:
    """Map day -> +1/-1: that day's close vs the 200-day SMA ending that day."""
    sma = btc_daily["close"].rolling(BTC_SMA_DAYS).mean()
    out = {}
    for day, close, s in zip(btc_daily["day"], btc_daily["close"], sma):
        if not np.isnan(s):
            out[int(day)] = 1 if close > s else -1
    return out


def btc_trend_at(trend_by_day: dict[int, int], t_ms: int) -> int:
    """BTC trend for a bar closing at `t_ms`, using yesterday's daily values. 0 if unknown."""
    yesterday = day_floor(t_ms) - DAY_MS
    return trend_by_day.get(yesterday, 0)
