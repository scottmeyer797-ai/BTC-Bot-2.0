import csv
import json

import pytest

from bot.config import BAR_MS, load_config
from bot.indicators import DAY_MS
from bot.run import Bot
from bot.state import load_state, save_state
from tests.fake_exchange import FakeExchange, World

END = (1_800_000_000_000 // DAY_MS) * DAY_MS + 8 * 3600_000  # a 08:00 UTC bar close


class Alerts:
    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)


@pytest.fixture
def env(tmp_path):
    def make(mode="challenge", **extra):
        e = {"MODE": mode, "REPO_ROOT": str(tmp_path), "STATE_DIR": str(tmp_path / "state"),
             "CACHE_DIR": str(tmp_path / "cache")}
        e.update(extra)
        return load_config(e)
    return make


def run(cfg, ex, world, dry_run=False):
    alerts = Alerts()
    bot = Bot(cfg, ex, dry_run=dry_run, now_ms=world.end_ms + 120_000, alerter=alerts)
    bot.run()
    return bot, alerts


def signals(cfg):
    with open(cfg.log_dir / "signals.csv") as f:
        return list(csv.DictReader(f))


def trades(cfg):
    p = cfg.log_dir / "trades.csv"
    return list(csv.DictReader(open(p))) if p.exists() else []


def state(cfg):
    return json.loads(cfg.state_path.read_text())


def entered_world(env):
    w = World(END)
    w.set_breakout()
    ex = FakeExchange(w)
    cfg = env()
    bot, alerts = run(cfg, ex, w)
    return cfg, w, ex, bot, alerts


def test_breakout_is_entered_with_tpsl(env):
    cfg, w, ex, bot, alerts = entered_world(env)
    st = state(cfg)
    assert len(st["open_trades"]) == 1
    t = st["open_trades"][0]
    assert t["symbol"] == "SOL" and t["side"] == "long" and t["status"] == "open"
    assert t["level"] == 110.0
    assert t["stop"] == pytest.approx(110 - 0.5 * t["atr"])
    assert t["target"] == pytest.approx(112 + 3 * (112 - t["stop"]))
    # 2% of 100k at risk
    assert t["risk_amount"] == pytest.approx(2000, rel=0.01)
    assert [c[0] for c in ex.calls].count("market_entry") == 1
    assert len(ex.pending_tpsl("SOL-USDT")) == 1
    assert signals(cfg)[0]["action"] == "taken"
    assert any("ENTRY SOL" in a for a in alerts.sent)


def test_duplicate_run_does_not_double_the_trade(env):
    cfg, w, ex, bot, _ = entered_world(env)
    run(cfg, ex, w)
    run(cfg, ex, w)
    assert [c[0] for c in ex.calls].count("market_entry") == 1
    assert len(state(cfg)["open_trades"]) == 1


def test_crash_after_order_sent_is_recovered_not_repeated(env):
    cfg, w, ex, bot, _ = entered_world(env)
    st = state(cfg)
    t = st["open_trades"][0]
    # simulate a crash between sending the order and recording the fill
    t["status"] = "pending"
    st["last_processed_bar_close_ts"] = None
    st["last_entry_close_ts"] = {}
    save_state(cfg.state_path, st)
    run(cfg, ex, w)
    st = state(cfg)
    assert len(st["open_trades"]) == 1 and st["open_trades"][0]["status"] == "open"
    assert [c[0] for c in ex.calls].count("market_entry") == 1
    assert any(r["event"] == "entry_recovered" for r in trades(cfg))


def test_missing_tpsl_is_replaced(env):
    w = World(END)
    w.set_breakout()
    ex = FakeExchange(w, attached_tpsl_visible=False)
    cfg = env()
    run(cfg, ex, w)
    assert len(ex.pending_tpsl("SOL-USDT")) == 1  # placed right after entry
    ex.tpsl.clear()  # someone cancelled it
    w.advance(1)
    run(cfg, ex, w)
    o = ex.pending_tpsl("SOL-USDT")
    t = state(cfg)["open_trades"][0]
    assert len(o) == 1 and o[0].sl_trigger == pytest.approx(t["stop"], abs=0.01)
    assert sum(1 for r in trades(cfg) if r["event"] == "tpsl_replaced") == 2


def test_stop_hit_on_exchange_is_accounted(env):
    cfg, w, ex, bot, _ = entered_world(env)
    ex.trigger_stop("SOL-USDT")
    w.advance(1, {"SOL-USDT": 109.0})
    run(cfg, ex, w)
    st = state(cfg)
    assert st["open_trades"] == []
    t = st["closed_trades"][0]
    assert t["exit_reason"] == "stop"
    assert t["r_multiple"] == pytest.approx(-1, abs=0.05)
    assert t["funding"] == -1.5 and t["fees"] > 0
    assert st["consecutive_losses"] == 1
    assert st["realized_pnl"] == pytest.approx(t["net_pnl"])


def test_manual_close_is_recorded_and_leftover_tpsl_cancelled(env):
    cfg, w, ex, bot, _ = entered_world(env)
    ex.manual_close("SOL-USDT", 113.0)
    w.advance(1, {"SOL-USDT": 113.0})
    run(cfg, ex, w)
    t = state(cfg)["closed_trades"][0]
    assert t["exit_reason"].startswith("closed outside bot")
    assert ex.pending_tpsl("SOL-USDT") == []
    assert state(cfg)["consecutive_losses"] == 0


