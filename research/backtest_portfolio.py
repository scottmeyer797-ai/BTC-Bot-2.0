"""Bias-controlled backtest of every regime top-5 strategy, on BTC (in-sample) and an alt (out-of-sample).

Usage: python research/backtest_portfolio.py <btc_1h_dir> <btc_funding_dir> <alt_1h_dir> <alt_funding_dir> <alt_name> <out_dir>

Bias controls
- Look-ahead: every signal/stop/target/regime is recomputed from data truncated at random points and must
  match the full-history value (lookahead_test). Regime gates use the live label known at entry only.
- Execution: signal at the 4h close, fill at the OPEN of the next 1h bar. A stop gapped through fills at the
  open (worse than the stop). Stop is assumed first when one 1h bar touches stop and target. Signal exits
  and time exits fill at the next 1h open.
- Costs: 0.06% taker fee + 0.02% slippage per side (0.16% round trip); grids 0.02% maker per fill.
  Real Binance funding (8h) charged on the position notional for the holding period.
- Sizing: 1% of current equity at risk per trade (grid: 1% per cycle, 1R = one side fully filled and stopped),
  one position per strategy, equity marked to market on 4h closes.
- No parameter is changed from the original study; the alt is never used to choose anything.
"""
from __future__ import annotations

import glob
import json
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from btc_edge_stats import load_1h, resample  # noqa: E402
from regime_strategies import BAR4, DAY, MAKER_RT, features, regimes, specs  # noqa: E402

TAKER_RT = 0.0016
RISK = 0.01
SEEDS = 20
H = 3600_000

LIVE, HIND = "live top-5", "hindsight top-5"
CATALOG = [
    # id, strategy name, direction, regime it was picked for, which list
    ("BULL-L1", "RSI(14) 30/70 fade, target mid-band", "long", "bull", LIVE),
    ("BULL-L2", "Current bot: swing-level break + volume z>2, 3R", "short", "bull", LIVE),
    ("BULL-L3", "Volume spike z>3, follow candle, 3R", "both", "bull", LIVE),
    ("BULL-L4", "GRID 1.5", "both", "bull", LIVE),
    ("RANGE-L1", "Volume spike z>3, follow candle, 3R", "both", "range", LIVE),
    ("RANGE-L2", "Current bot: swing-level break + volume z>2, 3R", "long", "range", LIVE),
    ("RANGE-L3", "Donchian-20 breakout, trail 10-bar channel", "long", "range", LIVE),
    ("RANGE-L4", "20-day channel breakout (120x4h), trail 60-bar", "both", "range", LIVE),
    ("RANGE-L5", "GRID 0.5", "both", "range", LIVE),
    ("BEAR-L1", "Failed breakout: 20-bar break then 2 closes back inside, 2R", "both", "bear", LIVE),
    ("BEAR-L2", "GRID 0.5", "short", "bear", LIVE),
    ("BEAR-L3", "Donchian-20 breakout, trail 10-bar channel", "short", "bear", LIVE),
    ("BULL-H1", "EMA 20/50 cross, exit on cross back", "long", "bull", HIND),
    ("BULL-H2", "Donchian-55 turtle, trail 20-bar channel", "long", "bull", HIND),
    ("BULL-H3", "Donchian-20 breakout, trail 10-bar channel", "long", "bull", HIND),
    ("BULL-H4", "Current bot: swing-level break + volume z>2, 3R", "long", "bull", HIND),
    ("BULL-H5", "Chandelier trend: new 20-bar high above EMA100, 3-ATR chandelier", "long", "bull", HIND),
    ("RANGE-H1", "Volume spike z>3, follow candle, 3R", "short", "range", HIND),
    ("RANGE-H2", "Current bot: swing-level break + volume z>2, 3R", "long", "range", HIND),
    ("RANGE-H3", "3-bar pullback in trend, 2R", "short", "range", HIND),
    ("RANGE-H4", "GRID 0.5", "both", "range", HIND),
    ("RANGE-H5", "EMA20 pullback in trend (touch EMA20, close back in trend direction), 2R", "long", "range", HIND),
    ("BEAR-H1", "30-day time-series momentum (sign of 30d return)", "short", "bear", HIND),
    ("BEAR-H2", "Stretch fade: close >2.5 ATR from EMA20, target EMA20", "short", "bear", HIND),
    ("BEAR-H3", "EMA 20/50 cross, exit on cross back", "both", "bear", HIND),
    ("BEAR-H4", "RSI(14) 30/70 fade, target mid-band", "short", "bear", HIND),
    ("BEAR-H5", "Prior-day high/low sweep & reclaim, 2R", "short", "bear", HIND),
]


