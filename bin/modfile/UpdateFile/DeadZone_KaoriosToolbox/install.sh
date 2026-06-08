#!/usr/bin/env bash
# DeadZone Kaorios Toolbox — legacy compatibility wrapper
#
# Kousei / Kaorios Toolbox is now applied by the Lite style engine:
#   bin/scripts/style_mod_runner.py --style lite
#   Manifest: bin/styles/Lite/mods.json
#   Toolbox script: bin/scripts/deadzone_kaorios_toolbox.py
#
# This wrapper remains in UpdateFile/ to prevent insupdate.sh from failing
# when it discovers *.sh files. It exits 0 without running any patches.
#
# Control flags:
#   ENABLE_DEADZONE_PACKAGE_PATCHES        (default: true)  — upstream KouseiPatcher active
#   ENABLE_LEGACY_DEADZONE_KAORIOS_TOOLBOX (default: false) — set true to re-enable

set -euo pipefail

work_dir=$(pwd)

_pkg_patches="${ENABLE_DEADZONE_PACKAGE_PATCHES:-true}"
_legacy_kt="${ENABLE_LEGACY_DEADZONE_KAORIOS_TOOLBOX:-false}"

if [ "$_legacy_kt" != "true" ]; then
    if [ "$_pkg_patches" = "true" ]; then
        echo "[legacy-overlap] Skipping DeadZone_KaoriosToolbox because bin/package/KouseiPatcher is active"
    else
        echo "[DeadZone_KaoriosToolbox] Disabled — set ENABLE_LEGACY_DEADZONE_KAORIOS_TOOLBOX=true to enable"
    fi
    exit 0
fi

# Legacy path: delegate to the Lite style runner
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../.." && pwd)"
echo "[DeadZone_KaoriosToolbox] Running legacy path via style_mod_runner.py (Lite)..."
python3 "$PROJECT_ROOT/bin/scripts/style_mod_runner.py" \
    --style lite \
    --work-dir "$PROJECT_ROOT"