def test_time_exit_after_60_bars(env):
    cfg, w, ex, bot, _ = entered_world(env)
    w.advance(59, {"SOL-USDT": 113.0})
    run(cfg, ex, w)
    assert len(state(cfg)["open_trades"]) == 1
    w.advance(1, {"SOL-USDT": 113.0})
    run(cfg, ex, w)
    st = state(cfg)
    assert st["open_trades"] == [] and st["closed_trades"][0]["exit_reason"].startswith("time exit")
    assert ex.pending_tpsl("SOL-USDT") == []


def test_kill_switch_blocks_new_trades_only(env, tmp_path):
    w = World(END)
    w.set_breakout()
    ex = FakeExchange(w)
    (tmp_path / "STOP").write_text("")
    cfg = env()
    run(cfg, ex, w)
    assert "market_entry" not in [c[0] for c in ex.calls]
    s = signals(cfg)[0]
    assert s["action"] == "skipped" and "kill switch" in s["reason"]


def test_bot_enabled_false(env):
    w = World(END)
    w.set_breakout()
    ex = FakeExchange(w)
    cfg = env(BOT_ENABLED="false")
    run(cfg, ex, w)
    assert "market_entry" not in [c[0] for c in ex.calls]


def test_breach_flattens_and_stops(env):
    cfg, w, ex, bot, _ = entered_world(env)
    # replace the stop with a far one so the loss can exceed 5% before it triggers
    st = state(cfg)
    st["open_trades"][0]["stop"] = 50.0
    save_state(cfg.state_path, st)
    ex.tpsl.clear()
    w.advance(1, {"SOL-USDT": 106.0}, ranges={"SOL-USDT": (98.0, 107.0)})
    _, alerts = run(cfg, ex, w)
    st = state(cfg)
    assert st["failed"] and "DAILY LOSS" in st["failed_reason"]
    assert st["open_trades"] == [] and ex.pos == {}
    assert any("CHALLENGE FAILED" in a for a in alerts.sent)
    # a fresh breakout on a later bar is refused
    w.advance(10, {"SOL-USDT": 100.0})
    w.set_breakout()
    run(cfg, ex, w)
    assert [c[0] for c in ex.calls].count("market_entry") == 1
    assert signals(cfg)[-1]["reason"] == "challenge failed: trading stopped"


def test_guard_blocks_entry(env):
    w = World(END)
    w.set_breakout()
    ex = FakeExchange(w)
    cfg = env()
    st = load_state(cfg.state_path, "challenge", 100_000)
    st["realized_pnl"] = -8_500.0  # 8.5% drawdown (from a trade closed days ago): +2% new risk reaches 10%
    st["closed_trades"] = [{"id": "old", "symbol": "ETH", "net_pnl": -8_500.0, "exit_ts": END - 5 * DAY_MS,
                            "entry_ts": END - 6 * DAY_MS, "r_multiple": -1.0}]
    save_state(cfg.state_path, st)
    _, alerts = run(cfg, ex, w)
    assert "market_entry" not in [c[0] for c in ex.calls]
    assert "drawdown guard" in signals(cfg)[0]["reason"]
    assert any("GUARD BLOCK" in a for a in alerts.sent)


def test_loss_streak_halves_risk(env):
    w = World(END)
    w.set_breakout()
    ex = FakeExchange(w)
    cfg = env()
    st = load_state(cfg.state_path, "challenge", 100_000)
    st["consecutive_losses"] = 3
    save_state(cfg.state_path, st)
    run(cfg, ex, w)
    t = state(cfg)["open_trades"][0]
    assert t["risk_pct"] == 0.01 and t["risk_amount"] == pytest.approx(1000, rel=0.01)


def test_dry_run_sends_nothing_and_saves_nothing(env):
    w = World(END)
    w.set_breakout()
    ex = FakeExchange(w)
    cfg = env()
    bot, _ = run(cfg, ex, w, dry_run=True)
    assert [c for c in ex.calls if c[0] != "ensure_account_modes"] == []
    assert not cfg.state_path.exists()
    assert signals(cfg)[0]["action"] == "dry_run"
    assert any("SIGNAL SOL long" in r for r in bot.report)


def test_funded_mode_requires_btc_trend(env):
    w = World(END)
    w.set_breakout()
    ex = FakeExchange(w)
    cfg = env("funded")
    run(cfg, ex, w)  # flat BTC: close == SMA -> trend -1, long is skipped
    assert "market_entry" not in [c[0] for c in ex.calls]
    assert "BTC trend" in signals(cfg)[0]["reason"]


def test_missed_bar_signal_is_logged_as_stale(env):
    w = World(END)
    ex = FakeExchange(w)
    cfg = env()
    run(cfg, ex, w)       # processes bar END, no signal
    w.advance(1)
    w.set_breakout()      # breakout on bar END+1 ...
    w.advance(1)          # ... but the bot only runs after END+2
    run(cfg, ex, w)
    s = signals(cfg)
    assert s[-1]["action"] == "skipped" and s[-1]["reason"].startswith("stale")
    assert "market_entry" not in [c[0] for c in ex.calls]


def test_weekly_report_from_real_run(env):
    from bot.report import build_report, read_signals
    cfg, w, ex, bot, _ = entered_world(env)
    ex.trigger_stop("SOL-USDT")
    w.advance(1, {"SOL-USDT": 109.0})
    run(cfg, ex, w)
    md = build_report(state(cfg), read_signals(cfg.log_dir))
    assert "| All time | 1 | 0.0% | -1.0" in md
    assert "Versus backtest expectations" in md and "30%–35%" in md
    assert "xychart-beta" in md and "Daily-loss peak" in md
    assert "Trades per week" in md
