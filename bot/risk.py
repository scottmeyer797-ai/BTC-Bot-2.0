"""Risk caps, prop-firm guards and the loss-streak rule (pure functions)."""
from __future__ import annotations

from dataclasses import dataclass

from .config import DAILY_LOSS_LIMIT, LOSS_STREAK_HALVE, MAX_DRAWDOWN_LIMIT, ModeParams

EPS = 1e-9


# -- loss streak -----------------------------------------------------------
def effective_risk_pct(mode: ModeParams, consecutive_losses: int) -> float:
    """Risk per trade; halved while the losing streak is 3 or more."""
    return mode.risk_pct / 2 if consecutive_losses >= LOSS_STREAK_HALVE else mode.risk_pct


def update_loss_streak(consecutive_losses: int, net_pnl: float) -> int:
    """A loss (net P&L < 0) extends the streak, a win (> 0) resets it, exactly 0 leaves it."""
    if net_pnl < 0:
        return consecutive_losses + 1
    if net_pnl > 0:
        return 0
    return consecutive_losses


# -- account snapshot ------------------------------------------------------
@dataclass
class Snapshot:
    account_size: float
    equity: float               # simulated equity incl. open P&L
    day_start_equity: float     # simulated equity at 00:00 UTC today
    open_initial_risk: float    # sum of $ risk of open trades at entry (for the max-open-risk cap)
    open_remaining_risk: float  # sum of $ still at risk from current price to stop (for the guards)

    @property
    def todays_loss(self) -> float:
        return max(0.0, self.day_start_equity - self.equity)

    @property
    def drawdown(self) -> float:
        return max(0.0, self.account_size - self.equity)


def open_risk_cap_reason(mode: ModeParams, snap: Snapshot, new_risk: float) -> str | None:
    total = (snap.open_initial_risk + new_risk) / snap.equity
    if total > mode.max_open_risk + EPS:
        return (f"max open risk: open {snap.open_initial_risk / snap.equity:.2%} + new {new_risk / snap.equity:.2%}"
                f" > {mode.max_open_risk:.1%}")
    return None


def guard_block_reason(mode: ModeParams, snap: Snapshot, new_risk: float) -> str | None:
    """Pre-trade prop-firm guards. Blocks if the worst case would REACH the threshold.

    Today's loss and the drawdown already include open P&L, so open trades count
    only with the risk still remaining between current price and their stops.
    """
    daily = (snap.todays_loss + snap.open_remaining_risk + new_risk) / snap.day_start_equity
    if daily >= mode.daily_block - EPS:
        return (f"daily-loss guard: today's loss {snap.todays_loss:,.0f} + open risk {snap.open_remaining_risk:,.0f}"
                f" + new {new_risk:,.0f} = {daily:.2%} of day start >= {mode.daily_block:.1%}")
    dd = (snap.drawdown + snap.open_remaining_risk + new_risk) / snap.account_size
    if dd >= mode.drawdown_block - EPS:
        return (f"drawdown guard: drawdown {snap.drawdown:,.0f} + open risk {snap.open_remaining_risk:,.0f}"
                f" + new {new_risk:,.0f} = {dd:.2%} of start >= {mode.drawdown_block:.0%}")
    return None


def breach_reason(account_size: float, equity: float, day_start_equity: float) -> str | None:
    """Actual limit breach (5% daily from 00:00 UTC equity, 10% static from start)."""
    if equity <= day_start_equity * (1 - DAILY_LOSS_LIMIT) + EPS:
        return (f"DAILY LOSS LIMIT breached: equity {equity:,.2f} <= {day_start_equity * (1 - DAILY_LOSS_LIMIT):,.2f}"
                f" (5% below 00:00 UTC equity {day_start_equity:,.2f})")
    if equity <= account_size * (1 - MAX_DRAWDOWN_LIMIT) + EPS:
        return (f"MAX DRAWDOWN breached: equity {equity:,.2f} <= {account_size * (1 - MAX_DRAWDOWN_LIMIT):,.2f}"
                f" (10% below starting balance)")
    return None


# -- worst case between runs -----------------------------------------------
@dataclass
class TradeExposure:
    symbol: str
    side: str            # long | short
    entry_ts: int        # ms, when the position was opened
    exit_ts: int | None  # ms, when it closed (None = still open)
    entry_price: float
    stop: float
    qty: float           # base-currency quantity (contracts x contract value)
    realized_pnl: float = 0.0  # net P&L once closed


def worst_equity_path(base_equity: float, exposures: list[TradeExposure], bars: dict, start_ms: int,
                      end_ms: int, bar_ms: int) -> list[tuple[int, float]]:
    """Worst simulated equity in every 4h bar whose close is in (start_ms, end_ms].

    `base_equity` is the realized equity before `start_ms` excluding the given
    exposures. For every bar each trade contributes its realized P&L if it had
    already closed, otherwise its unrealized P&L at the bar's adverse extreme
    (low for longs, high for shorts) clamped at its stop. `bars` maps symbol to a
    frame with ts/high/low columns.
    """
    closes = set()
    for df in bars.values():
        closes.update(int(t) + bar_ms for t in df["ts"] if start_ms < int(t) + bar_ms <= end_ms)
    path = []
    lookup = {s: df.set_index("ts") for s, df in bars.items()}
    for c in sorted(closes):
        open_ts = c - bar_ms
        eq = base_equity
        for t in exposures:
            if t.exit_ts is not None and t.exit_ts <= open_ts:
                eq += t.realized_pnl
                continue
            if t.entry_ts >= c:
                continue  # opened after this bar (an entry inside the bar counts as open: conservative)
            df = lookup.get(t.symbol)
            if df is None or open_ts not in df.index:
                continue
            hi, lo = float(df.at[open_ts, "high"]), float(df.at[open_ts, "low"])
            if t.side == "long":
                px = max(lo, t.stop)
                eq += (px - t.entry_price) * t.qty
            else:
                px = min(hi, t.stop)
                eq += (t.entry_price - px) * t.qty
        path.append((c, eq))
    return path
