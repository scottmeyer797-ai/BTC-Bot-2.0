import numpy as np
import pandas as pd

from bot.config import BAR_MS
from bot.indicators import DAY_MS

T0 = 1_700_000_000_000 // DAY_MS * DAY_MS  # a UTC midnight


def bars_from_daily(highs, lows, start=T0, base_vol=100.0):
    """6 x 4h bars per day; the day's high is in bar 2, the low in bar 4, close mid-range."""
    rows = []
    for d, (h, l) in enumerate(zip(highs, lows)):
        mid = (h + l) / 2
        for b in range(6):
            ts = start + d * DAY_MS + b * BAR_MS
            hi = h if b == 2 else mid + (h - mid) * 0.5
            lo = l if b == 4 else mid - (mid - l) * 0.5
            rows.append([ts, mid, hi, lo, mid, base_vol])
    return pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])


def random_walk_bars(n, seed=0, start=T0):
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0, 0.01, n)))
    open_ = np.concatenate([[100], close[:-1]])
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.01, n))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.01, n))
    vol = rng.lognormal(5, 0.4, n)
    ts = start + np.arange(n) * BAR_MS
    return pd.DataFrame({"ts": ts, "open": open_, "high": high, "low": low, "close": close, "volume": vol})
