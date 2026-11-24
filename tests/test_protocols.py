"""Exit protocols (break-even, partials, trailing runner), long-only, Binance volume and manage-only runs."""
import json

import numpy as np
import pandas as pd
import pytest

from bot.config import BAR_MS, COSTS_RT, load_config
from bot.run import Bot
from bot.signals import Signal
from tests.fake_exchange import FakeExchange, World
from tests.test_run import END, Alerts, signals, state, trades

SOL = "SOL-USDT"


@pytest.fixture
def env(tmp_path):
    def make(**extra):
        e = {"MODE": "challenge", "REPO_ROOT": str(tmp_path), "STATE_DIR": str(tmp_path / "state"),
             "CACHE_DIR": str(tmp_path / "cache"), "EXIT_PROTOCOL": "R1", "VOLUME_SOURCE": "blofin"}
        e.update(extra)
        return load_config(e)
    return make


def run(cfg, ex, w, **kw):
    alerts = Alerts()
    bot = Bot(cfg, ex, dry_run=False, now_ms=w.end_ms + 120_000, alerter=alerts, **kw)
    bot.run()
    return bot, alerts


def entered(env, **extra):
    w = World(END)
    w.set_breakout()
    ex = FakeExchange(w)
    cfg = env(**extra)
    run(cfg, ex, w)
    return cfg, w, ex


def trade(cfg):
    return state(cfg)["open_trades"][0]


def orders(ex):
    return sorted(ex.pending_tpsl(SOL), key=lambda o: (o.tp_trigger or 0))


# -- R1: entry ------------------------------------------------------------------
def test_r1_entry_full_stop_and_half_take_profit(env):
    cfg, w, ex = entered(env)
    t = trade(cfg)
    assert t["protocol"] == "R1" and t["side"] == "long"
    assert t["r_unit"] == pytest.approx(112 - t["stop0"])
    [p] = t["partials"]
    assert p["r"] == 3.0 and float(p["contracts"]) == pytest.approx(float(t["contracts"]) / 2, abs=0.01)
    assert p["price"] == pytest.approx(112 + 3 * t["r_unit"])
    # entry attached only the stop; the bot then placed: full-size stop + half-size take-profit
    entry_call = next(c for c in ex.calls if c[0] == "market_entry")
    o = orders(ex)
    assert len(o) == 2
    sl_only, tp_only = o
    assert sl_only.tp_trigger is None and sl_only.sl_trigger == pytest.approx(t["stop0"], abs=0.01)
    assert tp_only.sl_trigger is None and tp_only.size == pytest.approx(float(p["contracts"]))
    assert t["max_bars"] == 360


# -- break-even ------------------------------------------------------------------
def test_break_even_at_2R(env):
    cfg, w, ex = entered(env)
    w.advance(1, {SOL: 113.0}, ranges={SOL: (112.5, 118.0)})  # high 118 > 2R (~117.8)
    _, alerts = run(cfg, ex, w)
    t = trade(cfg)
    assert t["be_done"] and t["stop"] == pytest.approx(112 * (1 + COSTS_RT))
    sl = next(o for o in ex.pending_tpsl(SOL) if o.sl_trigger is not None)
    assert sl.sl_trigger == pytest.approx(112 * (1 + COSTS_RT), abs=0.01)
    assert any("break-even" in a for a in alerts.sent)
    assert any(r["event"] == "stop_moved" for r in trades(cfg))


def test_no_break_even_below_2R(env):
    cfg, w, ex = entered(env)
    w.advance(1, {SOL: 113.0}, ranges={SOL: (112.5, 117.0)})  # high below 2R
    run(cfg, ex, w)
    t = trade(cfg)
    assert not t["be_done"] and t["stop"] == pytest.approx(t["stop0"])


def test_stop_moved_past_price_closes_at_market(env):
    cfg, w, ex = entered(env)
    w.advance(1, {SOL: 111.5}, ranges={SOL: (111.0, 118.0)})  # reached 2R, now back below break-even
    run(cfg, ex, w)
    st = state(cfg)
    assert st["open_trades"] == []
    assert st["closed_trades"][0]["exit_reason"] == "stop moved past price between runs"


