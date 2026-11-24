# Partial-exit / runner study: pre-registration

Written and committed **before** any of these variants was simulated. Nothing here may change after results exist. Any
later change will be listed in the results report as a deviation.

**Goal (from the owner):** with a ~30% win rate, get the most out of BTC's biggest moves in bull markets. **Break-even at
+2R is kept in every variant** (the earlier study found it costs nothing). The question is how to split the position
between banked profit and a runner.

## Fixed parts (same as the exit study, `exit_study_preregistration.md`)

- **Entry:** the current bot's long side, every signal evaluated on its own (6-bar cooldown).
- **Simulation:** 1h path, stop before targets within a bar, gap-aware stops, activations effective from the next 1h bar.
  Costs 0.16% round trip on the full size; real Binance funding on the size still open.
- R = net P&L ÷ initial risk. Win = net R > 0.
- **Break-even:** once the high since entry reaches +2R, the stop on everything still open moves to entry + costs (from the
  next bar).
- **Runner trails** use 4h ATR(14) from the last closed 4h bar and the highest high since entry. Each trail starts when
  its activation level is reached. **Runner maximum hold: 360 × 4h bars (60 days)**, so big trends aren't cut short. All
  other parts keep the 60-bar limit only as part of the reference variants below.

## Variants (fixed list, 12)

| ID | Protocol |
|---|---|
| B0 | Reference: 100% at 3R, no break-even, 60-bar time exit (the bot today) |
| **BE2** | **Comparison point: 100% at 3R, break-even at +2R, 60-bar time exit** (the owner's chosen rule) |
| R1 | 50% at 3R; runner 50% trails at highest high − 3 ATR once +3R is reached |
| R2 | 33% at 2R, 33% at 4R; runner 34% trails at highest high − 3 ATR once +4R is reached |
| R3 | 50% at 2R; runner 50% trails at highest high − 3 ATR once +2R is reached |
| R4 | 25% at 2R, 25% at 3R; runner 50% trails at highest high − 3 ATR once +3R is reached |
| R5 | 50% at 3R; runner 50% trails at the low of the last 10 × 4h bars once +3R is reached |
| R6 | 50% at 3R; runner 50% trails at highest high − 4.5 ATR once +3R is reached (wider, for big moves) |
| R7 | 50% at 3R; runner 50% exits at the next open after a 4h close below the 4h EMA50, once +3R is reached |
| R8 | 0% banked; at +3R the stop locks at +2R and trails at highest high − 3 ATR (the earlier T3TR, plus break-even at 2R) |
| R9 | Regime-adaptive: if the live regime label at entry is **bull**, use R1; otherwise use BE2 |
| R10 | Regime-adaptive: if the live label at entry is **bull**, use R6; otherwise use BE2 |

R1–R8 all have break-even at +2R and a 360-bar maximum hold.

## Hypotheses (written before seeing results)

- **H1:** runner variants (R1, R4–R8) raise expectancy vs BE2 slightly over all trades (+0.03 to +0.10R), and **more on
  trades entered in bull labels** (+0.10 to +0.30R).
- **H2:** taking the first partial at 2R (R2, R3, R4) gives the highest win rates (≥ 40%) but less expectancy than
  R1 (first partial at 3R). R1 is the best of the "half-and-half" designs on all trades.
- **H3:** the wider 4.5 ATR runner (R6) beats the 3 ATR runner (R1) on bull-label trades, but not on all trades.
- **H4:** the EMA50 runner (R7) holds longest, does best in bull labels, and has the deepest drawdown. The structure trail
  (R5) is between R1 and R7.
- **H5:** R8 (whole position runs) has the highest mean R of R1–R8 but the most variance. Its win rate is about equal to
  BE2's.
- **H6:** the regime-adaptive variants (R9, R10) are better than BE2 overall by a small amount. Because only ~20% of
  trades are bull-labelled, their overall gain is smaller than R1 / R6 on bull trades.
- **Overall:** at most one or two runner variants pass the full rule. The benefit is concentrated in the few biggest trades.
  Without the top 5% of trades, runners are about equal to BE2.

## Data splits and decision rule

- **Development:** BTC entries 2020-04 … 2023-12.
- **Holdout:** BTC entries 2024-01 … 2026-11, plus ADA, LINK and SOL (full history). Pooled holdout = all of these.
- **Comparison:** paired difference vs **BE2** on the same trades (mean net R).
- A variant **beats BE2** only if all of these hold:
  1. paired difference > 0 on development;
  2. > 0 on the BTC 2024–26 holdout;
  3. > 0 on at least 2 of the 3 alts;
  4. pooled holdout paired t ≥ 2.0 (11 comparisons; Bonferroni-adjusted t ≈ 2.8 reported too);
  5. pooled holdout win rate ≥ 30%.
- **Bull check** (the owner's goal), reported for every variant: the paired difference vs BE2 on **bull-label entries**
  in the pooled holdout, and on BTC across the whole period. It's informative, not a pass condition, because the samples
  are small.
- **Also reported:**
  - win rate, profit factor, max losing streak, max drawdown (1% risk per trade);
  - average hold;
  - share of total R from the top 5% of trades, and mean R without the top 5% (tests the "overall" hypothesis);
  - mean R on trades whose best move reached +5R or more (how much of the big moves each protocol captures).
