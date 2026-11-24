# Partial-exit / runner study: results

Plan, hypotheses and pass rule: `partials_study_preregistration.md`, committed in `ba23b41` **before** any simulation.
**No deviations** from the plan. Code: `research/partials_study.py`. Trades: `research/results/partials_trades.csv`.

**Checks:**
- The two reference variants (B0, BE2) reproduce the earlier exit study exactly, trade for trade.
- Adding the EMA50 runner option to the exit engine left the earlier study's results unchanged.

**Same entries as before:** the current bot's long side.

| Data set | Trades |
|---|---:|
| BTC 2020–23 (development) | 75 |
| BTC 2024–26 (holdout) | 58 |
| ADA | 117 |
| LINK | 136 |
| SOL | 93 |
| **Pooled holdout** | **404** |
| of which bull-label entries | 59 |
| BTC bull-label entries, all years | 22 |

**Comparison point:** BE2 (100% at 3R, break-even at +2R), the owner's rule.

## Verdict

**No variant passes the full pre-registered rule, but R1 misses by a hair.**

**R1** = break-even at +2R; bank 50% at 3R; the other 50% trails at (highest high − 3 ATR), held up to 60 days.
- Better than BE2 in **every one of the five test sets**: BTC development +0.09R, BTC 2024–26 +0.12R, ADA +0.09R, LINK +0.04R,
  SOL +0.23R.
- Pooled holdout: **+0.32R vs +0.21R** per trade, win rate 30%, max drawdown 15% vs 13% (at 1% risk), same 14-trade max
  losing streak.
- Paired t = **1.96** vs the required 2.0. The Bonferroni-adjusted bar (2.8) is not met.
- It's the best-supported runner design, but it's not proven.

**R4** is the "higher win rate" alternative: break-even at +2R, bank 25% at 2R and 25% at 3R, the last 50% trails at 3 ATR.
- Better than BE2 in all five sets as well, by a smaller margin: +0.09R pooled, t = 1.7.
- It keeps the **win rate at 41%** (vs 31%) and cuts the max losing streak from 14 to 10.

## Results (mean net R per trade; in brackets the paired difference vs BE2)

| Variant | BTC dev | BTC 2024–26 | ADA | LINK | SOL | **Pooled holdout** | Bull, pooled holdout | Bull, BTC all years | Win % | Streak | DD | Hold | t |
|---|---|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|
| B0 (3R, no BE) | +0.46 | +0.25 | +0.16 | +0.22 | +0.25 | +0.22 (+0.00) | +0.32 | +0.51 | 34% | 14 | 15% | 1.7 d | – |
| **BE2 (your rule)** | +0.46 | +0.29 | +0.19 | +0.19 | +0.22 | **+0.21** | +0.31 | +0.42 | 31% | 14 | 13% | 1.6 d | – |
| **R1** 50% @3R + 3 ATR runner | +0.55 (+0.09) | +0.41 (+0.12) | +0.28 (+0.09) | +0.24 (+0.04) | +0.45 (+0.23) | **+0.32 (+0.11)** | +0.76 (+0.45) | +0.21 (−0.21) | 30% | 14 | 15% | 2.4 d | **1.96** |
| R2 33% @2R, 33% @4R + runner | +0.47 (+0.01) | +0.32 (+0.03) | +0.27 (+0.08) | +0.20 (+0.01) | +0.32 (+0.10) | +0.26 (+0.05) | +0.53 (+0.22) | +0.09 (−0.33) | 41% | 10 | 15% | 2.7 d | 1.0 |
| R3 50% @2R + runner | +0.42 (−0.04) | +0.34 (+0.05) | +0.27 (+0.08) | +0.16 (−0.03) | +0.29 (+0.07) | +0.25 (+0.04) | +0.65 (+0.34) | +0.15 (−0.27) | 41% | 10 | 13% | 2.2 d | 0.6 |
| **R4** 25% @2R, 25% @3R + 50% runner | +0.50 (+0.04) | +0.38 (+0.09) | +0.29 (+0.10) | +0.22 (+0.03) | +0.40 (+0.18) | **+0.31 (+0.09)** | +0.73 (+0.43) | +0.17 (−0.25) | **41%** | **10** | 14% | 2.4 d | 1.7 |
| R5 50% @3R + 10-bar-low runner | +0.56 (+0.10) | +0.43 (+0.14) | +0.19 (+0.01) | +0.21 (+0.02) | +0.37 (+0.14) | +0.27 (+0.06) | +0.69 (+0.38) | +0.23 (−0.19) | 30% | 14 | 16% | 2.6 d | 1.2 |
| R6 50% @3R + 4.5 ATR runner | +0.61 (+0.15) | +0.43 (+0.14) | +0.18 (−0.00) | +0.17 (−0.03) | +0.39 (+0.17) | +0.26 (+0.05) | +0.68 (+0.37) | +0.16 (−0.26) | 30% | 14 | 18% | 3.0 d | 0.8 |
| R7 50% @3R + EMA50 runner | +0.78 (+0.33) | +0.37 (+0.08) | +0.18 (−0.01) | +0.16 (−0.03) | +0.53 (+0.31) | +0.28 (+0.07) | +0.87 (+0.56) | +0.44 (+0.01) | 30% | 14 | 17% | 3.3 d | 0.9 |
| R8 all runs: lock +2R at 3R, 3 ATR trail | +0.68 (+0.22) | +0.48 (+0.19) | +0.17 (−0.02) | +0.35 (+0.16) | +0.48 (+0.26) | +0.35 (+0.14) | +0.40 (+0.09) | +0.13 (−0.29) | 30% | 14 | 16% | 2.1 d | 1.9 |
| R9 runner (R1) only if bull label | +0.41 (−0.05) | +0.28 (−0.01) | +0.27 (+0.09) | +0.23 (+0.04) | +0.35 (+0.12) | +0.28 (+0.07) | = R1 | = R1 | 31% | 14 | 13% | 1.7 d | 1.6 |
| R10 runner (R6) only if bull label | +0.39 (−0.07) | +0.28 (−0.01) | +0.23 (+0.04) | +0.25 (+0.06) | +0.32 (+0.10) | +0.27 (+0.05) | = R6 | = R6 | 31% | 14 | 13% | 1.8 d | 1.3 |

