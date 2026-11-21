import numpy as np
import pandas as pd

from bot.indicators import DAY_MS, add_indicators, btc_trend_at, btc_trend_by_day
from tests.helpers import T0, random_walk_bars


def test_atr_is_simple_mean_of_true_range():
    df = random_walk_bars(100, seed=1)
    out = add_indicators(df)
    pc = df.close.shift(1)
    tr = np.maximum.reduce([df.high - df.low, (df.high - pc).abs(), (df.low - pc).abs()])
    assert np.isclose(out.atr.iloc[50], tr[37:51].mean())
    assert out.atr.iloc[:13].isna().all() and not np.isnan(out.atr.iloc[13])


def test_volume_zscore():
    df = random_walk_bars(120, seed=2)
    out = add_indicators(df)
    w = df.volume.iloc[61:111]
    assert np.isclose(out.vol_z.iloc[110], (df.volume.iloc[110] - w.mean()) / w.std())


def test_vol_rank_needs_300_bars_and_is_a_percentile():
    df = random_walk_bars(1300, seed=4)
    out = add_indicators(df)
    assert out.vol_rank.iloc[:300].isna().all()
    first_valid = out.vol_rank.first_valid_index()
    assert first_valid == 13 + 299
    natr = (out.atr / out.close).to_numpy()
    i = 1250
    w = natr[i - 999:i + 1]
    assert np.isclose(out.vol_rank.iloc[i], (w <= natr[i]).mean())
    assert out.vol_rank.dropna().between(0, 1).all()


def test_btc_trend_uses_yesterday():
    days = T0 + np.arange(260) * DAY_MS
    close = np.r_[np.full(230, 100.0), np.full(30, 200.0)]
    daily = pd.DataFrame({"day": days, "close": close})
    tb = btc_trend_by_day(daily)
    # day 230 is the first close above the SMA; it only counts from day 231 onwards
    assert btc_trend_at(tb, int(days[230]) + 4 * 3600_000) == -1
    assert btc_trend_at(tb, int(days[231])) == 1
    assert btc_trend_at(tb, int(days[100])) == 0  # < 200 days of history
