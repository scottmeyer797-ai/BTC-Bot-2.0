"""Exit study for the current bot's long entries. Follows research/exit_study_preregistration.md exactly.

Usage: python research/exit_study.py <out_dir> BTC=<1h>,<fund> ADA=<1h>,<fund> LINK=... SOL=...
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from backtest_portfolio import TAKER_RT, Mkt, load_funding  # noqa: E402
from btc_edge_stats import load_1h  # noqa: E402
from regime_strategies import BAR4  # noqa: E402

ENTRY = "Current bot: swing-level break + volume z>2, 3R"
COOLDOWN = 6
HOLDOUT_START = 1704067200000  # 2024-01-01 UTC

VARIANTS = {
    "B0": dict(targets=[(3, 1.0)], max_bars=60),
    "T1.5": dict(targets=[(1.5, 1.0)], max_bars=60),
    "T2": dict(targets=[(2, 1.0)], max_bars=60),
    "T2.5": dict(targets=[(2.5, 1.0)], max_bars=60),
    "T4": dict(targets=[(4, 1.0)], max_bars=60),
    "T5": dict(targets=[(5, 1.0)], max_bars=60),
    "N60": dict(targets=[], max_bars=60),
    "BE1": dict(targets=[(3, 1.0)], max_bars=60, be=1.0),
    "BE1.5": dict(targets=[(3, 1.0)], max_bars=60, be=1.5),
    "BE2": dict(targets=[(3, 1.0)], max_bars=60, be=2.0),
    "P1": dict(targets=[(1, 0.5), (3, 0.5)], max_bars=60),
    "P1.5": dict(targets=[(1.5, 0.5), (3, 0.5)], max_bars=60),
    "P2-4": dict(targets=[(2, 0.5), (4, 0.5)], max_bars=60),
    "P1.5BE": dict(targets=[(1.5, 0.5), (3, 0.5)], max_bars=60, be_after_partial=True),
    "TR3-1": dict(targets=[], max_bars=180, trail=("atr", 3.0, 1.0, None)),
    "TR2-2": dict(targets=[], max_bars=180, trail=("atr", 2.0, 2.0, None)),
    "TRS-1": dict(targets=[], max_bars=180, trail=("struct", 10, 1.0, None)),
    "T3TR": dict(targets=[], max_bars=180, trail=("atr", 3.0, 3.0, 2.0)),
    "TIME30": dict(targets=[(3, 1.0)], max_bars=30),
    "TIME90": dict(targets=[(3, 1.0)], max_bars=90),
}


def entries(mk: Mkt):
    sp = mk.specs[ENTRY]
    out, last = [], -10**9
    for i in range(mk.start_i, len(mk.c4) - 2):
        if not sp.le[i] or i - last < COOLDOWN:
            continue
        j0 = mk.e[i]
        if j0 >= len(mk.ts1) - 1:
            break
        entry, stop = mk.o1[j0], sp.stop_l[i]
        risk = entry - stop if np.isfinite(stop) else np.nan
        if not np.isfinite(risk) or risk <= 0 or not (0.002 <= risk / entry <= 0.20):
            continue
        last = i
        out.append((i, j0, entry, stop, risk))
    return out


class Exits:
    def __init__(self, mk: Mkt):
        self.mk = mk
        self.close4 = mk.ts4 + BAR4
        self.atr4 = mk.df.atr.to_numpy()
        self.low10 = mk.df.low.rolling(10).min().to_numpy()
        self.ema50 = mk.df.ema50.to_numpy()
        self.close_px4 = mk.df.close.to_numpy()
        self.close4_set = set(int(x) for x in self.close4)

    def last_closed_4h(self, t):
        return int(np.searchsorted(self.close4, t, side="right")) - 1

    def run(self, v: dict, j0: int, entry: float, stop0: float, risk: float):
        mk = self.mk
        o1, hi, lo, ts1 = mk.o1, mk.hi, mk.lo, mk.ts1
        max_h = v["max_bars"] * 4
        targets = list(v["targets"])
        stop, pending = stop0, None
        rem, fills = 1.0, []          # (fraction, price, time)
        hh = entry
        be_px = entry * (1 + TAKER_RT)  # break-even including round-trip costs
        trail = v.get("trail")
        trail_on, locked = False, False
        partial_done = False
        n1 = len(o1)
        j = j0
        end = min(j0 + max_h, n1 - 1)
        while j < end and rem > 1e-9:
            if pending is not None:
                stop, pending = max(stop, pending), None
            o, h, l = o1[j], hi[j], lo[j]
            if o <= stop:
                fills.append((rem, o, ts1[j])); rem = 0; break
            if l <= stop:
                fills.append((rem, stop, ts1[j])); rem = 0; break
            for tR, frac in list(targets):
                px = entry + tR * risk
                if h >= px:
                    take = min(frac, rem)
                    fills.append((take, px, ts1[j])); rem -= take
                    targets.remove((tR, frac))
                    partial_done = True
                else:
                    break
            if rem <= 1e-9:
                break
            hh = max(hh, h)
            # activations take effect from the next bar
            cand = None
            if v.get("be") and hh >= entry + v["be"] * risk:
                cand = be_px
            if v.get("be_after_partial") and partial_done:
                cand = be_px if cand is None else max(cand, be_px)
            if trail:
                kind, k, act, lock = trail
                if not trail_on and hh >= entry + act * risk:
                    trail_on = True
                    if lock is not None:
                        locked = True
                if trail_on:
                    b = self.last_closed_4h(ts1[j] + 3600_000)  # 4h bars closed by the end of this 1h bar
                    if kind == "ema50":
                        # runner exits at the next open after a 4h close below the 4h EMA50
                        t_px = None
                        if int(ts1[j]) + 3600_000 in self.close4_set and b >= 0 and \
                                self.close_px4[b] < self.ema50[b] and j + 1 < n1:
                            fills.append((rem, o1[j + 1], ts1[j + 1])); rem = 0
                            break
                    elif kind == "atr" and b >= 0 and np.isfinite(self.atr4[b]):
                        t_px = hh - k * self.atr4[b]
                    elif kind == "struct" and b >= 0 and np.isfinite(self.low10[b]):
                        t_px = self.low10[b]
                    else:
                        t_px = None
                    if locked:
                        t_px = max(t_px or -np.inf, entry + lock * risk)
                    if t_px is not None:
                        cand = t_px if cand is None else max(cand, t_px)
            if cand is not None and cand > stop:
                pending = cand
            j += 1
        if rem > 1e-9:  # time exit at the next open
            jx = min(j, n1 - 1)
            fills.append((rem, o1[jx], ts1[jx]))
        t_in = ts1[j0]
        gross = sum(f * (px - entry) for f, px, _ in fills) / risk
        stop_pct = risk / entry
        fund = -sum(f * mk.funding_between(int(t_in), int(t)) for f, _, t in fills) / stop_pct
        net = gross + fund - TAKER_RT / stop_pct
        t_out = max(t for _, _, t in fills)
        return net, gross, fund, (t_out - t_in) / 3600_000


def study(mk: Mkt, name: str) -> pd.DataFrame:
    ex = Exits(mk)
    rows = []
    for i, j0, entry, stop, risk in entries(mk):
        rec = {"coin": name, "t_in": int(mk.ts1[j0]), "regime": mk.regime_at(int(mk.ts1[j0])),
               "stop_pct": risk / entry}
        for vid, v in VARIANTS.items():
            net, gross, fund, hours = ex.run(v, j0, entry, stop, risk)
            rec[vid], rec[vid + "_h"] = net, hours
        rows.append(rec)
    return pd.DataFrame(rows)


def summarize(t: pd.DataFrame) -> dict:
    out = {}
    for vid in VARIANTS:
        r = t[vid]
        d = r - t["B0"]
        streak = mx = 0
        for x in r:
            streak = streak + 1 if x <= 0 else 0
            mx = max(mx, streak)
        eq = np.cumprod(1 + 0.01 * r.to_numpy())
        dd = float((1 - eq / np.maximum.accumulate(eq)).max()) if len(eq) else 0.0
        wins, losses = r[r > 0].sum(), -r[r < 0].sum()
        out[vid] = {
            "n": int(len(r)), "exp": float(r.mean()), "win": float((r > 0).mean()),
            "pf": float(wins / losses) if losses > 0 else None, "max_losing_streak": int(mx),
            "dd_1pct": dd, "avg_hold_days": float(t[vid + "_h"].mean() / 24),
            "diff_vs_B0": float(d.mean()),
            "t_vs_B0": float(d.mean() / (d.std(ddof=1) / np.sqrt(len(d)))) if len(d) > 1 and d.std() > 0 else 0.0,
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
        print("done", name, len(frames[-1]), "trades", flush=True)
    T = pd.concat(frames, ignore_index=True)
    T.to_csv(out / "exit_trades.csv", index=False)
    btc = T[T.coin == "BTC"]
    sets = {
        "BTC dev 2020-23": btc[btc.t_in < HOLDOUT_START],
        "BTC holdout 2024-26": btc[btc.t_in >= HOLDOUT_START],
        **{c: T[T.coin == c] for c in T.coin.unique() if c != "BTC"},
    }
    sets["pooled holdout"] = pd.concat([sets["BTC holdout 2024-26"]] + [T[T.coin == c] for c in T.coin.unique() if c != "BTC"])
    sets["BTC dev, range-gated"] = sets["BTC dev 2020-23"][sets["BTC dev 2020-23"].regime == "range"]
    sets["pooled holdout, range-gated"] = sets["pooled holdout"][sets["pooled holdout"].regime == "range"]
    res = {k: summarize(v) for k, v in sets.items()}
    alts = [c for c in T.coin.unique() if c != "BTC"]
    verdict = {}
    for vid in VARIANTS:
        if vid == "B0":
            continue
        c1 = res["BTC dev 2020-23"][vid]["diff_vs_B0"] > 0
        c2 = res["BTC holdout 2024-26"][vid]["diff_vs_B0"] > 0
        n_alt = sum(res[a][vid]["diff_vs_B0"] > 0 for a in alts)
        c3 = n_alt >= 2
        tp = res["pooled holdout"][vid]["t_vs_B0"]
        c4 = tp >= 2.0
        c5 = res["pooled holdout"][vid]["win"] >= 0.30
        verdict[vid] = {"dev>0": c1, "btc_holdout>0": c2, "alts>0": n_alt, "pooled_t": tp, "pooled_t>=2": c4,
                        "bonferroni_t>=2.9": tp >= 2.9, "win>=30%": c5, "beats_B0": all([c1, c2, c3, c4, c5])}
    (out / "exit_results.json").write_text(json.dumps({"sets": res, "verdict": verdict}, indent=1))


if __name__ == "__main__":
    main(*sys.argv[1:])
