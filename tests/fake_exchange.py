"""In-memory stand-in for bot.exchange.BlofinDemo, used by the run/reconcile tests."""
from __future__ import annotations

import itertools
from decimal import Decimal

import pandas as pd

from bot.config import BAR_MS
from bot.exchange import Instrument, Position, TpslOrder
from bot.indicators import DAY_MS


def make_inst(inst_id, cv="1", lot="0.01", min_size="0.01", tick="0.01"):
    return Instrument(inst_id, Decimal(cv), Decimal(lot), Decimal(min_size), Decimal(tick), Decimal("1000000"), 75)


class World:
    """Synthetic market: flat around 100 with one daily swing high at 110, then a breakout bar."""

    def __init__(self, end_ms: int, days: int = 420):
        self.end_ms = end_ms  # close time of the newest bar
        n = days * 6
        start = end_ms - n * BAR_MS
        rows = []
        swing_day = (end_ms - 40 * DAY_MS) // DAY_MS * DAY_MS
        for k in range(n):
            ts = start + k * BAR_MS
            c = 100.0
            hi, lo = c + 0.5, c - 0.5
            if swing_day <= ts < swing_day + DAY_MS and (ts - swing_day) // BAR_MS == 2:
                hi = 110.0
            vol = 90.0 if k % 2 else 110.0
            rows.append([ts, c, hi, lo, c, vol])
        df = pd.DataFrame(rows, columns=["ts", "open", "high", "low", "close", "volume"])
        self.frames = {"SOL-USDT": df.copy(), "BTC-USDT": df.copy()}

    def set_breakout(self, inst_id="SOL-USDT"):
        df = self.frames[inst_id]
        i, j = len(df) - 2, len(df) - 1
        df.loc[i, ["open", "high", "low", "close"]] = [100.0, 109.4, 99.9, 109.0]
        df.loc[j, ["open", "high", "low", "close", "volume"]] = [109.0, 112.5, 108.8, 112.0, 1000.0]

    def advance(self, n_bars: int, inst_prices: dict | None = None, ranges: dict | None = None):
        """Append n flat bars to every symbol at the given closes (default: last close)."""
        for inst_id, df in self.frames.items():
            last = float(df["close"].iloc[-1])
            px = (inst_prices or {}).get(inst_id, last)
            lo, hi = (ranges or {}).get(inst_id, (px - 0.3, px + 0.3))
            add = [[int(df["ts"].iloc[-1]) + (k + 1) * BAR_MS, px, hi, lo, px, 100.0] for k in range(n_bars)]
            if add:
                self.frames[inst_id] = pd.concat([df, pd.DataFrame(add, columns=df.columns)], ignore_index=True)
        self.end_ms += n_bars * BAR_MS


