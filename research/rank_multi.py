"""Cross-coin verdicts: BTC (in-sample) vs every out-of-sample alt. Usage: python research/rank_multi.py <bt_out_dir>

Per alt verdict as in rank_backtests.py (PASS / WEAK / FAIL). Overall class over the alts:
  ROBUST     profitable (mean R > 0 and Sharpe > 0) on every alt and PASS on at least 2
  PROMISING  profitable on every alt, fewer than 2 PASS
  MIXED      profitable on some alts
  OVERFIT    profitable on no alt
Variants listed: BTC win >= 30% and mean R > 0, plus any variant profitable on BTC and every alt.
"""
import json
import sys
from pathlib import Path

import numpy as np

d = Path(sys.argv[1])
R = json.loads((d / "backtest_results.json").read_text())
alts = R["alts"]


def uniq(market):
    rows = {}
    for v in R[market].values():
        rows.setdefault((v["name"], v["direction"], v["mode"]), v)
    return rows


M = {m: uniq(m) for m in ["BTC"] + alts}


def prof(m):
    return m.get("n", 0) >= 10 and m["exp"] > 0 and m["sharpe"] > 0


def verdict(v):
    m = v["metrics"]
    if m.get("n", 0) < 10:
        return "FAIL"
    edge = (m.get("t", 0) >= 2) if v["name"].startswith("GRID") else \
        (v["baseline"].get("p") is not None and v["baseline"]["p"] <= 0.10)
    if m["exp"] > 0 and m["win"] >= 0.30 and m["sharpe"] > 0 and edge:
        return "PASS"
    return "WEAK" if prof(m) else "FAIL"


rows = []
for key, v in M["BTC"].items():
    b = v["metrics"]
    if b.get("n", 0) == 0:
        continue
    elig = b["win"] >= 0.30 and b["exp"] > 0
    alt_v = {a: M[a][key] for a in alts}
    n_prof = sum(prof(alt_v[a]["metrics"]) for a in alts)
    n_pass = sum(verdict(alt_v[a]) == "PASS" for a in alts)
    if not elig and not (prof(b) and n_prof == len(alts)):
        continue
    cls = ("ROBUST" if n_prof == len(alts) and n_pass >= 2 else "PROMISING" if n_prof == len(alts)
           else "MIXED" if n_prof else "OVERFIT")
    # pooled out-of-sample mean R (trade-weighted)
    ns = [alt_v[a]["metrics"].get("n", 0) for a in alts]
    pooled = sum(alt_v[a]["metrics"]["exp"] * n for a, n in zip(alts, ns) if n) / max(sum(ns), 1)
    rows.append(dict(key=key, v=v, b=b, alt=alt_v, cls=cls, n_pass=n_pass, n_prof=n_prof, pooled=pooled, elig=elig))

order = {"ROBUST": 0, "PROMISING": 1, "MIXED": 2, "OVERFIT": 3}
rows.sort(key=lambda r: (order[r["cls"]], -r["pooled"]))
nm = lambda k: f"{k[0].replace('GRID', 'Grid')[:60]} [{k[1]}] ({k[2]})"
print(f"{'class':9} {'strategy':88} | BTC  exp  win  Sh  | " + " | ".join(f"{a}: exp  win  Sh   p   verdict" for a in alts) + " | pooled OOS exp")
for r in rows:
    b = r["b"]
    cells = []
    for a in alts:
        m, p = r["alt"][a]["metrics"], r["alt"][a]["baseline"].get("p")
        ps = "grid" if r["key"][0].startswith("GRID") else f"{p:.2f}" if p is not None else " n/a"
        cells.append(f"{m['exp']:+.2f} {m['win']:3.0%} {m['sharpe']:+.2f} {ps:>4} {verdict(r['alt'][a]):4}" if m.get("n") else "no trades")
    print(f"{r['cls']:9} {nm(r['key'])[:88]:88} | {b['exp']:+.2f} {b['win']:3.0%} {b['sharpe']:+.2f} | " + " | ".join(cells)
          + f" | {r['pooled']:+.2f}{'' if r['elig'] else '  (BTC win<30%)'}")

keys = [k for k in M["BTC"] if all(M[x][k]["metrics"].get("n", 0) >= 10 for x in ["BTC"] + alts)]


def rho(x, y):
    a = np.array([M[x][k]["metrics"]["exp"] for k in keys]).argsort().argsort()
    b = np.array([M[y][k]["metrics"]["exp"] for k in keys]).argsort().argsort()
    return float(np.corrcoef(a, b)[0, 1])


mk = ["BTC"] + alts
print(f"\nSpearman rank correlation of mean R ({len(keys)} variants):")
for i, x in enumerate(mk):
    print("  " + x + ": " + "  ".join(f"{y} {rho(x, y):+.2f}" for y in mk[i + 1:]))
from collections import Counter
print(Counter(r["cls"] for r in rows if r["elig"]))
(d / "ranking_multi.json").write_text(json.dumps(
    [{"key": list(r["key"]), "class": r["cls"], "n_pass": r["n_pass"], "n_profitable": r["n_prof"],
      "pooled_oos_exp": r["pooled"], "btc": r["b"], **{a: {"metrics": r["alt"][a]["metrics"],
      "p": r["alt"][a]["baseline"].get("p"), "verdict": verdict(r["alt"][a])} for a in alts}} for r in rows],
    indent=1, default=float))
