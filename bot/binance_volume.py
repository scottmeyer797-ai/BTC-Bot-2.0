"""4h volume from Binance spot (public market-data endpoint, no key, not region-restricted).

The volume filter of the strategy was researched on Binance volume; BloFin's own volume flags only ~40-50% of the
same spikes, Binance spot ~75-80% (research/backtest_report.md). Only volume is taken from Binance: prices, signals'
levels, stops and orders stay on BloFin.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

import pandas as pd
import requests

from .config import BAR_MS

log = logging.getLogger(__name__)
URL = "https://data-api.binance.vision/api/v3/klines"


def binance_symbol(inst_id: str) -> str:
    return inst_id.replace("-", "")  # BTC-USDT -> BTCUSDT


def fetch_4h_volume(inst_id: str, n_bars: int, now_ms: int | None = None, session=None) -> pd.DataFrame:
    """Closed 4h candles' base volume, oldest first: columns ts (open time, ms), volume."""
    now_ms = now_ms or int(time.time() * 1000)
    s = session or requests
    rows, end = [], None
    while len(rows) < n_bars:
        params = {"symbol": binance_symbol(inst_id), "interval": "4h", "limit": 1000}
        if end is not None:
            params["endTime"] = end
        r = s.get(URL, params=params, timeout=20)
        r.raise_for_status()
        page = r.json()
        if not page:
            break
        rows.extend(page)
        end = int(page[0][0]) - 1
        if len(page) < 1000:
            break
    df = pd.DataFrame([(int(k[0]), float(k[5])) for k in rows], columns=["ts", "volume"])
    df = df.drop_duplicates("ts").sort_values("ts")
    return df[df.ts + BAR_MS <= now_ms].tail(n_bars).reset_index(drop=True)


def apply_volume(df: pd.DataFrame, vol: pd.DataFrame, min_coverage: float = 0.95, check_bars: int = 300):
    """Replace df.volume with Binance volume on matching 4h bars.

    Returns (new_df, ok, coverage). Not ok (and df unchanged) when fewer than `min_coverage` of the last
    `check_bars` bars have a Binance value, e.g. the endpoint failed or the symbol isn't listed there.
    """
    m = df.merge(vol.rename(columns={"volume": "bvol"}), on="ts", how="left")
    recent = m.tail(check_bars)
    coverage = float(recent.bvol.notna().mean()) if len(recent) else 0.0
    if coverage < min_coverage:
        return df, False, coverage
    out = df.copy()
    out["volume"] = m["bvol"].to_numpy()
    return out, True, coverage


def cached_fetch(inst_id: str, cache_dir: Path, n_bars: int, now_ms: int | None = None, fetcher=None) -> pd.DataFrame:
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{inst_id}_4H_binance_volume.csv"
    fetcher = fetcher or fetch_4h_volume
    cached = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=["ts", "volume"])
    need = n_bars if len(cached) < n_bars * 0.95 else 30
    fresh = fetcher(inst_id, need, now_ms)
    df = pd.concat([cached, fresh]) if len(cached) else fresh
    df = df.astype({"ts": "int64"}).drop_duplicates("ts", keep="last").sort_values("ts")
    df = df.tail(n_bars).reset_index(drop=True)
    df.to_csv(path, index=False)
    return df
