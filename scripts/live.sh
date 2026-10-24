#!/usr/bin/env bash
# The whole live layer in one command, for the key owner (spends real SOL, capped at $ITB_CAP_SOL, default 0.05):
#   preflight (read-only) -> run --live (~60 min) -> collect -> analyze -> sweep (deposits back to the key) -> preflight.
# Usage: ITB_KEYPAIR=~/.config/itb/itb-keypair.json scripts/live.sh   [minutes, default 60]
set -euo pipefail
cd "$(dirname "$0")/.."
export ITB_KEYPAIR="${ITB_KEYPAIR:-$HOME/.config/itb/itb-keypair.json}"
MIN="${1:-60}"
case "$(cd "$(dirname "$ITB_KEYPAIR")" && pwd)" in "$PWD"*) echo "keypair must live outside the repo"; exit 1;; esac

uv run python -m itb preflight
# caffeinate keeps the Mac awake for the run (no-op elsewhere)
KEEP=""; command -v caffeinate >/dev/null && KEEP="caffeinate -i"
$KEEP uv run python -m itb run --live --yes-spend --minutes "$MIN" --max-windows "${ITB_MAX_WINDOWS:-350}"
sleep 60  # let the last blocks finalize
uv run python -m itb collect --skip-done
uv run python -m itb analyze
uv run python -m itb sweep --yes
sleep 20
uv run python -m itb preflight || true   # prints what is left on the key
echo "done: results in report/results.md, raw data in data/runs/"
