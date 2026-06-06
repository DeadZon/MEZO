#!/usr/bin/env bash
# DeadZone Lite — base mod style
# Runs ALL automatic ROM mods via the Lite mod runner (style_mod_runner.py).
# Stable/Legend/Ninja inherit this script through their own insmod.sh.
set -euo pipefail

work_dir=${work_dir:-$(pwd)}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
RUNNER_PY="$PROJECT_ROOT/bin/scripts/style_mod_runner.py"

echo "[STYLE] Lite: running DeadZone Lite mod runner..."

if ! python3 "$RUNNER_PY" --style lite --work-dir "$PROJECT_ROOT"; then
    echo "[STYLE][ERROR] style_mod_runner.py exited with error — aborting Lite." >&2
    exit 1
fi

echo "[STYLE] Lite mods complete."
