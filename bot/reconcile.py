"""Reconcile saved state with the exchange, account for exits, verify TP/SL.

Run at the start of every run, so a crash, a duplicate run or a manual close
on the exchange never leads to a doubled trade or a lost exit.
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal

from .exchange import Instrument, Position
from .risk import update_loss_streak
from .state import ms_to_iso

log = logging.getLogger(__name__)


def direction(side: str) -> int:
    return 1 if side == "long" else -1


def entry_side(side: str) -> str:
    return "buy" if side == "long" else "sell"


def close_side(side: str) -> str:
    return "sell" if side == "long" else "buy"


def trade_qty(t: dict) -> float:
    return float(t["contracts"]) * float(t["contract_value"])


def _num(x, default=0.0) -> float:
    try:
        return float(x) if x not in (None, "") else default
    except (TypeError, ValueError):
        return default


class Reconciler:
    def __init__(self, client, state: dict, instruments: dict[str, Instrument], journal, alerter, now_ms: int):
        self.client = client
        self.state = state
        self.instruments = instruments
        self.journal = journal
        self.alerter = alerter
        self.now_ms = now_ms

    # -- entries ---------------------------------------------------------------
    def resolve_pending(self) -> None:
        """Entries whose order was sent but whose fill was never recorded (e.g. crash)."""
        for t in [t for t in self.state["open_trades"] if t["status"] == "pending"]:
            od = self.client.order_by_client_id(t["inst_id"], t["id"])
            filled = _num(od.get("filledSize")) if od else 0.0
            if od and filled > 0:
                self.mark_filled(t, od)
                self.journal.trade("entry_recovered", trade_id=t["id"], symbol=t["symbol"], side=t["side"],
                                   order_id=t.get("order_id"), price=t["entry_price"], contracts=t["contracts"],
                                   details="pending entry found filled on exchange")
            elif od and od.get("state") in ("live", "partially_filled"):
                log.warning("entry %s still live on exchange; leaving pending", t["id"])
            else:
                self.state["open_trades"].remove(t)
                self.journal.trade("entry_dropped", trade_id=t["id"], symbol=t["symbol"], side=t["side"],
                                   details=f"no filled order with clientOrderId {t['id']} on exchange")

    def mark_filled(self, t: dict, od: dict) -> None:
        inst = self.instruments[t["inst_id"]]
        filled = Decimal(str(_num(od.get("filledSize"))))
        t["status"] = "open"
        t["order_id"] = str(od.get("orderId") or t.get("order_id"))
        t["contracts"] = str(filled.quantize(inst.lot_size))
        t["entry_price"] = _num(od.get("averagePrice"), t["ref_price"])
        t["entry_fee"] = abs(_num(od.get("fee")))
        t["entry_ts"] = int(_num(od.get("updateTime") or od.get("createTime"), self.now_ms))
        per = float(inst.contract_value) * abs(t["ref_price"] - t["stop"])
        t["risk_amount"] = float(filled) * per

    # -- open trades -------------------------------------------------------------
    def sync_positions(self, positions: dict[str, Position], prices: dict[str, float]) -> None:
        by_inst = {}
        for t in self.state["open_trades"]:
            if t["status"] == "open":
                by_inst[t["inst_id"]] = t
        for inst_id, t in list(by_inst.items()):
            pos = positions.get(inst_id)
            sign = direction(t["side"])
            if pos is None or pos.contracts * sign <= 0:
                self.finalize_exit(t, prices.get(inst_id))
                continue
            have = Decimal(str(abs(pos.contracts)))
            want = Decimal(t["contracts"])
            if have != want:
                msg = f"{t['symbol']}: exchange position {have} contracts != state {want}; adopting exchange size"
                log.warning(msg)
                self.journal.trade("size_mismatch", trade_id=t["id"], symbol=t["symbol"], side=t["side"],
                                   contracts=str(have), details=msg)
                self.alerter.send("⚠️ " + msg)
                t["contracts"] = str(have)
        known = {t["inst_id"] for t in self.state["open_trades"]}
        unmanaged = []
        for inst_id, pos in positions.items():
            if inst_id not in known:
                unmanaged.append({"inst_id": inst_id, "contracts": pos.contracts})
                if inst_id not in {u["inst_id"] for u in self.state.get("unmanaged_positions", [])}:
                    self.alerter.send(f"⚠️ {inst_id}: position of {pos.contracts} contracts not opened by the bot; "
                                      "leaving it alone (not managed, not counted in simulated equity)")
        self.state["unmanaged_positions"] = unmanaged

    def finalize_exit(self, t: dict, last_price: float | None, reason: str | None = None) -> dict:
        """Position is gone: work out exit price, fees and funding from fills and close the trade."""
        reason = reason or t.get("exit_reason_pending")
        fills = []
        try:
            fills = self.client.fills(t["inst_id"], int(t.get("entry_ts", self.now_ms)) - 60_000)
        except Exception as e:  # noqa: BLE001 - accounting must not stop the run
            log.warning("fills lookup failed for %s: %s", t["inst_id"], e)
        csd = close_side(t["side"])
        entry_fills = [f for f in fills if str(f.get("orderId")) == str(t.get("order_id"))]
        exit_fills = [f for f in fills if f.get("side") == csd and str(f.get("orderId")) != str(t.get("order_id"))]
        qty_cv = float(t["contract_value"])
        sign = direction(t["side"])
        estimated = False
        if exit_fills:
            size = sum(_num(f.get("fillSize")) for f in exit_fills)
            exit_price = sum(_num(f.get("fillPrice")) * _num(f.get("fillSize")) for f in exit_fills) / max(size, 1e-12)
            exit_ts = max(int(f["ts"]) for f in exit_fills)
        else:
            exit_price = last_price if last_price else t["entry_price"]
            exit_ts = self.now_ms
            estimated = True
        gross = sign * (exit_price - t["entry_price"]) * float(t["contracts"]) * qty_cv
        fees = sum(abs(_num(f.get("fee"))) for f in entry_fills + exit_fills) if fills else 0.0
        if not entry_fills:
            fees += t.get("entry_fee", 0.0)
        funding = None
        try:
            funding = self.client.funding_fees(t["inst_id"], int(t.get("entry_ts", exit_ts)), exit_ts)
        except Exception as e:  # noqa: BLE001
            log.warning("funding lookup failed for %s: %s", t["inst_id"], e)
        funding = funding or 0.0
        net = gross - fees + funding
        r_mult = net / t["risk_amount"] if t.get("risk_amount") else 0.0
        if reason is None:
            r_dist = abs(t["ref_price"] - t["stop"]) or 1e-12
            if abs(exit_price - t["stop"]) <= 0.25 * r_dist:
                reason = "stop"
            elif abs(exit_price - t["target"]) <= 0.25 * r_dist:
                reason = "target"
            else:
                reason = "closed outside bot (manual/liquidation)"
        t.update(status="closed", exit_ts=exit_ts, exit_price=exit_price, exit_reason=reason, gross_pnl=gross,
                 fees=fees, funding=funding, net_pnl=net, r_multiple=r_mult, exit_estimated=estimated)
        t.pop("exit_reason_pending", None)
        self.state["open_trades"].remove(t)
        self.state["closed_trades"].append(t)
        self.state["realized_pnl"] += net
        self.state["consecutive_losses"] = update_loss_streak(self.state["consecutive_losses"], net)
        self._cancel_leftover_tpsl(t)
        self.journal.trade("exit", trade_id=t["id"], symbol=t["symbol"], side=t["side"], price=exit_price,
                           contracts=t["contracts"], pnl=gross, fee=fees, funding=funding, net_pnl=net,
                           r_multiple=r_mult, details=f"{reason}{' (exit price estimated)' if estimated else ''}")
        if fees:
            self.journal.trade("fee", trade_id=t["id"], symbol=t["symbol"], fee=fees)
        if funding:
            self.journal.trade("funding", trade_id=t["id"], symbol=t["symbol"], funding=funding)
        self.alerter.send(f"{'✅' if net > 0 else '❌'} EXIT {t['symbol']} {t['side']} ({reason}) at {exit_price:.6g}: "
                          f"net {net:+,.2f} USDT = {r_mult:+.2f}R · losing streak {self.state['consecutive_losses']}")
        return t

    def _cancel_leftover_tpsl(self, t: dict) -> None:
        try:
            left = [o.tpsl_id for o in self.client.pending_tpsl(t["inst_id"])]
            if left:
                self.client.cancel_tpsl(t["inst_id"], left)
        except Exception as e:  # noqa: BLE001
            log.warning("could not cancel leftover TP/SL on %s: %s", t["inst_id"], e)

    # -- exits initiated by the bot ---------------------------------------------
    def close_trade(self, t: dict, reason: str, last_price: float | None) -> None:
        t["exit_reason_pending"] = reason
        self.client.close_position(t["inst_id"], f"x{t['symbol']}{self.now_ms // 1000}")
        time.sleep(getattr(self.client, "settle_seconds", 2))
        self.finalize_exit(t, last_price, reason)

    # -- TP/SL ---------------------------------------------------------------
    def verify_tpsl(self, t: dict) -> str:
        """Make sure exactly the right stop and target are on the exchange. Returns what happened."""
        inst = self.instruments[t["inst_id"]]
        tick = float(inst.tick_size)
        orders = self.client.pending_tpsl(t["inst_id"])

        def ok(o) -> bool:
            size_ok = o.size is None or abs(o.size - float(t["contracts"])) < float(inst.lot_size) / 2
            return (o.sl_trigger is not None and abs(o.sl_trigger - float(inst.round_price(t["stop"]))) <= tick / 2
                    and o.tp_trigger is not None
                    and abs(o.tp_trigger - float(inst.round_price(t["target"]))) <= tick / 2 and size_ok)

        if any(ok(o) for o in orders):
            good = next(o for o in orders if ok(o))
            t["tpsl_id"] = good.tpsl_id
            extra = [o.tpsl_id for o in orders if o.tpsl_id != good.tpsl_id]
            if extra:
                self.client.cancel_tpsl(t["inst_id"], extra)
                return f"ok (cancelled {len(extra)} stray TP/SL orders)"
            return "ok"
        if orders:
            self.client.cancel_tpsl(t["inst_id"], [o.tpsl_id for o in orders])
        n = t.get("tpsl_replacements", 0) + 1
        t["tpsl_replacements"] = n
        t["tpsl_id"] = self.client.place_tpsl(inst, close_side(t["side"]), Decimal(t["contracts"]), t["stop"],
                                              t["target"], f"t{t['symbol']}{t['entry_bar_close_ts'] // 1000}{n}")
        msg = (f"{t['symbol']}: TP/SL {'missing' if not orders else 'wrong'} on exchange; re-placed "
               f"SL {t['stop']:.6g} / TP {t['target']:.6g}")
        self.journal.trade("tpsl_replaced", trade_id=t["id"], symbol=t["symbol"], side=t["side"],
                           order_id=t["tpsl_id"], stop=t["stop"], target=t["target"], details=msg)
        return msg


def describe_trade(t: dict) -> str:
    return (f"{t['symbol']} {t['side']} {t['contracts']} @ {t.get('entry_price', 0):.6g} SL {t['stop']:.6g} "
            f"TP {t['target']:.6g} opened {ms_to_iso(t.get('entry_ts'))}")
