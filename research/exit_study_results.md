# Exit study: results

Plan, hypotheses and decision rule: `exit_study_preregistration.md`, committed in `9108bb4` **before** any simulation.
**No deviations** from the plan: same 20 variants, same splits, same pass rule. Code: `research/exit_study.py`. Every trade
for every variant: `research/results/exit_trades.csv`.

**Fixed entry:** the current bot's long side, every signal evaluated on its own (6-bar cooldown).

| Data set | Trades |
|---|---:|
| BTC 2020–23 (development) | 75 |
| BTC 2024–26 (holdout) | 58 |
| ADA | 117 |
| LINK | 136 |
| SOL | 93 |
| **Pooled holdout** (everything except BTC development) | **404** |

## Verdict

**No exit variant beats the current 3R target under the pre-registered rule. Keep B0.**

The closest is **T3TR**:
- **Rule:** when +3R is reached, don't take profit. Lock the stop at +2R and trail it at (highest high − 3 ATR).
- **Results:** better than B0 on BTC development (+0.35R), BTC holdout (+0.20R) and 2 of 3 alts (LINK +0.15, SOL +0.23,
  ADA −0.02). Pooled holdout: **+0.34R vs +0.22R** per trade, 33% win rate, max drawdown 17% vs 15%.
- **Why it fails:** only on the significance bar (t = 1.7 vs the required 2.0). It's a reasonable candidate for a forward
  test next to B0, but not a proven improvement.

## Results (mean net R per trade; in brackets the paired difference vs B0 on the same trades)

| Variant | BTC dev | BTC holdout | ADA | LINK | SOL | Pooled holdout | Win % | Max losing streak | Max DD (1% risk) | Avg hold | t vs B0 |
|---|---|---|---|---|---|---|---:|---:|---:|---:|---:|
| **B0 3R target (current)** | +0.46 | +0.25 | +0.16 | +0.22 | +0.25 | **+0.22** | 34% | 14 | 15% | 1.7 d | – |
| T1.5 | +0.21 (−0.24) | +0.12 (−0.13) | +0.15 (−0.01) | +0.14 (−0.08) | +0.04 (−0.21) | +0.12 (−0.10) | 48% | 9 | 17% | 0.9 d | −1.5 |
| T2 | +0.28 (−0.18) | +0.21 (−0.04) | +0.26 (+0.09) | +0.14 (−0.08) | +0.03 (−0.22) | +0.16 (−0.06) | 42% | 10 | 16% | 1.2 d | −1.1 |
| T2.5 | +0.46 (+0.00) | +0.21 (−0.04) | +0.18 (+0.02) | +0.15 (−0.07) | +0.09 (−0.16) | +0.16 (−0.06) | 36% | 14 | 15% | 1.5 d | −1.9 |
| T4 | +0.54 (+0.08) | +0.12 (−0.13) | +0.29 (+0.12) | +0.31 (+0.10) | +0.25 (+0.00) | +0.26 (+0.05) | 29% | 16 | 16% | 2.1 d | +1.0 |
| T5 | +0.53 (+0.07) | +0.30 (+0.04) | +0.40 (+0.24) | +0.26 (+0.04) | +0.28 (+0.03) | +0.31 (+0.10) | 27% | 17 | 17% | 2.5 d | +1.4 |
| N60 (no target) | +1.26 (+0.80) | +0.51 (+0.25) | +0.77 (+0.61) | +0.45 (+0.23) | +0.26 (+0.01) | +0.51 (+0.29) | **22%** | **25** | **36%** | 3.6 d | +1.6 |
| BE1 | +0.19 (−0.26) | +0.24 (−0.02) | +0.10 (−0.06) | +0.13 (−0.09) | +0.08 (−0.17) | +0.13 (−0.09) | 27% | 13 | 16% | 1.1 d | −1.6 |
| BE1.5 | +0.25 (−0.21) | +0.35 (+0.10) | +0.08 (−0.08) | +0.17 (−0.05) | +0.21 (−0.04) | +0.18 (−0.04) | 28% | 16 | 17% | 1.4 d | −0.9 |
| BE2 | +0.46 (+0.00) | +0.29 (+0.04) | +0.19 (+0.02) | +0.19 (−0.03) | +0.22 (−0.03) | +0.21 (−0.00) | 31% | 14 | 13% | 1.6 d | −0.1 |
| P1 | +0.27 (−0.18) | +0.10 (−0.15) | +0.13 (−0.03) | +0.16 (−0.06) | +0.15 (−0.11) | +0.14 (−0.08) | 34% | 14 | 11% | 1.7 d | −2.1 |
| P1.5 | +0.34 (−0.12) | +0.19 (−0.06) | +0.16 (−0.01) | +0.18 (−0.04) | +0.15 (−0.10) | +0.17 (−0.05) | 48% | 9 | 15% | 1.7 d | −1.5 |
| P2-4 | +0.41 (−0.05) | +0.16 (−0.09) | +0.27 (+0.11) | +0.23 (+0.01) | +0.14 (−0.11) | +0.21 (−0.00) | 42% | 10 | 15% | 2.1 d | −0.1 |
| P1.5BE | +0.23 (−0.23) | +0.24 (−0.02) | +0.12 (−0.05) | +0.16 (−0.06) | +0.13 (−0.13) | +0.15 (−0.07) | 48% | 9 | 16% | 1.4 d | −1.4 |
| TR3-1 | +0.45 (−0.01) | +0.31 (+0.06) | +0.28 (+0.12) | +0.13 (−0.09) | +0.48 (+0.23) | +0.28 (+0.07) | 30% | 14 | 26% | 2.0 d | +0.6 |
| TR2-2 | +0.69 (+0.23) | +0.26 (+0.01) | +0.20 (+0.04) | +0.16 (−0.06) | +0.06 (−0.19) | +0.16 (−0.05) | 39% | 10 | 17% | 1.7 d | −0.9 |
| TRS-1 | +0.73 (+0.27) | +0.45 (+0.20) | +0.15 (−0.02) | +0.17 (−0.05) | +0.32 (+0.07) | +0.24 (+0.02) | 31% | 14 | 29% | 2.2 d | +0.2 |
| **T3TR** | +0.81 (+0.35) | +0.45 (+0.20) | +0.14 (−0.02) | +0.37 (+0.15) | +0.48 (+0.23) | **+0.34 (+0.12)** | 33% | 14 | 17% | 2.3 d | **+1.7** |
| TIME30 | +0.41 (−0.05) | +0.20 (−0.06) | +0.14 (−0.02) | +0.22 (+0.01) | +0.22 (−0.03) | +0.20 (−0.02) | 34% | 15 | 15% | 1.5 d | −0.9 |
| TIME90 | +0.52 (+0.06) | +0.32 (+0.06) | +0.16 (−0.00) | +0.25 (+0.03) | +0.24 (−0.01) | +0.23 (+0.01) | 33% | 14 | 15% | 1.8 d | +1.2 |

