"""BTC price-action statistics for edge hunting (3 years, Binance USDT-M BTCUSDT perp, 1h -> 4h/1D).

Usage: python btc_edge_stats.py <binance_csv_dir> <out_dir>
"""
from __future__ import annotations

import glob
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from bot.indicators import add_indicators, daily_candles, levels_at, swing_levels  # noqa: E402

H = 3600_000
BAR4 = 4 * H
DAY = 24 * H
KS = [1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
MAX_HOLD_H = 240          # 60 x 4h bars
COST_PCT = 0.0014         # round trip: 2 x 0.05% taker + 2 x 0.02% slippage


# ------------------------------------------------------------------ data
def load_1h(src: str) -> pd.DataFrame:
    frames = []
    for f in sorted(glob.glob(f"{src}/*.csv")):
        df = pd.read_csv(f, header=None)
        if not str(df.iloc[0, 0]).isdigit():
            df = df.iloc[1:]
        df = df.iloc[:, :6].astype(float)
        df.columns = ["ts", "open", "high", "low", "close", "volume"]
        frames.append(df)
    df = pd.concat(frames).drop_duplicates("ts").sort_values("ts").reset_index(drop=True)
    df["ts"] = df["ts"].astype("int64")
    if df["ts"].iloc[-1] > 1e14:  # microseconds in newer files
        df.loc[df.ts > 1e14, "ts"] //= 1000
    return df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)


