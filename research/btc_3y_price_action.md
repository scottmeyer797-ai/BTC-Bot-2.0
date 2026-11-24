# BTC price action, Nov 2023 – Nov 2026: statistics for finding an edge

**Goal:** an entry rule with a win rate of at least 30% and positive expectancy after costs.

**Data:** Binance USDT-margined BTCUSDT perpetual, 1h candles (28,320 bars, no gaps), resampled to 4h and daily (UTC).
BloFin demo history only starts in Aug 2024, so it can't cover 3 years. Where they overlap, Binance and BloFin prices
agree closely: average close difference 0.018%, bar-range correlation 0.999. **Volume does not agree** (see section 5).

**Method for every entry rule:**
- Entry at the close of the 4h signal bar.
- Fixed stop, and targets of 1, 1.5, 2, 2.5, 3, 4 and 5R. Exits are simulated on the **1h path**; if one 1h bar touches both
  stop and target, the stop counts first (conservative). Trades not stopped or at target close at market after 60 × 4h
  bars (10 days).
- Costs: 0.14% round trip (2 × 0.05% taker fee + 2 × 0.02% slippage), converted into R for each trade.
- At most one new trade per side every 6 bars.
- Every result is also split into **IS** (in-sample, the first 2 years) and **OOS** (out-of-sample, the last 12 months).

Script: `research/btc_edge_stats.py`.

**Breakeven win rate at each target, before costs:** 1R → 50%, 1.5R → 40%, 2R → 33%, 2.5R → 29%, 3R → 25%, 4R → 20%,
5R → 17%. Costs add roughly 0.05–0.15R per trade, so the real breakeven is a few points higher.

---

## 1. What kind of market this was

| Year | Return | Volatility (annualized) | Max drawdown | Up days | Avg daily range |
|---|---:|---:|---:|---:|---:|
| 2024 | +121% | 53% | 26% | 53% | 4.2% |
| 2025 | −6% | 42% | 32% | 50% | 3.4% |
| 2026 (to Nov 23) | −30% | 45% | 40% | 49% | 3.4% |

- BTC closed above its 200-day average on 52% of days: one bull year followed by about two years of chop and decline.
- **Close to a random walk.** The variance ratio is 0.96 / 0.96 / 0.98 / 1.03 at 2 / 5 / 10 / 20 days. A value above 1 would mean
  trending and below 1 mean-reverting, so there is no strong trend or mean-reversion at these horizons.
- Correlation of each return with the previous one: daily −0.04, 4h −0.01. There's no next-bar edge in plain direction.
- **After big days** (moves larger than 2 standard deviations):
  - after a big **up** day (n=32), the next 5 days averaged **+2.0%** and were up 62% of the time;
  - after a big **down** day (n=31), the next 5 days averaged −0.7% and were up 48% of the time.

  That's mild momentum after large moves, not reversal, but the sample is small.

## 2. Time of day and day of week (UTC)

| 4h block starting at | 00 | 04 | 08 | 12 | 16 | 20 |
|---|---:|---:|---:|---:|---:|---:|
| Avg return (bp) | −1.4 | +0.3 | **+5.5** (t=2.4) | −2.9 | −1.2 | +4.1 |
| Avg range | 1.39% | **1.12%** | 1.14% | **1.90%** | 1.59% | 1.38% |

| Day | Mon | Tue | Wed | Thu | Fri | Sat | Sun |
|---|---:|---:|---:|---:|---:|---:|---:|
| Avg return (bp) | +45 (t=2.0) | −26 | +39 | −37 | +1 | −2 | +11 |
| Avg range | 4.4% | 4.1% | 4.1% | 4.0% | 4.3% | **2.1%** | 2.9% |

- **Volatility patterns are reliable:**
  - the 12:00–16:00 UTC block, when US markets open, has the widest range, 1.7× the quietest block (04:00–08:00);
  - weekends move about half as much as weekdays.

  These matter for stop placement and for which bars count as "high volume".
