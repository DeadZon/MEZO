#!/usr/bin/env bash
# DeadZone Kaorios Toolbox — base mod installer
#
# Runs for ALL DeadZone styles (Stable, Legend, and future styles).
# Automatically discovered and executed by bin/modfile/UpdateFile/insupdate.sh.
#
# Features applied:
#   - Kaorios Toolbox APK install (system_ext/priv-app)
#   - privapp whitelist XML install
#   - build.prop property injection
#   - Kaorios classes.dex injection into framework.jar
#   - V2.0.3+ smali hooks: Instrumentation, ApplicationPackageManager,
#     AndroidKeyStoreKeyPairGeneratorSpi, AndroidKeyStoreSpi, SystemServer
#
# This is a base DeadZone feature, not style-specific.
# Legend and future styles inherit it from this base installer.

set -euo pipefail

work_dir=$(pwd)
source "$work_dir/functions.sh"

mods "DeadZone Kaorios Toolbox — Integrating V2.0.4 as base feature"

python3 "$work_dir/bin/scripts/deadzone_kaorios_toolbox.py"
KAORIOS_EXIT=$?

if [ $KAORIOS_EXIT -ne 0 ]; then
    error "DeadZone Kaorios Toolbox FAILED (exit $KAORIOS_EXIT)"
    error "Check output/reports/kaorios_error_report.txt for details"
    exit $KAORIOS_EXIT
fi

mods "DeadZone Kaorios Toolbox — Done"
