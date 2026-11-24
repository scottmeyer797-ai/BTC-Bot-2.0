"""Rank strategies per regime. Usage: python research/rank_regimes.py <out_dir> [--md]

Qualifies when, for that regime: n >= 20, win rate >= 30%, mean net R > 0, positive in both 2020-22 and
2023-26 (where each has >= 5 trades), and an entry edge: beats >= 90% of exit-matched random-entry runs
(p <= 0.10). Grids have no entry signal to randomise, so they need t >= 2 instead. One direction per strategy.
"""
import json
import sys
from pathlib import Path

d = Path(sys.argv[1])
r = json.loads((d / "regime_results.json").read_text())
base = {(b["name"], b["direction"]): b for b in json.loads((d / "baselines.json").read_text())}


def rows_for(view, rg):
    out = []
    for x in r["results"]:
        v = x[view][rg]
        if v.get("n", 0) < 20:
            continue
        t = v["exp"] / v["se"] if v.get("se") else 0.0
        cons = (v["n_a"] < 5 or v["exp_a"] > 0) and (v["n_b"] < 5 or v["exp_b"] > 0)
        b = base.get((x["name"], x["direction"]), {}).get(view, {}).get(rg, {})
        if x["family"] == "grid":
            edge, p, beats = v["exp"], None, t >= 2.0
        else:
            edge, p = b.get("edge"), b.get("p")
            beats = p is not None and p <= 0.10
        qual = v["win"] >= 0.30 and v["exp"] > 0 and cons and beats
        out.append(dict(x=x, v=v, t=t, cons=cons, edge=edge, p=p, beats=beats, qual=qual, base=b))
    out.sort(key=lambda z: (z["qual"], z["edge"] if z["edge"] is not None else -9), reverse=True)
    seen, top = set(), []
    for z in out:
        if z["x"]["name"] in seen:
            continue
        seen.add(z["x"]["name"])
        top.append(z)
    return top


def fmt(z):
    x, v = z["x"], z["v"]
    base_txt = "grid (no entry baseline)" if x["family"] == "grid" else \
        f"random twin {z['base'].get('base_median', 0):+.2f}R, edge {z['edge']:+.2f}R, p={z['p']:.2f}"
    return (f"{x['name']} [{x['direction']}] | n={v['n']} win {v['win']:.0%} exp {v['exp']:+.2f}R t={z['t']:.1f} "
            f"| R/month {v['r_per_month']:+.2f} | 2020-22 {v['exp_a']:+.2f} (n={v['n_a']}), 2023-26 {v['exp_b']:+.2f} "
            f"(n={v['n_b']}) | {base_txt}")


for view in ("live", "real"):
    print(f"\n==================== {view.upper()} ====================")
    for rg in ("bull", "range", "bear"):
        top = rows_for(view, rg)
        q = [z for z in top if z["qual"]]
        print(f"\n--- {rg}: {len(q)} qualify ---")
        for z in q[:5]:
            print("  OK  " + fmt(z))
        if len(q) < 5:
            for z in [z for z in top if not z["qual"] and z["v"]["exp"] > 0][: 5 - len(q)]:
                why = []
                if not z["beats"]:
                    why.append("no entry edge vs random" if z["x"]["family"] != "grid" else "t<2")
                if not z["cons"]:
                    why.append("not positive in both periods")
                if z["v"]["win"] < 0.30:
                    why.append("win<30%")
                print("  ..  " + fmt(z) + "  <- " + ", ".join(why))