# ---------------------------------------------------------------- market bundle
def load_funding(src: str) -> pd.DataFrame:
    fr = []
    for f in sorted(glob.glob(f"{src}/*.csv")):
        d = pd.read_csv(f)
        fr.append(d.iloc[:, [0, 2]].set_axis(["t", "rate"], axis=1))
    fr = pd.concat(fr).drop_duplicates("t").sort_values("t").reset_index(drop=True)
    return fr


class Mkt:
    def __init__(self, h1: pd.DataFrame, funding: pd.DataFrame):
        self.h1 = h1
        self.h4, self.d1 = resample(h1, BAR4), resample(h1, DAY)
        self.df = features(self.h4, self.d1)
        rg = regimes(self.d1)
        self.reg_of_day = dict(zip(rg.applies_day, rg.regime))
        self.first_day = int(rg.dropna(subset=["regime"]).applies_day.iloc[0])
        self.o1, self.hi, self.lo, self.cl, self.ts1 = (h1[k].to_numpy() for k in ("open", "high", "low", "close", "ts"))
        self.ts4 = self.df.ts.to_numpy()
        self.c4 = self.df.close.to_numpy()
        self.s = np.searchsorted(self.ts1, self.ts4)
        self.e = np.searchsorted(self.ts1, self.ts4 + BAR4)
        # funding: cumulative rate at each funding time; extend past the archive with the last 30-day mean
        f = funding[funding.t <= self.ts1[-1]]
        last = f.t.iloc[-1]
        extra = np.arange(last + 8 * H, self.ts1[-1] + 1, 8 * H)
        self.f_t = np.r_[f.t.to_numpy(), extra]
        self.f_cum = np.cumsum(np.r_[f.rate.to_numpy(), np.full(len(extra), f.rate.tail(90).mean())])
        self.funding_extrapolated_from = int(last)
        self.specs = {sp.name: sp for sp in specs(self.df)}
        self.start_i = int(np.searchsorted(self.ts4, self.first_day))

    def funding_between(self, t0: int, t1: int) -> float:
        a, b = np.searchsorted(self.f_t, t0, side="right"), np.searchsorted(self.f_t, t1, side="right")
        return float((self.f_cum[b - 1] if b else 0.0) - (self.f_cum[a - 1] if a else 0.0))

    def regime_at(self, t_ms: int):
        return self.reg_of_day.get(t_ms // DAY * DAY)


# ---------------------------------------------------------------- simulators
def simulate(sp, mk: Mkt, direction: str, gate: str | None):
    n = len(mk.c4)
    allow_l, allow_s = direction in ("both", "long"), direction in ("both", "short")
    rows, i = [], mk.start_i
    while i < n - 2:
        side = 1 if (allow_l and sp.le[i]) else -1 if (allow_s and sp.se[i]) else 0
        if side == 0:
            i += 1
            continue
        j0 = mk.e[i]                       # first 1h bar after the signal bar
        if j0 >= len(mk.ts1):
            break
        t_in = int(mk.ts1[j0])
        if gate and mk.regime_at(t_in) != gate:
            i += 1
            continue
        entry = mk.o1[j0]
        stop = sp.stop_l[i] if side > 0 else sp.stop_s[i]
        risk = (entry - stop) * side if np.isfinite(stop) else np.nan
        if not np.isfinite(risk) or risk <= 0 or not (0.002 <= risk / entry <= 0.20):
            i += 1
            continue
        if sp.tgt_r:
            tgt = entry + side * sp.tgt_r * risk
        elif sp.tgt_l is not None:
            tgt = sp.tgt_l[i] if side > 0 else sp.tgt_s[i]
            if not np.isfinite(tgt) or (tgt - entry) * side <= 0:
                i += 1
                continue
        else:
            tgt = None
        trail = sp.trail_l if side > 0 else sp.trail_s
        xsig = sp.xl if side > 0 else sp.xs
        exit_px = exit_j = None
        k = i + 1
        while k < n and k - i <= sp.max_bars:
            for j in range(max(mk.s[k], j0), mk.e[k]):
                o = mk.o1[j]
                if (o <= stop) if side > 0 else (o >= stop):
                    exit_px, exit_j = o, j          # gapped through the stop
                    break
                if (mk.lo[j] <= stop) if side > 0 else (mk.hi[j] >= stop):
                    exit_px, exit_j = stop, j
                    break
                if tgt is not None and ((mk.hi[j] >= tgt) if side > 0 else (mk.lo[j] <= tgt)):
                    exit_px, exit_j = tgt, j
                    break
            if exit_px is not None:
                break
            if xsig is not None and xsig[k] and mk.e[k] < len(mk.o1):
                exit_px, exit_j = mk.o1[mk.e[k]], mk.e[k]
                break
            if trail is not None and np.isfinite(trail[k]):
                stop = max(stop, trail[k]) if side > 0 else min(stop, trail[k])
            k += 1
        if exit_px is None:
            k = min(k, n - 1)
            exit_j = min(mk.e[k], len(mk.o1) - 1)
            exit_px = mk.o1[exit_j]
        t_out = int(mk.ts1[exit_j])
        stop_pct = risk / entry
        r_gross = (exit_px - entry) * side / risk
        r_fund = -side * mk.funding_between(t_in, t_out) * (exit_px + entry) / 2 / entry / stop_pct
        r_net = r_gross + r_fund - TAKER_RT / stop_pct
        rows.append((t_in, t_out, side, entry, exit_px, stop_pct, r_gross, r_fund, r_net, i, min(k, n - 1),
                     mk.regime_at(t_in)))
        i = max(k, i + 1)
    return pd.DataFrame(rows, columns=["t_in", "t_out", "side", "entry", "exit", "stop_pct", "r_gross", "r_fund",
                                       "r", "i_in", "k_out", "regime"])


def simulate_grid(mk: Mkt, step_atr: float, direction: str, gate: str | None, levels=5, life_days=7):
    ts1, o1, hi, lo, cl = mk.ts1, mk.o1, mk.hi, mk.lo, mk.cl
    atr4 = dict(zip(mk.df.ts.to_numpy(), mk.df.atr.to_numpy()))
    allow_l, allow_s = direction in ("both", "long"), direction in ("both", "short")
    risk_units = sum(levels + 1 - lv for lv in range(1, levels + 1))
    rows, j, n1 = [], int(np.searchsorted(ts1, mk.first_day)), len(ts1)
    while j < n1 - 1:
        a = atr4.get(ts1[j] // BAR4 * BAR4 - BAR4, np.nan)
        if not np.isfinite(a) or (gate and mk.regime_at(int(ts1[j])) != gate):
            j += 1
            continue
        c0, s = cl[j], step_atr * a
        lo_stop, hi_stop = c0 - (levels + 1) * s, c0 + (levels + 1) * s
        L = {lv: None for lv in range(1, levels + 1)}
        Sx = {lv: None for lv in range(1, levels + 1)}
        pnl, fills, k = 0.0, 0, j + 1
        while k < min(j + life_days * 24, n1):
            if lo[k] <= lo_stop or hi[k] >= hi_stop:
                down = lo[k] <= lo_stop
                px = min(o1[k], lo_stop) if down else max(o1[k], hi_stop)  # gap-aware
                for e in L.values():
                    if e is not None:
                        pnl += (px if down else cl[k]) - e
                for e in Sx.values():
                    if e is not None:
                        pnl += e - (px if not down else cl[k])
                L = dict.fromkeys(L)
                Sx = dict.fromkeys(Sx)
                break
            for lv, e in L.items():
                if e is not None and hi[k] >= e + s:
                    pnl += s
                    L[lv] = None
            for lv, e in Sx.items():
                if e is not None and lo[k] <= e - s:
                    pnl += s
                    Sx[lv] = None
            if allow_l:
                for lv in L:
                    if L[lv] is None and lo[k] <= c0 - lv * s:
                        L[lv], fills = c0 - lv * s, fills + 1
            if allow_s:
                for lv in Sx:
                    if Sx[lv] is None and hi[k] >= c0 + lv * s:
                        Sx[lv], fills = c0 + lv * s, fills + 1
            k += 1
        k = min(k, n1 - 1)
        for e in L.values():
            if e is not None:
                pnl += cl[k] - e
        for e in Sx.values():
            if e is not None:
                pnl += e - cl[k]
        pnl -= fills * MAKER_RT * c0
        r = pnl / (risk_units * s)
        rows.append((int(ts1[j]), int(ts1[k]), 0, c0, cl[k], risk_units * s / c0, r, 0.0, r, -1, -1,
                     mk.regime_at(int(ts1[j]))))
        j = k + 1
    return pd.DataFrame(rows, columns=["t_in", "t_out", "side", "entry", "exit", "stop_pct", "r_gross", "r_fund",
                                       "r", "i_in", "k_out", "regime"])


def run(mk: Mkt, name: str, direction: str, gate: str | None):
    if name.startswith("GRID"):
        return simulate_grid(mk, float(name.split()[1]), direction, gate)
    return simulate(mk.specs[name], mk, direction, gate)


# ---------------------------------------------------------------- equity & metrics
def equity_curve(t: pd.DataFrame, mk: Mkt) -> pd.Series:
    """Equity on 4h closes, 1% risk per trade, marked to market for bar-based trades."""
    eq = np.ones(len(mk.ts4))
    e = 1.0
    last_k = mk.start_i
    for row in t.itertuples():
        if row.i_in < 0:  # grid: realized at cycle end
            k = int(np.searchsorted(mk.ts4, row.t_out))
            eq[last_k:k] = e
            e *= 1 + RISK * row.r
            last_k = k
            continue
        i, k = row.i_in, row.k_out
        eq[last_k:i + 1] = e
        qty = RISK * e / (row.stop_pct * row.entry)
        for b in range(i + 1, k):
            eq[b] = e + qty * (mk.c4[b] - row.entry) * row.side
        e *= 1 + RISK * row.r
        last_k = k
    eq[last_k:] = e
    s = pd.Series(eq[mk.start_i:], index=pd.to_datetime(mk.ts4[mk.start_i:] + BAR4, unit="ms", utc=True))
    return s


def metrics(t: pd.DataFrame, eq: pd.Series) -> dict:
    if t.empty:
        return {"n": 0}
    years = (eq.index[-1] - eq.index[0]).days / 365.25
    daily = eq.resample("1D").last().pct_change().dropna()
    dd = 1 - eq / eq.cummax()
    r = t.r
    streak = mx = 0
    for x in r:
        streak = streak + 1 if x < 0 else 0
        mx = max(mx, streak)
    wins, losses = r[r > 0].sum(), -r[r < 0].sum()
    return {
        "n": int(len(t)), "per_year": len(t) / years, "win": float((r > 0).mean()), "exp": float(r.mean()),
        "t": float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))) if len(r) > 1 and r.std() > 0 else 0.0,
        "pf": float(wins / losses) if losses > 0 else float("inf"),
        "funding_r": float(t.r_fund.mean()), "total_return": float(eq.iloc[-1] - 1),
        "cagr": float(eq.iloc[-1] ** (1 / years) - 1), "max_dd": float(dd.max()),
        "sharpe": float(daily.mean() / daily.std() * np.sqrt(365)) if daily.std() > 0 else 0.0,
        "mar": float((eq.iloc[-1] ** (1 / years) - 1) / dd.max()) if dd.max() > 0 else 0.0,
        "max_losing_streak": int(mx), "worst_r": float(r.min()), "best_r": float(r.max()),
        "exposure": float(((t.t_out - t.t_in).sum()) / ((eq.index[-1] - eq.index[0]).total_seconds() * 1000)),
        "exp_2020_22": float(r[t.t_in < 1672531200000].mean()) if (t.t_in < 1672531200000).any() else None,
        "exp_2023_26": float(r[t.t_in >= 1672531200000].mean()) if (t.t_in >= 1672531200000).any() else None,
    }


