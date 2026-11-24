"""Reconcile saved state with the exchange, manage stops, account for exits, keep TP/SL on the exchange.

Run at the start of every run, so a crash, a duplicate run or a manual close on the exchange never leads to a
doubled trade or a lost exit. Every close-side fill is booked exactly once (by trade id), which handles partial
take-profits, runner exits and manual partial closes the same way.
"""
from __future__ import annotations

import logging
import time
from decimal import Decimal

import numpy as np

from .config import BAR_MS, COSTS_RT, EXIT_PROTOCOLS
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


def protocol_of(t: dict):
    return EXIT_PROTOCOLS.get(t.get("protocol", "B0"), EXIT_PROTOCOLS["B0"])


def upgrade_trade(t: dict) -> dict:
    """Fill in fields that trades saved by older versions of the bot don't have."""
    t.setdefault("protocol", "B0")
    t.setdefault("stop0", t["stop"])
    t.setdefault("r_unit", abs(t["ref_price"] - t["stop0"]))
    t.setdefault("init_contracts", t["contracts"])
    t.setdefault("gross_closed", 0.0)
    t.setdefault("exit_fees", 0.0)
    t.setdefault("realized_added", 0.0)
    t.setdefault("accounted_fills", [])
    t.setdefault("be_done", False)
    t.setdefault("trail_on", False)
    t.setdefault("best", t.get("entry_price", t["ref_price"]))
    t.setdefault("max_bars", protocol_of(t).max_bars)
    t.setdefault("target_r", 3.0)
    if "partials" not in t:
        t["partials"] = [{"r": t["target_r"], "frac": 1.0, "contracts": t["contracts"], "price": t["target"],
                          "done": False}]
    return t


def plan_partials(t: dict, inst: Instrument) -> list[dict]:
    """Partial take-profits for the filled size, per the trade's exit protocol."""
    proto = protocol_of(t)
    sign = direction(t["side"])
    init = Decimal(t["init_contracts"])
    out, used = [], Decimal(0)
    for r, frac in proto.partials:
        r = t["target_r"] if r is None else r
        if frac >= 1.0:
            c = init - used
        else:
            c = inst.round_contracts_down(init * Decimal(str(frac)))
            c = min(c, init - used)
        used += c
        out.append({"r": r, "frac": frac, "contracts": str(c), "price": t["ref_price"] + sign * r * t["r_unit"],
                    "done": c <= 0})
    return out


