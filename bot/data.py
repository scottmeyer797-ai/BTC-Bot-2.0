"""4h candle loading with a local CSV cache (confirmed candles only)."""
from __future__ import annotations

import logging
import time
from pathlib import Path

import pandas as pd

from .config import BAR_MS, HISTORY_BARS

log = logging.getLogger(__name__)
COLS = ["ts", "open", "high", "low", "close", "volume"]


def load_candles(client, inst_id: str, cache_dir: Path, n_bars: int = HISTORY_BARS,
                 now_ms: int | None = None) -> pd.DataFrame:
    """Return up to `n_bars` confirmed 4h candles for `inst_id`, oldest first."""
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{inst_id}_4H.csv"
    now_ms = now_ms or int(time.time() * 1000)
    cached = pd.read_csv(path) if path.exists() else pd.DataFrame(columns=COLS)
    if len(cached) >= n_bars * 0.95:
        last = int(cached["ts"].iloc[-1])
        gap = max(2, (now_ms - last) // BAR_MS + 3)
        fresh = client.candles(inst_id, int(min(gap, n_bars)), newer_than_ms=last)
    else:
        fresh = client.candles(inst_id, n_bars + 2)
    fresh = fresh[fresh["confirmed"]][COLS] if len(fresh) else fresh
    df = pd.concat([cached[COLS], fresh], ignore_index=True) if len(cached) else fresh[COLS]
    df = df.astype({"ts": "int64"}).drop_duplicates("ts", keep="last").sort_values("ts")
    df = df[df["ts"] + BAR_MS <= now_ms].tail(n_bars).reset_index(drop=True)
    _check_gaps(inst_id, df)
    df.to_csv(path, index=False)
    return df


def _check_gaps(inst_id: str, df: pd.DataFrame) -> None:
    if len(df) < 2:
        return
    d = df["ts"].diff().dropna()
    gaps = int((d != BAR_MS).sum())
    if gaps:
        log.warning("%s: %d gaps in 4h candle history", inst_id, gaps)