def random_baseline(mk: Mkt, name: str, direction: str, gate: str | None, real: pd.DataFrame) -> dict:
    if name.startswith("GRID") or len(real) < 5:
        return {"p": None, "base_median": None}
    sp = mk.specs[name]
    c, a = mk.df.close.to_numpy(), mk.df.atr.to_numpy()
    stop_l = np.where(np.isfinite(sp.stop_l), sp.stop_l, c - 1.5 * a)
    stop_s = np.where(np.isfinite(sp.stop_s), sp.stop_s, c + 1.5 * a)
    n_bars = len(c) - mk.start_i
    if gate:
        in_gate = np.mean([mk.regime_at(int(x) + BAR4) == gate for x in mk.ts4[mk.start_i:]])
        n_bars *= max(in_gate, 1e-3)
    p = min(0.5, len(real) * 1.3 / max(n_bars, 1))
    share_long = float((real.side > 0).mean())
    vals = []
    for seed in range(SEEDS):
        rng = np.random.default_rng(5000 + seed)
        pick, lng = rng.random(len(c)) < p, rng.random(len(c)) < share_long
        t = simulate(replace(sp, le=pick & lng, se=pick & ~lng, stop_l=stop_l, stop_s=stop_s), mk, direction, gate)
        if len(t) >= 5:
            vals.append(t.r.mean())
    vals = np.array(vals)
    return {"p": float((vals >= real.r.mean()).mean()) if len(vals) else None,
            "base_median": float(np.median(vals)) if len(vals) else None}


