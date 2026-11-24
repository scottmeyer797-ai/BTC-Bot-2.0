"""Build the dashboard's data file from the bot's state and logs.

    STATE_DIR=path/to/bot-state python scripts/export_dashboard.py [--out <dir>] [--preview]

Writes <out>/data.json (default: $STATE_DIR/docs) and copies dashboard/index.html next to it, so the folder
is a complete static site (GitHub Pages can serve the bot-state branch's /docs folder).
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import DAILY_LOSS_LIMIT, DEMO_BASE_URL, MAX_DRAWDOWN_LIMIT, load_config  # noqa: E402
from bot.state import load_state, ms_to_iso, utcnow_iso  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OPEN_FIELDS = ["id", "symbol", "inst_id", "side", "status", "protocol", "entry_ts", "entry_bar_close_ts", "entry_price",
               "ref_price", "level", "atr", "stop0", "stop", "target", "r_unit", "target_r", "contracts",
               "init_contracts", "contract_value", "risk_amount", "risk_pct", "leverage", "bars_held", "max_bars",
               "entry_fee", "partials", "be_done", "trail_on", "best", "realized_added", "gross_closed", "exit_fees",
               "vol_z", "vol_rank", "btc_trend", "volume_source", "mode"]
CLOSED_EXTRA = ["exit_ts", "exit_price", "exit_reason", "gross_pnl", "fees", "funding", "net_pnl", "r_multiple",
                "exit_estimated", "close_fills"]


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def pick(t: dict, fields: list[str]) -> dict:
    out = {k: t.get(k) for k in fields if k in t}
    for k in ("entry_ts", "exit_ts", "entry_bar_close_ts"):
        if out.get(k):
            out[k + "_iso"] = ms_to_iso(out[k])
    return out


def build(cfg, preview: bool = False) -> dict:
    st = load_state(cfg.state_path, cfg.mode.name, cfg.account_size)
    hist = [h for h in st.get("equity_history", []) if not h.get("dry_run")]
    closed = sorted(st.get("closed_trades", []), key=lambda t: t.get("exit_ts", 0))
    rs = [t.get("r_multiple", 0.0) for t in closed]
    wins = [r for r in rs if r > 0]
    peak, max_dd = cfg.account_size, 0.0
    for h in hist:
        peak = max(peak, h["equity"])
        max_dd = max(max_dd, (peak - h["equity"]) / peak)
    last = hist[-1] if hist else None
    return {
        "generated_at": utcnow_iso(),
        "preview": preview,
        "exchange": {"name": "BloFin demo", "rest": DEMO_BASE_URL},
        "bot": {
            "mode": st.get("mode", cfg.mode.name), "account_size": cfg.account_size,
            "risk_pct": cfg.mode.risk_pct, "target_r": cfg.mode.target_r, "max_open_risk": cfg.mode.max_open_risk,
            "exit_protocol": cfg.exit_protocol.name, "exit_description": cfg.exit_protocol.description,
            "long_only": cfg.long_only, "volume_source": cfg.volume_source, "enabled": not cfg.kill_switch,
            "daily_loss_limit": DAILY_LOSS_LIMIT, "max_drawdown_limit": MAX_DRAWDOWN_LIMIT,
            "daily_block": cfg.mode.daily_block, "drawdown_block": cfg.mode.drawdown_block,
            "failed": st.get("failed", False), "failed_reason": st.get("failed_reason"),
            "failed_at": st.get("failed_at"), "consecutive_losses": st.get("consecutive_losses", 0),
        },
        "summary": {
            "last_run": last["time"] if last else None, "last_bar_close": last["bar_close"] if last else None,
            "equity": last["equity"] if last else cfg.account_size,
            "realized_pnl": st.get("realized_pnl", 0.0),
            "day_start_equity": st.get("day_start_equity", {}),
            "closed_trades": len(closed), "open_trades": len(st.get("open_trades", [])),
            "win_rate": len(wins) / len(rs) if rs else None, "avg_r": sum(rs) / len(rs) if rs else None,
            "total_r": sum(rs), "best_r": max(rs) if rs else None, "worst_r": min(rs) if rs else None,
            "max_drawdown": max_dd,
        },
        "equity": [{"t": h["time"], "equity": h["equity"], "realized": h["realized"], "unrealized": h["unrealized"],
                    "open": h.get("open_trades", 0)} for h in hist],
        "open_trades": [pick(t, OPEN_FIELDS) for t in st.get("open_trades", [])],
        "closed_trades": [pick(t, OPEN_FIELDS + CLOSED_EXTRA) for t in closed],
        "unmanaged_positions": st.get("unmanaged_positions", []),
        "signals": read_csv(cfg.log_dir / "signals.csv"),
        "events": read_csv(cfg.log_dir / "trades.csv"),
        "selftest": (cfg.state_dir / "selftest" / "last.md").read_text()
        if (cfg.state_dir / "selftest" / "last.md").exists() else None,
    }


def main(argv=None) -> Path:
    p = argparse.ArgumentParser()
    p.add_argument("--out", help="output folder (default: $STATE_DIR/docs)")
    p.add_argument("--preview", action="store_true", help="mark the data as a preview (shows a banner)")
    a = p.parse_args(argv)
    cfg = load_config()
    out = Path(a.out) if a.out else cfg.state_dir / "docs"
    out.mkdir(parents=True, exist_ok=True)
    (out / "data.json").write_text(json.dumps(build(cfg, a.preview), indent=1, default=str))
    shutil.copy(ROOT / "dashboard" / "index.html", out / "index.html")
    (out / ".nojekyll").write_text("")
    print(f"dashboard written to {out}")
    return out


if __name__ == "__main__":
    main()