**Range-gated entries only** (secondary, pooled holdout, 289 trades): the same picture.
- B0 makes +0.28R.
- T3TR makes +0.43R (difference +0.15R, t = 1.8).
- T5 makes +0.41R (29% win), and N60 +0.61R (24% win).
- Break-even and partial variants are all at or below B0.

## Hypotheses: what held up

| # | Prediction | Result |
|---|---|---|
| H1 | Break-even at +1R lowers expectancy; the cost shrinks for later triggers; BE2 is about neutral; fewer losing trades | **Confirmed.** BE1 −0.09R, BE1.5 −0.04R, BE2 −0.00R. Full losses fall from 66% to 43% of trades, but the saved trades become scratches that end slightly negative after costs and funding, and fewer trades reach 3R (14% vs 20%). |
| H2 | 1.5R / 2R targets raise the win rate above 40% but lower expectancy | **Confirmed.** Win rates 48% / 42%; expectancy −0.10 / −0.06R. |
| H3 | 4R, 5R and no target: same or higher expectancy, win rate < 30% | **Confirmed.** +0.05 / +0.10 / +0.29R, win rates 29% / 27% / 22%. |
| H4 | 50% partials at 1R / 1.5R raise the win rate by 8–15 points for −0.02 to −0.10R; P1.5BE costs more | **Partly.** P1.5: +14 points for −0.05R ✓. P1: win rate unchanged (34%), because the half left after a +1R partial is usually stopped, leaving a small net loss ✗. P1.5BE costs a little more than P1.5 ✓. |
| H5 | Trailing (TR3-1, T3TR) adds +0.05 to +0.15R; TR2-2 in between; the structure trail is the weakest | **Mostly.** T3TR +0.12R ✓, TR3-1 +0.07R ✓. TR2-2 came out **below** B0 (−0.05R) ✗. The structure trail (+0.02R) is weaker than the ATR trails ✓, but not the weakest. |
| H6 | 30-bar time exit lowers expectancy; 90 bars about neutral | **Confirmed**, both effects small (−0.02 / +0.01R). |
| Overall | Nothing beats B0 robustly; if anything does, it's a let-winners-run variant, at a lower win rate | **Confirmed.** T3TR comes closest. Its win rate is unchanged (33%), not lower. |

## What it means

1. **Break-even stops hurt this strategy.** They feel safer (fewer full losses) but cost expectancy, because breakout trades
   usually pull back before they work. Only a late trigger (+2R) is harmless, and it doesn't help either.
2. **Taking profit early lowers expectancy.** 1.5R / 2R targets and 50% partials lift the win rate to 42–48%, and they
   shorten losing streaks (9–10 vs 14), but they give up 0.05–0.10R per trade. That's the price of a smoother ride.
3. **The money is in the right tail.** Every "let it run" variant (T4, T5, N60, TR3-1, T3TR) makes more per trade, but:
   - the win rate drops below your 30% bar for T4, T5 and N60;
   - N60 has a 36% drawdown at 1% risk, with 25 losses in a row.

   T3TR is the one that keeps the 33% win rate and the 17% drawdown while adding about +0.12R per trade.
4. **Recommendation:** keep the 3R target live. Optionally, run T3TR in the demo next to B0 as a pre-declared test. It's a
   small change to the exit logic (at 3R: lock +2R and trail at highest high − 3 ATR, max 30 days). After about 60–100
   trades the comparison will be clear either way.

## Caveats

- **Small development set:** 75 BTC trades. The holdout (404 trades) is the main evidence.
- **Signals are evaluated independently** (overlaps allowed) to keep the comparison exactly paired. In the live bot, a
  longer-holding exit would block some later entries on the same coin.
- **Binance prices, funding and volume.** BloFin fills will differ slightly.
