"""Thin BloFin DEMO client built on ccxt.

ccxt is used for request signing, rate limiting and its built-in demo URL
(`set_sandbox_mode(True)`). Every call goes through BloFin's raw endpoints
(ccxt "implicit" methods) so the exact request fields are under our control,
particularly for TP/SL orders. The demo-URL guard is re-checked before every
request.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

import ccxt
import pandas as pd

from .config import BAR, DEMO_BASE_URL, Config, assert_demo_url

log = logging.getLogger(__name__)

MARGIN_MODE = "isolated"
POSITION_SIDE = "net"


@dataclass(frozen=True)
class Instrument:
    inst_id: str
    contract_value: Decimal
    lot_size: Decimal
    min_size: Decimal
    tick_size: Decimal
    max_market_size: Decimal
    max_leverage: int

    def round_contracts_down(self, contracts: float | Decimal) -> Decimal:
        c = Decimal(str(contracts))
        steps = (c / self.lot_size).to_integral_value(rounding=ROUND_DOWN)
        out = steps * self.lot_size
        return out if out >= self.min_size else Decimal(0)

    def round_price(self, price: float | Decimal) -> Decimal:
        p = Decimal(str(price))
        return (p / self.tick_size).to_integral_value(rounding=ROUND_HALF_UP) * self.tick_size

    def fmt_contracts(self, contracts: Decimal) -> str:
        return format(contracts.quantize(self.lot_size), "f")

    def fmt_price(self, price: float | Decimal) -> str:
        return format(self.round_price(price).quantize(self.tick_size), "f")


@dataclass(frozen=True)
class Position:
    inst_id: str
    contracts: float          # signed: + long, - short (net mode)
    avg_price: float
    unrealized_pnl: float
    leverage: float
    margin_mode: str


@dataclass(frozen=True)
class TpslOrder:
    tpsl_id: str
    inst_id: str
    side: str
    size: float | None        # None / -1 means whole position
    tp_trigger: float | None
    sl_trigger: float | None


def _f(x, default=None):
    try:
        if x is None or x == "":
            return default
        return float(x)
    except (TypeError, ValueError):
        return default


class BlofinDemo:
    def __init__(self, cfg: Config, *, private: bool = True):
        assert_demo_url(cfg.base_url)
        # requests_trust_env: honour HTTPS_PROXY / CA bundle env vars (no-op when none are set)
        params = {"enableRateLimit": True, "requests_trust_env": True, "options": {"defaultType": "swap"}}
        if private and cfg.has_credentials:
            params.update(apiKey=cfg.api_key, secret=cfg.api_secret, password=cfg.passphrase)
        self.ex = ccxt.blofin(params)
        self.ex.set_sandbox_mode(True)
        self._guard()
        self.private = private and cfg.has_credentials

    # -- guard -------------------------------------------------------------
    def _guard(self) -> None:
        url = self.ex.urls.get("api", {}).get("rest")
        assert_demo_url(url)
        if url.rstrip("/") != DEMO_BASE_URL:  # belt and braces
            raise RuntimeError("demo guard failed")

    def _call(self, name: str, params=None):
        self._guard()
        fn = getattr(self.ex, name)
        resp = fn(params if params is not None else {})
        if str(resp.get("code", "0")) != "0":
            raise ccxt.ExchangeError(f"{name}: {resp}")
        return resp.get("data")

    def _need_private(self):
        if not self.private:
            raise RuntimeError("BloFin credentials are not configured")

    # -- public ------------------------------------------------------------
    def instruments(self) -> dict[str, Instrument]:
        data = self._call("publicGetMarketInstruments", {"instType": "SWAP"})
        out = {}
        for d in data:
            if d.get("state") != "live":
                continue
            out[d["instId"]] = Instrument(
                inst_id=d["instId"],
                contract_value=Decimal(d["contractValue"]),
                lot_size=Decimal(d["lotSize"]),
                min_size=Decimal(d["minSize"]),
                tick_size=Decimal(d["tickSize"]),
                max_market_size=Decimal(d.get("maxMarketSize") or "1e18"),
                max_leverage=int(Decimal(d.get("maxLeverage") or "1")),
            )
        return out

    def candles(self, inst_id: str, n_bars: int, bar: str = BAR, newer_than_ms: int | None = None) -> pd.DataFrame:
        """Most recent `n_bars` candles (oldest first). Paginates with `after`.

        Columns: ts (open time, ms), open, high, low, close, volume (base ccy), confirmed (bool).
        Stops early once candles at or before `newer_than_ms` are reached.
        """
        rows: list[list] = []
        after = None
        while len(rows) < n_bars:
            params = {"instId": inst_id, "bar": bar, "limit": min(1000, n_bars - len(rows) + 1)}
            if after is not None:
                params["after"] = after
            page = self._call("publicGetMarketCandles", params)
            if not page:
                break
            rows.extend(page)
            after = page[-1][0]
            if newer_than_ms is not None and int(page[-1][0]) <= newer_than_ms:
                break
            if len(page) < params["limit"] - 1:
                break
        if not rows:
            return pd.DataFrame(columns=["ts", "open", "high", "low", "close", "volume", "confirmed"])
        df = pd.DataFrame(
            [[int(r[0]), float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[6]), str(r[8]) == "1"] for r in rows],
            columns=["ts", "open", "high", "low", "close", "volume", "confirmed"],
        )
        return df.drop_duplicates("ts").sort_values("ts").reset_index(drop=True)

    def last_prices(self) -> dict[str, float]:
        data = self._call("publicGetMarketTickers", {})
        return {d["instId"]: _f(d.get("last")) for d in data if _f(d.get("last"))}

    # -- account -----------------------------------------------------------
    def usdt_balance(self) -> dict:
        self._need_private()
        data = self._call("privateGetAccountBalance")
        for d in data.get("details", []):
            if d.get("currency") == "USDT":
                return {"equity": _f(d.get("equity"), 0.0), "available": _f(d.get("available"), 0.0)}
        return {"equity": 0.0, "available": 0.0}

    def positions(self) -> dict[str, Position]:
        self._need_private()
        data = self._call("privateGetAccountPositions") or []
        out = {}
        for d in data:
            c = _f(d.get("positions"), 0.0)
            if not c:
                continue
            if d.get("positionSide") == "short" and c > 0:
                c = -c
            out[d["instId"]] = Position(
                inst_id=d["instId"], contracts=c, avg_price=_f(d.get("averagePrice"), 0.0),
                unrealized_pnl=_f(d.get("unrealizedPnl"), 0.0), leverage=_f(d.get("leverage"), 0.0),
                margin_mode=d.get("marginMode", ""),
            )
        return out

    def ensure_account_modes(self, have_positions: bool) -> list[str]:
        """Make sure the account is in net position mode and isolated margin."""
        self._need_private()
        notes = []
        pm = (self._call("privateGetAccountPositionMode") or {}).get("positionMode")
        if pm != "net_mode":
            if have_positions:
                raise RuntimeError(f"Account is in {pm}; switch to net_mode manually (positions are open)")
            self._call("privatePostAccountSetPositionMode", {"positionMode": "net_mode"})
            notes.append(f"position mode {pm} -> net_mode")
        mm = (self._call("privateGetAccountMarginMode") or {}).get("marginMode")
        if mm != MARGIN_MODE:
            if have_positions:
                raise RuntimeError(f"Account margin mode is {mm}; switch to isolated manually (positions are open)")
            self._call("privatePostAccountSetMarginMode", {"marginMode": MARGIN_MODE})
            notes.append(f"margin mode {mm} -> {MARGIN_MODE}")
        return notes

    def set_leverage(self, inst_id: str, leverage: int) -> None:
        self._need_private()
        self._call("privatePostAccountSetLeverage", {
            "instId": inst_id, "leverage": str(int(leverage)), "marginMode": MARGIN_MODE,
            "positionSide": POSITION_SIDE,
        })

    # -- orders ------------------------------------------------------------
    def market_entry(self, inst: Instrument, side: str, contracts: Decimal, stop: float, target: float,
                     client_oid: str) -> str:
        """Market entry with TP/SL attached (both trigger market orders, -1 = market)."""
        self._need_private()
        data = self._call("privatePostTradeOrder", {
            "instId": inst.inst_id, "marginMode": MARGIN_MODE, "positionSide": POSITION_SIDE,
            "side": side, "orderType": "market", "size": inst.fmt_contracts(contracts),
            "clientOrderId": client_oid,
            "slTriggerPrice": inst.fmt_price(stop), "slOrderPrice": "-1",
            "tpTriggerPrice": inst.fmt_price(target), "tpOrderPrice": "-1",
        })
        first = data[0] if isinstance(data, list) else data
        if str(first.get("code", "0")) != "0":
            raise ccxt.ExchangeError(f"entry rejected: {first}")
        return str(first.get("orderId"))

    def order_by_client_id(self, inst_id: str, client_oid: str) -> dict | None:
        self._need_private()
        try:
            data = self._call("privateGetTradeOrderDetail", {"instId": inst_id, "clientOrderId": client_oid})
            d = data[0] if isinstance(data, list) else data
            if d:
                return d
        except ccxt.BaseError as e:
            log.info("order-detail lookup for %s failed (%s); scanning history", client_oid, e)
        for name in ("privateGetTradeOrdersHistory", "privateGetTradeOrdersPending"):
            try:
                for d in self._call(name, {"instId": inst_id, "limit": "100"}) or []:
                    if d.get("clientOrderId") == client_oid:
                        return d
            except ccxt.BaseError as e:
                log.warning("%s failed: %s", name, e)
        return None

    def pending_tpsl(self, inst_id: str | None = None) -> list[TpslOrder]:
        self._need_private()
        params = {"limit": "100"}
        if inst_id:
            params["instId"] = inst_id
        data = self._call("privateGetTradeOrdersTpslPending", params) or []
        out = []
        for d in data:
            size = _f(d.get("size"))
            out.append(TpslOrder(
                tpsl_id=str(d.get("tpslId")), inst_id=d.get("instId"), side=d.get("side"),
                size=None if size is None or size < 0 else size,
                tp_trigger=_f(d.get("tpTriggerPrice")), sl_trigger=_f(d.get("slTriggerPrice")),
            ))
        return out

    def place_tpsl(self, inst: Instrument, close_side: str, contracts: Decimal, stop: float, target: float,
                   client_oid: str) -> str:
        self._need_private()
        data = self._call("privatePostTradeOrderTpsl", {
            "instId": inst.inst_id, "marginMode": MARGIN_MODE, "positionSide": POSITION_SIDE,
            "side": close_side, "size": inst.fmt_contracts(contracts), "reduceOnly": "true",
            "clientOrderId": client_oid,
            "slTriggerPrice": inst.fmt_price(stop), "slOrderPrice": "-1",
            "tpTriggerPrice": inst.fmt_price(target), "tpOrderPrice": "-1",
        })
        d = data[0] if isinstance(data, list) else data
        if str(d.get("code", "0")) != "0":
            raise ccxt.ExchangeError(f"tpsl rejected: {d}")
        return str(d.get("tpslId"))

    def cancel_tpsl(self, inst_id: str, tpsl_ids: list[str]) -> None:
        self._need_private()
        if tpsl_ids:
            self._guard()
            self.ex.privatePostTradeCancelTpsl([{"instId": inst_id, "tpslId": i} for i in tpsl_ids])

    def close_position(self, inst_id: str, client_oid: str) -> None:
        self._need_private()
        self._call("privatePostTradeClosePosition", {
            "instId": inst_id, "marginMode": MARGIN_MODE, "positionSide": POSITION_SIDE,
            "clientOrderId": client_oid,
        })

    def fills(self, inst_id: str, begin_ms: int) -> list[dict]:
        self._need_private()
        out, end = [], None
        for _ in range(20):
            params = {"instId": inst_id, "begin": str(begin_ms), "limit": "100"}
            if end:
                params["end"] = str(end)
            page = self._call("privateGetTradeFillsHistory", params) or []
            out.extend(page)
            if len(page) < 100:
                break
            end = min(int(p["ts"]) for p in page) - 1
        seen, uniq = set(), []
        for f in out:
            if f.get("tradeId") not in seen:
                seen.add(f.get("tradeId"))
                uniq.append(f)
        return sorted(uniq, key=lambda f: int(f["ts"]))

    def funding_fees(self, inst_id: str, begin_ms: int, end_ms: int) -> float | None:
        """Net funding paid(-)/received(+) on `inst_id` in [begin, end]. None if unavailable."""
        self._need_private()
        try:
            data = self._call("privateGetAccountFundingFees", {"instId": inst_id, "begin": str(begin_ms),
                                                               "end": str(end_ms), "limit": "100"}) or []
        except ccxt.BaseError as e:
            log.warning("funding-fees lookup failed for %s: %s", inst_id, e)
            return None
        total = 0.0
        for d in data:
            ts = int(d.get("ts") or d.get("fundingTime") or 0)
            if ts and not (begin_ms <= ts <= end_ms):
                continue
            total += _f(d.get("fundingFee") or d.get("fee") or d.get("amount"), 0.0)
        return total
