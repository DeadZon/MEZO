#!/usr/bin/env bash
# DeadZone MEZO JAR Mods — legacy unified installer
#
# Runs for ALL DeadZone styles (Stable, Legend, and future styles).
# Automatically discovered and executed by bin/modfile/UpdateFile/insupdate.sh.
#
# Applies all MEZO JAR mods through the unified JAR patch engine:
#   - framework.jar    (Build, Activity, ApplicationPackageManager, PackagePartitions)
#   - services.jar     (AccountManager, AMS, BroadcastController, PermissionMgr,
#                       StatusBar, DisplayRotation, PhoneWindowMgr, AppsFilter)
#   - telephony-common (NotificationChannelController)
#   - mediatek-telephony-common (Bluetooth/WifiManagerCompatible)
#   - miui-framework   (remove DRM classes, add EU translation utilities)
#   - miui-services    (remove WMServiceConnection)
#   - miui-wifi-service (MiuiWifiService country code observer)
#
# Control flags:
#   ENABLE_DEADZONE_PACKAGE_PATCHES  (default: true)  — upstream COREPATCH active
#   ENABLE_LEGACY_DEADZONE_JARMODS   (default: false) — set true to re-enable

set -euo pipefail

work_dir=$(pwd)
source "$work_dir/functions.sh"

_pkg_patches="${ENABLE_DEADZONE_PACKAGE_PATCHES:-true}"
_legacy_jar="${ENABLE_LEGACY_DEADZONE_JARMODS:-false}"

if [ "$_legacy_jar" != "true" ]; then
    if [ "$_pkg_patches" = "true" ]; then
        echo "[legacy-overlap] Skipping DeadZone_JarMods because bin/package/COREPATCH is active"
    else
        mods "[DeadZone_JarMods] Disabled — set ENABLE_LEGACY_DEADZONE_JARMODS=true to enable"
    fi
    exit 0
fi

mods "DeadZone MEZO JAR Mods — running unified JAR patch engine"

python3 "$work_dir/bin/scripts/deadzone_jar_patch_engine.py"
ENGINE_EXIT=$?

if [ $ENGINE_EXIT -ne 0 ]; then
    error "DeadZone MEZO JAR Mods FAILED (exit $ENGINE_EXIT)"
    error "Check output/reports/jar_patches/deadzone_mezo_jar_mods_error.txt for details"
    exit $ENGINE_EXIT
fi

mods "DeadZone MEZO JAR Mods — Done"
