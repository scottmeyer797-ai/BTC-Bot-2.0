# Which strategy types work in which BTC regime? (Jan 2020 – Nov 2026)

> **Correction (grid results).** The first version of this report ranked grids near the top in range and bear markets.
> That came from a bug in the grid simulator: when one 1h bar fell through several grid levels and then the stop, the levels
> crossed on the way down were never filled, so stop-out losses were understated. With the bug fixed, **no grid variant shows
> an edge in any regime** (best: +0.02R per cycle in range, t = 0.5). The tables below are corrected. All non-grid results
> were unaffected.

**Question:** for a set of regime-specific bots (bull / consolidation / bear), what are the 5 best strategy types for each
regime, with a win rate of at least 30% and positive expectancy?

**Short answer:**
1. **The style matches the regime, but only in hindsight.** If you know in advance what the market will do over the next
   30 days:
   - long trend-following wins in bull months;
   - volume-spike entries, the current bot's longs and pullbacks win in sideways months (grids don't);
   - short momentum and shorting stretched rallies win in bear months.

   That supports your idea.
2. **A live regime label can't tell you the next month in advance.** The 30-day label used here (and others like it, in our
   experience) says "bull" when the next 30 days really are a clean bull move only 22% of the time, against a 21% base rate.
   For bear it's 13% against 13%. By the time a trend is confirmed, much of it has already happened.
3. **So the top 5 depends on whether the regime is known in advance or detected live.** Both lists are below. The live
   list is what a regime-switching bot would really get.

## Data and method

- **Data:** Binance BTCUSDT perpetual, 1h candles, Jan 2020 – Nov 2026 (60,456 bars, no gaps), resampled to 4h and daily
  (UTC). Regimes are labelled from Apr 2020, after a 100-day warm-up.
- **Strategy types:** 24 rule types plus a grid at 3 spacings, each run long+short, long only and short only. That's 81
  variants: trend following, breakouts, pullbacks, mean reversion, fades and grids (list at the end).
- **Trades:**
  - One open position at a time per variant.
  - Entry at the 4h close. Stops and targets are checked on the 1h path, with the stop counted first if a bar touches both.
    Exit signals and trailing stops update at 4h closes.
  - Results are in **R** (P&L ÷ initial risk) after costs: 0.14% round trip for market orders, 0.04% for grid limit orders.
- **Grids:**
  - 5 buy levels below and 5 sell levels above the price when set up, spaced 0.5 / 1 / 1.5 × ATR(4h). Each level takes
    profit one step away and re-arms.
  - Hard stop one step beyond the outer level; re-centred every 7 days or after a stop.
  - Each grid cycle counts as one trade, with 1R = the loss if one side fills completely and is stopped.
- **Two regime views** (each trade gets the regime of its entry day):
  - **Live** (what a bot can know at the time), from data up to yesterday's close:
    - **bull** = price above its 100-day average, the average rising over 20 days, and a 30-day efficiency ratio ≥ 0.2
      (clean, directional movement rather than chop);
    - **bear** = the mirror image;
    - **range** = everything else.
  - **Hindsight** (what the market actually did): the next 30 days returned ≥ +10% with efficiency ≥ 0.25 = bull,
    ≤ −10% = bear, anything else = range.
- **Requirements to make a top 5** (in that regime):
  - at least 20 trades, win rate ≥ 30%, and average net R > 0;
  - positive in both 2020–22 and 2023–26 (where each has at least 5 trades);
  - **an entry edge**: it beats at least 18 of 20 runs of random entries at the same frequency and long/short mix,
    with **the same exits** (p ≤ 0.10). Grids have no entry signal to randomise, so they need t ≥ 2 instead.
  - Only one direction per strategy, so the 5 are different strategies.

**Why the exit-matched random baseline matters:** random entries with a trailing-stop exit made about +0.15 to +0.38R per
trade in this period. BTC went from 7k to 60k+, and trailing exits capture that drift and the big moves. Many trend
systems look profitable mainly because of their exit, not their entry. Every edge below is measured **against its own
random twin**, not against zero.

## Regimes over time

| | Bull | Range | Bear |
|---|---:|---:|---:|
| Share of days (live label) | 22% | 64% | 13% |
| Months | 17.7 | 50.8 | 10.3 |
| Average length of a spell | 7 days | 13 days | 8 days |
| BTC return over the next 30 days, average | +9.1% | +3.7% | −1.4% |
| Buy and hold, annualized, while in this regime | +117% | +30% | −30% |

**How well the live label predicts the next 30 days:**

