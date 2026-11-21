# BloFin demo self-test — 2026-11-21T03:21:06Z

| Check | Result | Detail |
|---|---|---|
| account modes net + isolated | ✅ | already set |
| set leverage 1x isolated | ✅ |  |
| market entry accepted | ✅ | orderId 1000145828019, 0.1 contracts @ ~58359.4 |
| entry filled and found by clientOrderId | ✅ | state filled, avg 58311.600000000000000000, fee 0.003498696000000000 |
| position visible | ✅ | Position(inst_id='BTC-USDT', contracts=0.1, avg_price=58311.6, unrealized_pnl=4.9428623017e-05, leverage=1.0, margin_mode='isolated') |
| attached stop-loss listed on exchange | ✅ | SL 56608.6 |
| attached take-profit listed on exchange | ✅ | TP 61277.4 |
| bot TP/SL check after entry | ✅ | ok |
| TP/SL deleted for the repair test | ✅ |  |
| bot re-placed missing TP/SL | ✅ | BTC: TP/SL missing on exchange; re-placed SL 56608.6 / TP 61277.4 |
| second check finds them in place | ✅ | ok |
| position closed | ✅ |  |
| no TP/SL left behind | ✅ |  |
| fills readable | ✅ | 2 fills, fees 0.006999 USDT |
| funding-fees endpoint readable | ✅ | 0.0 |

**15/15 passed**
