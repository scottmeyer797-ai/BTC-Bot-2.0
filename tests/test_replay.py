import pytest

from bot.config import BAR_MS, MODES
from bot.indicators import DAY_MS
from bot.replay import replay, summarize
from tests.fake_exchange import World

END = (1_800_000_000_000 // DAY_MS) * DAY_MS + 8 * 3600_000


def frames(world):
    return {i.split("-")[0]: df for i, df in world.frames.items()}


def test_replay_finds_breakout_and_hits_target():
    w = World(END)
    w.set_breakout()
    stop = None
    w.advance(3, {"SOL-USDT": 125.0}, ranges={"SOL-USDT": (111.0, 140.0)})
    trades, skipped = replay(frames(w), MODES["challenge"], END - 10 * DAY_MS)
    assert len(trades) == 1
    t = trades[0]
    assert (t.symbol, t.side, t.level, t.reason) == ("SOL", "long", 110.0, "target")
    assert t.r == pytest.approx(3.0)
    assert summarize(trades)["win_rate"] == 1.0


def test_replay_stop_first_when_bar_spans_both():
    w = World(END)
    w.set_breakout()
    w.advance(1, {"SOL-USDT": 112.0}, ranges={"SOL-USDT": (100.0, 140.0)})
    trades, _ = replay(frames(w), MODES["challenge"], END - 10 * DAY_MS)
    assert trades[0].reason == "stop" and trades[0].r == pytest.approx(-1.0)


def test_replay_time_exit():
    w = World(END)
    w.set_breakout()
    w.advance(60, {"SOL-USDT": 113.0}, ranges={"SOL-USDT": (112.0, 114.0)})
    trades, _ = replay(frames(w), MODES["challenge"], END - 10 * DAY_MS)
    assert trades[0].reason == "time" and trades[0].bars == 60


@pytest.mark.replay
def test_replay_last_90_days_on_blofin_demo(capsys):
    """Network: replays the last 90 days of BloFin demo candles and prints the trades."""
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
    import replay_90d
    s = replay_90d.main(["--days", "90"])
    out = capsys.readouterr().out
    with capsys.disabled():
        print(out)
    assert s["closed"] + s["open"] >= 0
