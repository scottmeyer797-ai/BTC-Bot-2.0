# Backtest of the regime top-5 strategies: BTC (in-sample) and ADA (out-of-sample)

**Period:** Apr 2020 – Nov 2026. Binance USDT-margined perpetuals, 1h candles resampled to 4h and daily.

**Tested:** every strategy from both top-5 lists in `regime_strategy_report.md`, the live list and the hindsight list. Each
was run in two ways:
- **always on**;
- **regime-gated**: new trades only while the live regime label (known at the time) matches the regime the strategy was
  picked for.

That's 46 distinct variants. Script: `research/backtest_portfolio.py`; ranking: `research/rank_backtests.py`.

## Bias controls

| Bias | How it's handled | Check |
|---|---|---|
| Look-ahead in indicators, signals, stops, targets or regime labels | Everything is recomputed on data cut off at 25 random points and compared with the full-history value at that point | **3,125 checks, 0 mismatches** |
| Hindsight regime | Gates use only the live label from yesterday's close. The hindsight label is never used to trade | by construction |
| Unrealistic fills | Signal at the 4h close, **fill at the next 1h open**. A stop that gaps is filled at the (worse) open. Stop first if one 1h bar hits stop and target. Signal and time exits fill at the next open | by construction |
| Costs | 0.06% taker fee + 0.02% slippage per side (0.16% round trip); grids pay 0.02% maker per fill | |
| Funding | **Real Binance 8h funding** for the holding period, scaled by notional. The last 3 weeks of Nov 2026 use the previous 30 days' average | costs −0.03 to −0.14R per trade on trend-following longs (longs usually pay); about −0.03R on the current bot's longs |
| Sizing and drawdown | 1% of current equity at risk per trade, one position per strategy, equity marked to market on every 4h close (grids: worst point inside each cycle) | |
| Simulator bugs | The grid simulator didn't fill levels crossed in the same bar as the stop. It's fixed, and the earlier regime report is corrected | grid results fell to about breakeven |
| Data snooping / selection | No parameter was changed. The strategies were **chosen on BTC 2020–26**, so BTC numbers are in-sample by construction. ADA was never looked at before this test | the ADA column is the honest verdict |
| Luck | Each strategy is compared with 20 runs of random entries using **the same exits**, frequency and long/short mix | edge p-value |
| Survivorship | ADA has been top-20 throughout, but is ~85% below its 2021 high, so it isn't a coin chosen for doing well | |

**Out-of-sample verdict on ADA** (only for strategies that qualify on BTC: win rate ≥ 30% and mean R > 0):
- **PASS:** mean R > 0, win rate ≥ 30%, Sharpe > 0, and an entry edge (beats ≥ 90% of random twins; grids: t ≥ 2).
- **WEAK:** profitable on ADA but without a significant edge (or win rate < 30%).
- **FAIL:** loses on ADA.

## Ranking (by Sharpe on BTC; Sharpe from daily equity, annualized)

