"""Rank backtests on BTC and check them out-of-sample on the alt.

Usage: python research/rank_backtests.py <bt_out_dir>

BTC rank: by Sharpe (daily, marked to market), among variants with win >= 30% and mean net R > 0.
Alt verdict (no parameter changes, alt never used for selection):
  PASS  mean R > 0, win >= 30%, Sharpe > 0 and an entry edge (beats >= 90% of exit-matched random runs;
        grids: t >= 2)
  WEAK  mean R > 0 and Sharpe > 0 but no significant edge
  FAIL  otherwise
"""
import json
import sys
from pathlib import Path

import numpy as np

d = Path(sys.argv[1])
R = json.loads((d / "backtest_results.json").read_text())
alt = R["alt"]


def uniq(market):
    rows = {}
    for k, v in R[market].items():
        key = (v["name"], v["direction"], v["mode"] if v["mode"] == "always on" else v["mode"])
        rows.setdefault(key, {**v, "ids": []})["ids"].append(v["id"])
    return rows


btc, oos = uniq("BTC"), uniq(alt)


def edge_ok(v):
    if v["name"].startswith("GRID"):
        return v["metrics"].get("t", 0) >= 2
    p = v["baseline"].get("p")
    return p is not None and p <= 0.10


def verdict(v):
    m = v["metrics"]
    if m.get("n", 0) < 10:
        return "FAIL (too few trades)"
    if m["exp"] > 0 and m["win"] >= 0.30 and m["sharpe"] > 0 and edge_ok(v):
        return "PASS"
    if m["exp"] > 0 and m["sharpe"] > 0:
        return "WEAK"
    return "FAIL"


table = []
for key, v in btc.items():
    m = v["metrics"]
    if m.get("n", 0) == 0:
        continue
    eligible = m["win"] >= 0.30 and m["exp"] > 0
    o = oos[key]
    table.append((eligible, m["sharpe"], key, v, o))
table.sort(key=lambda z: (z[0], z[1]), reverse=True)


def name(v):
    n = v["name"].replace("GRID 0.5", "Grid 0.5 ATR").replace("GRID 1.5", "Grid 1.5 ATR")
    return f"{n} [{v['direction']}] ({v['mode']})"


print(f"look-ahead test: {R['lookahead']['checks']} checks, {R['lookahead']['n_mismatch']} mismatches")
print(f"\n{'#':>2} {'strategy':95} | BTC: n  win   expR  Sharpe  CAGR   maxDD  edge-p | {alt}: n  win   expR  Sharpe  CAGR   maxDD  edge-p  verdict")
rank = 0
out_rows = []
for eligible, sh, key, v, o in table:
    m, mo = v["metrics"], o["metrics"]
    rank += 1 if eligible else 0
    vd = verdict(o) if eligible else "-"
    bp, op = v["baseline"].get("p"), o["baseline"].get("p")
    bps = "grid" if v["name"].startswith("GRID") else f"{bp:.2f}" if bp is not None else "n/a"
    ops = "grid" if o["name"].startswith("GRID") else f"{op:.2f}" if op is not None else "n/a"
    mo_ok = mo.get("n", 0) > 0
    print(f"{rank if eligible else '--':>2} {name(v)[:95]:95} | {m['n']:4d} {m['win']:4.0%} {m['exp']:+6.2f} {m['sharpe']:6.2f} {m['cagr']:+6.1%} {m['max_dd']:6.1%} {bps:>5} | "
          + (f"{mo['n']:4d} {mo['win']:4.0%} {mo['exp']:+6.2f} {mo['sharpe']:6.2f} {mo['cagr']:+6.1%} {mo['max_dd']:6.1%} {ops:>5}  {vd}" if mo_ok else "no trades"))
    out_rows.append({"rank": rank if eligible else None, "key": list(key), "ids": v["ids"], "btc": m, "btc_p": bp,
                     "alt": mo, "alt_p": op, "verdict": vd, "list": v["list"], "regime": v["regime"]})

# rank stability: Spearman correlation of mean R across all variants
keys = [k for k in btc if btc[k]["metrics"].get("n", 0) >= 10 and oos[k]["metrics"].get("n", 0) >= 10]
a = np.array([btc[k]["metrics"]["exp"] for k in keys])
b = np.array([oos[k]["metrics"]["exp"] for k in keys])
ra, rb = a.argsort().argsort(), b.argsort().argsort()
rho = float(np.corrcoef(ra, rb)[0, 1])
print(f"\nSpearman rank correlation of mean R, BTC vs {alt}, {len(keys)} variants: {rho:+.2f}")
elig = [r for r in out_rows if r["rank"]]
for vd in ("PASS", "WEAK", "FAIL"):
    print(vd, sum(1 for r in elig if r["verdict"].startswith(vd)), "of", len(elig))
(d / "ranking.json").write_text(json.dumps({"rows": out_rows, "spearman": rho, "n_rank": len(keys)}, indent=1,
                                           default=float))
