"""Exit-matched random baselines for every strategy variant, per regime.

For each strategy + direction: random entries at the same frequency and long/short mix, with the strategy's
own stop/target/trailing/exit rules (stop falls back to 1.5 ATR where the strategy's stop only exists on
signal bars). 20 seeds. Edge = strategy mean R - median random mean R; p = share of seeds >= strategy.

Usage: python research/regime_baselines.py <binance_1h_csv_dir> <out_dir>
"""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from btc_edge_stats import load_1h, resample  # noqa: E402
from regime_strategies import (BAR4, DAY, Market, evaluate, features, realized_regimes, regimes, simulate,  # noqa: E402
                               specs)

SEEDS = 20


def main(src, out_dir):
    out = Path(out_dir)
    h1 = load_1h(src)
    h4, d1 = resample(h1, BAR4), resample(h1, DAY)
    rg = regimes(d1)
    live = dict(zip(rg.applies_day, rg.regime))
    real = realized_regimes(d1)
    valid = rg.dropna(subset=["regime"])
    months = {r: 1.0 for r in ("bull", "bear", "range")}
    df = features(h4, d1)
    m = Market(h1, df)
    start = int(np.searchsorted(df.ts.to_numpy(), valid.ts.iloc[0]))
    first_day = valid.applies_day.iloc[0]
    c, a = df.close.to_numpy(), df.atr.to_numpy()
    res = []
    for sp in specs(df):
        stop_l = np.where(np.isfinite(sp.stop_l), sp.stop_l, c - 1.5 * a)
        stop_s = np.where(np.isfinite(sp.stop_s), sp.stop_s, c + 1.5 * a)
        for direction in ("both", "long", "short"):
            real_t = simulate(sp, m, direction, start)
            real_t = real_t[real_t.ts >= first_day]
            if len(real_t) < 10:
                continue
            p = min(0.5, len(real_t) * 1.3 / max(len(df) - start, 1))  # a bit denser: some picks are skipped
            share_long = float((real_t.side > 0).mean())
            base = {"live": {r: [] for r in ("bull", "bear", "range")}, "real": {r: [] for r in ("bull", "bear", "range")}}
            for seed in range(SEEDS):
                rng = np.random.default_rng(1000 + seed)
                pick = rng.random(len(df)) < p
                lng = rng.random(len(df)) < share_long
                rs = replace(sp, le=pick & lng, se=pick & ~lng, stop_l=stop_l, stop_s=stop_s)
                t = simulate(rs, m, direction, start)
                t = t[t.ts >= first_day]
                for view, mp in (("live", live), ("real", real)):
                    ev = evaluate(t, mp, months, 1)
                    for r in base[view]:
                        base[view][r].append(ev[r].get("exp", np.nan) if ev[r].get("n", 0) >= 5 else np.nan)
            entry = {"name": sp.name, "direction": direction}
            for view, mp in (("live", live), ("real", real)):
                ev = evaluate(real_t, mp, months, 1)
                entry[view] = {}
                for r in base[view]:
                    b = np.array([x for x in base[view][r] if np.isfinite(x)])
                    s = ev[r].get("exp", np.nan) if ev[r].get("n", 0) else np.nan
                    entry[view][r] = {"base_median": float(np.median(b)) if len(b) else None,
                                      "base_p90": float(np.percentile(b, 90)) if len(b) else None,
                                      "edge": float(s - np.median(b)) if len(b) and np.isfinite(s) else None,
                                      "p": float((b >= s).mean()) if len(b) and np.isfinite(s) else None}
            res.append(entry)
        print("baseline done", sp.name, flush=True)
    (out / "baselines.json").write_text(json.dumps(res, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