| # | Strategy | Mode | BTC trades | BTC win | BTC R / trade | BTC Sharpe | BTC CAGR | BTC max DD | ADA win | ADA R / trade | ADA Sharpe | ADA edge p | ADA verdict |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 1 | Volume spike z>3, follow candle, 3R (both) | range only | 148 | 43% | +0.44 | 1.16 | +10.0% | 8.1% | 32% | +0.10 | 0.30 | 0.20 | WEAK |
| 2 | Volume spike z>3, follow candle, 3R (both) | always | 234 | 39% | +0.31 | 1.04 | +11.1% | 9.2% | 29% | +0.01 | 0.07 | 0.20 | WEAK |
| 3 | Donchian-20 breakout + 10-bar trail (long) | range only | 174 | 33% | +0.49 | 0.99 | +12.3% | 13.7% | 28% | −0.03 | −0.06 | 0.55 | **FAIL** |
| 4 | 20-day channel breakout + 60-bar trail (both) | range only | 75 | 37% | +0.86 | 0.93 | +9.4% | 18.3% | 23% | +0.59 | 0.63 | 0.30 | WEAK |
| 5 | **Current bot (swing level + volume), 3R (long)** | **range only** | 98 | 44% | +0.46 | 0.90 | +6.8% | 8.2% | 36% | **+0.30** | **0.55** | **0.00** | **PASS** |
| 6 | Chandelier trend (long) | always | 219 | 39% | +0.20 | 0.89 | +6.6% | 10.8% | 29% | −0.01 | −0.02 | 0.35 | **FAIL** |
| 7 | Donchian-55 turtle (long) | always | 119 | 34% | +0.60 | 0.86 | +10.2% | 12.9% | 28% | +0.42 | 0.60 | 0.10 | WEAK |
| 8 | 20-day channel breakout + 60-bar trail (both) | always | 96 | 34% | +0.67 | 0.84 | +9.4% | 18.2% | 27% | **+0.84** | **0.90** | 0.10 | WEAK |
| 9 | **Current bot, 3R (long)** | **always** | 130 | 40% | +0.35 | 0.82 | +6.8% | 8.7% | 31% | +0.11 | 0.27 | **0.00** | **PASS** |
| 10 | Donchian-20 breakout + 10-bar trail (long) | always | 254 | 33% | +0.31 | 0.81 | +10.9% | 15.7% | 30% | +0.15 | 0.44 | 0.10 | WEAK |
| 11 | Volume spike z>3, 3R (short) | range only | 83 | 40% | +0.34 | 0.72 | +4.2% | 7.9% | 30% | +0.01 | 0.03 | 0.60 | WEAK |
| 12 | RSI(14) < 30 dip buy (long) | bull only | 20 | 65% | +0.46 | 0.71 | +1.4% | 2.8% | 42% | −0.00 | −0.00 | 0.41 | **FAIL** |
| 13 | Volume spike z>3, 3R (short) | always | 134 | 36% | +0.23 | 0.60 | +4.4% | 10.2% | 29% | −0.01 | −0.02 | 0.70 | **FAIL** |
| 14 | Failed 20-bar breakout, 2R (both) | bear only | 27 | 56% | +0.36 | 0.58 | +1.4% | 4.6% | 30% | −0.34 | −0.69 | 1.00 | **FAIL** |
| 15 | Grid 0.5 ATR (short) | bear only | 128 | 51% | +0.09 | 0.53 | +1.7% | 5.4% | 51% | +0.03 | 0.27 | (t < 2) | WEAK |
| 16 | **Current bot, 3R (long)** | **bull only** | 22 | 41% | +0.52 | 0.52 | +1.7% | 3.5% | 37% | +0.38 | 0.33 | 0.10 | PASS (19 trades) |
| 17 | Donchian-55 turtle (long) | bull only | 39 | 31% | +0.48 | 0.41 | +2.6% | 14.4% | 28% | +0.24 | 0.23 | 0.60 | WEAK |
| 18 | 3-bar pullback in trend, 2R (short) | range only | 85 | 44% | +0.13 | 0.33 | +1.5% | 8.2% | 36% | +0.00 | 0.00 | 0.75 | WEAK |
| 19 | RSI(14) > 70 fade (short) | bear only | 11 | 55% | +0.24 | 0.29 | +0.4% | 3.2% | 26% | −0.31 | −0.41 | 0.90 | **FAIL** |
| 20 | Chandelier trend (long) | bull only | 67 | 37% | +0.11 | 0.27 | +1.0% | 8.0% | 32% | −0.04 | −0.12 | 0.75 | **FAIL** |
| 21 | Grid 0.5 ATR (both) | always | 802 | 39% | +0.02 | 0.24 | +1.7% | 27.9% | 43% | +0.06 | 0.71 | (t ≥ 2) | WEAK (BTC too weak) |
| 22 | Donchian-20 breakout + trail (long) | bull only | 68 | 32% | +0.12 | 0.19 | +1.1% | 12.3% | 35% | +0.55 | 0.62 | 0.00 | PASS |
| 23 | 3-bar pullback in trend, 2R (short) | always | 114 | 40% | +0.06 | 0.17 | +0.8% | 9.3% | 37% | +0.05 | 0.17 | 0.55 | WEAK |
| 24 | Grid 0.5 ATR (short) | always | 802 | 46% | +0.01 | 0.16 | +0.9% | 20.4% | 47% | +0.02 | 0.30 | (t < 2) | WEAK |
| 25 | Current bot, 3R (short) | always | 160 | 32% | +0.07 | 0.16 | +1.4% | 24.7% | 29% | +0.05 | 0.14 | 0.40 | WEAK |
| 26 | Grid 0.5 ATR (both) | range only | 561 | 40% | +0.01 | 0.14 | +0.6% | 23.1% | 44% | +0.08 | 0.77 | (t ≥ 2) | PASS on ADA only |
| 27 | Current bot, 3R (short) | bull only | 24 | 33% | +0.13 | 0.13 | +0.4% | 5.6% | 36% | +0.37 | 0.30 | 0.10 | PASS (14 trades) |
| 28 | EMA20 pullback (long) | range only | 160 | 39% | +0.04 | 0.13 | +0.7% | 15.1% | 38% | +0.04 | 0.13 | 0.00 | PASS (tiny edge) |
| 29 | Donchian-20 breakdown + trail (short) | bear only | 32 | 34% | +0.07 | 0.09 | +0.3% | 7.2% | 48% | +0.40 | 0.65 | 0.05 | PASS |
| 30 | Prior-day high sweep & reclaim, 2R (short) | bear only | 89 | 40% | +0.03 | 0.09 | +0.3% | 10.1% | 39% | +0.00 | 0.01 | 0.55 | WEAK |
| 31 | EMA20 pullback (long) | always | 245 | 39% | +0.02 | 0.07 | +0.2% | 20.6% | 37% | −0.01 | −0.04 | 0.00 | FAIL |
| 32 | Stretch fade > 2.5 ATR (short) | bear only | 18 | 33% | +0.04 | 0.05 | +0.1% | 5.6% | 30% | −0.12 | −0.19 | 0.70 | FAIL |

