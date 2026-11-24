"""Partial-exit / runner study. Follows research/partials_study_preregistration.md exactly.

Usage: python research/partials_study.py <out_dir> BTC=<1h>,<fund> ADA=... LINK=... SOL=...
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_portfolio import Mkt, load_funding  # noqa: E402
from btc_edge_stats import load_1h  # noqa: E402
from exit_study import HOLDOUT_START, Exits, entries  # noqa: E402

RUN = 360
VARIANTS = {
    "B0": dict(targets=[(3, 1.0)], max_bars=60),
    "BE2": dict(targets=[(3, 1.0)], max_bars=60, be=2.0),
    "R1": dict(targets=[(3, 0.5)], max_bars=RUN, be=2.0, trail=("atr", 3.0, 3.0, None)),
    "R2": dict(targets=[(2, 0.33), (4, 0.33)], max_bars=RUN, be=2.0, trail=("atr", 3.0, 4.0, None)),
    "R3": dict(targets=[(2, 0.5)], max_bars=RUN, be=2.0, trail=("atr", 3.0, 2.0, None)),
    "R4": dict(targets=[(2, 0.25), (3, 0.25)], max_bars=RUN, be=2.0, trail=("atr", 3.0, 3.0, None)),
    "R5": dict(targets=[(3, 0.5)], max_bars=RUN, be=2.0, trail=("struct", 10, 3.0, None)),
    "R6": dict(targets=[(3, 0.5)], max_bars=RUN, be=2.0, trail=("atr", 4.5, 3.0, None)),
    "R7": dict(targets=[(3, 0.5)], max_bars=RUN, be=2.0, trail=("ema50", 0, 3.0, None)),
    "R8": dict(targets=[], max_bars=RUN, be=2.0, trail=("atr", 3.0, 3.0, 2.0)),
}
ADAPTIVE = {"R9": "R1", "R10": "R6"}
ALL = list(VARIANTS) + list(ADAPTIVE)


def mfe(mk, j0, entry, stop, risk, hours=RUN * 4):
    lo, hi = mk.lo[j0:j0 + hours], mk.hi[j0:j0 + hours]
    hit = np.flatnonzero(lo <= stop)
    k = hit[0] if len(hit) else len(lo)
    return float((hi[:max(k, 1)].max() - entry) / risk)


def study(mk: Mkt, name: str) -> pd.DataFrame:
    ex = Exits(mk)
    rows = []
    for i, j0, entry, stop, risk in entries(mk):
        rec = {"coin": name, "t_in": int(mk.ts1[j0]), "regime": mk.regime_at(int(mk.ts1[j0])),
               "mfe": mfe(mk, j0, entry, stop, risk)}
        for vid, v in VARIANTS.items():
            net, _, _, hours = ex.run(v, j0, entry, stop, risk)
            rec[vid], rec[vid + "_h"] = net, hours
        bull = rec["regime"] == "bull"
        for vid, base in ADAPTIVE.items():
            src = base if bull else "BE2"
            rec[vid], rec[vid + "_h"] = rec[src], rec[src + "_h"]
        rows.append(rec)
    return pd.DataFrame(rows)


def summarize(t: pd.DataFrame) -> dict:
    out = {}
    for vid in ALL:
        r = t[vid].to_numpy()
        if len(r) == 0:
            out[vid] = {"n": 0}
            continue
        d = r - t["BE2"].to_numpy()
        streak = mx = 0
        for x in r:
            streak = streak + 1 if x <= 0 else 0
            mx = max(mx, streak)
        eq = np.cumprod(1 + 0.01 * r)
        srt = np.sort(r)[::-1]
        k = max(1, int(round(0.05 * len(r))))
        big = t["mfe"].to_numpy() >= 5
        wins, losses = r[r > 0].sum(), -r[r < 0].sum()
        out[vid] = {
            "n": int(len(r)), "exp": float(r.mean()), "win": float((r > 0).mean()),
            "pf": float(wins / losses) if losses > 0 else None, "max_losing_streak": int(mx),
            "dd_1pct": float((1 - eq / np.maximum.accumulate(eq)).max()),
            "avg_hold_days": float(t[vid + "_h"].mean() / 24),
            "diff_vs_BE2": float(d.mean()),
            "t_vs_BE2": float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))) if len(d) > 1 and d.std() > 0 else 0.0,
            "top5pct_share": float(srt[:k].sum() / r.sum()) if r.sum() > 0 else None,
            "exp_without_top5pct": float(srt[k:].mean()) if len(srt) > k else None,
            "n_mfe5": int(big.sum()), "exp_on_mfe5": float(r[big].mean()) if big.any() else None,
        }
    return out


def main(out_dir, *coins):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    frames = []
    for arg in coins:
        name, dirs = arg.split("=")
        kl, fu = dirs.split(",")
        frames.append(study(Mkt(load_1h(kl), load_funding(fu)), name))
        print("done", name, len(frames[-1]), flush=True)
    T = pd.concat(frames, ignore_index=True)
    T.to_csv(out / "partials_trades.csv", index=False)
    btc = T[T.coin == "BTC"]
    alts = [c for c in T.coin.unique() if c != "BTC"]
    hold = pd.concat([btc[btc.t_in >= HOLDOUT_START]] + [T[T.coin == c] for c in alts])
    sets = {"BTC dev 2020-23": btc[btc.t_in < HOLDOUT_START], "BTC holdout 2024-26": btc[btc.t_in >= HOLDOUT_START],
            **{c: T[T.coin == c] for c in alts}, "pooled holdout": hold,
            "bull: pooled holdout": hold[hold.regime == "bull"], "bull: BTC all years": btc[btc.regime == "bull"],
            "BTC all years": btc}
    res = {k: summarize(v) for k, v in sets.items()}
    verdict = {}
    for vid in ALL:
        if vid in ("BE2",):
            continue
        c1 = res["BTC dev 2020-23"][vid]["diff_vs_BE2"] > 0
        c2 = res["BTC holdout 2024-26"][vid]["diff_vs_BE2"] > 0
        n_alt = sum(res[a][vid]["diff_vs_BE2"] > 0 for a in alts)
        tp = res["pooled holdout"][vid]["t_vs_BE2"]
        c5 = res["pooled holdout"][vid]["win"] >= 0.30
        verdict[vid] = {"dev>0": c1, "btc_holdout>0": c2, "alts>0": n_alt, "pooled_t": tp, "t>=2": tp >= 2.0,
                        "bonferroni_t>=2.8": tp >= 2.8, "win>=30%": c5,
                        "beats_BE2": all([c1, c2, n_alt >= 2, tp >= 2.0, c5])}
    (out / "partials_results.json").write_text(json.dumps({"sets": res, "verdict": verdict}, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:])
