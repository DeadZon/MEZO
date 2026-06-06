#!/usr/bin/env bash
# DeadZone Kaorios Toolbox — compatibility wrapper (DISABLED)
#
# Kousei / Kaorios Toolbox is now applied by the Lite style engine:
#   bin/scripts/style_mod_runner.py --style lite
#   Manifest: bin/styles/Lite/mods.json
#   Toolbox script: bin/scripts/deadzone_kaorios_toolbox.py
#
# This wrapper remains in UpdateFile/ to prevent insupdate.sh from failing
# when it discovers *.sh files. It exits 0 without running any patches.
# The env-flag gate (ENABLE_DEADZONE_KAORIOS_TOOLBOX) prevents duplicate
# execution if this file is ever re-enabled.

set -euo pipefail

work_dir=$(pwd)

if [ "${ENABLE_DEADZONE_KAORIOS_TOOLBOX:-false}" != "true" ]; then
    echo "[DeadZone_KaoriosToolbox] Handled by Lite style engine — skipping compatibility wrapper."
    exit 0
fi

# If the flag is explicitly set to true (unusual), delegate to the new runner.
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../.." && pwd)"
echo "[DeadZone_KaoriosToolbox] Delegating to style_mod_runner.py (Lite)..."
python3 "$PROJECT_ROOT/bin/scripts/style_mod_runner.py" \
    --style lite \
    --work-dir "$PROJECT_ROOT"