# ---------------------------------------------------------------- look-ahead test
def lookahead_test(h1: pd.DataFrame, n_cuts=25, seed=0) -> dict:
    """Recompute everything on data truncated after bar t and compare bar t with the full-history values."""
    full = Mkt(h1, pd.DataFrame({"t": [0], "rate": [0.0]}))
    names = list(full.specs)
    arr_fields = ["le", "se", "stop_l", "stop_s", "tgt_l", "tgt_s", "trail_l", "trail_s", "xl", "xs"]
    rng = np.random.default_rng(seed)
    cuts = rng.integers(full.start_i + 50, len(full.ts4) - 5, n_cuts)
    mismatches, checks = [], 0
    for t in cuts:
        cut_ts = full.ts4[t] + BAR4
        h1t = h1[h1.ts < cut_ts].reset_index(drop=True)
        trunc = Mkt(h1t, pd.DataFrame({"t": [0], "rate": [0.0]}))
        assert trunc.ts4[-1] == full.ts4[t]
        for nm in names:
            a, b = full.specs[nm], trunc.specs[nm]
            for f in arr_fields:
                x, y = getattr(a, f), getattr(b, f)
                if x is None:
                    continue
                checks += 1
                xv, yv = x[t], y[-1]
                same = (xv == yv) or (isinstance(xv, (float, np.floating)) and np.isnan(xv) and np.isnan(yv)) or \
                    (isinstance(xv, (float, np.floating)) and np.isclose(xv, yv, rtol=1e-9, atol=1e-12))
                if not same:
                    mismatches.append((int(full.ts4[t]), nm, f, float(xv), float(yv)))
        day = (full.ts4[t] + BAR4) // DAY * DAY
        checks += 1
        if full.reg_of_day.get(day) != trunc.reg_of_day.get(day):
            mismatches.append((int(full.ts4[t]), "regime", "label", full.reg_of_day.get(day), trunc.reg_of_day.get(day)))
    return {"cuts": int(n_cuts), "checks": checks, "mismatches": mismatches[:50], "n_mismatch": len(mismatches)}


