"""Which strategy types work in which BTC regime?

Usage: python research/regime_strategies.py <binance_1h_csv_dir> <out_dir>

- BTCUSDT perp 1h candles (Binance), resampled to 4h and daily (UTC).
- Daily regime (bull / bear / range) from information up to the previous day's close only.
- ~25 strategy types x {long+short, long only, short only}. One position at a time per variant;
  stops/targets resolved on the 1h path (stop first if both in one 1h bar); signal exits at 4h closes.
- Every trade is measured in R (P&L / initial risk) after costs, and attributed to the regime at entry.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from btc_edge_stats import load_1h, resample  # noqa: E402
from bot.indicators import daily_candles, levels_at, swing_levels  # noqa: E402

H, BAR4, DAY = 3600_000, 4 * 3600_000, 86_400_000
TAKER_RT = 0.0014   # 2 x 0.05% fee + 2 x 0.02% slippage (market orders)
MAKER_RT = 0.0004   # 2 x 0.02% maker fee (grid limit orders)
SPLIT = pd.Timestamp("2023-01-01", tz="UTC").value // 10**6


# ---------------------------------------------------------------- regimes
def regimes(d1: pd.DataFrame, er_range=0.20) -> pd.DataFrame:
    """bull: close > SMA100, SMA100 rising over 20d, 30d efficiency ratio >= er_range.
    bear: mirror. range: everything else (choppy or mixed signals). Applied to the NEXT day."""
    d = d1.copy()
    c = d["close"]
    d["sma100"] = c.rolling(100).mean()
    d["slope"] = d["sma100"] / d["sma100"].shift(20) - 1
    d["er30"] = (c - c.shift(30)).abs() / c.diff().abs().rolling(30).sum()
    bull = (c > d.sma100) & (d.slope > 0) & (d.er30 >= er_range)
    bear = (c < d.sma100) & (d.slope < 0) & (d.er30 >= er_range)
    d["regime"] = np.where(bull, "bull", np.where(bear, "bear", "range"))
    d.loc[d.sma100.isna() | d.slope.isna() | d.er30.isna(), "regime"] = None
    d["applies_day"] = d["ts"] + DAY
    return d


def realized_regimes(d1: pd.DataFrame, move=0.10, er_min=0.25) -> dict:
    """Hindsight label: what the market actually did over the NEXT 30 days from each day.
    bull: +10% or more with efficiency ratio >= 0.25; bear: mirror; range: otherwise."""
    c = d1["close"]
    fwd = c.shift(-30) / c - 1
    path = c.diff().abs().rolling(30).sum().shift(-30)
    er = (c.shift(-30) - c).abs() / path
    lab = np.where((fwd >= move) & (er >= er_min), "bull", np.where((fwd <= -move) & (er >= er_min), "bear", "range"))
    lab = pd.Series(lab, index=d1.index).where(fwd.notna())
    return dict(zip(d1["ts"], lab))


# ---------------------------------------------------------------- indicators (4h)
def ema(x, n):
    return x.ewm(span=n, adjust=False).mean()


def rsi(c, n):
    dlt = c.diff()
    up = dlt.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-dlt.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def adx(df, n=14):
    h, l, c = df.high, df.low, df.close
    up, dn = h.diff(), -l.diff()
    pdm = np.where((up > dn) & (up > 0), up, 0.0)
    ndm = np.where((dn > up) & (dn > 0), dn, 0.0)
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / n, adjust=False).mean()
    pdi = 100 * pd.Series(pdm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    ndi = 100 * pd.Series(ndm, index=df.index).ewm(alpha=1 / n, adjust=False).mean() / atr
    dx = 100 * (pdi - ndi).abs() / (pdi + ndi)
    return dx.ewm(alpha=1 / n, adjust=False).mean()


def supertrend(df, atr, mult=3.0):
    hl2 = ((df.high + df.low) / 2).to_numpy()
    c = df.close.to_numpy()
    a = atr.to_numpy()
    n = len(df)
    up, dn, line, dirn = np.full(n, np.nan), np.full(n, np.nan), np.full(n, np.nan), np.zeros(n)
    for i in range(n):
        if np.isnan(a[i]):
            continue
        bu, bd = hl2[i] - mult * a[i], hl2[i] + mult * a[i]
        if i == 0 or np.isnan(up[i - 1]):
            up[i], dn[i], dirn[i] = bu, bd, 1
        else:
            up[i] = max(bu, up[i - 1]) if c[i - 1] > up[i - 1] else bu
            dn[i] = min(bd, dn[i - 1]) if c[i - 1] < dn[i - 1] else bd
            if dirn[i - 1] == 1 and c[i] < up[i]:
                dirn[i] = -1
            elif dirn[i - 1] == -1 and c[i] > dn[i]:
                dirn[i] = 1
            else:
                dirn[i] = dirn[i - 1]
        line[i] = up[i] if dirn[i] == 1 else dn[i]
    return pd.Series(line, index=df.index), pd.Series(dirn, index=df.index)


def features(h4: pd.DataFrame, d1: pd.DataFrame) -> pd.DataFrame:
    df = h4.reset_index(drop=True).copy()
    c, h, l = df.close, df.high, df.low
    pc = c.shift()
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    df["atr"] = tr.rolling(14).mean()
    for n in (20, 50, 100, 200):
        df[f"ema{n}"] = ema(c, n)
    df["rsi2"], df["rsi14"] = rsi(c, 2), rsi(c, 14)
    df["sma5"] = c.rolling(5).mean()
    m, s = c.rolling(20).mean(), c.rolling(20).std()
    df["bb_mid"], df["bb_up"], df["bb_lo"] = m, m + 2 * s, m - 2 * s
    bw = (4 * s) / m
    df["bw_pct"] = bw.rolling(120).rank(pct=True)
    df["adx"] = adx(df)
    for n in (10, 20, 55, 60, 120):
        df[f"hh{n}"] = h.rolling(n).max().shift(1)
        df[f"ll{n}"] = l.rolling(n).min().shift(1)
    df["hh22"], df["ll22"] = h.rolling(22).max(), l.rolling(22).min()
    df["st_line"], df["st_dir"] = supertrend(df, df["atr"])
    df["roc180"] = c / c.shift(180) - 1
    v = df.volume
    df["vol_z"] = (v - v.rolling(50).mean()) / v.rolling(50).std()
    r = np.log(c).diff()
    df["ret_z"] = r / r.rolling(100).std()
    # prior UTC day high/low, usable from the next day
    dd = d1.set_index(d1["ts"] + DAY)[["high", "low"]].rename(columns={"high": "pdh", "low": "pdl"})
    df = df.join(dd, on=(df.ts // DAY) * DAY)
    df["hour"] = (df.ts // H) % 24
    df["day"] = (df.ts // DAY) * DAY
    # swing levels (current bot)
    lv = swing_levels(daily_candles(h4, int(h4.ts.iloc[-1]) + BAR4))
    df["lv_long"], df["lv_short"] = np.nan, np.nan
    for i in range(1, len(df)):
        L = levels_at(lv, int(df.ts.iat[i]) + BAR4)
        if not len(L) or not np.isfinite(df.atr.iat[i]):
            continue
        ci, cp, a = df.close.iat[i], df.close.iat[i - 1], df.atr.iat[i]
        lo = L[(ci > L + 0.2 * a) & (cp <= L)]
        sh = L[(ci < L - 0.2 * a) & (cp >= L)]
        if len(lo):
            df.at[i, "lv_long"] = lo.max()
        elif len(sh):
            df.at[i, "lv_short"] = sh.min()
    return df


# ---------------------------------------------------------------- strategy specs
@dataclass
class Spec:
    name: str
    family: str                 # trend | breakout | pullback | mean-reversion | grid | fade
    le: np.ndarray              # long entry at close of bar i
    se: np.ndarray
    stop_l: np.ndarray          # initial stop price for a long entered at bar i
    stop_s: np.ndarray
    tgt_r: float | None = None  # fixed target in R
    tgt_l: np.ndarray | None = None  # fixed target price (e.g. band mid at entry)
    tgt_s: np.ndarray | None = None
    trail_l: np.ndarray | None = None  # ratcheting stop candidate after each bar
    trail_s: np.ndarray | None = None
    xl: np.ndarray | None = None       # exit long at close of bar k
    xs: np.ndarray | None = None
    max_bars: int = 60
    exit_on_opposite: bool = False
    notes: str = ""
    extra: dict = field(default_factory=dict)


def B(x):
    return np.nan_to_num(np.asarray(x, dtype=float), nan=0.0).astype(bool)


def specs(df: pd.DataFrame) -> list[Spec]:
    c, o, h, l, a = df.close, df.open, df.high, df.low, df.atr
    cp = c.shift()
    S = []

    def add(**kw):
        S.append(Spec(**kw))

    # ---- trend following
    add(name="Donchian-20 breakout, trail 10-bar channel", family="trend",
        le=B((c > df.hh20) & (cp <= df.hh20.shift())), se=B((c < df.ll20) & (cp >= df.ll20.shift())),
        stop_l=(c - 2 * a).to_numpy(), stop_s=(c + 2 * a).to_numpy(),
        trail_l=df.ll10.to_numpy(), trail_s=df.hh10.to_numpy(), max_bars=180)
    add(name="Donchian-55 turtle, trail 20-bar channel", family="trend",
        le=B((c > df.hh55) & (cp <= df.hh55.shift())), se=B((c < df.ll55) & (cp >= df.ll55.shift())),
        stop_l=(c - 2 * a).to_numpy(), stop_s=(c + 2 * a).to_numpy(),
        trail_l=df.ll20.to_numpy(), trail_s=df.hh20.to_numpy(), max_bars=300)
    add(name="20-day channel breakout (120x4h), trail 60-bar", family="trend",
        le=B((c > df.hh120) & (cp <= df.hh120.shift())), se=B((c < df.ll120) & (cp >= df.ll120.shift())),
        stop_l=(c - 3 * a).to_numpy(), stop_s=(c + 3 * a).to_numpy(),
        trail_l=df.ll60.to_numpy(), trail_s=df.hh60.to_numpy(), max_bars=400)
    x20_50 = (df.ema20 > df.ema50)
    add(name="EMA 20/50 cross, exit on cross back", family="trend",
        le=B(x20_50 & ~x20_50.shift(fill_value=False)), se=B(~x20_50 & x20_50.shift(fill_value=False)),
        stop_l=(c - 2 * a).to_numpy(), stop_s=(c + 2 * a).to_numpy(),
        xl=B(~x20_50), xs=B(x20_50), max_bars=400)
    x50_200 = (df.ema50 > df.ema200)
    add(name="EMA 50/200 cross, exit on cross back", family="trend",
        le=B(x50_200 & ~x50_200.shift(fill_value=False)), se=B(~x50_200 & x50_200.shift(fill_value=False)),
        stop_l=(c - 3 * a).to_numpy(), stop_s=(c + 3 * a).to_numpy(),
        xl=B(~x50_200), xs=B(x50_200), max_bars=1000)
    st = df.st_dir
    add(name="Supertrend(10,3) flip, trail on line", family="trend",
        le=B((st == 1) & (st.shift() == -1)), se=B((st == -1) & (st.shift() == 1)),
        stop_l=df.st_line.to_numpy(), stop_s=df.st_line.to_numpy(),
        trail_l=df.st_line.to_numpy(), trail_s=df.st_line.to_numpy(), max_bars=400)
    add(name="Chandelier trend: new 20-bar high above EMA100, 3-ATR chandelier", family="trend",
        le=B((c > df.hh20) & (c > df.ema100)), se=B((c < df.ll20) & (c < df.ema100)),
        stop_l=(c - 3 * a).to_numpy(), stop_s=(c + 3 * a).to_numpy(),
        trail_l=(df.hh22 - 3 * a).to_numpy(), trail_s=(df.ll22 + 3 * a).to_numpy(), max_bars=400)
    roc = df.roc180
    add(name="30-day time-series momentum (sign of 30d return)", family="trend",
        le=B((roc > 0) & (roc.shift() <= 0)), se=B((roc < 0) & (roc.shift() >= 0)),
        stop_l=(c - 3 * a).to_numpy(), stop_s=(c + 3 * a).to_numpy(),
        xl=B(roc < 0), xs=B(roc > 0), max_bars=1000)
    # ---- breakout with fixed targets
    lvl, lvs = df.lv_long, df.lv_short
    stp = (abs(c - (lvl - 0.5 * a)) / c).between(0.003, 0.10) | (abs(c - (lvs + 0.5 * a)) / c).between(0.003, 0.10)
    add(name="Current bot: swing-level break + volume z>2, 3R", family="breakout",
        le=B(lvl.notna() & (df.vol_z > 2) & stp), se=B(lvs.notna() & (df.vol_z > 2) & stp),
        stop_l=(lvl - 0.5 * a).to_numpy(), stop_s=(lvs + 0.5 * a).to_numpy(), tgt_r=3.0)
    add(name="Volume spike z>3, follow candle, 3R", family="breakout",
        le=B((df.vol_z > 3) & (c > o)), se=B((df.vol_z > 3) & (c < o)),
        stop_l=(c - 1.5 * a).to_numpy(), stop_s=(c + 1.5 * a).to_numpy(), tgt_r=3.0)
    sq = (df.bw_pct.rolling(5).min() < 0.2)
    add(name="Bollinger squeeze breakout, 3R", family="breakout",
        le=B(sq & (c > df.bb_up)), se=B(sq & (c < df.bb_lo)),
        stop_l=(c - 1.5 * a).to_numpy(), stop_s=(c + 1.5 * a).to_numpy(), tgt_r=3.0)
    first = df.hour == 0
    orh = pd.Series(np.where(first, h, np.nan)).ffill()
    orl = pd.Series(np.where(first, l, np.nan)).ffill()
    sameday = df.day == pd.Series(np.where(first, df.day, np.nan)).ffill()
    newday = df.hour == 20  # exit at the close of the last bar of the day
    add(name="Daily opening-range (00-04 UTC) breakout, 2R, exit end of day", family="breakout",
        le=B(~first & sameday & (c > orh) & (cp <= orh)), se=B(~first & sameday & (c < orl) & (cp >= orl)),
        stop_l=orl.to_numpy(), stop_s=orh.to_numpy(), tgt_r=2.0, xl=B(newday), xs=B(newday), max_bars=6)
    inside = (h.shift() <= h.shift(2)) & (l.shift() >= l.shift(2))
    add(name="Inside-bar breakout, 2R", family="breakout",
        le=B(inside & (c > h.shift(2))), se=B(inside & (c < l.shift(2))),
        stop_l=l.shift(2).to_numpy(), stop_s=h.shift(2).to_numpy(), tgt_r=2.0, max_bars=30)
    # ---- pullbacks in trend
    up = (c > df.ema50) & (df.ema50 > df.ema200)
    dn = (c < df.ema50) & (df.ema50 < df.ema200)
    add(name="Trend pullback: RSI14 back above 40 in uptrend / below 60 in downtrend, 2R", family="pullback",
        le=B(up & (df.rsi14 > 40) & (df.rsi14.shift() <= 40)), se=B(dn & (df.rsi14 < 60) & (df.rsi14.shift() >= 60)),
        stop_l=(c - 2 * a).to_numpy(), stop_s=(c + 2 * a).to_numpy(), tgt_r=2.0)
    add(name="EMA20 pullback in trend (touch EMA20, close back in trend direction), 2R", family="pullback",
        le=B(up & (l <= df.ema20) & (c > df.ema20) & (c > o)), se=B(dn & (h >= df.ema20) & (c < df.ema20) & (c < o)),
        stop_l=(c - 1.5 * a).to_numpy(), stop_s=(c + 1.5 * a).to_numpy(), tgt_r=2.0)
    three_dn = (c < cp) & (cp < c.shift(2)) & (c.shift(2) < c.shift(3))
    three_up = (c > cp) & (cp > c.shift(2)) & (c.shift(2) > c.shift(3))
    add(name="3-bar pullback in trend, 2R", family="pullback",
        le=B(up & three_dn), se=B(dn & three_up),
        stop_l=(c - 2 * a).to_numpy(), stop_s=(c + 2 * a).to_numpy(), tgt_r=2.0)
    # ---- mean reversion
    add(name="Bollinger(20,2) fade, target mid-band", family="mean-reversion",
        le=B(c < df.bb_lo), se=B(c > df.bb_up),
        stop_l=(c - 1.5 * a).to_numpy(), stop_s=(c + 1.5 * a).to_numpy(),
        tgt_l=df.bb_mid.to_numpy(), tgt_s=df.bb_mid.to_numpy(), max_bars=30)
    add(name="RSI(2) extreme (<5 / >95), exit on close beyond SMA5", family="mean-reversion",
        le=B(df.rsi2 < 5), se=B(df.rsi2 > 95), stop_l=(c - 2 * a).to_numpy(), stop_s=(c + 2 * a).to_numpy(),
        xl=B(c > df.sma5), xs=B(c < df.sma5), max_bars=20)
    add(name="RSI(14) 30/70 fade, target mid-band", family="mean-reversion",
        le=B((df.rsi14 < 30) & (df.rsi14.shift() >= 30)), se=B((df.rsi14 > 70) & (df.rsi14.shift() <= 70)),
        stop_l=(c - 2 * a).to_numpy(), stop_s=(c + 2 * a).to_numpy(),
        tgt_l=df.bb_mid.to_numpy(), tgt_s=df.bb_mid.to_numpy(), max_bars=30)
    mid20 = (df.hh20 + df.ll20) / 2
    add(name="Range fade at 20-bar high/low when ADX<20, target channel mid", family="mean-reversion",
        le=B((df.adx < 20) & (l <= df.ll20) & (c > df.ll20)), se=B((df.adx < 20) & (h >= df.hh20) & (c < df.hh20)),
        stop_l=(df.ll20 - a).to_numpy(), stop_s=(df.hh20 + a).to_numpy(),
        tgt_l=mid20.to_numpy(), tgt_s=mid20.to_numpy(), max_bars=30)
    add(name="Stretch fade: close >2.5 ATR from EMA20, target EMA20", family="mean-reversion",
        le=B(c < df.ema20 - 2.5 * a), se=B(c > df.ema20 + 2.5 * a),
        stop_l=(c - 1.5 * a).to_numpy(), stop_s=(c + 1.5 * a).to_numpy(),
        tgt_l=df.ema20.to_numpy(), tgt_s=df.ema20.to_numpy(), max_bars=30)
    add(name="Fade a >2.5σ 4h move, 2R", family="mean-reversion",
        le=B(df.ret_z < -2.5), se=B(df.ret_z > 2.5),
        stop_l=(l - 0.5 * a).to_numpy(), stop_s=(h + 0.5 * a).to_numpy(), tgt_r=2.0, max_bars=30)
    # ---- fades / failed moves
    add(name="Prior-day high/low sweep & reclaim, 2R", family="fade",
        le=B((l < df.pdl) & (c > df.pdl)), se=B((h > df.pdh) & (c < df.pdh)),
        stop_l=(l - 0.25 * a).to_numpy(), stop_s=(h + 0.25 * a).to_numpy(), tgt_r=2.0, max_bars=30)
    brk_up = (c.shift(2) > df.hh20.shift(2))
    brk_dn = (c.shift(2) < df.ll20.shift(2))
    add(name="Failed breakout: 20-bar break then 2 closes back inside, 2R", family="fade",
        le=B(brk_dn & (cp > df.ll20.shift(2)) & (c > df.ll20.shift(2))),
        se=B(brk_up & (cp < df.hh20.shift(2)) & (c < df.hh20.shift(2))),
        stop_l=(l.rolling(3).min() - 0.25 * a).to_numpy(), stop_s=(h.rolling(3).max() + 0.25 * a).to_numpy(),
        tgt_r=2.0, max_bars=30)
    return S


# ---------------------------------------------------------------- simulators
class Market:
    def __init__(self, h1, df):
        self.hi, self.lo, self.cl, self.ts1 = (h1[k].to_numpy() for k in ("high", "low", "close", "ts"))
        self.s = np.searchsorted(self.ts1, df.ts.to_numpy())
        self.e = np.searchsorted(self.ts1, df.ts.to_numpy() + BAR4)
        self.c4 = df.close.to_numpy()
        self.ts4 = df.ts.to_numpy()


def simulate(sp: Spec, m: Market, direction: str, start_i: int):
    n = len(m.c4)
    rows = []
    i = start_i
    allow_l, allow_s = direction in ("both", "long"), direction in ("both", "short")
    while i < n - 1:
        side = 1 if (allow_l and sp.le[i]) else -1 if (allow_s and sp.se[i]) else 0
        if side == 0:
            i += 1
            continue
        entry = m.c4[i]
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
        exit_px, k = None, i + 1
        trail = sp.trail_l if side > 0 else sp.trail_s
        xsig = sp.xl if side > 0 else sp.xs
        opp = sp.se if side > 0 else sp.le
        while k < n and k - i <= sp.max_bars:
            for j in range(m.s[k], m.e[k]):
                if (m.lo[j] <= stop) if side > 0 else (m.hi[j] >= stop):
                    exit_px = stop
                    break
                if tgt is not None and ((m.hi[j] >= tgt) if side > 0 else (m.lo[j] <= tgt)):
                    exit_px = tgt
                    break
            if exit_px is not None:
                break
            if (xsig is not None and xsig[k]) or (sp.exit_on_opposite and opp[k]):
                exit_px = m.c4[k]
                break
            if trail is not None and np.isfinite(trail[k]):
                stop = max(stop, trail[k]) if side > 0 else min(stop, trail[k])
            k += 1
        k = min(k, n - 1)
        if exit_px is None:
            exit_px = m.c4[k]
        r = (exit_px - entry) * side / risk - TAKER_RT / (risk / entry)
        rows.append((m.ts4[i] + BAR4, side, r, risk / entry, k - i))
        i = k if k > i else i + 1
    return pd.DataFrame(rows, columns=["ts", "side", "r", "stop_pct", "bars"])


def simulate_grid(h1, df, step_atr: float, levels: int = 5, life_days: int = 7, direction="both"):
    """Grid bot, one row per grid cycle (set-up until stop-out or `life_days`, then re-centre).

    Buy limits at centre - j*step (take profit one step higher, then re-arm); sell limits at centre + j*step.
    Grid stop at centre +/- (levels+1)*step closes everything. 1R = the loss if one side is fully filled
    and stopped (sum of each level's distance to the stop), so a cycle compares with a single 1R trade.
    Maker costs on every fill. A take-profit only fills in a later 1h bar than its entry (conservative).
    """
    ts1, hi, lo, cl = (h1[k].to_numpy() for k in ("ts", "high", "low", "close"))
    atr4 = dict(zip(df.ts.to_numpy(), df.atr.to_numpy()))
    rows = []
    j, n1 = 0, len(ts1)
    allow_l, allow_s = direction in ("both", "long"), direction in ("both", "short")
    risk_units = sum(levels + 1 - lv for lv in range(1, levels + 1))  # 15 steps for 5 levels
    while j < n1 - 1:
        a = atr4.get(ts1[j] // BAR4 * BAR4 - BAR4, np.nan)
        if not np.isfinite(a):
            j += 1
            continue
        c0, s = cl[j], step_atr * a
        lo_stop, hi_stop = c0 - (levels + 1) * s, c0 + (levels + 1) * s
        L = {lv: None for lv in range(1, levels + 1)}
        Sx = {lv: None for lv in range(1, levels + 1)}
        pnl, fills = 0.0, 0
        end, k = j + life_days * 24, j + 1
        while k < min(end, n1):
            if lo[k] <= lo_stop or hi[k] >= hi_stop:
                for e in L.values():
                    if e is not None:
                        pnl += (lo_stop if lo[k] <= lo_stop else cl[k]) - e
                for e in Sx.values():
                    if e is not None:
                        pnl += e - (hi_stop if hi[k] >= hi_stop else cl[k])
                L = {lv: None for lv in L}
                Sx = {lv: None for lv in Sx}
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
                        L[lv] = c0 - lv * s
                        fills += 1
            if allow_s:
                for lv in Sx:
                    if Sx[lv] is None and hi[k] >= c0 + lv * s:
                        Sx[lv] = c0 + lv * s
                        fills += 1
            k += 1
        k = min(k, n1 - 1)
        for e in L.values():
            if e is not None:
                pnl += cl[k] - e
        for e in Sx.values():
            if e is not None:
                pnl += e - cl[k]
        pnl -= fills * MAKER_RT * c0
        rows.append((ts1[j], 0, pnl / (risk_units * s), risk_units * s / c0 / levels, (k - j) / 4))
        j = k + 1
    return pd.DataFrame(rows, columns=["ts", "side", "r", "stop_pct", "bars"])


# ---------------------------------------------------------------- evaluation
def evaluate(t: pd.DataFrame, reg_of_day: dict, months_in: dict, entry_day_offset: int = 1) -> dict:
    """entry_day_offset=1: trade ts is the 4h close, so the entry day is (ts-1)//DAY."""
    t = t.copy()
    t["regime"] = ((t.ts - entry_day_offset) // DAY * DAY).map(reg_of_day)
    out = {}
    for rg in ("bull", "bear", "range"):
        x = t[t.regime == rg]
        if len(x) == 0:
            out[rg] = {"n": 0}
            continue
        a, b = x[x.ts < SPLIT], x[x.ts >= SPLIT]
        wins, losses = x.r[x.r > 0].sum(), -x.r[x.r < 0].sum()
        out[rg] = {
            "n": int(len(x)), "win": float((x.r > 0).mean()), "exp": float(x.r.mean()),
            "se": float(x.r.std(ddof=1) / np.sqrt(len(x))) if len(x) > 1 else float("nan"),
            "pf": float(wins / losses) if losses > 0 else float("inf"),
            "r_per_month": float(x.r.sum() / months_in[rg]),
            "n_a": int(len(a)), "exp_a": float(a.r.mean()) if len(a) else float("nan"),
            "n_b": int(len(b)), "exp_b": float(b.r.mean()) if len(b) else float("nan"),
            "avg_bars": float(x.bars.mean()) if x.bars.notna().any() else None,
            "stop_med": float(x.stop_pct.median()),
        }
    return out


def main(src, out_dir):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    h1 = load_1h(src)
    h4, d1 = resample(h1, BAR4), resample(h1, 86_400_000)
    rg = regimes(d1)
    reg_of_day = dict(zip(rg.applies_day, rg.regime))
    valid = rg.dropna(subset=["regime"])
    months_in = {r: float((valid.regime == r).sum() / 30.44) for r in ("bull", "bear", "range")}
    # regime summary: forward 30d return by regime (sanity check) + spells
    v = valid.copy()
    v["fwd30"] = v.close.shift(-30) / v.close - 1
    spells = (v.regime != v.regime.shift()).cumsum()
    summary = {r: {"days": int((v.regime == r).sum()),
                   "share": float((v.regime == r).mean()),
                   "fwd30_mean": float(v.fwd30[v.regime == r].mean()),
                   "fwd30_up": float((v.fwd30[v.regime == r] > 0).mean()),
                   "avg_spell_days": float(v.groupby(spells).regime.agg(["first", "size"]).query("first == @r")["size"].mean())}
               for r in ("bull", "bear", "range")}
    monthly = v.assign(m=pd.to_datetime(v.ts, unit="ms").dt.strftime("%Y-%m")).groupby("m").regime.agg(
        lambda s: s.value_counts().idxmax())
    # benchmarks: buy & hold return per day in each regime
    d = d1.copy()
    d["ret"] = d.close.pct_change()
    d["regime"] = d.ts.map(reg_of_day)
    bench = {r: {"daily_mean": float(d.ret[d.regime == r].mean()),
                 "ann": float((1 + d.ret[d.regime == r]).prod() ** (365 / max((d.regime == r).sum(), 1)) - 1)}
             for r in ("bull", "bear", "range")}

    real = realized_regimes(d1)
    rv = pd.Series({k: v for k, v in real.items() if k >= valid.ts.iloc[0]}).dropna()
    months_real = {r: float((rv == r).sum() / 30.44) for r in ("bull", "bear", "range")}
    summary["realized_share"] = {r: float((rv == r).mean()) for r in ("bull", "bear", "range")}
    both = pd.DataFrame({"live": pd.Series(reg_of_day), "real": pd.Series(real)}).dropna()
    summary["agreement"] = pd.crosstab(both.live, both.real, normalize="index").round(3).to_dict()

    df = features(h4, d1)
    m = Market(h1, df)
    start_i = int(np.searchsorted(df.ts.to_numpy(), valid.ts.iloc[0]))
    first_day = valid.applies_day.iloc[0]
    results = []

    def record(name, family, direction, t, offset):
        t = t[t.ts >= first_day]
        results.append({"name": name, "family": family, "direction": direction, "n_total": int(len(t)),
                        "live": evaluate(t, reg_of_day, months_in, offset),
                        "real": evaluate(t, real, months_real, offset)})
        t.assign(strategy=name, direction=direction).to_csv(out / f"trades_{len(results):03d}.csv", index=False)

    for sp in specs(df):
        for direction in ("both", "long", "short"):
            record(sp.name, sp.family, direction, simulate(sp, m, direction, start_i), 1)
        print("done", sp.name, flush=True)
    for step in (0.5, 1.0, 1.5):
        for direction in ("both", "long", "short"):
            record(f"Grid {step:g} ATR spacing, 5 levels/side, weekly re-centre", "grid", direction,
                   simulate_grid(h1, df, step, direction=direction), 0)
        print("done grid", step, flush=True)
    summary["months_real"] = months_real
    (out / "regime_results.json").write_text(json.dumps(
        {"regime_summary": summary, "months_in": months_in, "benchmarks": bench, "monthly": monthly.to_dict(),
         "results": results, "first_day": int(valid.ts.iloc[0]), "last_day": int(valid.ts.iloc[-1])},
        indent=1, default=float))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
