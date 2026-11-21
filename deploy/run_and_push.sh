#!/usr/bin/env bash
# One bot run on a VPS, then (optionally) push state/logs to the bot-state branch.
# STATE_DIR should be a clone of the bot-state branch, e.g. /opt/btc-bot-state.
set -uo pipefail
cd "$(dirname "$0")/.."
./.venv/bin/python -m bot.run
status=$?
if [ "$(date -u +%u%H)" = "100" ]; then ./.venv/bin/python scripts/weekly_report.py || true; fi
if [ "${PUSH_STATE:-true}" = "true" ] && [ -d "${STATE_DIR}/.git" ]; then
  cd "$STATE_DIR"
  git add -A
  git diff --cached --quiet || git commit -q -m "bot run $(date -u +%Y-%m-%dT%H:%MZ) (vps)"
  git push -q origin bot-state || echo "push failed; will retry next run"
fi
exit $status