# ---------------------------------------------------------------- main
def evaluate_market(mk: Mkt, label: str, out: Path) -> dict:
    res, seen = {}, {}
    for cid, name, direction, regime, src in CATALOG:
        for mode, gate in (("always on", None), (f"only in {regime}", regime)):
            key = (name, direction, gate)
            if key not in seen:
                t = run(mk, name, direction, gate)
                eq = equity_curve(t, mk)
                seen[key] = {"metrics": metrics(t, eq), "baseline": random_baseline(mk, name, direction, gate, t)}
                t.to_csv(out / f"trades_{label}_{cid}_{'gated' if gate else 'ungated'}.csv", index=False)
                eq.resample("1D").last().to_csv(out / f"equity_{label}_{cid}_{'gated' if gate else 'ungated'}.csv")
            res[f"{cid}|{mode}"] = {"id": cid, "name": name, "direction": direction, "regime": regime, "list": src,
                                    "mode": mode, **seen[key]}
        print(label, "done", cid, flush=True)
    return res


def main(btc_dir, btc_f, alt_dir, alt_f, alt_name, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    h1_btc = load_1h(btc_dir)
    la = lookahead_test(h1_btc)
    print("look-ahead test:", la["checks"], "checks,", la["n_mismatch"], "mismatches", flush=True)
    btc = Mkt(h1_btc, load_funding(btc_f))
    alt = Mkt(load_1h(alt_dir), load_funding(alt_f))
    res = {"lookahead": la, "alt": alt_name,
           "funding_extrapolated_from": {"BTC": btc.funding_extrapolated_from, alt_name: alt.funding_extrapolated_from},
           "BTC": evaluate_market(btc, "BTC", out), alt_name: evaluate_market(alt, alt_name, out)}
    (out / "backtest_results.json").write_text(json.dumps(res, indent=1, default=float))


if __name__ == "__main__":
    main(*sys.argv[1:7])