class FakeExchange:
    settle_seconds = 0

    def __init__(self, world: World, balance: float = 200_000.0, attached_tpsl_visible: bool = True):
        self.world = world
        self.private = True
        self.balance = balance
        self.attached_tpsl_visible = attached_tpsl_visible
        self.insts = {i: make_inst(i) for i in world.frames}
        self.pos: dict[str, dict] = {}
        self.orders: dict[str, dict] = {}
        self.tpsl: dict[str, TpslOrder] = {}
        self.fill_log: list[dict] = []
        self.funding = -1.5
        self.calls: list[tuple] = []
        self.ids = itertools.count(1000)
        self.leverage = {}

    # public
    def instruments(self):
        return dict(self.insts)

    def candles(self, inst_id, n_bars, bar="4H", newer_than_ms=None):
        df = self.world.frames[inst_id].copy()
        df["confirmed"] = True
        return df.tail(n_bars).reset_index(drop=True)

    def price(self, inst_id):
        return float(self.world.frames[inst_id]["close"].iloc[-1])

    def last_prices(self):
        return {i: self.price(i) for i in self.world.frames}

    # account
    def usdt_balance(self):
        return {"equity": self.balance, "available": self.balance}

    def positions(self):
        return {i: Position(i, p["contracts"], p["avg"], 0.0, 1, "isolated") for i, p in self.pos.items()}

    def ensure_account_modes(self, have_positions):
        self.calls.append(("ensure_account_modes",))
        return []

    def set_leverage(self, inst_id, lev):
        self.calls.append(("set_leverage", inst_id, lev))
        self.leverage[inst_id] = lev

    # orders
    def _fill(self, inst_id, side, size, price, order_id, ts):
        fee = abs(size * price) * 0.0005
        self.fill_log.append({"instId": inst_id, "tradeId": str(next(self.ids)), "orderId": order_id,
                              "fillPrice": str(price), "fillSize": str(size), "side": side, "fee": str(fee),
                              "ts": str(ts)})
        return fee

    def market_entry(self, inst, side, contracts, stop, target, client_oid):
        self.calls.append(("market_entry", inst.inst_id, side, str(contracts), client_oid))
        oid = str(next(self.ids))
        px = self.price(inst.inst_id)
        size = float(contracts)
        fee = self._fill(inst.inst_id, side, size, px, oid, self.world.end_ms + 60_000)
        self.pos[inst.inst_id] = {"contracts": size if side == "buy" else -size, "avg": px}
        self.orders[client_oid] = {"orderId": oid, "clientOrderId": client_oid, "state": "filled",
                                   "filledSize": str(size), "averagePrice": str(px), "fee": str(fee),
                                   "updateTime": str(self.world.end_ms + 60_000)}
        if self.attached_tpsl_visible:
            tid = str(next(self.ids))
            self.tpsl[tid] = TpslOrder(tid, inst.inst_id, "sell" if side == "buy" else "buy", None,
                                       None if target is None else float(inst.round_price(target)),
                                       float(inst.round_price(stop)))
        return oid

    def order_by_client_id(self, inst_id, client_oid):
        return self.orders.get(client_oid)

    def pending_tpsl(self, inst_id=None):
        return [o for o in self.tpsl.values() if inst_id is None or o.inst_id == inst_id]

    def place_tpsl(self, inst, close_side, contracts, stop, target, client_oid):
        self.calls.append(("place_tpsl", inst.inst_id, str(contracts), stop, target))
        tid = str(next(self.ids))
        self.tpsl[tid] = TpslOrder(tid, inst.inst_id, close_side, float(contracts),
                                   None if target is None else float(inst.round_price(target)),
                                   None if stop is None else float(inst.round_price(stop)))
        return tid

    def cancel_tpsl(self, inst_id, ids):
        self.calls.append(("cancel_tpsl", inst_id, tuple(ids)))
        for i in ids:
            self.tpsl.pop(i, None)

    def _exit(self, inst_id, price, size=None):
        p = self.pos[inst_id]
        side = "sell" if p["contracts"] > 0 else "buy"
        size = abs(p["contracts"]) if size is None else min(size, abs(p["contracts"]))
        self._fill(inst_id, side, size, price, str(next(self.ids)), self.world.end_ms + 30_000)
        left = abs(p["contracts"]) - size
        if left <= 1e-12:
            del self.pos[inst_id]
        else:
            p["contracts"] = left if p["contracts"] > 0 else -left

    def close_position(self, inst_id, client_oid):
        self.calls.append(("close_position", inst_id))
        if inst_id in self.pos:
            self._exit(inst_id, self.price(inst_id))

    def fills(self, inst_id, begin_ms):
        return [f for f in self.fill_log if f["instId"] == inst_id and int(f["ts"]) >= begin_ms]

    def funding_fees(self, inst_id, begin_ms, end_ms):
        return self.funding

    # test helpers ------------------------------------------------------------
    def trigger_stop(self, inst_id):
        o = next(o for o in self.tpsl.values() if o.inst_id == inst_id and o.sl_trigger is not None)
        self._exit(inst_id, o.sl_trigger)
        self.tpsl = {k: v for k, v in self.tpsl.items() if v.inst_id != inst_id}

    def trigger_tp(self, inst_id):
        """Fill the nearest take-profit order (partial or full)."""
        tps = [(k, o) for k, o in self.tpsl.items() if o.inst_id == inst_id and o.tp_trigger is not None]
        k, o = min(tps, key=lambda x: x[1].tp_trigger)
        self._exit(inst_id, o.tp_trigger, o.size)
        del self.tpsl[k]
        if inst_id not in self.pos:
            self.tpsl = {k: v for k, v in self.tpsl.items() if v.inst_id != inst_id}

    def manual_close(self, inst_id, price):
        self._exit(inst_id, price)
