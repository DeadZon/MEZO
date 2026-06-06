#!/usr/bin/env python3
"""Generate output/reports/active_mods_report.txt.

Records which DeadZone build-time mods are enabled or disabled based on
environment feature flags, displayed in the grouped hierarchy shown in Lite.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

WORK_DIR    = Path(__file__).parent.parent.parent
REPORTS_DIR = WORK_DIR / "bin" / "output" / "reports"

# _FLAGS kept for backward compat — maps flag_key → (env_var, default_enabled)
_FLAGS: dict[str, tuple[str, bool]] = {
    "ENABLE_SIGNATURE_VERIFICATION_BYPASS":  ("ENABLE_SIGNATURE_VERIFICATION_BYPASS",  True),
    "ENABLE_INVOKE_CUSTOM":                  ("ENABLE_INVOKE_CUSTOM",                  True),
    "ENABLE_FIX_BOOTLOOP_A15":               ("ENABLE_FIX_BOOTLOOP_A15",               True),
    "ENABLE_MIUI_SERVICES_CN_GLOBAL":        ("ENABLE_MIUI_SERVICES_CN_GLOBAL",        True),
    "ENABLE_POLICY_MANAGER_CN_MODEL":        ("ENABLE_POLICY_MANAGER_CN_MODEL",        True),
    "ENABLE_POWERKEEPER_CN_GLOBAL":          ("ENABLE_POWERKEEPER_CN_GLOBAL",          True),
    "ENABLE_POWERKEEPER_MILLETCONFIG":       ("ENABLE_POWERKEEPER_MILLETCONFIG",       True),
    "ENABLE_POWERKEEPER_GMS_CONTROL":        ("ENABLE_POWERKEEPER_GMS_CONTROL",        True),
    "ENABLE_PROVISION_MEZO_STRINGS":         ("ENABLE_PROVISION_MEZO_STRINGS",         True),
    "ENABLE_MIUISYSTEMUI_VOLTE_CN":          ("ENABLE_MIUISYSTEMUI_VOLTE_CN",          True),
    "ENABLE_DEADZONE_KAORIOS_TOOLBOX":       ("ENABLE_DEADZONE_KAORIOS_TOOLBOX",       True),
    "ENABLE_POCO_LAUNCHER_SPOOF":            ("ENABLE_POCO_LAUNCHER_SPOOF",            True),
    "ENABLE_DEADZONE_JAR_MODS":              ("ENABLE_DEADZONE_JAR_MODS",              False),
    "ENABLE_DEADZONE_MEZO_FRAMEWORK_MODS":   ("ENABLE_DEADZONE_MEZO_FRAMEWORK_MODS",   False),
    "ENABLE_MYMEZO_DERIVED_PATCHES":         ("ENABLE_MYMEZO_DERIVED_PATCHES",         False),
    "ENABLE_EXPERIMENTAL_JAR_PATCH_ENGINE":  ("ENABLE_EXPERIMENTAL_JAR_PATCH_ENGINE",  False),
}

_LABELS: dict[str, str] = {
    "ENABLE_SIGNATURE_VERIFICATION_BYPASS":  "Signature Verification Bypass",
    "ENABLE_INVOKE_CUSTOM":                  "invoke-custom handling",
    "ENABLE_FIX_BOOTLOOP_A15":               "fix bootloop A15",
    "ENABLE_MIUI_SERVICES_CN_GLOBAL":        "miui-services CN/global Build flag patches",
    "ENABLE_POLICY_MANAGER_CN_MODEL":        "miui-services PolicyManager CN_MODEL patch",
    "ENABLE_POWERKEEPER_CN_GLOBAL":          "PowerKeeper CN/global Build flag patches",
    "ENABLE_POWERKEEPER_MILLETCONFIG":       "PowerKeeper MilletConfig patch",
    "ENABLE_POWERKEEPER_GMS_CONTROL":        "PowerKeeper isGmsControlEnabled patch",
    "ENABLE_PROVISION_MEZO_STRINGS":         "Provision MEZO strings",
    "ENABLE_MIUISYSTEMUI_VOLTE_CN":          "Hide 4G Icon And Show VoLTE On Statusbar OS2/3 CN",
    "ENABLE_DEADZONE_KAORIOS_TOOLBOX":       "Kousei / Kaorios Toolbox",
    "ENABLE_POCO_LAUNCHER_SPOOF":            "POCO Launcher To MiuiHome Spoofing",
    "ENABLE_DEADZONE_JAR_MODS":              "DeadZone_JarMods",
    "ENABLE_DEADZONE_MEZO_FRAMEWORK_MODS":   "DeadZone_MEZOFramework",
    "ENABLE_MYMEZO_DERIVED_PATCHES":         "MyMezo-derived patches",
    "ENABLE_EXPERIMENTAL_JAR_PATCH_ENGINE":  "experimental JAR patch engine",
}


def _is_enabled(flag: str, default: bool) -> bool:
    val = os.environ.get(flag, "")
    return default if val == "" else val.lower() == "true"


def _on(flag_key: str) -> str:
    env_var, default = _FLAGS[flag_key]
    return "ON" if _is_enabled(env_var, default) else "OFF"


def write_report() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    dz_style = os.environ.get("DZ_STYLE", "Plus")

    # Grouped hierarchy section
    lines = [
        "DeadZone Active Mods Report",
        "=" * 40,
        f"Generated : {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        f"DZ_STYLE  : {dz_style}",
        "",
        f"DeadZone Framework/JAR Patches: {_on('ENABLE_SIGNATURE_VERIFICATION_BYPASS')}",
        f"  * Signature Verification Bypass: {_on('ENABLE_SIGNATURE_VERIFICATION_BYPASS')}",
        f"  * invoke-custom handling: {_on('ENABLE_INVOKE_CUSTOM')}",
        f"  * fix bootloop A15: {_on('ENABLE_FIX_BOOTLOOP_A15')}",
        f"  * miui-services CN/global Build flag patches: {_on('ENABLE_MIUI_SERVICES_CN_GLOBAL')}",
        f"  * miui-services PolicyManager CN_MODEL patch: {_on('ENABLE_POLICY_MANAGER_CN_MODEL')}",
        "",
        f"Lite APK/App Patches: {_on('ENABLE_PROVISION_MEZO_STRINGS')}",
        f"  * PowerKeeper CN/global Build flag patches: {_on('ENABLE_POWERKEEPER_CN_GLOBAL')}",
        f"  * PowerKeeper MilletConfig patch: {_on('ENABLE_POWERKEEPER_MILLETCONFIG')}",
        f"  * PowerKeeper isGmsControlEnabled patch: {_on('ENABLE_POWERKEEPER_GMS_CONTROL')}",
        f"  * Provision MEZO strings: {_on('ENABLE_PROVISION_MEZO_STRINGS')}",
        f"  * Hide 4G Icon And Show VoLTE On Statusbar OS2/3 CN: {_on('ENABLE_MIUISYSTEMUI_VOLTE_CN')}",
        "",
        f"Kousei / Kaorios Toolbox: {_on('ENABLE_DEADZONE_KAORIOS_TOOLBOX')}",
        f"POCO Launcher To MiuiHome Spoofing: {_on('ENABLE_POCO_LAUNCHER_SPOOF')}",
        "",
    ]

    # Flat [ON]/[OFF] list for backward compat
    enabled:  list[str] = []
    disabled: list[str] = []
    for flag_key, (env_var, default) in _FLAGS.items():
        label = _LABELS[flag_key]
        if _is_enabled(env_var, default):
            enabled.append(label)
        else:
            disabled.append(label)

    lines += [f"Enabled ({len(enabled)}):"]
    for m in enabled:
        lines.append(f"  [ON]  {m}")
    lines += ["", f"Temporarily disabled ({len(disabled)}):"]
    for m in disabled:
        lines.append(f"  [OFF] {m}")

    lines += [
        "",
        "Notes:",
        "  - Framework/JAR and APK patches are ON by default — run by the Lite style engine.",
        "  - JAR mods and experimental mods remain opt-in via env flags.",
        "  - OS1/OS2/OS3/Universal/UpdateFile mods are routed through the Lite style engine.",
        f"  - Lite mod runner report: {REPORTS_DIR / 'lite_mod_report.json'}",
    ]

    out = REPORTS_DIR / "active_mods_report.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[ACTIVE_MODS] Report written -> {out}")


if __name__ == "__main__":
    write_report()
    sys.exit(0)