**Not ranked because the BTC win rate is below 30%**, though robust on both coins:
- EMA 20/50 cross (long): BTC +0.84R, 24% win, Sharpe 0.96. ADA +0.64R, 20% win, edge p = 0.00.
- EMA 20/50 cross (both): BTC +0.41R. ADA +0.36R.

**Rank agreement BTC vs ADA:** Spearman +0.33 across the 46 variants. Some general signal, plenty of BTC-specific noise.

## What survives

**Robust on both coins with a real entry edge:**
1. **The current bot's long side, range-gated or always on.**
   - Range-gated: BTC +0.46R per trade (44% win, Sharpe 0.90, max DD 8%); ADA +0.30R (36% win, Sharpe 0.55).
   - The ADA edge is significant: it beat all 20 random twins (p = 0.00).
   - This is the single most robust strategy in the study.

**Positive on both coins, but without a significant edge or with low win rates** (trend-following long, mostly carried
by a few big trends):

2. 20-day channel breakout with a 60-bar trail, always on: BTC +0.67R, ADA +0.84R. Win rates 27–34%.
3. Donchian-55 turtle, long: BTC +0.60R, ADA +0.42R. Win rate ~28–34%.
4. Donchian-20 breakout, long, always on: BTC +0.31R, ADA +0.15R.
5. EMA 20/50 cross, long: BTC +0.84R, ADA +0.64R, but with only 20–24% winners, so it misses your 30% bar.

**Overfit to BTC (great on BTC, nothing on ADA):**
- **Volume spike z>3:** #1 and #2 on BTC, about zero on ADA (+0.01 to +0.10R, no edge). With next-bar fills, funding and
  BloFin-level fees it doesn't carry over. The earlier multi-coin check used softer assumptions.
