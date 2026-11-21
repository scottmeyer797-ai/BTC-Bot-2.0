"""Weekly markdown report from the state file and the CSV logs."""
from __future__ import annotations

import csv
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .state import ms_to_iso

EXPECTATIONS = {
    "challenge": {"avg_r": 0.15, "win_lo": 0.30, "win_hi": 0.35,
                  "note": "≈ +0.15R per trade over the long run, but flat to negative since Aug 2026; "
                          "win rate ≈ 30–35% at 3R"},
    "funded": {"avg_r": None, "win_lo": 0.22, "win_hi": 0.28,
               "note": "win rate ≈ 25% at 5R (no per-trade R expectation given)"},
}


def _dt(iso: str) -> datetime:
    return datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def _stats(trades: list[dict]) -> dict:
    n = len(trades)
    rs = [t["r_multiple"] for t in trades]
    wins = sum(1 for r in rs if r > 0)
    avg = sum(rs) / n if n else 0.0
    sd = math.sqrt(sum((r - avg) ** 2 for r in rs) / (n - 1)) if n > 1 else 0.0
    return {"n": n, "wins": wins, "win_rate": wins / n if n else 0.0, "avg_r": avg, "total_r": sum(rs),
            "se": sd / math.sqrt(n) if n > 1 else float("nan"),
            "net": sum(t.get("net_pnl", 0.0) for t in trades), "fees": sum(t.get("fees", 0.0) for t in trades),
            "funding": sum(t.get("funding", 0.0) for t in trades)}


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return c - h, c + h


def _stats_rows(label: str, s: dict) -> str:
    return (f"| {label} | {s['n']} | {s['win_rate']:.1%} | {s['avg_r']:+.2f}R | {s['total_r']:+.2f}R | "
            f"{s['net']:+,.2f} | {s['fees']:,.2f} | {s['funding']:+,.2f} |")


