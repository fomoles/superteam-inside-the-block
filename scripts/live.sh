#!/usr/bin/env bash
# The whole live layer in one command, for the key owner (spends real SOL, capped at $ITB_CAP_SOL, default 0.08):
#   preflight (read-only) -> run --live (180 min by default) -> collect -> analyze -> sweep (deposits back to the key) -> preflight.
# Usage: ITB_KEYPAIR=~/.config/itb/itb-keypair.json scripts/live.sh   [minutes, default 180]
# A 10-minute pilot first is cheap (~80 windows, <= 0.004 SOL): scripts/live.sh 10
set -euo pipefail
cd "$(dirname "$0")/.."
export ITB_KEYPAIR="${ITB_KEYPAIR:-$HOME/.config/itb/itb-keypair.json}"
MIN="${1:-180}"
export ITB_CAP_SOL="${ITB_CAP_SOL:-0.08}" ITB_MAX_WINDOWS="${ITB_MAX_WINDOWS:-1100}"
case "$(cd "$(dirname "$ITB_KEYPAIR")" && pwd)" in "$PWD"*) echo "keypair must live outside the repo"; exit 1;; esac

uv run python -m itb preflight
# caffeinate keeps the Mac awake for the run (no-op elsewhere)
KEEP=""; command -v caffeinate >/dev/null && KEEP="caffeinate -i"
$KEEP uv run python -m itb run --live --yes-spend --minutes "$MIN" --max-windows "$ITB_MAX_WINDOWS"
sleep 60  # let the last blocks finalize
uv run python -m itb collect --skip-done
uv run python -m itb analyze
uv run python -m itb sweep --yes
sleep 20
uv run python -m itb preflight || true   # prints what is left on the key
echo "done: results in report/results.md, raw data in data/runs/"
