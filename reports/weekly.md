# Weekly report — 2026-11-23 00:39 UTC

Mode **challenge** · notional account 100,000 USDT · BloFin **demo**

- Status: ✅ active
- Simulated equity: **100,000.00** (+0.00% vs start)
- Open trades: 0 · losing streak: 0

## Trades

| Period | Trades | Win rate | Avg R | Total R | Net P&L | Fees | Funding |
|---|---:|---:|---:|---:|---:|---:|---:|
| Last 7 days | 0 | 0.0% | +0.00R | +0.00R | +0.00 | 0.00 | +0.00 |
| All time | 0 | 0.0% | +0.00R | +0.00R | +0.00 | 0.00 | +0.00 |

## Equity

```mermaid
xychart-beta
  title "Simulated equity (end of day, USDT)"
  x-axis ["11-21", "11-22", "11-23"]
  line [100000, 100000, 100000]
```

| Day | Equity |
|---|---:|
| 2026-11-21 | 100,000.00 |
| 2026-11-22 | 100,000.00 |
| 2026-11-23 | 100,000.00 |

- Max drawdown (peak to trough): **0.00%**
- Max drawdown from starting balance (prop-firm static): **0.00%** of 10% limit
- Daily-loss peak: **0.00%** of 00:00 UTC equity on 2026-11-23 (5% limit)
- Equity is sampled once per run (every 4h), so intrabar extremes are not in these figures; the bot's own breach check also uses 4h highs/lows.

## Versus backtest expectations

Backtest: ≈ +0.15R per trade over the long run, but flat to negative since Aug 2026; win rate ≈ 30–35% at 3R.

| Metric | Forward test | 95% range | Backtest |
|---|---:|---:|---:|
| Win rate | 0.0% (0/0) | 0%–100% | 30%–35% |
| Avg R per trade | +0.00R | n/a | +0.15R (recently ≈ 0 or below) |

_Only 0 closed trade(s): too few to tell the strategy apart from its backtest. Ranges above show how wide the uncertainty still is._