def resample(h1: pd.DataFrame, ms: int) -> pd.DataFrame:
    g = h1.groupby(h1["ts"] // ms * ms)
    out = pd.DataFrame({"open": g["open"].first(), "high": g["high"].max(), "low": g["low"].min(),
                        "close": g["close"].last(), "volume": g["volume"].sum(), "n": g["ts"].count()})
    out = out.reset_index().rename(columns={"index": "ts"})
    return out[out["n"] == ms // H].drop(columns="n").reset_index(drop=True)


# ------------------------------------------------------------------ exit simulator on the 1h path
class PathSim:
    def __init__(self, h1: pd.DataFrame):
        self.ts = h1["ts"].to_numpy()
        self.hi = h1["high"].to_numpy()
        self.lo = h1["low"].to_numpy()
        self.cl = h1["close"].to_numpy()

    def run(self, entry_ts: int, side: int, entry: float, stop: float) -> dict | None:
        """Outcome for every target k (in R). Stop wins ties inside one 1h bar (conservative)."""
        i0 = np.searchsorted(self.ts, entry_ts)
        if i0 >= len(self.ts) or self.ts[i0] != entry_ts:
            return None
        i1 = min(i0 + MAX_HOLD_H, len(self.ts))
        if i1 - i0 < MAX_HOLD_H:
            return None  # not enough future data
        hi, lo = self.hi[i0:i1], self.lo[i0:i1]
        r = abs(entry - stop)
        if side > 0:
            fav, adv = (hi - entry) / r, (entry - lo) / r
        else:
            fav, adv = (entry - lo) / r, (hi - entry) / r
        stop_hit = np.flatnonzero(adv >= 1.0)
        si = stop_hit[0] if len(stop_hit) else MAX_HOLD_H
        mfe = fav[:si].max() if si > 0 else 0.0
        out = {"mfe": float(mfe), "stopped": bool(len(stop_hit))}
        last = (self.cl[i1 - 1] - entry) / r * side
        for k in KS:
            th = np.flatnonzero(fav >= k)
            ti = th[0] if len(th) else MAX_HOLD_H
            if ti < si:
                out[k] = k
            elif si < MAX_HOLD_H:
                out[k] = -1.0
            else:
                out[k] = float(last)
        return out


# ------------------------------------------------------------------ indicators
def prep(h4: pd.DataFrame, d1: pd.DataFrame) -> pd.DataFrame:
    df = add_indicators(h4)  # close_ts, atr, vol_z, vol_rank
    c = df["close"]
    df["ret"] = np.log(c).diff()
    df["ret_z"] = df["ret"] / df["ret"].rolling(100).std()
    delta = c.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    df["rsi"] = 100 - 100 / (1 + up / dn)
    df["dc_hi20"] = df["high"].rolling(20).max().shift(1)
    df["dc_lo20"] = df["low"].rolling(20).min().shift(1)
    df["dc_hi55"] = df["high"].rolling(55).max().shift(1)
    df["dc_lo55"] = df["low"].rolling(55).min().shift(1)
    df["ema50"] = c.ewm(span=50, adjust=False).mean()
    # daily context known at each 4h close: yesterday's values
    d = d1.copy()
    d["sma200"] = d["close"].rolling(200).mean()
    d["sma50"] = d["close"].rolling(50).mean()
    d["trend"] = np.where(d["close"] > d["sma200"], 1, -1)
    d.loc[d["sma200"].isna(), "trend"] = 0
    d["pdh"], d["pdl"] = d["high"], d["low"]
    d["day_next"] = d["ts"] + DAY  # values usable from the next day
    m = d.set_index("day_next")[["trend", "pdh", "pdl", "sma50", "sma200"]]
    day_of = (df["ts"] // DAY) * DAY
    df = df.join(m, on=day_of)
    df["dow"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.dayofweek
    df["hour"] = pd.to_datetime(df["ts"], unit="ms", utc=True).dt.hour
    return df


# ------------------------------------------------------------------ entry families
def signals(df: pd.DataFrame, levels: pd.DataFrame) -> dict[str, list[tuple]]:
    """Each signal: (i, side, stop). Entry = close of bar i, at its close time."""
    fam: dict[str, list[tuple]] = {k: [] for k in [
        "A current: swing-level break + vol z>2", "B swing-level break, no volume filter",
        "C 4h Donchian-20 break, stop 1.5 ATR", "D 4h Donchian-55 break, stop 2 ATR",
        "E trend pullback: 200d trend + 4h RSI<30/>70", "F mean reversion: 4h move < -2.5σ / > +2.5σ",
        "G prior-day high/low sweep & reclaim", "H volume spike z>3, follow candle direction",
        "R random entries, stop 1.5 ATR"]}
    rng = np.random.default_rng(7)
    n = len(df)
    for i in range(300, n):
        row, prev = df.iloc[i], df.iloc[i - 1]
        atr, c = row["atr"], row["close"]
        if not np.isfinite(atr):
            continue
        t = int(row["close_ts"])
        lv = levels_at(levels, t)
        if len(lv):
            longs = lv[(c > lv + 0.2 * atr) & (prev["close"] <= lv)]
            shorts = lv[(c < lv - 0.2 * atr) & (prev["close"] >= lv)]
            s = None
            if len(longs):
                L = longs.max(); s = (i, 1, L - 0.5 * atr)
            elif len(shorts):
                L = shorts.min(); s = (i, -1, L + 0.5 * atr)
            if s and 0.003 <= abs(c - s[2]) / c <= 0.10:
                fam["B swing-level break, no volume filter"].append(s)
                if row["vol_z"] > 2.0:
                    fam["A current: swing-level break + vol z>2"].append(s)
        if c > row["dc_hi20"] and prev["close"] <= row["dc_hi20"]:
            fam["C 4h Donchian-20 break, stop 1.5 ATR"].append((i, 1, c - 1.5 * atr))
        elif c < row["dc_lo20"] and prev["close"] >= row["dc_lo20"]:
            fam["C 4h Donchian-20 break, stop 1.5 ATR"].append((i, -1, c + 1.5 * atr))
        if c > row["dc_hi55"] and prev["close"] <= row["dc_hi55"]:
            fam["D 4h Donchian-55 break, stop 2 ATR"].append((i, 1, c - 2 * atr))
        elif c < row["dc_lo55"] and prev["close"] >= row["dc_lo55"]:
            fam["D 4h Donchian-55 break, stop 2 ATR"].append((i, -1, c + 2 * atr))
        if row["trend"] == 1 and row["rsi"] < 30 and prev["rsi"] >= 30:
            fam["E trend pullback: 200d trend + 4h RSI<30/>70"].append((i, 1, c - 1.5 * atr))
        elif row["trend"] == -1 and row["rsi"] > 70 and prev["rsi"] <= 70:
            fam["E trend pullback: 200d trend + 4h RSI<30/>70"].append((i, -1, c + 1.5 * atr))
        if row["ret_z"] < -2.5:
            fam["F mean reversion: 4h move < -2.5σ / > +2.5σ"].append((i, 1, row["low"] - 0.5 * atr))
        elif row["ret_z"] > 2.5:
            fam["F mean reversion: 4h move < -2.5σ / > +2.5σ"].append((i, -1, row["high"] + 0.5 * atr))
        if np.isfinite(row["pdl"]):
            if row["low"] < row["pdl"] and c > row["pdl"]:
                fam["G prior-day high/low sweep & reclaim"].append((i, 1, row["low"] - 0.25 * atr))
            elif row["high"] > row["pdh"] and c < row["pdh"]:
                fam["G prior-day high/low sweep & reclaim"].append((i, -1, row["high"] + 0.25 * atr))
        if row["vol_z"] > 3.0:
            side = 1 if c > row["open"] else -1
            fam["H volume spike z>3, follow candle direction"].append((i, side, c - side * 1.5 * atr))
        if rng.random() < 0.05:
            side = 1 if rng.random() < 0.5 else -1
            fam["R random entries, stop 1.5 ATR"].append((i, side, c - side * 1.5 * atr))
    return fam


def run_family(df, sim, sigs, cooldown=6):
    rows, last = [], {}
    for i, side, stop in sigs:
        if i - last.get(side, -10**9) < cooldown:
            continue
        row = df.iloc[i]
        c = float(row["close"])
        stop_pct = abs(c - stop) / c
        if not (0.002 <= stop_pct <= 0.15):
            continue
        res = sim.run(int(row["close_ts"]), side, c, float(stop))
        if res is None:
            continue
        last[side] = i
        cost_r = COST_PCT / stop_pct
        rec = {"ts": int(row["close_ts"]), "side": side, "stop_pct": stop_pct, "cost_r": cost_r,
               "trend": row["trend"], "vol_rank": row["vol_rank"], "dow": row["dow"], "hour": row["hour"],
               "mfe": res["mfe"]}
        for k in KS:
            rec[f"g{k}"] = res[k]
            rec[f"n{k}"] = res[k] - cost_r
        rows.append(rec)
    return pd.DataFrame(rows)


def summarize(t: pd.DataFrame) -> dict:
    if t.empty:
        return {"n": 0}
    out = {"n": len(t)}
    for k in KS:
        out[f"win{k}"] = float((t[f"g{k}"] > 0).mean())
        out[f"exp{k}"] = float(t[f"n{k}"].mean())
        out[f"se{k}"] = float(t[f"n{k}"].std(ddof=1) / np.sqrt(len(t))) if len(t) > 1 else np.nan
    out["mfe_med"] = float(t["mfe"].median())
    out["stop_med"] = float(t["stop_pct"].median())
    out["cost_med"] = float(t["cost_r"].median())
    return out


def main(src, out_dir):
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    h1 = load_1h(src)
    h4, d1 = resample(h1, BAR4), resample(h1, DAY)
    start = int(h1["ts"].iloc[-1]) - 3 * 365 * DAY
    res = {"range": [int(h1.ts.iloc[0]), int(h1.ts.iloc[-1])], "start3y": start}

    # ---------- market character (last 3 years)
    d = d1[d1.ts >= start].copy()
    d["ret"] = np.log(d["close"]).diff()
    d["year"] = pd.to_datetime(d.ts, unit="ms", utc=True).dt.year
    d["range_pct"] = (d["high"] - d["low"]) / d["open"]
    yr = []
    for y, g in d.groupby("year"):
        eq = g["close"] / g["close"].cummax()
        yr.append({"year": int(y), "days": len(g), "ret": float(g["close"].iloc[-1] / g["open"].iloc[0] - 1),
                   "vol_ann": float(g["ret"].std() * np.sqrt(365)), "max_dd": float(1 - eq.min()),
                   "up_days": float((g["close"] > g["open"]).mean()), "avg_range": float(g["range_pct"].mean())})
    res["years"] = yr
    dd = d1.copy(); dd["sma200"] = dd["close"].rolling(200).mean()
    dd = dd[dd.ts >= start]
    res["pct_above_200d"] = float((dd["close"] > dd["sma200"]).mean())

    # ---------- trend vs mean reversion
    r1 = d["ret"].dropna()
    res["ac_daily"] = {lag: float(r1.autocorr(lag)) for lag in (1, 2, 5)}
    h4s = h4[h4.ts >= start].copy(); h4s["ret"] = np.log(h4s["close"]).diff()
    res["ac_4h"] = {lag: float(h4s["ret"].autocorr(lag)) for lag in (1, 2, 6)}
    vr = {}
    for k in (2, 5, 10, 20):
        rk = np.log(d["close"]).diff(k).dropna()
        vr[k] = float(rk.var() / (k * r1.var()))
    res["variance_ratio"] = vr
    # next-day after big days
    d["z"] = d["ret"] / d["ret"].rolling(60).std()
    d["next1"] = d["ret"].shift(-1); d["next5"] = np.log(d["close"]).shift(-5) - np.log(d["close"])
    big = {}
    for name, m in [("down >2σ", d.z < -2), ("up >2σ", d.z > 2), ("all", d.z.notna())]:
        g = d[m].dropna(subset=["next1", "next5"])
        big[name] = {"n": len(g), "next1_mean": float(g.next1.mean()), "next1_up": float((g.next1 > 0).mean()),
                     "next5_mean": float(g.next5.mean()), "next5_up": float((g.next5 > 0).mean())}
    res["after_big_days"] = big

    # ---------- seasonality (4h blocks and weekdays)
    h4s["hour"] = pd.to_datetime(h4s.ts, unit="ms", utc=True).dt.hour
    h4s["dow"] = pd.to_datetime(h4s.ts, unit="ms", utc=True).dt.dayofweek
    h4s["rng"] = (h4s.high - h4s.low) / h4s.open
    def sea(g):
        r = g["ret"].dropna()
        return {"n": len(r), "mean_bp": float(r.mean() * 1e4), "t": float(r.mean() / (r.std() / np.sqrt(len(r)))),
                "up": float((r > 0).mean()), "range_pct": float(g["rng"].mean())}
    res["by_hour"] = {int(h): sea(g) for h, g in h4s.groupby("hour")}
    d["dow"] = pd.to_datetime(d.ts, unit="ms", utc=True).dt.dayofweek
    res["by_dow"] = {int(k): {"n": len(g), "mean_bp": float(g.ret.mean() * 1e4),
                              "t": float(g.ret.mean() / (g.ret.std() / np.sqrt(len(g)))),
                              "up": float((g.ret > 0).mean()), "range_pct": float(g.range_pct.mean())}
                     for k, g in d.dropna(subset=["ret"]).groupby("dow")}

    # ---------- entry families with R exits
    df = prep(h4, d1)
    levels = swing_levels(daily_candles(h4, int(h4.ts.iloc[-1]) + BAR4))
    sim = PathSim(h1)
    fams = signals(df, levels)
    split = int(h1["ts"].iloc[-1]) - 365 * DAY
    fam_res, trades_all = {}, {}
    for name, sigs in fams.items():
        t = run_family(df, sim, sigs)
        t = t[t.ts >= start]
        trades_all[name] = t
        fam_res[name] = {
            "all": summarize(t), "is": summarize(t[t.ts < split]), "oos": summarize(t[t.ts >= split]),
            "long": summarize(t[t.side > 0]), "short": summarize(t[t.side < 0]),
            "with_trend": summarize(t[t.side == t.trend]), "against_trend": summarize(t[t.side == -t.trend]),
            "volrank_le_0.9": summarize(t[t.vol_rank <= 0.9]), "volrank_gt_0.9": summarize(t[t.vol_rank > 0.9]),
            "volrank_le_0.5": summarize(t[t.vol_rank <= 0.5]),
            "with_trend_is": summarize(t[(t.side == t.trend) & (t.ts < split)]),
            "with_trend_oos": summarize(t[(t.side == t.trend) & (t.ts >= split)]),
        }
        t.to_csv(out / f"trades_{name[0]}.csv", index=False)
    res["families"] = fam_res
    res["split"] = split
    (out / "results.json").write_text(json.dumps(res, indent=1, default=float))
    print("done", {k: v["all"].get("n") for k, v in fam_res.items()})


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
