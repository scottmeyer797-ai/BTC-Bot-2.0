"""Position sizing and leverage."""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

from .config import MAX_LEVERAGE
from .exchange import Instrument


@dataclass
class SizeResult:
    contracts: Decimal
    leverage: int
    risk_amount: float      # $ lost if the stop fills exactly, after rounding
    notional: float
    note: str | None = None          # e.g. "risk reduced: leverage cap 5x"
    skip_reason: str | None = None


def _ceil(x: float) -> int:
    return max(1, math.ceil(x - 1e-9))


def size_position(inst: Instrument, equity: float, risk_pct: float, entry: float, stop: float,
                  available_margin: float | None = None, max_leverage: int = MAX_LEVERAGE) -> SizeResult:
    """contracts = (risk% x equity) / stop distance, rounded down to the lot size.

    Leverage is the smallest integer that lets the position's isolated margin fit
    in the margin budget (simulated equity, or the demo account's available
    balance if that is smaller), capped at 5x and the instrument maximum. If even
    the cap is not enough the position is shrunk to fit and a note is returned.
    """
    cv = float(inst.contract_value)
    per_contract_risk = cv * abs(entry - stop)
    if per_contract_risk <= 0 or equity <= 0:
        return SizeResult(Decimal(0), 0, 0.0, 0.0, skip_reason="invalid stop or equity")
    lev_cap = min(max_leverage, inst.max_leverage)
    budget, budget_name = equity, "leverage cap"
    if available_margin is not None and available_margin * 0.98 < equity:
        budget, budget_name = max(available_margin * 0.98, 0.0), "insufficient demo margin"
    raw = risk_pct * equity / per_contract_risk
    note = None
    if raw * cv * entry > budget * lev_cap:
        raw = budget * lev_cap / (cv * entry)
        note = f"risk reduced: {budget_name} ({lev_cap}x)"
    if raw > float(inst.max_market_size):
        raw = float(inst.max_market_size)
        note = "risk reduced: exchange max market order size"
    contracts = inst.round_contracts_down(raw)
    if contracts <= 0:
        return SizeResult(Decimal(0), 0, 0.0, 0.0, note=note,
                          skip_reason=f"size {raw:.4f} contracts below minimum {inst.min_size}")
    notional = float(contracts) * cv * entry
    leverage = min(_ceil(notional / budget), lev_cap) if budget > 0 else lev_cap
    return SizeResult(contracts, leverage, float(contracts) * per_contract_risk, notional, note=note)
