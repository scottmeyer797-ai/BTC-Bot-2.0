import numpy as np
import pandas as pd
import pytest

from bot.config import BAR_MS, MODES
from bot.signals import detect_signal, signal_filter_reason


def frame(prev_close, close, atr=1.0, vol_z=2.5, vol_rank=0.5):
    return pd.DataFrame({
        "ts": [0, BAR_MS], "close": [prev_close, close], "atr": [atr, atr], "vol_z": [0.0, vol_z],
        "vol_rank": [vol_rank, vol_rank],
    })


def test_long_breakout_takes_highest_level():
    sig = detect_signal("X", frame(99.0, 101.0), 1, np.array([98.0, 99.5, 100.0, 100.9]))
    # 100.9 fails close > L + 0.2*ATR (101.1); 98 fails prev <= L; highest valid is 100.0
    assert sig.side == "long" and sig.level == 100.0
    assert sig.stop == pytest.approx(99.5)
    assert sig.target(3.0) == pytest.approx(101.0 + 3 * 1.5)
    assert sig.bar_close_ts == 2 * BAR_MS


def test_short_breakdown_takes_lowest_level():
    sig = detect_signal("X", frame(101.0, 99.0), 1, np.array([102.0, 100.5, 100.0, 99.1]))
    assert sig.side == "short" and sig.level == 100.0
    assert sig.stop == pytest.approx(100.5)
    assert sig.target(5.0) == pytest.approx(99.0 - 5 * 1.5)


def test_needs_volume_z_strictly_above_2():
    assert detect_signal("X", frame(99.0, 101.0, vol_z=2.0), 1, np.array([100.0])) is None
    assert detect_signal("X", frame(99.0, 101.0, vol_z=2.01), 1, np.array([100.0])) is not None


def test_needs_previous_close_on_other_side():
    assert detect_signal("X", frame(100.1, 101.0), 1, np.array([100.0])) is None
    assert detect_signal("X", frame(100.0, 101.0), 1, np.array([100.0])) is not None  # prev <= L


def test_break_must_exceed_0_2_atr():
    assert detect_signal("X", frame(99.0, 100.2), 1, np.array([100.0])) is None  # not strictly >
    assert detect_signal("X", frame(99.0, 100.21), 1, np.array([100.0])) is not None


def _sig(**kw):
    s = detect_signal("X", frame(99.0, 101.0, **{k: v for k, v in kw.items() if k in ("atr", "vol_rank")}), 1,
                      np.array([100.0]))
    return s


@pytest.mark.parametrize("close,atr,ok", [
    (100.05, 0.2, False),   # stop 99.90 -> 0.15% < 0.3%
    (100.25, 0.5, True),    # stop 99.75 -> 0.50%
    (105.0, 8.0, True),     # stop 96.00 -> 8.6%
    (105.0, 20.0, False),   # stop 90.00 -> 14.3% > 10%
])
def test_stop_distance_bounds(close, atr, ok):
    s = detect_signal("X", frame(99.9, close, atr=atr), 1, np.array([100.0]))
    assert s is not None
    reason = signal_filter_reason(s, MODES["challenge"], 0, None)
    assert (reason is None) == ok, (s.stop_pct, reason)


def test_cooldown_6_bars():
    s = _sig()
    m = MODES["challenge"]
    assert "cooldown" in signal_filter_reason(s, m, 0, s.bar_close_ts - 5 * BAR_MS)
    assert signal_filter_reason(s, m, 0, s.bar_close_ts - 6 * BAR_MS) is None


def test_funded_filters():
    m = MODES["funded"]
    s = _sig(vol_rank=0.5)
    assert signal_filter_reason(s, m, +1, None) is None
    assert "BTC trend" in signal_filter_reason(s, m, -1, None)
    assert "unknown" in signal_filter_reason(s, m, 0, None)
    assert "volatility rank" in signal_filter_reason(_sig(vol_rank=0.91), m, +1, None)
    assert signal_filter_reason(_sig(vol_rank=0.90), m, +1, None) is None
    assert "unavailable" in signal_filter_reason(_sig(vol_rank=float("nan")), m, +1, None)
    # challenge ignores both
    assert signal_filter_reason(_sig(vol_rank=0.99), MODES["challenge"], -1, None) is None
