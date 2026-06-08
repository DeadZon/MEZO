#!/usr/bin/env bash
# DeadZone MEZO — upstream package patch orchestrator.
# All bin/package modules are active by default (ENABLE_DEADZONE_PACKAGE_PATCHES=true).
#
# Path detection uses BASH_SOURCE so this script is safe regardless of cwd.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_DIR="$SCRIPT_DIR"

# work_dir: prefer WORK_DIR env (set by build.sh), fall back to cwd
work_dir="${WORK_DIR:-$(pwd)}"
source "$work_dir/functions.sh"

echo "[package] Package dir: $PACKAGE_DIR"
echo "[package] ENABLE_DEADZONE_PACKAGE_PATCHES=${ENABLE_DEADZONE_PACKAGE_PATCHES:-true}"
echo "[package] Using upstream bin/package as authoritative package patch system"

mods "Add Package..."

# ── Discover and run each module ─────────────────────────────────────────────

# COREPATCH — always present (required)
if [ -d "$PACKAGE_DIR/COREPATCH" ]; then
    echo "[package] COREPATCH: found"
    bash "$PACKAGE_DIR/COREPATCH/update.sh"
else
    echo "[package] COREPATCH: missing — skipped"
fi

# DISABLE_AVB — always present (required)
if [ -f "$PACKAGE_DIR/DISABLE_AVB/DISABLEavb.sh" ]; then
    echo "[package] DISABLE_AVB: found"
    bash "$PACKAGE_DIR/DISABLE_AVB/DISABLEavb.sh"
else
    echo "[package] DISABLE_AVB: missing — skipped"
fi

# KouseiPatcher
if [ -f "$PACKAGE_DIR/KouseiPatcher/update.sh" ]; then
    echo "[package] KouseiPatcher: found"
    bash "$PACKAGE_DIR/KouseiPatcher/update.sh"
else
    echo "[package] KouseiPatcher: missing — skipped"
fi

# NOTIFICATION_FIX
if [ -f "$PACKAGE_DIR/NOTIFICATION_FIX/notificationFIX.sh" ]; then
    echo "[package] NOTIFICATION_FIX: found"
    bash "$PACKAGE_DIR/NOTIFICATION_FIX/notificationFIX.sh"
else
    echo "[package] NOTIFICATION_FIX: missing — skipped"
fi

# RefreshRate
if [ -f "$PACKAGE_DIR/RefreshRate/1hz.sh" ]; then
    echo "[package] RefreshRate: found"
    bash "$PACKAGE_DIR/RefreshRate/1hz.sh"
else
    echo "[package] RefreshRate: missing — skipped"
fi

mods "Add Package Done"

# ── Package system report ─────────────────────────────────────────────────────
_REPORTS_DIR="$work_dir/bin/output/reports"
mkdir -p "$_REPORTS_DIR"

_mod_status() { [ -d "$PACKAGE_DIR/$1" ] && echo "found/active" || echo "missing"; }
_file_status() { [ -f "$PACKAGE_DIR/$1" ] && echo "found/active" || echo "missing"; }

cat > "$_REPORTS_DIR/package_system_report.txt" << REPORT
DeadZone MEZO — Package System Report
======================================
Generated   : $(date -u '+%Y-%m-%dT%H:%M:%SZ')
Work dir    : $work_dir
Package dir : $PACKAGE_DIR

ENABLE_DEADZONE_PACKAGE_PATCHES=${ENABLE_DEADZONE_PACKAGE_PATCHES:-true}

Authoritative system:
  bin/package/patchpackage.sh

Detected upstream modules:
  COREPATCH        : $(_mod_status COREPATCH)
  KouseiPatcher    : $(_mod_status KouseiPatcher)
  NOTIFICATION_FIX : $(_file_status NOTIFICATION_FIX/notificationFIX.sh)
  DISABLE_AVB      : $(_mod_status DISABLE_AVB)
  RefreshRate      : $(_file_status RefreshRate/1hz.sh)

Legacy overlaps (disabled by default when ENABLE_DEADZONE_PACKAGE_PATCHES=true):
  DeadZone_FrameworkPatcher : skipped by default (ENABLE_LEGACY_DEADZONE_FRAMEWORK_PATCHER=false)
  DeadZone_JarMods          : skipped by default (ENABLE_LEGACY_DEADZONE_JARMODS=false)
  DeadZone_KaoriosToolbox   : skipped by default (ENABLE_LEGACY_DEADZONE_KAORIOS_TOOLBOX=false)
  old signature bypass      : skipped by default (covered by ENABLE_LEGACY_DEADZONE_FRAMEWORK_PATCHER)

Re-enable instructions:
  To use legacy modules instead of upstream package patches, set:
    ENABLE_DEADZONE_PACKAGE_PATCHES=false
    ENABLE_LEGACY_DEADZONE_JARMODS=true           # re-enable JAR mod engine
    ENABLE_LEGACY_DEADZONE_FRAMEWORK_PATCHER=true # re-enable old framework patcher
    ENABLE_LEGACY_DEADZONE_KAORIOS_TOOLBOX=true   # re-enable old Kaorios wrapper
REPORT

echo "[package] Report written → $_REPORTS_DIR/package_system_report.txt"