# -- partial + trailing runner ------------------------------------------------------
def test_partial_then_trailing_runner_then_stop(env):
    cfg, w, ex = entered(env)
    t0 = trade(cfg)
    half = float(t0["partials"][0]["contracts"])
    full = float(t0["contracts"])
    tp_px = t0["partials"][0]["price"]
    # price runs through 3R: the exchange fills the half take-profit
    w.advance(1, {SOL: 120.9}, ranges={SOL: (112.5, 121.0)})
    ex.trigger_tp(SOL)
    _, alerts = run(cfg, ex, w)
    t = trade(cfg)
    assert t["partials"][0]["done"] and float(t["contracts"]) == pytest.approx(full - half, abs=0.01)
    assert t["trail_on"] and t["be_done"]
    assert t["stop"] > 112 * (1 + COSTS_RT)          # trail is above break-even
    assert any("PARTIAL" in a for a in alerts.sent)
    st = state(cfg)
    partial_fee = float(ex.fill_log[1]["fee"])  # fill 0 = entry, fill 1 = the half take-profit
    assert st["realized_pnl"] == pytest.approx((tp_px - 112) * half - partial_fee, rel=1e-6)
    # only a stop for the rest remains on the exchange
    o = ex.pending_tpsl(SOL)
    assert len(o) == 1 and o[0].tp_trigger is None and o[0].size == pytest.approx(full - half, abs=0.01)
    stop_after_first = t["stop"]
    # a new high ratchets the trail up, never down
    w.advance(1, {SOL: 126.0}, ranges={SOL: (121.0, 127.0)})
    run(cfg, ex, w)
    assert trade(cfg)["stop"] > stop_after_first
    w.advance(1, {SOL: 124.0}, ranges={SOL: (123.5, 125.0)})
    run(cfg, ex, w)
    trailing = trade(cfg)["stop"]
    # runner stopped out
    ex.trigger_stop(SOL)
    w.advance(1, {SOL: trailing - 0.5}, ranges={SOL: (trailing - 1, trailing + 0.5)})
    run(cfg, ex, w)
    st = state(cfg)
    c = st["closed_trades"][0]
    assert c["exit_reason"] == "trailing stop"
    gross = (tp_px - 112) * half + (trailing - 112) * (full - half)
    assert c["gross_pnl"] == pytest.approx(gross, rel=1e-3)
    assert c["r_multiple"] > 1.5
    assert st["realized_pnl"] == pytest.approx(c["net_pnl"])       # partial + rest booked exactly once
    assert st["consecutive_losses"] == 0
    assert ex.pending_tpsl(SOL) == []


def test_r4_two_partials(env):
    cfg, w, ex = entered(env, EXIT_PROTOCOL="R4")
    t = trade(cfg)
    assert [p["r"] for p in t["partials"]] == [2.0, 3.0]
    assert len(ex.pending_tpsl(SOL)) == 3  # stop + two take-profits
    w.advance(1, {SOL: 118.5}, ranges={SOL: (112.5, 118.6)})
    ex.trigger_tp(SOL)  # the 2R quarter fills
    run(cfg, ex, w)
    t = trade(cfg)
    assert [p["done"] for p in t["partials"]] == [True, False]
    assert t["be_done"] and not t["trail_on"]
    o = ex.pending_tpsl(SOL)
    assert len(o) == 2 and sum(1 for x in o if x.tp_trigger) == 1


def test_be2_keeps_single_combined_order(env):
    cfg, w, ex = entered(env, EXIT_PROTOCOL="BE2")
    o = ex.pending_tpsl(SOL)
    assert len(o) == 1 and o[0].tp_trigger is not None and o[0].sl_trigger is not None
    assert trade(cfg)["max_bars"] == 60


def test_time_exit_uses_protocol_limit(env):
    cfg, w, ex = entered(env)
    w.advance(60, {SOL: 113.0}, ranges={SOL: (112.6, 113.4)})
    run(cfg, ex, w)
    assert len(state(cfg)["open_trades"]) == 1  # R1 allows 360 bars, not 60


# -- long-only ---------------------------------------------------------------------
def test_long_only_skips_shorts(env):
    w = World(END)
    ex = FakeExchange(w)
    cfg = env()  # LONG_ONLY defaults to true
    bot, _ = run(cfg, ex, w)
    sig = Signal(symbol="SOL", bar_ts=bot.latest_close - BAR_MS, bar_close_ts=bot.latest_close, side="short",
                 level=101.0, close=99.0, prev_close=101.5, atr=1.0, stop=101.5, stop_pct=0.025, vol_z=3.0,
                 vol_rank=0.5)
    bot.consider(sig, SOL, 0, {"equity": 1e6, "available": 1e6})
    assert signals(cfg)[-1]["reason"] == "long-only mode (shorts disabled)"
    assert "market_entry" not in [c[0] for c in ex.calls]


