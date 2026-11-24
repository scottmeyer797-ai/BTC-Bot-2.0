# BloFin demo self-test — 2026-11-24T18:40:30Z

| Check | Result | Detail |
|---|---|---|
| account modes net + isolated | ✅ | already set |
| set leverage 1x isolated | ✅ |  |
| market entry accepted | ✅ | orderId 1000146231703, 0.2 contracts @ ~60113.4 |
| entry filled and found by clientOrderId | ✅ | state filled, avg 60121.700000000000000000, fee 0.007214604000000000 |
| position visible | ✅ | Position(inst_id='BTC-USDT', contracts=0.2, avg_price=60121.7, unrealized_pnl=-0.001222455796966, leverage=1.0, margin_mode='isolated') |
| attached stop-loss listed on exchange | ✅ | SL 58310.0 |
| attached take-profit listed on exchange | ✅ | TP 63119.1 |
| bot TP/SL check after entry | ✅ | ok |
| TP/SL deleted for the repair test | ✅ |  |
| bot re-placed missing TP/SL | ✅ | BTC: TP/SL missing on exchange; placed SL 58310 TP 63119.1 x0.2 |
| second check finds them in place | ✅ | ok |
| stop-only order accepted (full size) | ✅ | [TpslOrder(tpsl_id='10004684891', inst_id='BTC-USDT', side='sell', size=0.2, tp_trigger=None, sl_trigger=58310.0)] |
| take-profit-only order accepted (half size) | ✅ | [TpslOrder(tpsl_id='10004684892', inst_id='BTC-USDT', side='sell', size=0.1, tp_trigger=63119.1, sl_trigger=None)] |
| position closed | ✅ |  |
| no TP/SL left behind | ✅ |  |
| fills readable | ✅ | 2 fills, fees 0.014429 USDT |
| funding-fees endpoint readable | ✅ | 0.0 |

**17/17 passed**
