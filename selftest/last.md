# BloFin demo self-test — 2026-11-21T03:33:45Z

| Check | Result | Detail |
|---|---|---|
| account modes net + isolated | ✅ | already set |
| set leverage 1x isolated | ✅ |  |
| market entry accepted | ✅ | orderId 1000145833315, 0.1 contracts @ ~56965.8 |
| entry filled and found by clientOrderId | ✅ | state filled, avg 56997.900000000000000000, fee 0.003419874000000000 |
| position visible | ✅ | Position(inst_id='BTC-USDT', contracts=0.1, avg_price=56997.9, unrealized_pnl=-0.00247333902535, leverage=1.0, margin_mode='isolated') |
| attached stop-loss listed on exchange | ✅ | SL 55256.8 |
| attached take-profit listed on exchange | ✅ | TP 59814.1 |
| bot TP/SL check after entry | ✅ | ok |
| TP/SL deleted for the repair test | ✅ |  |
| bot re-placed missing TP/SL | ✅ | BTC: TP/SL missing on exchange; re-placed SL 55256.8 / TP 59814.1 |
| second check finds them in place | ✅ | ok |
| position closed | ✅ |  |
| no TP/SL left behind | ✅ |  |
| fills readable | ✅ | 4 fills, fees 0.013840 USDT |
| funding-fees endpoint readable | ✅ | 0.0 |

**15/15 passed**
