import numpy as np
import pytest

from bot.indicators import DAY_MS, daily_candles, levels_at, swing_levels
from tests.helpers import T0, bars_from_daily, random_walk_bars


def _flat(n, h=100.0, l=90.0):
    return [h] * n, [l] * n


def test_daily_candles_aggregate_utc_days_and_drop_open_day():
    highs, lows = _flat(3)
    highs[1], lows[1] = 120.0, 80.0
    df = bars_from_daily(highs, lows)
    d = daily_candles(df, as_of_ms=T0 + 2 * DAY_MS + 4 * 3600_000)  # day 2 not closed yet
    assert list(d["day"]) == [T0, T0 + DAY_MS]
    assert d.loc[1, "high"] == 120.0 and d.loc[1, "low"] == 80.0
    assert (d["bars"] == 6).all()


def test_swing_high_needs_strictly_higher_than_5_each_side():
    highs, lows = _flat(21)
    highs[10] = 150.0
    lv = swing_levels(daily_candles(bars_from_daily(highs, lows), T0 + 21 * DAY_MS))
    hi = lv[lv.kind == "high"]
    assert list(hi["price"]) == [150.0]
    assert int(hi["day"].iloc[0]) == T0 + 10 * DAY_MS


def test_tie_is_not_a_swing():
    highs, lows = _flat(21)
    highs[10] = 150.0
    highs[13] = 150.0
    lv = swing_levels(daily_candles(bars_from_daily(highs, lows), T0 + 21 * DAY_MS))
    assert lv[lv.kind == "high"].empty


def test_swing_low_detected():
    highs, lows = _flat(21)
    lows[8] = 50.0
    lv = swing_levels(daily_candles(bars_from_daily(highs, lows), T0 + 21 * DAY_MS))
    assert list(lv[lv.kind == "low"]["price"]) == [50.0]


def test_level_not_usable_before_its_5_confirming_days_close():
    """No look-ahead: swing on day 10 is usable only from the close of day 15 (= start of day 16)."""
    highs, lows = _flat(25)
    highs[10] = 150.0
    df = bars_from_daily(highs, lows)
    usable_at = T0 + 16 * DAY_MS
    for t in range(int(T0 + 10 * DAY_MS), int(T0 + 20 * DAY_MS) + 1, 4 * 3600_000):
        # rebuild everything only from data known at time t, as the live bot does
        known = df[df.ts + 4 * 3600_000 <= t]
        lv = swing_levels(daily_candles(known, t))
        visible = 150.0 in levels_at(lv, t)
        assert visible == (t >= usable_at), f"t={(t - T0) / DAY_MS:.3f}d"


def test_full_history_levels_match_truncated_history():
    """Computing levels once on all data and filtering by time gives the same answer as truncation."""
    df = random_walk_bars(6 * 200, seed=3)
    full = swing_levels(daily_candles(df, int(df.ts.iloc[-1]) + 4 * 3600_000))
    for k in range(400, len(df), 37):
        t = int(df.ts.iloc[k]) + 4 * 3600_000
        trunc = swing_levels(daily_candles(df.iloc[:k + 1], t))
        assert sorted(levels_at(full, t)) == sorted(levels_at(trunc, t))


def test_levels_expire_after_365_days():
    highs, lows = _flat(400)
    highs[10] = 150.0
    df = bars_from_daily(highs, lows)
    lv = swing_levels(daily_candles(df, T0 + 400 * DAY_MS))
    assert 150.0 in levels_at(lv, T0 + (10 + 365) * DAY_MS)
    assert 150.0 not in levels_at(lv, T0 + (10 + 366) * DAY_MS)
