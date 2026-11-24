# Exit study: pre-registration

Written and committed **before** any exit variant was simulated. The git commit timestamp of this file is the proof. Nothing
in this file may be changed after results exist. Any later change will be listed in the results report as a deviation.

## Fixed entry (not part of the study)

The current bot's **long** side, the only strategy that passed out-of-sample on ADA, LINK and SOL:
- Signal: a closed 4h candle with volume z > 2 that closes above a daily swing level by more than 0.2 × ATR(14), after the
  previous close was at or below the level. Daily swing levels: higher than 5 days each side, usable after the 5 later days
  close, at most 365 days old.
- Stop: level − 0.5 × ATR. Signals with a stop < 0.3% or > 10% away are skipped.
- Entry at the open of the next 1h bar. **Always on** (no regime gate). A range-gated subset is reported too, as
  secondary.
- To keep the comparison exactly paired, **every signal is evaluated as its own trade** (overlapping trades allowed) with
  a 6-bar cooldown between signals. Every exit variant therefore sees the same entries.

## Simulation rules (all variants)

- 1h path. Within a 1h bar the **stop is checked before any target** (conservative). A stop gapped through fills at the
  open. Targets are limit orders and fill at their price.
- Break-even moves and trailing stops are **activated on a bar's high** but only become the active stop **from the next
  1h bar** (no same-bar ordering bias).
- Trailing levels use 4h ATR(14) from the last closed 4h bar, and highs seen since entry.
- Costs: 0.16% round trip (0.06% taker + 0.02% slippage per side), charged on the full size whether it exits in one fill or
  in parts. Real Binance 8h funding, applied to the size still open over time.
- R = net P&L ÷ initial risk (entry − initial stop). Win = net R > 0.

## Variants (fixed list, 20; no others will be added to the ranking)

| ID | Exit |
|---|---|
| **B0** | **Baseline: target 3R, time exit 60 × 4h bars** (the current bot) |
| T1.5, T2, T2.5, T4, T5 | Target 1.5 / 2 / 2.5 / 4 / 5R, time exit 60 bars |
| N60 | No target, time exit 60 bars only |
| BE1, BE1.5, BE2 | Target 3R; stop moves to break-even (entry + costs) once price reaches +1 / +1.5 / +2R |
| P1, P1.5 | 50% off at +1R / +1.5R, rest at 3R, time exit 60 bars |
| P2-4 | 50% off at +2R, rest at 4R |
| P1.5BE | 50% off at +1.5R, then the stop on the rest moves to break-even, rest at 3R |
| TR3-1 | No target; once +1R is reached, trail at (highest high since entry − 3 ATR); max 180 bars |
| TR2-2 | No target; once +2R is reached, trail at (highest high − 2 ATR); max 180 bars |
| TRS-1 | No target; once +1R is reached, trail at the low of the last 10 × 4h bars; max 180 bars |
| T3TR | When +3R is reached, don't exit: lock the stop at +2R and trail at highest high − 3 ATR; max 180 bars |
| TIME30, TIME90 | Target 3R, time exit after 30 / 90 bars |

## Hypotheses (written before seeing any result)

Reasoning: earlier studies showed that half of all breakout trades never reach +1R before the stop. They also showed that
random entries with trailing exits profited on BTC (fat right tail and long-term drift).

- **H1 (break-even):** moving the stop to break-even **lowers** expectancy vs B0 at +1R (normal pullbacks stop out trades
  that would have reached 3R). The cost shrinks as the trigger rises (+1.5R, +2R), and BE2 is about neutral. BE variants
  raise the share of non-losing trades.
- **H2 (lower targets):** T1.5 and T2 raise the win rate (above 40%) but **lower** expectancy vs B0.
- **H3 (higher targets / no target):** T4, T5 and N60 have about the same or slightly higher expectancy than B0, but win
  rates **below 30%**.
- **H4 (partials):** P1 and P1.5 raise the win rate by about 8–15 points at a small cost in expectancy (−0.02 to −0.10R).
  P1.5BE costs more than P1.5.
- **H5 (trailing):** letting winners run with a trailing stop (TR3-1, T3TR) **raises** expectancy vs B0 on BTC by
  roughly +0.05 to +0.15R. TR2-2 is in between. TRS-1 (structure trail) does worse than the ATR trails.
- **H6 (time):** TIME30 lowers expectancy (cuts trades that need time); TIME90 is about neutral.
- **Overall expectation:** no exit variant beats B0 robustly on all test sets. If one does, it'll be a "let winners run"
  variant (T3TR or TR3-1), and it'll do so at the cost of a lower win rate.

## Data splits and decision rule

- **Development:** BTC trades entered 2020-04 … 2023-12. Used to describe the variants and pick the best candidates.
- **Test set 1:** BTC trades entered 2024-01 … 2026-11 (time holdout).
- **Test set 2:** ADA, LINK, SOL, full history (cross-coin holdout).
- **Primary metric:** mean net R per trade, compared **paired** with B0 on the same trades (difference per trade).
- A variant **beats B0** only if all of these hold:
  1. its paired mean difference vs B0 is > 0 on development;
  2. it is > 0 on the BTC 2024–26 holdout;
  3. it is > 0 on at least 2 of the 3 alts;
  4. the pooled holdout (BTC 2024–26 + 3 alts) paired t-stat is ≥ 2.0 (19 comparisons, so a single t ≈ 2 result is
     treated with caution: Bonferroni-adjusted t for 19 tests ≈ 2.9 is reported too);
  5. its own win rate is ≥ 30% on the pooled holdout (your requirement).
- Secondary metrics, reported but not used to decide: win rate, profit factor, max losing streak, average hold, R
  distribution, max drawdown of a 1%-risk equity curve.
- If no variant passes, the conclusion is "keep B0".
