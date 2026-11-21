from decimal import Decimal

import pytest

from bot.exchange import Instrument
from bot.sizing import size_position


def inst(cv="0.001", lot="0.1", min_size="0.1", max_mkt="100000", max_lev=150):
    return Instrument("BTC-USDT", Decimal(cv), Decimal(lot), Decimal(min_size), Decimal("0.1"), Decimal(max_mkt),
                      max_lev)


def test_basic_size_rounds_down_to_lot():
    # 2% of 100k = 2000 risk; stop distance 1000 -> 2 BTC = 2000 contracts of 0.001
    r = size_position(inst(), 100_000, 0.02, entry=50_000, stop=49_000)
    assert r.contracts == Decimal("2000.0") and r.skip_reason is None and r.note is None
    assert r.risk_amount == pytest.approx(2000)
    assert r.notional == pytest.approx(100_000)
    assert r.leverage == 1


def test_rounding_never_rounds_up():
    r = size_position(inst(lot="1", min_size="1", cv="1"), 10_000, 0.02, entry=20.0, stop=19.3)
    assert r.contracts == Decimal(285)  # 200 / 0.7 = 285.7
    assert r.risk_amount <= 200


def test_leverage_just_high_enough():
    # stop 0.8%: notional = 2000/0.008 = 250k = 2.5x equity -> 3x
    r = size_position(inst(), 100_000, 0.02, entry=50_000, stop=49_600)
    assert r.leverage == 3 and r.note is None


def test_leverage_cap_shrinks_position():
    # stop 0.3%: notional would be 666k = 6.7x -> capped at 5x = 500k
    r = size_position(inst(), 100_000, 0.02, entry=50_000, stop=49_850)
    assert r.leverage == 5
    assert r.notional <= 500_000 + 1e-6
    assert "leverage cap" in r.note
    assert r.risk_amount < 2000


def test_insufficient_demo_margin_uses_available_balance():
    r = size_position(inst(), 100_000, 0.02, entry=50_000, stop=49_000, available_margin=10_000)
    assert r.leverage == 5 and r.notional <= 10_000 * 0.98 * 5 + 1e-6
    assert "insufficient demo margin" in r.note


def test_below_min_size_skips():
    r = size_position(inst(lot="1", min_size="1", cv="0.01"), 100, 0.0075, entry=600, stop=500)
    assert r.contracts == 0 and "below minimum" in r.skip_reason


def test_instrument_max_leverage_respected():
    r = size_position(inst(max_lev=3), 100_000, 0.02, entry=50_000, stop=49_850)
    assert r.leverage == 3 and r.notional <= 300_000 + 1e-6
