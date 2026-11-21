import pandas as pd
import pytest

from bot.config import BAR_MS, MODES
from bot.risk import (Snapshot, TradeExposure, breach_reason, effective_risk_pct, guard_block_reason,
                      open_risk_cap_reason, update_loss_streak, worst_equity_path)

C, F = MODES["challenge"], MODES["funded"]


def snap(equity=100_000, day_start=100_000, init=0.0, rem=0.0, size=100_000):
    return Snapshot(size, equity, day_start, init, rem)


# -- loss streak -------------------------------------------------------------
def test_loss_streak_halves_after_three_losses_until_a_win():
    s = 0
    risks = []
    for pnl in [-1, -1, -1, -1, 0, -1, +1, -1]:
        risks.append(effective_risk_pct(C, s))
        s = update_loss_streak(s, pnl)
    assert risks == [0.02, 0.02, 0.02, 0.01, 0.01, 0.01, 0.01, 0.02]
    assert effective_risk_pct(F, 3) == pytest.approx(0.00375)


# -- open-risk cap -------------------------------------------------------------
def test_open_risk_cap():
    assert open_risk_cap_reason(C, snap(init=2000), 2000) is None  # exactly 4%
    assert "max open risk" in open_risk_cap_reason(C, snap(init=2000.01), 2000)
    assert open_risk_cap_reason(F, snap(init=2250), 750) is None   # 3%
    assert open_risk_cap_reason(F, snap(init=2251), 750) is not None


# -- pre-trade guards ---------------------------------------------------------
def test_daily_guard_blocks_when_it_would_reach_the_limit():
    # challenge: 5%. lost 2000 today, 1000 still at risk, new 2000 -> exactly 5% -> block
    assert "daily-loss" in guard_block_reason(C, snap(equity=98_000, rem=1000), 2000)
    assert guard_block_reason(C, snap(equity=98_000, rem=999), 2000) is None
    # funded: 4.5%
    assert "daily-loss" in guard_block_reason(F, snap(equity=96_000, rem=0), 500)
    assert guard_block_reason(F, snap(equity=96_000, rem=0), 499) is None


def test_daily_guard_measured_from_day_start_equity():
    s = snap(equity=103_000, day_start=105_000, rem=1000)  # down 2000 today
    assert "daily-loss" in guard_block_reason(C, s, 2250 + 1)  # (2000+1000+2251)/105000 = 5.0%
    assert guard_block_reason(C, s, 2000) is None


def test_drawdown_guard_static_from_start():
    # down 7% overall, 0 today; 2% open, 1% new -> 10% -> block
    s = snap(equity=93_000, day_start=93_000, rem=2000)
    assert "drawdown" in guard_block_reason(C, s, 1000)
    assert guard_block_reason(C, s, 999) is None
    # funded 9%
    assert "drawdown" in guard_block_reason(F, snap(equity=93_000, day_start=93_000, rem=1250), 750)


def test_gains_do_not_create_negative_loss():
    s = snap(equity=110_000, day_start=100_000)
    assert s.todays_loss == 0 and s.drawdown == 0


# -- actual breach --------------------------------------------------------------
def test_breach_detection():
    assert breach_reason(100_000, 95_001, 100_000) is None
    assert "DAILY" in breach_reason(100_000, 95_000, 100_000)
    assert "DRAWDOWN" in breach_reason(100_000, 90_000, 91_000)
    assert breach_reason(100_000, 90_001, 91_000) is None


# -- worst case between runs ---------------------------------------------------
def test_worst_equity_path_uses_adverse_extreme_clamped_at_stop():
    t0 = 1_000 * BAR_MS
    bars = {"BTC": pd.DataFrame({"ts": [t0, t0 + BAR_MS], "high": [110.0, 105.0], "low": [96.0, 80.0]})}
    ex = [TradeExposure("BTC", "long", t0 - 1, None, 100.0, 90.0, qty=10)]
    path = worst_equity_path(1000.0, ex, bars, t0, t0 + 2 * BAR_MS, BAR_MS)
    assert path == [(t0 + BAR_MS, 1000.0 - 40.0), (t0 + 2 * BAR_MS, 1000.0 - 100.0)]  # 2nd bar clamped at stop 90


def test_worst_equity_path_short_and_closed_trade():
    t0 = 1_000 * BAR_MS
    bars = {"ETH": pd.DataFrame({"ts": [t0, t0 + BAR_MS], "high": [52.0, 51.0], "low": [49.0, 48.0]})}
    ex = [TradeExposure("ETH", "short", t0 - 1, t0 + BAR_MS, 50.0, 55.0, qty=2, realized_pnl=-3.0)]
    path = worst_equity_path(0.0, ex, bars, t0, t0 + 2 * BAR_MS, BAR_MS)
    assert path == [(t0 + BAR_MS, -4.0), (t0 + 2 * BAR_MS, -3.0)]
