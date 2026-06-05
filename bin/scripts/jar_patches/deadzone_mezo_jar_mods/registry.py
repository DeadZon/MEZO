#!/usr/bin/env python3
"""Mod registry for DeadZone MEZO JAR mods.

Each mod is a dict with keys:
  jar       - logical JAR name (must match engine JAR_CANDIDATES key)
  name      - short human-readable mod name
  core      - bool; if True, a complete failure raises an error in the engine
  fn        - Callable[[workspace_dir: Path, results: list], None]
              appends a ModResult to results

All mods are registered via register(). The engine calls get_mods_for_jar()
to retrieve the ordered list for each JAR.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from . import (
    framework_patch,
    services_patch,
    miui_framework_patch,
    miui_services_patch,
    telephony_patch,
    mediatek_telephony_patch,
    miui_wifi_patch,
)


_REGISTRY: list[dict] = []


def _reg(jar: str, name: str, fn: Callable, core: bool = False) -> None:
    _REGISTRY.append({"jar": jar, "name": name, "fn": fn, "core": core})


# ── framework.jar ─────────────────────────────────────────────────────────────
_reg("framework", "Build.isBuildConsistent -> always true",
     framework_patch.patch_build_is_consistent, core=False)
_reg("framework", "Activity.setDisablePreviewScreenshots -> whitelist",
     framework_patch.patch_activity_preview_screenshots, core=False)
_reg("framework", "ApplicationPackageManager.getDefaultIcon -> IconCustomizer",
     framework_patch.patch_apm_get_default_icon, core=False)
_reg("framework", "PackagePartitions fingerprints -> add eu.version.code_time",
     framework_patch.patch_package_partitions_fingerprints, core=False)

# ── services.jar ──────────────────────────────────────────────────────────────
_reg("services", "AccountManagerService.checkPackageSignature -> isTrustedAccountSignature",
     services_patch.patch_account_manager_signature, core=False)
_reg("services", "ActivityManagerService -> remove syncFontForWebView calls",
     services_patch.patch_ams_remove_sync_font, core=False)
_reg("services", "BroadcastController -> guard DEBUG_BROADCAST log",
     services_patch.patch_broadcast_controller_debug, core=False)
_reg("services", "PermissionManagerServiceImpl -> isSignedWithPlatformKey gate",
     services_patch.patch_permission_mgr_platform_key, core=False)
_reg("services", "StatusBarManagerService.reboot -> int mode support",
     services_patch.patch_statusbar_reboot_mode, core=False)
_reg("services", "DisplayRotation$SettingsObserver -> allow_all_rotations",
     services_patch.patch_display_rotation_all_rotations, core=False)
_reg("services", "PhoneWindowManagerStub -> isEnableCombinationPowerVolumeUpGlobalActions",
     services_patch.patch_phone_window_mgr_stub, core=False)
_reg("services", "AppsFilterImpl.canQueryPackage -> compareSignatures",
     services_patch.patch_apps_filter_signatures, core=False)

# ── telephony-common.jar ──────────────────────────────────────────────────────
_reg("telephony-common", "NotificationChannelController -> setBlockable(true)",
     telephony_patch.patch_notification_channel_blockable, core=False)

# ── mediatek-telephony-common.jar ────────────────────────────────────────────
_reg("mediatek-telephony-common", "BluetoothAdapterCompatible.isNeeded -> ro.boot.hwc check",
     mediatek_telephony_patch.patch_bluetooth_is_needed, core=False)
_reg("mediatek-telephony-common", "WifiManagerCompatible.isNeeded -> ro.boot.hwc check",
     mediatek_telephony_patch.patch_wifi_is_needed, core=False)

# ── miui-framework.jar ───────────────────────────────────────────────────────
_reg("miui-framework", "Remove miui/drm/DrmBroadcast",
     miui_framework_patch.remove_drm_broadcast, core=False)
_reg("miui-framework", "Remove miui/drm/ThemeReceiver",
     miui_framework_patch.remove_theme_receiver, core=False)
_reg("miui-framework", "Remove miui/drm/ThemeReceiver$ValidateThemeTask",
     miui_framework_patch.remove_theme_receiver_validate_task, core=False)
_reg("miui-framework", "Remove miui/util/font/SymlinkUtils",
     miui_framework_patch.remove_symlink_utils, core=False)
_reg("miui-framework", "Add eu/xiaomi/util/* classes",
     miui_framework_patch.add_eu_xiaomi_util_classes, core=False)

# ── miui-services.jar ────────────────────────────────────────────────────────
_reg("miui-services", "Remove com/miui/server/WMServiceConnection",
     miui_services_patch.remove_wm_service_connection, core=False)

# ── miui-wifi-service.jar ────────────────────────────────────────────────────
_reg("miui-wifi", "MiuiWifiService -> registerCountryCodeChangedObserver",
     miui_wifi_patch.patch_register_country_code_observer, core=False)
_reg("miui-wifi", "Add MiuiWifiService$7 class",
     miui_wifi_patch.add_miui_wifi_service_7, core=False)


def get_mods_for_jar(jar_name: str) -> list[dict]:
    return [m for m in _REGISTRY if m["jar"] == jar_name]


def get_all_jar_names() -> list[str]:
    seen: list[str] = []
    for m in _REGISTRY:
        if m["jar"] not in seen:
            seen.append(m["jar"])
    return seen
