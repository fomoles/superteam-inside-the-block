#!/usr/bin/env bash
# Run 2, the confirmatory run fixed in notes/preregistration-v2.md, for the key owner (spends real SOL):
#   47-validator panel (data/panel-v2.json), probes that cap their loaded account data, its own spend ledger.
#   preflight (read-only) -> run --live (180 min) -> collect -> analyze -> checks C1-C7 -> sweep -> preflight.
# Usage: ITB_KEYPAIR=~/.config/itb/itb-keypair.json scripts/live2.sh   [minutes, default 180]
# Expected spend ≈ 0.04 SOL in fees (run 1: 0.0389 for the same 1100 windows); hard cap 0.06.
set -euo pipefail
cd "$(dirname "$0")/.."
export ITB_KEYPAIR="${ITB_KEYPAIR:-$HOME/.config/itb/itb-keypair.json}"
MIN="${1:-180}"
export ITB_CAP_SOL="${ITB_CAP_SOL:-0.06}" ITB_MAX_WINDOWS="${ITB_MAX_WINDOWS:-1100}"
export ITB_PANEL=data/panel-v2.json ITB_DATA_LIMIT=32768 ITB_LEDGER=data/spend-ledger-run2.json
case "$(cd "$(dirname "$ITB_KEYPAIR")" && pwd)" in "$PWD"*) echo "keypair must live outside the repo"; exit 1;; esac

uv run python -m itb preflight
KEEP=""; command -v caffeinate >/dev/null && KEEP="caffeinate -i"
before="$(ls data/runs)"
$KEEP uv run python -m itb run --live --yes-spend --minutes "$MIN" --max-windows "$ITB_MAX_WINDOWS"
RUN="$(comm -13 <(echo "$before") <(ls data/runs) | grep -- '-live$' | tail -1)"
sleep 60  # let the last blocks finalize
uv run python -m itb collect --skip-done
uv run python -m itb analyze
PYTHONPATH=. uv run python scripts/live_analysis.py data > data/results/live_analysis_runs1-2.txt || true
PYTHONPATH=. uv run python scripts/sort_model.py data --run "$RUN" --fig report/figures/sort_model_run2.png \
  > data/results/sort_model_run2.txt
uv run python -m itb sweep --yes
sleep 20
uv run python -m itb preflight || true   # prints what is left on the key
echo "done: run $RUN; pre-registered checks at the end of data/results/sort_model_run2.txt"
