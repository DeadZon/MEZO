#!/usr/bin/env bash
# DeadZone Framework Patcher — legacy compatibility wrapper
#
# The three framework patches (Signature Verification Bypass, invoke-custom handling,
# fix bootloop A15) are now applied by the Lite style engine:
#   bin/scripts/style_mod_runner.py --style lite
#   Manifest: bin/styles/Lite/mods.json
#   Patch script: bin/scripts/deadzone_framework_patches.py
#
# This wrapper remains in UpdateFile/ to prevent insupdate.sh from failing
# when it discovers *.sh files. It exits 0 without running any patches.
#
# Control flags:
#   ENABLE_DEADZONE_PACKAGE_PATCHES      (default: true)  — upstream COREPATCH active
#   ENABLE_LEGACY_DEADZONE_FRAMEWORK_PATCHER (default: false) — set true to re-enable

set -euo pipefail

work_dir=$(pwd)

_pkg_patches="${ENABLE_DEADZONE_PACKAGE_PATCHES:-true}"
_legacy_fw="${ENABLE_LEGACY_DEADZONE_FRAMEWORK_PATCHER:-false}"

if [ "$_legacy_fw" != "true" ]; then
    if [ "$_pkg_patches" = "true" ]; then
        echo "[legacy-overlap] Skipping DeadZone_FrameworkPatcher because bin/package/COREPATCH is active"
    else
        echo "[DeadZone_FrameworkPatcher] Disabled — set ENABLE_LEGACY_DEADZONE_FRAMEWORK_PATCHER=true to enable"
    fi
    exit 0
fi

# Legacy path: run the old framework patcher via the Lite style runner
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../../.." && pwd)"
echo "[DeadZone_FrameworkPatcher] Running legacy path via style_mod_runner.py (Lite)..."
python3 "$PROJECT_ROOT/bin/scripts/style_mod_runner.py" \
    --style lite \
    --work-dir "$PROJECT_ROOT"
