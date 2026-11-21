"""Build reports/weekly.md from the state file and logs.

    STATE_DIR=path/to/bot-state python scripts/weekly_report.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.config import load_config  # noqa: E402
from bot.report import build_report, read_signals  # noqa: E402


def main() -> Path:
    cfg = load_config()
    if not cfg.state_path.exists():
        raise SystemExit(f"no state file at {cfg.state_path}")
    state = json.loads(cfg.state_path.read_text())
    md = build_report(state, read_signals(cfg.log_dir))
    cfg.report_dir.mkdir(parents=True, exist_ok=True)
    out = cfg.report_dir / "weekly.md"
    out.write_text(md)
    print(f"wrote {out}")
    return out


if __name__ == "__main__":
    main()