- **Donchian-20 long, range-gated:** #3 on BTC, loses on ADA.
- **Chandelier trend, long:** loses on ADA.
- **Every short and bear-market strategy except one:** failed-breakout fades, RSI > 70 fades, stretched-rally fades and
  prior-day sweeps fail or are flat on ADA. Donchian-20 breakdown (bear-gated) passes on ADA but is barely positive on BTC
  (+0.07R), so it isn't consistent either.

**Grids:** after the simulator fix, about breakeven on BTC in every mode. A 0.5 ATR grid passes on ADA (+0.06 to
+0.08R per cycle), but with a 23–28% drawdown on BTC. It's not robust across the two coins.

## What this means for regime bots

| Regime | Robust choice | Evidence |
|---|---|---|
| **Bull** | Long trend following: current bot longs; 20-day channel breakout; Donchian-55 long | positive on both coins; current bot longs significant on both |
| **Range / consolidation** | **Current bot longs, range-gated** (best Sharpe on both coins); no grid | significant on both coins |
| **Bear** | **Nothing robust.** Best option on this evidence: stay flat, or run long-only systems that simply stop getting signals | every bear short failed or was inconsistent on ADA |

**Implications for the running forward test:**
- The current bot's **long** side is the most robust thing found.
- Its **short** side made +0.07R on BTC and +0.05R on ADA, about zero after costs, with a 20–25% drawdown.
- Running the bot long-only, or long-only outside bear labels, is worth considering. That would change your original
  spec, so it's your call: I haven't changed the bot.

## Caveats

- **Two coins and one period.** ADA is strongly correlated with BTC, so it's a fair but not independent test. A third coin
  (e.g. LINK or AVAX) would strengthen any PASS.
- **Small regime-gated samples.** Bull- and bear-gated variants have 11–68 trades, too few for firm conclusions.
- **Win rate vs your 30% bar:** the most robust trend strategies win only 20–35% of the time and rely on a few large
  winners. Expect long losing streaks: 7–13 losses in a row on BTC, and up to 21–24 for the EMA 20/50 cross on ADA.
- **Venue:** Binance prices and funding were used. BloFin fills and funding will differ slightly, and BloFin's volume
  differs a lot, which matters for the volume filter of the current bot.

---

## Extra out-of-sample check: LINK and SOL

The same 46 variants were run on **LINK** (Jan 2020 – Nov 2026) and **SOL** (Sept 2020 – Nov 2026, from its listing), with
the same code, settings and costs, and real funding for each coin. LINK had never been looked at before. SOL had been seen
once, in the first report's cross-check of the volume-spike rule only.

**Classes over the 3 out-of-sample coins (ADA, LINK, SOL):**
- **ROBUST:** profitable (mean R > 0 and Sharpe > 0) on all 3, and PASS on at least 2.
- **PROMISING:** profitable on all 3, fewer than 2 PASS.
- **MIXED:** profitable on 1 or 2.
- **OVERFIT:** profitable on none.

Script: `research/rank_multi.py`; numbers in `research/results/ranking_multi.json`.

### ROBUST

| Strategy | Mode | BTC R / win | ADA R / win (p) | LINK R / win (p) | SOL R / win (p) | Pooled out-of-sample R |
|---|---|---|---|---|---|---:|
| **Current bot, long** | **range only** | +0.46 / 44% | +0.30 / 36% (0.00) PASS | +0.11 / 30% (0.05) PASS | +0.32 / 35% (0.00) PASS | +0.23 |
| **Current bot, long** | **always on** | +0.35 / 40% | +0.11 / 31% (0.00) PASS | +0.21 / 33% (0.05) PASS | +0.25 / 33% (0.00) PASS | +0.19 |
| Current bot, long | bull only | +0.52 / 41% | +0.38 / 37% (0.10) PASS | +0.27 / 35% (0.10) PASS | +0.27 / 33% (0.20) WEAK | +0.31 |
| Donchian-20 breakout + trail, long | bull only | +0.12 / 32% | +0.55 / 35% (0.00) PASS | +0.28 / 40% (0.10) PASS | +0.14 / 31% (0.30) WEAK | +0.31 |
| Grid 0.5 ATR, both | range only | +0.01 / 40% | +0.08 / 44% PASS | +0.13 / 46% PASS | +0.07 / 41% WEAK | +0.10 |