- **Direction patterns are not reliable.** The 08:00 block and Mondays reach t≈2, but with 13 slices tested, one or two of
  that size are expected by chance. Don't build on them without more data.

## 3. Entry rules tested (BTC, 3 years, net R per trade)

| Entry rule | Trades | Win % at 2R | Net at 2R | Win % at 3R | Net at 3R | 3R first 2 yrs (IS) | 3R last 12 months (OOS) |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Random entries** (baseline), stop 1.5 ATR | 276 | 32% | −0.12 | 26% | −0.10 | −0.05 | −0.22 |
| A. Current bot: swing-level break + volume z > 2 | 137 | 36% | −0.02 | 28% | −0.04 | +0.06 | **−0.21** |
| B. Swing-level break, no volume filter | 577 | 35% | −0.08 | 27% | −0.04 | −0.02 | −0.08 |
| C. 4h 20-bar high/low (Donchian) break, stop 1.5 ATR | 336 | 34% | −0.05 | 27% | −0.03 | +0.10 | **−0.29** |
| D. 4h 55-bar high/low (Donchian) break, stop 2 ATR | 185 | 37% | +0.04 | 31% | +0.09 | +0.10 | +0.08 |
| D, only with the 200-day trend | 93 | 39% | +0.11 | 33% | +0.20 | +0.07 | +0.51 (n=27) |
| E. Pullback in 200-day trend (4h RSI < 30 / > 70) | 61 | 38% | +0.04 | 23% | −0.22 | +0.01 | −0.57 |
| F. Fade a 4h move bigger than 2.5σ (mean reversion) | 189 | 31% | −0.22 | 23% | −0.25 | −0.31 | −0.15 |
| G. Sweep of prior-day high/low, then close back inside | 648 | 34% | −0.12 | 27% | −0.12 | −0.11 | −0.14 |
| **H. Volume spike z > 3, enter in the candle's direction, stop 1.5 ATR** | 122 | **40%** | **+0.12** | **35%** | **+0.20** | **+0.19** | **+0.22** |
| H, only with the 200-day trend | 51 | 47% | +0.32 | 37% | +0.31 | +0.34 | +0.28 |

How to read it:
- **Random entries lose about 0.1R per trade:** that's the cost of trading. A rule has to beat this baseline, not zero.
- **The current bot's rule (A) has no edge on BTC alone,** and its last 12 months are clearly negative (−0.21R at 3R).
  Longs made +0.28R and shorts −0.27R. The 5R target used in funded mode is only positive because of the first 2 years.
- **Fading moves (F) and sweep-and-reclaim (G) lose everywhere.** These are popular price-action ideas, but on BTC 4h they're
  worse than random.
- **Most rules have a median best move before the stop of about 1R.** Half of all trades never get to +1R. The win rate
  at 4R is almost the same as at 5R, because trades that run far tend to keep running. For win rate ≥ 30%, targets of 2–3R
  are the realistic range.
- **Costs matter a lot with tight stops.** With a 1% stop, the 0.14% round trip costs 0.14R per trade. Rules with stops
  around 2% or more (D, H) lose much less to costs.

## 4. The best candidate: volume-spike momentum (H)

**Rule:**
- Signal: a 4h candle closes with volume z-score > 3 (volume vs its 50-bar average and spread).
- Entry: at the close, in the direction of the candle (green → long, red → short).
- Stop: 1.5 × ATR(14) from the entry.
- Target: 3R. Close at market after 60 bars (10 days) if neither is hit.

**Results on BTC:** 122 trades in 3 years (about 0.8 per week).

| | Win % at 2R | Net at 2R | Win % at 3R | Net at 3R |
|---|---:|---:|---:|---:|
| All trades | 40% | +0.12R | 35% | +0.20R |

- Positive in each year: 2024 +0.23R, 2025 +0.14R, 2026 +0.29R per trade at 3R.
- Same result in the first 2 years (+0.19R) and the last 12 months (+0.22R).
- Longs and shorts are both positive.

