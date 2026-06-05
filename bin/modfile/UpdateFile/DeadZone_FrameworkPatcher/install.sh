#!/usr/bin/env bash
# DeadZone Framework Patcher — base mod installer
#
# Runs for ALL DeadZone styles (Stable, Legend, and future styles).
# Automatically discovered and executed by bin/modfile/UpdateFile/insupdate.sh.
#
# Features applied:
#   - Signature Verification Bypass
#   - invoke-custom handling
#
# Both features are base DeadZone features, not style-specific.
# Legend and future styles inherit them from this base installer.

set -euo pipefail

work_dir=$(pwd)
source "$work_dir/functions.sh"

if [ "${ENABLE_DEADZONE_FRAMEWORK_PATCHER:-false}" != "true" ]; then
    mods "[DeadZone_FrameworkPatcher] Disabled temporarily — skipping Signature Verification Bypass + invoke-custom"
    exit 0
fi

mods "DeadZone Framework Patcher — Signature Verification Bypass + invoke-custom"

python3 "$work_dir/bin/scripts/deadzone_framework_patcher.py"
PATCHER_EXIT=$?

if [ $PATCHER_EXIT -ne 0 ]; then
    error "DeadZone Framework Patcher FAILED (exit $PATCHER_EXIT)"
    error "Check output/reports/framework_patcher_error.txt for details"
    exit $PATCHER_EXIT
fi

mods "DeadZone Framework Patcher — Done"

# Write active mods report for this build
python3 "$work_dir/bin/scripts/write_active_mods_report.py" || true