How unlikely is this by luck? For a strategy with no edge, PASS on all 3 coins (each p ≤ 0.10) has roughly a 1-in-1,000
chance, and PASS on 2 of 3 roughly 3%. Among ~32 variants, about one "2 of 3" result is expected by luck alone, but a
"3 of 3" isn't. **The current bot's long side (range-gated or always on) is the one result that is very unlikely to be
luck.** The grid works on the alts but not on BTC itself (+0.01R), so treat it as an alt-only idea. Its funding cost is
not modelled.

### PROMISING (profitable everywhere, edge not proven or win rate < 30%)

| Strategy | Mode | BTC R / win | ADA | LINK | SOL |
|---|---|---|---|---|---|
| EMA 20/50 cross, long | always on | +0.84 / 24% | +0.64 / 20% | +0.46 / 21% | +0.88 / 29% |
| EMA 20/50 cross, both | always on | +0.41 / 25% | +0.36 / 26% | +0.26 / 23% | +0.49 / 28% |
| Donchian-55 turtle, long | always on | +0.60 / 34% | +0.42 / 28% | +0.11 / 25% | +0.68 / 35% |
| Donchian-55 turtle, long | bull only | +0.48 / 31% | +0.24 / 28% | +0.34 / 28% | +1.46 / 45% |
| Donchian-20 breakout + trail, long | always on | +0.31 / 33% | +0.15 / 30% | +0.01 / 31% | +0.19 / 34% |
| 3-bar pullback in trend, short | range only | +0.13 / 44% | +0.00 / 36% | +0.17 / 43% | +0.20 / 42% |

Long trend following makes money on every coin, but with 20–35% win rates and long losing streaks. The EMA 20/50 cross
has the biggest pooled gain (+0.65R per trade) but fails your 30% win-rate bar everywhere.

### MIXED or worse

- **Volume spike z>3 (every variant):** passes on SOL, weak on ADA, **loses on LINK**. SOL's ranking tracks BTC's closely
  (rank correlation +0.73), which flatters it. Coin-dependent, not a general edge.
- **20-day channel breakout:** big on BTC, ADA and SOL, **loses on LINK**.
- **Current bot, short side:** about zero everywhere (pooled +0.05R), with large drawdowns.
- **All bear-market strategies** (failed-breakout fade, RSI > 70 fade, stretch fade, prior-day sweep, short grid,
  Donchian-20 breakdown): none is profitable on all 3 coins. Pooled out-of-sample R ranges from −0.14 to +0.15.

**Rank agreement of mean R across the 46 variants:**

| | ADA | LINK | SOL |
|---|---:|---:|---:|
| BTC | +0.33 | +0.37 | +0.73 |
| ADA | | +0.22 | +0.41 |
| LINK | | | +0.31 |

### Updated bottom line

| Regime | What survives 4 coins | Confidence |
|---|---|---|
| **Bull** | Current bot longs; Donchian-20 long (bull-gated); long trend following (EMA 20/50, Donchian-55), but expect a low win rate | high for current bot longs, medium for the rest |
| **Range / consolidation** | **Current bot longs, range-gated**: PASS on all 3 out-of-sample coins. On alts only: a 0.5 ATR neutral grid | high / low |
| **Bear** | **Nothing.** Stay flat or let long-only systems go quiet | none of the shorts survived |

**For the running bot:** this strengthens the case for going **long-only**:
- the long side passes on 3 of 3 unseen coins;
- the short side earns about zero after costs.

**One caveat that matters for the live bot:** these backtests use Binance volume for the z > 2 filter, while the live bot
uses BloFin volume, which only partly matches. Switching the volume source to Binance would make the live bot match what
was tested.
