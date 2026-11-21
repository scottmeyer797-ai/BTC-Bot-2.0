"""Replay the signal logic over the last N days of BloFin demo candles (public data, no keys needed).

    python scripts/replay_90d.py [--days 90] [--mode challenge|funded]
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import MODES, QUOTE, UNIVERSE, load_config  # noqa: E402
from bot.data import load_candles  # noqa: E402
from bot.exchange import BlofinDemo  # noqa: E402
from bot.indicators import DAY_MS  # noqa: E402
from bot.replay import replay, summarize  # noqa: E402
from bot.state import ms_to_iso  # noqa: E402


def main(argv=None) -> dict:
    p = argparse.ArgumentParser()
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--mode", choices=sorted(MODES), default=os.environ.get("MODE", "challenge"))
    args = p.parse_args(argv)
    cfg = load_config()
    client = BlofinDemo(cfg, private=False)
    listed = client.instruments()
    frames = {}
    for sym in UNIVERSE:
        inst_id = f"{sym}-{QUOTE}"
        if inst_id not in listed:
            print(f"skip {inst_id}: not listed on BloFin demo")
            continue
        frames[sym] = load_candles(client, inst_id, cfg.cache_dir)
    now = int(time.time() * 1000)
    mode = MODES[args.mode]
    trades, skipped = replay(frames, mode, now - args.days * DAY_MS)
    print(f"\nReplay of the last {args.days} days, mode={mode.name} (target {mode.target_r:g}R, "
          f"risk {mode.risk_pct:.2%}); stop-first on ambiguous bars, no fees/slippage\n")
    print(f"{'signal bar close':20} {'sym':5} {'side':5} {'level':>11} {'entry':>11} {'stop':>11} {'target':>11} "
          f"{'exit':>11} {'reason':7} {'bars':>4} {'R':>6}")
    for t in sorted(trades, key=lambda t: t.entry_close_ts):
        print(f"{ms_to_iso(t.entry_close_ts):20} {t.symbol:5} {t.side:5} {t.level:11.6g} {t.entry:11.6g} "
              f"{t.stop:11.6g} {t.target:11.6g} {(t.exit or 0):11.6g} {(t.reason or 'open'):7} {t.bars:4d} "
              f"{(t.r if t.r is not None else 0):+6.2f}")
    s = summarize(trades)
    print(f"\nclosed {s['closed']}, still open {s['open']}, win rate {s['win_rate']:.1%}, "
          f"avg {s['avg_r']:+.2f}R, total {s['total_r']:+.2f}R")
    if skipped:
        print(f"\nskipped signals ({len(skipped)}):")
        for c, sym, side, reason in skipped:
            print(f"  {ms_to_iso(c)} {sym:5} {side:5} {reason}")
    return s


if __name__ == "__main__":
    main()