**Nearby settings, BTC, net R at 3R:**

| Volume z above | Stop 1.0 ATR | Stop 1.5 ATR | Stop 2.0 ATR |
|---|---:|---:|---:|
| 2.0 | −0.05 | +0.01 | −0.05 |
| 2.5 | +0.15 | +0.04 | +0.04 |
| 3.0 | +0.18 | +0.20 | +0.08 |
| 3.5 | +0.23 | +0.38 | +0.25 |

The bigger the volume spike, the better the result: a smooth pattern rather than one lucky setting. Below z = 2.5 it
disappears, which suggests the current bot's z > 2 threshold is too low.

**Same rule on other coins, unchanged** (not used to choose the rule), net R at 3R:

| | ETH | SOL | XRP | BNB | DOGE | 5 coins pooled |
|---|---:|---:|---:|---:|---:|---:|
| Trades | 106 | 106 | 131 | 139 | 143 | 625 |
| Win % at 3R | 37% | 34% | 34% | 34% | 28% | 33% |
| Net R at 3R | +0.41 | +0.22 | +0.17 | +0.20 | −0.02 | **+0.18** (95% range +0.05 to +0.33) |

**How confident to be:**
- **For:** it's positive on 5 of 6 coins and in every year on BTC, and stronger at higher volume thresholds.
- **Against, part 1:**
  - On BTC alone it isn't statistically significant: there's roughly a 10% chance the positive average is luck.
  - On the other coins it was **flat in the last 12 months** (−0.02R at 3R), with all of its gain in the first two years.
- **Against, part 2:**
  - Spikes often happen on several coins at once, so the pooled trades aren't independent. The real uncertainty is wider
    than the range shown.
  - About 50 variations were tested here, which inflates the best result.
- **The 200-day trend filter looked strong on BTC (+0.31R) but didn't help on the other coins** (+0.08R). Treat it as
  overfitting, not as part of the rule.

**Verdict:** H is the best lead from this data. It's worth a forward test alongside the current bot, but it is not a proven
edge. Expect about +0.1 to +0.2R per trade at a 33–35% win rate if it holds, and about zero if it doesn't.

## 5. Volume data warning: this affects the bot now

- BloFin's 4h volume tracks Binance's only loosely: the correlation of volume z-scores is 0.68.
- **Only 39–48% of Binance volume spikes (z > 3 / z > 2) are also spikes on BloFin.**
- The current bot computes its volume filter from BloFin volume, so about half of its signals differ from what a backtest
  on Binance or aggregated data would produce.
- **Recommendation:** compute volume signals from Binance futures volume (public endpoint, no API key, reachable from
  GitHub Actions), and keep BloFin only for prices and execution. Rule H depends on this completely.

## 6. What this suggests for the strategy

1. **Raise the volume threshold.** Results improve steadily from z > 2.5 to z > 3.5. At z > 2 there's no edge on BTC.
2. **Use 2–3R targets** if you want win rates of at least 30%. Above 3R the win rate drops below 30% and gains mostly come
   from rare runners.
3. **Use stops of at least about 1.5% (≥ 1.5 ATR on 4h).** Tighter stops lose 0.15R or more per trade to costs.
4. **Drop mean-reversion and sweep-and-reclaim ideas** on 4h. They're worse than random here.
5. **On BTC, the current rule's shorts are the problem** (−0.27R at 3R). Worth checking whether this holds across all 10
   coins before changing anything.
6. **Next step:** run rule H in demo next to the current strategy, with volume from Binance, and compare after about
   40–60 trades.

## Caveats

- All results use Binance data. BloFin fills, fees and funding will differ somewhat.
- Funding payments are not included, and the costs are assumed rather than measured.
- Stop-first when a 1h bar touches both stop and target makes results slightly pessimistic.
- About 1,000 trades per entry rule would be needed to measure a +0.1R edge reliably. These samples are 50–650 trades.