| Live label says… | Actually bull | Actually range | Actually bear |
|---|---:|---:|---:|
| bull | 22% | 73% | 5% |
| range | 24% | 61% | 15% |
| bear | 7% | 80% | 13% |
| *base rate* | *21%* | *66%* | *13%* |

The live label mostly tells you which trend **won't** happen next. For example, after a "bull" label a bear month is
unlikely (5% vs 13%). It does not tell you the current trend will continue. Labels also flip every 1–2 weeks, so a
switching bot would need some delay or hysteresis before switching, which makes it later still.

---

## Top 5 per regime: LIVE labels (what regime-switching bots would get)

### Bull label

| # | Strategy | Dir | Trades | Win % | Net R / trade | Edge vs random twin | 2020–22 / 2023–26 |
|---|---|---|---:|---:|---:|---:|---|
| 1 | RSI(14) dip below 30, exit at Bollinger mid-band (buy the dip) | long | 20 | 65% | +0.56 | +0.50 | +0.56 / +0.56 |
| 2 | Swing-level break + volume z>2, 3R (the current bot) | short | 24 | 42% | +0.28 | +0.49 | +1.33 / +0.01 |
| 3 | Volume spike z>3, follow the candle, 3R | both | 61 | 34% | +0.17 | +0.23 | +0.25 / +0.11 |
| — | *nothing else qualifies (the 1.5 ATR grid did before the correction)* | | | | | | |

Only 3 qualify, and the samples are small. Trend following entered **after** a "bull" label underperforms: the move is
usually mature. In a confirmed bull, buying dips does better than chasing breakouts.

### Range label (no confirmed trend)

| # | Strategy | Dir | Trades | Win % | Net R / trade | Edge vs random twin | 2020–22 / 2023–26 |
|---|---|---|---:|---:|---:|---:|---|
| 1 | Volume spike z>3, follow the candle, 3R | both | 145 | 43% | +0.46 | +0.49 (p = 0.00) | +0.37 / +0.53 |
| 2 | Swing-level break + volume z>2, 3R (the current bot) | long | 99 | 43% | +0.49 | +0.46 (p = 0.00) | +0.32 / +0.57 |
| 3 | Donchian-20 breakout, trail on 10-bar channel | long | 164 | 35% | +0.60 | +0.41 (p = 0.00) | +0.43 / +0.70 |
| 4 | 20-day channel breakout, trail on 60-bar channel | both | 75 | 37% | +0.96 | +0.57 (p = 0.10) | +1.28 / +0.81 |
| 5 | EMA 50/200 cross, exit on cross back | long | 32 | 44% | +5.89 | +5.74 (p = 0.10) | +10.33 / +3.22 |

EMA 50/200 is carried by a few huge trends (32 trades in 6.5 years).

**This is where breakouts earn their money:** new trends start while the label still says "range". The corrected grid
makes about +0.02R per weekly cycle here: no edge. Of everything in this study, the volume-spike rule is the strongest
statistically (t ≈ 3).

### Bear label

| # | Strategy | Dir | Trades | Win % | Net R / trade | Edge vs random twin | 2020–22 / 2023–26 |
|---|---|---|---:|---:|---:|---:|---|
| 1 | Failed breakout: 20-bar break, then 2 closes back inside, 2R | both | 24 | 58% | +0.42 | +0.53 (p = 0.00) | +0.35 / +0.50 |
| 2 | Donchian-20 breakdown, trail on 10-bar channel | short | 25 | 36% | +0.25 | +0.30 (p = 0.00) | +0.15 / +0.34 |
| — | *nothing else qualifies; runner-up, Supertrend flip short (+0.22R), misses the p ≤ 0.10 test (p = 0.16)* | | | | | | |

There are only about 10 months of bear labels in 7 years, so every bear result rests on 25–100 trades. It is the
weakest evidence in the study.

---

## Top 5 per regime: HINDSIGHT (if you knew what the next 30 days would be)

These answer "which style suits which kind of market". They can't be traded as shown, because the label uses the future.

| # | Bull months | Range months | Bear months |
|---|---|---|---|
| 1 | EMA 20/50 cross, long: +5.8R, 44% win | Volume spike z>3, short: +0.32R, 40% | 30-day momentum, short: +1.9R, 43% |
| 2 | Donchian-55 turtle, long: +4.1R, 65% | Current bot, long: +0.36R, 39% | Stretch fade (> 2.5 ATR above EMA20), short: +0.53R, 53% |
| 3 | Donchian-20 + trail, long: +2.5R, 54% | 3-bar pullback in trend, short: +0.10R, 43% | EMA 20/50 cross, both: +0.71R, 32% |
| 4 | Current bot, long: +1.5R, 70% | EMA20 pullback, long: +0.11R, 41% | RSI(14) above 70 fade, short: +0.48R, 67% |
| 5 | Chandelier trend, long: +1.5R, 58% | *(only 4 qualify)* | Prior-day high sweep & reclaim, short: +0.25R, 49% |

