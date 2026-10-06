#!/bin/bash
# Runner script for schedule reconciliation job
set -e

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON_BIN="/Users/michaelcadelago/antigravity-skills/universal/google_workspace/.venv/bin/python"

if [ ! -f "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

"$PYTHON_BIN" "$DIR/reconcile_schedule.py" "$@"