# -- volume source -------------------------------------------------------------------
def test_binance_volume_drives_the_signal(env):
    w = World(END)
    w.set_breakout()
    ex = FakeExchange(w)
    flat = lambda inst, n, now: pd.DataFrame({"ts": w.frames[inst].ts, "volume": 100.0 + (w.frames[inst].index % 2)})
    cfg = env(VOLUME_SOURCE="binance")
    bot, _ = run(cfg, ex, w, volume_fetcher=flat)  # Binance shows no spike -> no trade
    assert bot.vol_src["SOL"] == "binance"
    assert "market_entry" not in [c[0] for c in ex.calls]


def test_binance_volume_spike_trades_and_is_logged(env):
    w = World(END)
    w.set_breakout()
    ex = FakeExchange(w)
    same = lambda inst, n, now: w.frames[inst][["ts", "volume"]].copy()
    cfg = env(VOLUME_SOURCE="binance")
    run(cfg, ex, w, volume_fetcher=same)
    assert [c[0] for c in ex.calls].count("market_entry") == 1
    assert "volume: binance" in signals(cfg)[0]["note"]
    assert trade(cfg)["volume_source"] == "binance"


def test_binance_volume_failure_falls_back_to_blofin(env):
    w = World(END)
    w.set_breakout()
    ex = FakeExchange(w)

    def broken(inst, n, now):
        raise ConnectionError("451 restricted location")
    cfg = env(VOLUME_SOURCE="binance")
    bot, alerts = run(cfg, ex, w, volume_fetcher=broken)
    assert bot.vol_src["SOL"].startswith("blofin (Binance fallback")
    assert any("Binance volume unavailable" in a for a in alerts.sent)
    assert [c[0] for c in ex.calls].count("market_entry") == 1  # BloFin volume still has the spike


# -- manage-only runs ----------------------------------------------------------------
def test_manage_only_does_not_trade_or_consume_the_bar(env):
    w = World(END)
    w.set_breakout()
    ex = FakeExchange(w)
    cfg = env()
    run(cfg, ex, w, manage_only=True)
    assert "market_entry" not in [c[0] for c in ex.calls]
    assert state(cfg)["last_processed_bar_close_ts"] is None
    run(cfg, ex, w)  # the next full run still takes the signal
    assert [c[0] for c in ex.calls].count("market_entry") == 1


def test_manage_only_moves_stops(env):
    cfg, w, ex = entered(env)
    w.advance(1, {SOL: 113.0}, ranges={SOL: (112.5, 118.0)})
    run(cfg, ex, w, manage_only=True)
    assert trade(cfg)["be_done"]


# -- open-risk cap counts risk still at stake -------------------------------------------
def test_trade_at_break_even_frees_open_risk(env):
    cfg, w, ex = entered(env)
    w.advance(1, {SOL: 113.0}, ranges={SOL: (112.5, 118.0)})
    bot, _ = run(cfg, ex, w)
    t = trade(cfg)
    assert Bot.risk_at_stop(t) == 0.0
    assert bot.snapshot().open_initial_risk == 0.0


def test_closed_runner_does_not_trigger_false_limit_breach(env):
    """Regression: a closed trade's size is 0 afterwards; the between-runs worst-case check and the
    reconstructed day-start equity must use the size that was open, or a winning runner looks like a crash."""
    cfg, w, ex = entered(env)
    w.advance(1, {SOL: 120.9}, ranges={SOL: (112.5, 121.0)})
    ex.trigger_tp(SOL)
    run(cfg, ex, w)
    w.advance(4, {SOL: 127.0}, ranges={SOL: (126.0, 128.0)})  # runner well in profit, across a day boundary
    run(cfg, ex, w)
    ex.trigger_stop(SOL)
    stop = trade(cfg)["stop"]
    w.advance(1, {SOL: stop - 0.5}, ranges={SOL: (stop - 1, 127.5)})
    run(cfg, ex, w)
    w.advance(3, {SOL: 100.0}, ranges={SOL: (99.5, 101.0)})   # price collapses after the trade is closed
    run(cfg, ex, w)
    st = state(cfg)
    assert st["closed_trades"][0]["net_pnl"] > 0
    assert not st["failed"], st["failed_reason"]