class Reconciler:
    def __init__(self, client, state: dict, instruments: dict[str, Instrument], journal, alerter, now_ms: int):
        self.client = client
        self.state = state
        self.instruments = instruments
        self.journal = journal
        self.alerter = alerter
        self.now_ms = now_ms
        for t in state["open_trades"]:
            if t.get("status") == "open":
                upgrade_trade(t)

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
        filled = Decimal(str(_num(od.get("filledSize")))).quantize(inst.lot_size)
        t["status"] = "open"
        t["order_id"] = str(od.get("orderId") or t.get("order_id"))
        t["contracts"] = t["init_contracts"] = str(filled)
        t["entry_price"] = _num(od.get("averagePrice"), t["ref_price"])
        t["entry_fee"] = abs(_num(od.get("fee")))
        t["entry_ts"] = int(_num(od.get("updateTime") or od.get("createTime"), self.now_ms))
        t["risk_amount"] = float(filled) * float(inst.contract_value) * t["r_unit"]
        t["best"] = t["entry_price"]
        t["partials"] = plan_partials(t, inst)
        upgrade_trade(t)

    # -- fills -------------------------------------------------------------------
    def account_fills(self, t: dict) -> Decimal:
        """Book close-side fills not yet booked. Returns the contracts they closed."""
        try:
            fills = self.client.fills(t["inst_id"], int(t.get("entry_ts", self.now_ms)) - 60_000)
        except Exception as e:  # noqa: BLE001 - accounting must not stop the run
            log.warning("fills lookup failed for %s: %s", t["inst_id"], e)
            return Decimal(0)
        csd, sign, cv = close_side(t["side"]), direction(t["side"]), float(t["contract_value"])
        seen = set(t["accounted_fills"])
        closed = Decimal(0)
        for f in fills:
            fid = str(f.get("tradeId"))
            if f.get("side") != csd or fid in seen or str(f.get("orderId")) == str(t.get("order_id")):
                continue
            size, px = _num(f.get("fillSize")), _num(f.get("fillPrice"))
            t["gross_closed"] += sign * (px - t["entry_price"]) * size * cv
            t["exit_fees"] += abs(_num(f.get("fee")))
            t.setdefault("close_fills", []).append({"ts": int(_num(f.get("ts"))), "price": px, "size": size})
            t["accounted_fills"].append(fid)
            closed += Decimal(str(size))
        return closed

    def _book_realized(self, t: dict, net_so_far: float) -> None:
        delta = net_so_far - t["realized_added"]
        self.state["realized_pnl"] += delta
        t["realized_added"] = net_so_far

    # -- open trades -------------------------------------------------------------
    def sync_positions(self, positions: dict[str, Position], prices: dict[str, float]) -> None:
        for t in [t for t in self.state["open_trades"] if t["status"] == "open"]:
            inst = self.instruments.get(t["inst_id"])
            pos = positions.get(t["inst_id"])
            sign = direction(t["side"])
            if pos is None or pos.contracts * sign <= 0:
                self.finalize_exit(t, prices.get(t["inst_id"]))
                continue
            have, want = Decimal(str(abs(pos.contracts))), Decimal(t["contracts"])
            if inst is not None:
                have = have.quantize(inst.lot_size)
            if have < want:
                self.account_fills(t)
                self._mark_partials(t, have)
                t["contracts"] = str(have)
                self._book_realized(t, t["gross_closed"] - t["exit_fees"])
            elif have > want:
                msg = f"{t['symbol']}: exchange position {have} contracts > state {want}; adopting exchange size"
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

    def _mark_partials(self, t: dict, have: Decimal) -> None:
        """Mark partial targets as filled when the position shrank by their size (in order)."""
        closed_total = Decimal(t["init_contracts"]) - have
        cum = Decimal(0)
        for p in t["partials"]:
            if p["done"] and Decimal(p["contracts"]) > 0:
                cum += Decimal(p["contracts"])
                continue
            if p["done"]:
                continue
            if closed_total >= cum + Decimal(p["contracts"]):
                cum += Decimal(p["contracts"])
                p["done"], p["filled_at"] = True, self.now_ms
                self.journal.trade("partial_exit", trade_id=t["id"], symbol=t["symbol"], side=t["side"],
                                   price=p["price"], contracts=p["contracts"],
                                   details=f"{p['frac']:.0%} at {p['r']:g}R; {have} contracts left")
                self.alerter.send(f"💰 PARTIAL {t['symbol']} {t['side']}: {p['contracts']} contracts at {p['r']:g}R "
                                  f"({p['price']:.6g}); {have} left running")

    # -- stop management (break-even, trailing runner) ---------------------------
    def manage_stop(self, t: dict, ind, price: float | None) -> str | None:
        """Move the stop per the trade's protocol from closed 4h candles. Returns 'hit' if price is already
        beyond the new stop, else a description of the change, or None."""
        proto = protocol_of(t)
        sign = direction(t["side"])
        after = ind[ind["ts"] >= t["entry_bar_close_ts"]]
        if len(after):
            ext = float(after["high"].max()) if sign > 0 else float(after["low"].min())
            t["best"] = max(t["best"], ext) if sign > 0 else min(t["best"], ext)
        if price is not None:
            t["best"] = max(t["best"], price) if sign > 0 else min(t["best"], price)
        reached = (t["best"] - t["ref_price"]) * sign / t["r_unit"]
        new, why = t["stop"], []
        if proto.be_r is not None and not t["be_done"] and reached >= proto.be_r:
            be = t["entry_price"] * (1 + sign * COSTS_RT)
            t["be_done"] = True
            if (be - new) * sign > 0:
                new, why = be, why + [f"break-even (+{proto.be_r:g}R reached)"]
        if proto.trail is not None:
            k, act = proto.trail
            act = t["target_r"] if act is None else act
            if not t["trail_on"] and reached >= act:
                t["trail_on"] = True
            last = ind[ind["ts"] + BAR_MS <= self.now_ms].tail(1)
            atr = float(last["atr"].iloc[0]) if len(last) else float("nan")
            if t["trail_on"] and np.isfinite(atr):
                tr = t["best"] - sign * k * atr
                if (tr - new) * sign > 0:
                    new, why = tr, why + [f"trailing {k:g} ATR from best {t['best']:.6g}"]
        if (new - t["stop"]) * sign > 0:
            old = t["stop"]
            t["stop"] = new
            msg = f"{t['symbol']}: stop {old:.6g} -> {new:.6g} ({'; '.join(why)})"
            self.journal.trade("stop_moved", trade_id=t["id"], symbol=t["symbol"], side=t["side"], stop=new,
                               details=msg)
            if price is not None and (price - new) * sign <= 0:
                return "hit"
            return msg
        return None

    # -- exits -------------------------------------------------------------------
    def finalize_exit(self, t: dict, last_price: float | None, reason: str | None = None) -> dict:
        """Position is gone: book remaining fills, funding and the result, and close the trade."""
        reason = reason or t.pop("exit_reason_pending", None)
        before = Decimal(t["contracts"])
        closed_now = self.account_fills(t)
        sign, cv = direction(t["side"]), float(t["contract_value"])
        estimated = False
        missing = before - closed_now
        if missing > 0:  # fills not visible (yet): value the rest at the last price
            px = last_price if last_price else t["entry_price"]
            t["gross_closed"] += sign * (px - t["entry_price"]) * float(missing) * cv
            t.setdefault("close_fills", []).append({"ts": self.now_ms, "price": px, "size": float(missing),
                                                    "estimated": True})
            estimated = True
        fills = t.get("close_fills", [])
        size = sum(f["size"] for f in fills) or 1e-12
        exit_price = sum(f["price"] * f["size"] for f in fills) / size
        exit_ts = max([f["ts"] for f in fills] + [int(t.get("entry_ts", self.now_ms))])
        funding = None
        try:
            funding = self.client.funding_fees(t["inst_id"], int(t.get("entry_ts", exit_ts)), exit_ts)
        except Exception as e:  # noqa: BLE001
            log.warning("funding lookup failed for %s: %s", t["inst_id"], e)
        funding = funding or 0.0
        fees = t.get("entry_fee", 0.0) + t["exit_fees"]
        net = t["gross_closed"] - fees + funding
        r_mult = net / t["risk_amount"] if t.get("risk_amount") else 0.0
        if reason is None:
            last_px = fills[-1]["price"] if fills else exit_price
            near = 0.25 * (t.get("r_unit") or 1e-12)
            final_tp = t["partials"][-1]["price"] if t.get("partials") else t.get("target")
            if abs(last_px - t["stop"]) <= near:
                reason = ("trailing stop" if t.get("trail_on") else "break-even stop" if t.get("be_done")
                          else "stop")
            elif final_tp is not None and abs(last_px - final_tp) <= near:
                reason = "target"
            else:
                reason = "closed outside bot (manual/liquidation)"
        partial_txt = ", ".join(f"{p['r']:g}R" for p in t.get("partials", []) if p["done"] and p["frac"] < 1)
        # what was still open just before this close, and what partials had already banked
        t["contracts_at_close"], t["partial_net"] = str(before), t["realized_added"]
        t.update(status="closed", exit_ts=exit_ts, exit_price=exit_price, exit_reason=reason,
                 gross_pnl=t["gross_closed"], fees=fees, funding=funding, net_pnl=net, r_multiple=r_mult,
                 exit_estimated=estimated, contracts="0")
        self.state["open_trades"].remove(t)
        self.state["closed_trades"].append(t)
        self._book_realized(t, net)
        self.state["consecutive_losses"] = update_loss_streak(self.state["consecutive_losses"], net)
        self._cancel_leftover_tpsl(t)
        self.journal.trade("exit", trade_id=t["id"], symbol=t["symbol"], side=t["side"], price=exit_price,
                           contracts=t["init_contracts"], pnl=t["gross_closed"], fee=fees, funding=funding,
                           net_pnl=net, r_multiple=r_mult,
                           details=f"{reason}{'; partials at ' + partial_txt if partial_txt else ''}"
                                   f"{' (exit price estimated)' if estimated else ''}")
        if fees:
            self.journal.trade("fee", trade_id=t["id"], symbol=t["symbol"], fee=fees)
        if funding:
            self.journal.trade("funding", trade_id=t["id"], symbol=t["symbol"], funding=funding)
        self.alerter.send(f"{'✅' if net > 0 else '❌'} EXIT {t['symbol']} {t['side']} ({reason}) avg {exit_price:.6g}: "
                          f"net {net:+,.2f} USDT = {r_mult:+.2f}R · losing streak {self.state['consecutive_losses']}")
        return t

    def _cancel_leftover_tpsl(self, t: dict) -> None:
        try:
            left = [o.tpsl_id for o in self.client.pending_tpsl(t["inst_id"])]
            if left:
                self.client.cancel_tpsl(t["inst_id"], left)
        except Exception as e:  # noqa: BLE001
            log.warning("could not cancel leftover TP/SL on %s: %s", t["inst_id"], e)

    def close_trade(self, t: dict, reason: str, last_price: float | None) -> None:
        t["exit_reason_pending"] = reason
        self.client.close_position(t["inst_id"], f"x{t['symbol']}{self.now_ms // 1000}")
        time.sleep(getattr(self.client, "settle_seconds", 2))
        self.finalize_exit(t, last_price, reason)

    # -- TP/SL on the exchange ---------------------------------------------------
    def desired_orders(self, t: dict) -> list[tuple]:
        """(stop or None, target or None, contracts) that should be on the exchange for this trade."""
        pending = [p for p in t["partials"] if not p["done"] and Decimal(p["contracts"]) > 0]
        if len(pending) == 1 and Decimal(pending[0]["contracts"]) == Decimal(t["contracts"]):
            return [(t["stop"], pending[0]["price"], Decimal(t["contracts"]))]  # one combined order
        out = [(t["stop"], None, Decimal(t["contracts"]))]
        out += [(None, p["price"], Decimal(p["contracts"])) for p in pending]
        return out

    def verify_tpsl(self, t: dict) -> str:
        """Make sure exactly the desired stop / take-profit orders are on the exchange. Returns what happened."""
        inst = self.instruments[t["inst_id"]]
        tick, lot = float(inst.tick_size), float(inst.lot_size)
        orders = self.client.pending_tpsl(t["inst_id"])
        want = self.desired_orders(t)

        def same(px, val):
            if px is None:
                return val is None
            return val is not None and abs(val - float(inst.round_price(px))) <= tick / 2

        def matches(o, w):
            sl, tp, c = w
            size_ok = (o.size is None and c == Decimal(t["contracts"])) or \
                (o.size is not None and abs(o.size - float(c)) < lot / 2)
            return same(sl, o.sl_trigger) and same(tp, o.tp_trigger) and size_ok

        free = list(orders)
        ok = True
        for w in want:
            hit = next((o for o in free if matches(o, w)), None)
            if hit is None:
                ok = False
                break
            free.remove(hit)
        if ok and not free:
            t["tpsl_ids"] = [o.tpsl_id for o in orders]
            return "ok"
        if orders:
            self.client.cancel_tpsl(t["inst_id"], [o.tpsl_id for o in orders])
        n = t.get("tpsl_replacements", 0) + 1
        t["tpsl_replacements"] = n
        ids = []
        for k, (sl, tp, c) in enumerate(want):
            ids.append(self.client.place_tpsl(inst, close_side(t["side"]), c, sl, tp,
                                              f"t{t['symbol']}{t['entry_bar_close_ts'] // 1000}{n}{k}"))
        t["tpsl_ids"] = ids
        desc = "; ".join(("SL " + f"{sl:.6g}" if sl is not None else "") + (" TP " + f"{tp:.6g}" if tp is not None
                                                                              else "") + f" x{c}" for sl, tp, c in want)
        msg = f"{t['symbol']}: TP/SL {'missing' if not orders else 'updated'} on exchange; placed {desc}"
        self.journal.trade("tpsl_replaced", trade_id=t["id"], symbol=t["symbol"], side=t["side"],
                           stop=t["stop"], details=msg)
        return msg


def describe_trade(t: dict) -> str:
    parts = ", ".join(f"{p['r']:g}R {'done' if p['done'] else 'open'}" for p in t.get("partials", []))
    return (f"{t['symbol']} {t['side']} {t['contracts']} @ {t.get('entry_price', 0):.6g} SL {t['stop']:.6g} "
            f"[{t.get('protocol', 'B0')}: {parts}{', BE' if t.get('be_done') else ''}"
            f"{', trailing' if t.get('trail_on') else ''}] opened {ms_to_iso(t.get('entry_ts'))}")