**Where the runner profit comes from** (pooled holdout):

| | BE2 | R1 | R4 | R7 | R8 |
|---|---:|---:|---:|---:|---:|
| Share of total R from the best 5% of trades | 70% | 103% | 104% | 139% | 118% |
| Mean R per trade **without** the best 5% | +0.07 | −0.01 | −0.01 | −0.12 | −0.07 |
| Mean R on trades whose best move reached +5R (95 trades) | +2.56 | +3.33 | +3.16 | +3.26 | +3.47 |
| Largest single trade | – | +16.1R | +15.8R | +26.9R | +14.2R |

## Hypotheses: what held up

| # | Prediction | Result |
|---|---|---|
| H1 | Runners add +0.03 to +0.10R over all trades, and +0.10 to +0.30R on bull-label trades | **Mostly.** Over all trades +0.05 to +0.14R ✓ (R1 and R8 slightly above the range). Bull-label trades on the alts: +0.22 to +0.56R, bigger than predicted. **On BTC's own bull-label trades (22) runners did worse** (−0.19 to −0.33R), except R7 (+0.01) ✗. |
| H2 | A first partial at 2R gives the highest win rate (≥ 40%) but less than R1; R1 is the best half-and-half | **Confirmed.** R2, R3 and R4 all have a 41% win rate and earn less than R1. R1 beats R3, R5, R6 and R7. |
| H3 | The wider 4.5 ATR runner (R6) beats the 3 ATR runner in bull labels, but not overall | **Wrong.** R6 is behind R1 in bull labels too (+0.37 vs +0.45R). The 3 ATR trail is better everywhere. |
| H4 | The EMA50 runner holds longest, does best in bull labels, has the deepest drawdown; the 10-bar trail is in between | **Partly.** R7 holds longest (3.3 days) ✓ and is best on bull trades (+0.56R; the only runner not hurt on BTC bull trades) ✓. Its drawdown (17%) is not the deepest (R6 18%) ✗. R5 is not between R1 and R7 ✗. |
| H5 | R8 (whole position runs) has the highest mean R of the runners, the most variance, and about BE2's win rate | **Mostly.** Highest mean (+0.35R) ✓ and same win rate (30%) ✓. R7 has more variance ✗. |
| H6 | Using runners only in bull labels (R9, R10) beats BE2 a little overall, by less than R1 / R6 do | **Holdout confirmed** (+0.07 / +0.05R). On BTC development they were **worse** than BE2, because BTC bull-label runners lost. |
| Overall | At most 1–2 pass; the gains come from the few biggest trades; without the top 5%, runners ≈ BE2 | **None passes (R1 misses on t by 0.04).** The gains come entirely from the best 5% of trades: without them, runners are slightly **worse** than BE2. |

## The BTC bull-market surprise

BTC trades entered **while the live label already said bull** reached +5R less often (23%) than BTC trades entered
under other labels (30%). This matches the regime study: BTC's biggest moves start **before** the regime label switches to
bull. By the time the label confirms it, many moves are mature, and a runner gives profit back in the pullback.

The alts showed the opposite in this sample (their own bull labels, 50 trades), but the samples are small on both sides:

| | Bull-label trades | Reached +5R |
|---|---:|---:|
| BTC | 22 | 23% |
| ADA | 18 | 33% |
| LINK | 20 | 20% |
| SOL | 12 | 25% |

**Practical consequence:** to catch BTC's biggest moves, **run the runner on every trade, not only when the label says
bull.** Gating it on the bull label (R9, R10) cut BTC's gains.

## Recommendation

- **If you want to capture the big moves:** use **R1**.
  - Rule: break-even at +2R, 50% off at 3R, the rest trails at highest high − 3 ATR, for up to 60 days.
  - Results: better in every test set, about +0.11R per trade (+50% on top of BE2), at the same 30% win rate and a
    slightly deeper drawdown (15% vs 13%).
- **If you prefer a smoother ride:** use **R4**.
  - Rule: break-even at +2R, 25% off at 2R, 25% at 3R, the rest trails.
  - Results: +0.09R per trade, a 41% win rate, and max losing streaks of 10 instead of 14.
- **Either way:**
  - Expect the extra profit to come from a handful of big trades a year (5% of trades carry all of it).
  - Between those, a runner version looks slightly worse than BE2.
  - Neither is proven at the pre-registered significance level. The honest next step is a declared demo forward test of R1
    (or R4) next to BE2.

## Caveats

- Bull-label samples are small (22 BTC trades, 59 pooled holdout).
- Signals are evaluated independently (overlaps allowed) for an exact paired comparison. In live trading, a runner held
  for weeks blocks new entries on that coin, so the live gain would be somewhat smaller.
- Binance prices, funding and volume were used. BloFin fills differ slightly.
