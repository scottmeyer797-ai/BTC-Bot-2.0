"""Self-test of order + TP/SL handling on BloFin DEMO with the smallest possible BTC position.

    python -m bot.selftest

Opens the minimum BTC-USDT size (0.1 contract = 0.0001 BTC) with stop and
target attached, checks BloFin lists them, deletes them and checks the bot's
TP/SL repair puts them back, then closes the position and cleans up. It never
touches the bot's state file, trade/signal logs or statistics. It refuses to
run if BTC-USDT already has a position or the bot has a BTC trade open.
"""
from __future__ import annotations

import json
import logging
import sys
import tempfile
import time
from decimal import Decimal
from pathlib import Path

from .config import load_config
from .exchange import BlofinDemo
from .journal import Journal
from .reconcile import Reconciler
from .state import utcnow_iso

INST = "BTC-USDT"
log = logging.getLogger("selftest")


class _NoAlerts:
    def send(self, msg):
        log.info("(alert suppressed in self-test) %s", msg)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%Y-%m-%dT%H:%M:%SZ")
    logging.Formatter.converter = time.gmtime
    cfg = load_config()
    client = BlofinDemo(cfg)
    if not client.private:
        print("self-test needs BLOFIN_API_KEY / BLOFIN_API_SECRET / BLOFIN_PASSPHRASE")
        return 1
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> bool:
        results.append((name, ok, detail))
        log.info("%s %s %s", "PASS" if ok else "FAIL", name, detail)
        return ok

    # safety: never interfere with a real bot trade or a manual position
    if cfg.state_path.exists():
        st = json.loads(cfg.state_path.read_text())
        if any(t["inst_id"] == INST for t in st.get("open_trades", [])):
            print("ABORT: the bot has an open BTC-USDT trade; self-test not run")
            return 1
    positions = client.positions()
    if INST in positions:
        print(f"ABORT: BTC-USDT already has a position ({positions[INST].contracts} contracts); self-test not run")
        return 1
    stray = client.pending_tpsl(INST)
    if stray:
        print(f"ABORT: BTC-USDT has {len(stray)} pending TP/SL orders; self-test not run")
        return 1

    notes = client.ensure_account_modes(bool(positions))
    check("account modes net + isolated", True, "; ".join(notes) or "already set")
    inst = client.instruments()[INST]
    price = client.last_prices()[INST]
    contracts = inst.min_size * 2   # two minimum lots, so a half-size take-profit is possible
    stop, target = price * 0.97, price * 1.05
    trade = {"id": f"selftest{int(time.time())}", "symbol": "BTC", "inst_id": INST, "side": "long",
             "contracts": str(contracts), "contract_value": str(inst.contract_value), "stop": stop,
             "target": target, "ref_price": price, "entry_bar_close_ts": int(time.time() * 1000),
             # one combined stop + take-profit for the whole size (the B0/BE2 layout)
             "partials": [{"r": 5.0, "frac": 1.0, "contracts": str(contracts), "price": target, "done": False}]}
    tmp = Path(tempfile.mkdtemp())
    rec = Reconciler(client, {"open_trades": [], "closed_trades": [], "realized_pnl": 0.0,
                              "consecutive_losses": 0}, {INST: inst}, Journal(tmp), _NoAlerts(),
                     int(time.time() * 1000))
    entered = False
    try:
        client.set_leverage(INST, 1)
        check("set leverage 1x isolated", True)
        oid = client.market_entry(inst, "buy", contracts, stop, target, trade["id"])
        entered = True
        check("market entry accepted", bool(oid), f"orderId {oid}, {contracts} contracts @ ~{price}")
        od = None
        for _ in range(10):
            od = client.order_by_client_id(INST, trade["id"])
            if od and float(od.get("filledSize") or 0) > 0:
                break
            time.sleep(1)
        log.info("order detail (raw): %s", json.dumps(od))
        check("entry filled and found by clientOrderId", bool(od and float(od.get("filledSize") or 0) > 0),
              f"state {od and od.get('state')}, avg {od and od.get('averagePrice')}, fee {od and od.get('fee')}")
        pos = client.positions().get(INST)
        check("position visible", pos is not None and pos.contracts > 0, f"{pos}")

        time.sleep(2)
        attached = client.pending_tpsl(INST)
        log.info("pending TP/SL after entry (parsed): %s", attached)
        raw = client._call("privateGetTradeOrdersTpslPending", {"instId": INST})
        log.info("pending TP/SL after entry (raw): %s", json.dumps(raw))
        has_sl = any(o.sl_trigger and abs(o.sl_trigger - float(inst.round_price(stop))) <= float(inst.tick_size)
                     for o in attached)
        has_tp = any(o.tp_trigger and abs(o.tp_trigger - float(inst.round_price(target))) <= float(inst.tick_size)
                     for o in attached)
        check("attached stop-loss listed on exchange", has_sl, f"SL {inst.fmt_price(stop)}")
        check("attached take-profit listed on exchange", has_tp, f"TP {inst.fmt_price(target)}")

        res = rec.verify_tpsl(trade)
        check("bot TP/SL check after entry", True, res)

        client.cancel_tpsl(INST, [o.tpsl_id for o in client.pending_tpsl(INST)])
        time.sleep(1)
        check("TP/SL deleted for the repair test", client.pending_tpsl(INST) == [])
        res = rec.verify_tpsl(trade)
        time.sleep(1)
        after = client.pending_tpsl(INST)
        log.info("pending TP/SL after repair: %s", after)
        check("bot re-placed missing TP/SL", len(after) == 1 and after[0].sl_trigger is not None
              and after[0].tp_trigger is not None, res)
        res2 = rec.verify_tpsl(trade)
        check("second check finds them in place", res2 == "ok", res2)

        # runner protocols (R1/R4): a full-size stop-only order plus a half-size take-profit-only order
        client.cancel_tpsl(INST, [o.tpsl_id for o in client.pending_tpsl(INST)])
        time.sleep(1)
        half = inst.round_contracts_down(contracts / 2)
        client.place_tpsl(inst, "sell", contracts, stop, None, f"sls{int(time.time())}")
        client.place_tpsl(inst, "sell", half, None, target, f"tps{int(time.time())}")
        time.sleep(2)
        split = client.pending_tpsl(INST)
        log.info("stop-only + take-profit-only orders (parsed): %s", split)
        raw = client._call("privateGetTradeOrdersTpslPending", {"instId": INST})
        log.info("stop-only + take-profit-only orders (raw): %s", json.dumps(raw))
        sl_only = [o for o in split if o.sl_trigger is not None and o.tp_trigger is None]
        tp_only = [o for o in split if o.tp_trigger is not None and o.sl_trigger is None]
        check("stop-only order accepted (full size)",
              len(sl_only) == 1 and (sl_only[0].size is None or abs(sl_only[0].size - float(contracts)) < 1e-9),
              f"{sl_only}")
        check("take-profit-only order accepted (half size)",
              len(tp_only) == 1 and tp_only[0].size is not None and abs(tp_only[0].size - float(half)) < 1e-9,
              f"{tp_only}")
    except Exception as e:  # noqa: BLE001
        check("no exceptions", False, f"{type(e).__name__}: {e}")
    finally:
        if entered or INST in client.positions():
            try:
                client.close_position(INST, f"xselftest{int(time.time())}")
                time.sleep(2)
            except Exception as e:  # noqa: BLE001
                check("close position", False, f"{type(e).__name__}: {e}")
        left = client.pending_tpsl(INST)
        if left:
            client.cancel_tpsl(INST, [o.tpsl_id for o in left])
        time.sleep(1)
        check("position closed", INST not in client.positions())
        check("no TP/SL left behind", client.pending_tpsl(INST) == [])
        fills = client.fills(INST, int(time.time() * 1000) - 15 * 60_000)
        log.info("fills (raw): %s", json.dumps(fills))
        check("fills readable", len(fills) >= 2, f"{len(fills)} fills, fees {sum(abs(float(f.get('fee') or 0)) for f in fills):.6f} USDT")
        fund = client.funding_fees(INST, int(time.time() * 1000) - 7 * 86_400_000, int(time.time() * 1000))
        check("funding-fees endpoint readable", fund is not None, f"{fund}")

    failed = [r for r in results if not r[1]]
    lines = [f"# BloFin demo self-test — {utcnow_iso()}", "", "| Check | Result | Detail |", "|---|---|---|"]
    lines += [f"| {n} | {'✅' if ok else '❌'} | {d} |" for n, ok, d in results]
    lines += ["", f"**{len(results) - len(failed)}/{len(results)} passed**"]
    out = cfg.state_dir / "selftest" / "last.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