Your intuition holds **with perfect regime knowledge**:
- in bull markets, long trend following and breakouts dominate;
- in consolidation, volume-spike entries and the current bot's longs do best; grids are breakeven after the correction;
- in bear markets the winners are **shorting strength**: sell rallies that are stretched (RSI > 70, more than 2.5 ATR
  above EMA20), sell sweeps above the prior day's high, and short 30-day momentum.

## What doesn't work in any regime (live labels)

- Fading big 4h moves (−0.06 to −0.56R).
- Bollinger squeeze breakouts (−0.30 to −0.50R outside range).
- Daily opening-range breakout (−0.03 to −0.09R from 2,500 trades: the clearest "no edge" result).
- Inside-bar breakouts, and RSI(2) extremes on 4h (high win rates of 55–63%, but expectancy between −0.20R and +0.05R).
- EMA 20/50 cross entered during a confirmed trend (−0.45 to −0.54R).

---

## What this means for the regime-bot plan

1. **Separate bots per detected regime would trade late.** The two strongest bull-market tools (breakouts, trend
   following) earn their money **before** a regime detector confirms the bull. Gate them on "bull confirmed" and you cut
   off their best trades.
2. **A design that fits the evidence better:**
   - **Always-on breakout / trend bot, long-biased** (volume spike z>3; current bot longs; Donchian-20 long). This is the
     part that catches new bull trends. Let the regime label switch **off its shorts** in a bull and its longs in a bear,
     because the label is good at ruling out the opposite trend.
   - **No grid bot for now.** Corrected for the simulator bug, ATR-spaced grids at 0.5 / 1 / 1.5 ATR are breakeven in
     every regime. A grid would need a different design (wider range, no hard stop, funding-aware) and its own test first.
   - **Bear bot that shorts strength** (failed breakouts, Donchian-20 breakdowns), allowed only while the label says bear.
     It has the least evidence, so give it the smallest size.
3. **Better regime detection is the most valuable next research.** Even a modest improvement in predicting the next 30
   days matters more than any single strategy here. Candidates to test: faster labels (weekly structure, 20-day channel
   position), volatility regime (ATR percentile), funding rate and open interest.

## How much to trust this

- **84 variants × 3 regimes × 2 views were tested.** Some winners are luck. Results with t ≥ 3 are the most trustworthy:
  volume-spike in range and the hindsight bull trend strategies. Results with t < 1.5 are leads, not
  edges.
- **Bull and bear samples are small** (20–100 trades). Range results rest on 100–500 trades.
- **BTC only.** The earlier report found the volume-spike rule also works on ETH, SOL, XRP and BNB. The other rules here
  haven't been checked on other coins yet.
- **Not modelled here:** funding payments, and position sizing across bots running at the same time. Costs are assumed.
  The follow-up backtest (`research/backtest_report.md`) adds funding, next-bar fills and an out-of-sample coin.
- **R sizes aren't comparable across strategies.** Trailing-stop systems have a few very large winners (5R+), grids have
  many small ones. Compare on edge vs the random twin and on consistency, not raw R.

## Files

- `research/regime_strategies.py`: regime labels, the 24 rule types and grids, simulators.
- `research/regime_baselines.py`: random-entry twins with the same exits.
- `research/rank_regimes.py`: qualification and ranking.
- `research/results/regime_results.json` and `research/results/baselines.json`: all numbers behind these tables.

**Strategy list:**

| Family | Strategies |
|---|---|
| Trend following | Donchian-20 / Donchian-55 / 20-day channel breakouts with channel trailing stops; EMA 20/50 and 50/200 crosses; Supertrend(10,3); chandelier trend; 30-day time-series momentum |
| Breakouts | the current bot (swing level + volume); volume spike z>3; Bollinger squeeze; daily opening range; inside bar |
| Pullbacks | RSI(14) reclaim in trend; EMA20 touch; 3-bar pullback |
| Mean reversion | Bollinger fade; RSI(2) extremes; RSI(14) 30/70 fade; ADX<20 channel fade; stretch-from-EMA20 fade; fade of a >2.5σ 4h move |
| Fades | prior-day high/low sweep & reclaim; failed 20-bar breakout |
| Grids | 0.5 / 1 / 1.5 ATR spacing, 5 levels per side, weekly re-centre |