def build_report(state: dict, signal_rows: list[dict], now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    week_ago = now - timedelta(days=7)
    mode = state.get("mode", "challenge")
    size = float(state.get("account_size", 100000))
    closed = sorted(state.get("closed_trades", []), key=lambda t: t["exit_ts"])
    closed = [t for t in closed if "r_multiple" in t]
    week = [t for t in closed if t["exit_ts"] >= week_ago.timestamp() * 1000]
    s_all, s_week = _stats(closed), _stats(week)
    hist = [h for h in state.get("equity_history", []) if not h.get("dry_run")]

    out = [f"# Weekly report — {now:%Y-%m-%d %H:%M} UTC", "",
           f"Mode **{mode}** · notional account {size:,.0f} USDT · BloFin **demo**", ""]
    status = "🚨 **CHALLENGE FAILED** — " + str(state.get("failed_reason")) if state.get("failed") else "✅ active"
    equity = hist[-1]["equity"] if hist else size
    out += [f"- Status: {status}",
            f"- Simulated equity: **{equity:,.2f}** ({equity / size - 1:+.2%} vs start)",
            f"- Open trades: {len(state.get('open_trades', []))} · losing streak: {state.get('consecutive_losses', 0)}"
            f"{' (risk halved)' if state.get('consecutive_losses', 0) >= 3 else ''}", ""]

    out += ["## Trades", "", "| Period | Trades | Win rate | Avg R | Total R | Net P&L | Fees | Funding |",
            "|---|---:|---:|---:|---:|---:|---:|---:|", _stats_rows("Last 7 days", s_week),
            _stats_rows("All time", s_all), ""]
    if week:
        out += ["### Closed this week", "", "| Closed | Symbol | Side | Entry | Exit | Reason | R | Net |",
                "|---|---|---|---:|---:|---|---:|---:|"]
        for t in week:
            out.append(f"| {ms_to_iso(t['exit_ts'])} | {t['symbol']} | {t['side']} | {t['entry_price']:.6g} | "
                       f"{t['exit_price']:.6g} | {t['exit_reason']} | {t['r_multiple']:+.2f} | {t['net_pnl']:+,.2f} |")
        out.append("")
    if state.get("open_trades"):
        out += ["### Open", "", "| Symbol | Side | Entry | Stop | Target | Bars held | Risk |", "|---|---|---:|---:|---:|---:|---:|"]
        for t in state["open_trades"]:
            out.append(f"| {t['symbol']} | {t['side']} | {t.get('entry_price', 0):.6g} | {t['stop']:.6g} | "
                       f"{t['target']:.6g} | {t.get('bars_held', 0)} | {t.get('risk_amount', 0):,.2f} |")
        out.append("")

    # trades per week
    per_week = Counter()
    for t in closed + state.get("open_trades", []):
        ts = t.get("entry_ts") or t.get("entry_bar_close_ts")
        if ts:
            y, w, _ = datetime.fromtimestamp(ts / 1000, tz=timezone.utc).isocalendar()
            per_week[f"{y}-W{w:02d}"] += 1
    if per_week:
        out += ["## Trades per week", "", "| ISO week | Entries |", "|---|---:|"]
        out += [f"| {k} | {v} |" for k, v in sorted(per_week.items())]
        avg = sum(per_week.values()) / len(per_week)
        out += ["", f"Average {avg:.1f} entries per week.", ""]

    # equity curve, drawdown, daily-loss peak
    out += ["## Equity", ""]
    if hist:
        daily = {}
        for h in hist:
            daily[h["time"][:10]] = h["equity"]
        days = sorted(daily)
        out += ["```mermaid", "xychart-beta", '  title "Simulated equity (end of day, USDT)"',
                "  x-axis [" + ", ".join(f'"{d[5:]}"' for d in days) + "]",
                "  line [" + ", ".join(f"{daily[d]:.0f}" for d in days) + "]", "```", "",
                "| Day | Equity |", "|---|---:|"] + [f"| {d} | {daily[d]:,.2f} |" for d in days[-14:]] + [""]
        peak, max_dd = size, 0.0
        for h in hist:
            peak = max(peak, h["equity"])
            max_dd = max(max_dd, (peak - h["equity"]) / peak)
        static_dd = max(0.0, (size - min(h["equity"] for h in hist)) / size)
        lows = defaultdict(lambda: float("inf"))
        for h in hist:
            lows[h["time"][:10]] = min(lows[h["time"][:10]], h["equity"])
        day_start = state.get("day_start_equity", {})
        peaks = [((day_start[d] - lows[d]) / day_start[d], d) for d in lows if d in day_start and day_start[d]]
        dl, dl_day = max(peaks) if peaks else (0.0, "-")
        out += [f"- Max drawdown (peak to trough): **{max_dd:.2%}**",
                f"- Max drawdown from starting balance (prop-firm static): **{static_dd:.2%}** of 10% limit",
                f"- Daily-loss peak: **{max(dl, 0):.2%}** of 00:00 UTC equity on {dl_day} (5% limit)",
                "- Equity is sampled once per run (every 4h), so intrabar extremes are not in these figures; the "
                "bot's own breach check also uses 4h highs/lows.", ""]
    else:
        out += ["No live runs recorded yet.", ""]

    # expectations
    exp = EXPECTATIONS.get(mode, EXPECTATIONS["challenge"])
    lo, hi = _wilson(s_all["wins"], s_all["n"])
    out += ["## Versus backtest expectations", "", f"Backtest: {exp['note']}.", "",
            "| Metric | Forward test | 95% range | Backtest |", "|---|---:|---:|---:|",
            f"| Win rate | {s_all['win_rate']:.1%} ({s_all['wins']}/{s_all['n']}) | {lo:.0%}–{hi:.0%} | "
            f"{exp['win_lo']:.0%}–{exp['win_hi']:.0%} |"]
    if s_all["n"] > 1:
        ci = f"{s_all['avg_r'] - 1.96 * s_all['se']:+.2f} to {s_all['avg_r'] + 1.96 * s_all['se']:+.2f}R"
    else:
        ci = "n/a"
    exp_r = f"{exp['avg_r']:+.2f}R (recently ≈ 0 or below)" if exp["avg_r"] is not None else "—"
    out += [f"| Avg R per trade | {s_all['avg_r']:+.2f}R | {ci} | {exp_r} |", ""]
    if s_all["n"] < 30:
        out += [f"_Only {s_all['n']} closed trade(s): too few to tell the strategy apart from its backtest. "
                "Ranges above show how wide the uncertainty still is._", ""]
    elif exp["avg_r"] is not None and s_all["avg_r"] + 1.96 * s_all["se"] < 0:
        out += ["_Average R is significantly below zero: worse than even the recent flat/negative regime._", ""]

    # signals
    wk = [r for r in signal_rows if r.get("dry_run") in ("False", "false", False, "")
          and r.get("run_time") and _dt(r["run_time"]) >= week_ago]
    if wk:
        taken = sum(1 for r in wk if r["action"] == "taken")
        reasons = Counter((r["reason"] or "").split(":")[0].split(" (")[0] for r in wk if r["action"] == "skipped")
        out += ["## Signals this week", "", f"{len(wk)} signals, {taken} taken.", ""]
        if reasons:
            out += ["| Skipped because | Count |", "|---|---:|"] + [f"| {k} | {v} |" for k, v in reasons.most_common()]
            out.append("")
    return "\n".join(out) + "\n"


def read_signals(log_dir: Path) -> list[dict]:
    p = Path(log_dir) / "signals.csv"
    if not p.exists():
        return []
    with open(p) as f:
        return list(csv.DictReader(f))
