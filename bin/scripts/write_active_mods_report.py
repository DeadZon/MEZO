#!/usr/bin/env python3
"""Generate output/reports/active_mods_report.txt.

Records which DeadZone build-time mods are enabled or temporarily disabled
based on environment feature flags.
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

WORK_DIR    = Path(__file__).parent.parent.parent
REPORTS_DIR = WORK_DIR / "output" / "reports"

# Feature flag defaults — all new framework/JAR/Kaorios mods temporarily disabled
_FLAGS: dict[str, tuple[str, bool]] = {
    # (env_var, default_enabled)
    "ENABLE_DEADZONE_FRAMEWORK_PATCHER":    ("ENABLE_DEADZONE_FRAMEWORK_PATCHER",    False),
    "ENABLE_SIGNATURE_VERIFICATION_BYPASS": ("ENABLE_SIGNATURE_VERIFICATION_BYPASS", False),
    "ENABLE_INVOKE_CUSTOM":                 ("ENABLE_INVOKE_CUSTOM",                 False),
    "ENABLE_DEADZONE_KAORIOS_TOOLBOX":      ("ENABLE_DEADZONE_KAORIOS_TOOLBOX",      False),
    "ENABLE_DEADZONE_JAR_MODS":             ("ENABLE_DEADZONE_JAR_MODS",             False),
    "ENABLE_DEADZONE_MEZO_FRAMEWORK_MODS":  ("ENABLE_DEADZONE_MEZO_FRAMEWORK_MODS",  False),
    "ENABLE_MYMEZO_DERIVED_PATCHES":        ("ENABLE_MYMEZO_DERIVED_PATCHES",        False),
    "ENABLE_EXPERIMENTAL_JAR_PATCH_ENGINE": ("ENABLE_EXPERIMENTAL_JAR_PATCH_ENGINE", False),
}

# Human-readable labels for each flag
_LABELS: dict[str, str] = {
    "ENABLE_DEADZONE_FRAMEWORK_PATCHER":    "DeadZone_FrameworkPatcher",
    "ENABLE_SIGNATURE_VERIFICATION_BYPASS": "Signature Verification Bypass",
    "ENABLE_INVOKE_CUSTOM":                 "invoke-custom handling",
    "ENABLE_DEADZONE_KAORIOS_TOOLBOX":      "DeadZone_KaoriosToolbox",
    "ENABLE_DEADZONE_JAR_MODS":             "DeadZone_JarMods",
    "ENABLE_DEADZONE_MEZO_FRAMEWORK_MODS":  "DeadZone_MEZOFramework",
    "ENABLE_MYMEZO_DERIVED_PATCHES":        "MyMezo-derived patches",
    "ENABLE_EXPERIMENTAL_JAR_PATCH_ENGINE": "experimental JAR patch engine",
}


def _is_enabled(flag: str, default: bool) -> bool:
    val = os.environ.get(flag, "")
    if val == "":
        return default
    return val.lower() == "true"


def write_report() -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    enabled:  list[str] = []
    disabled: list[str] = []

    for flag, (env_var, default) in _FLAGS.items():
        label = _LABELS[flag]
        if _is_enabled(env_var, default):
            enabled.append(label)
        else:
            disabled.append(label)

    dz_style = os.environ.get("DZ_STYLE", "Stable")

    lines = [
        "DeadZone Active Mods Report",
        "=" * 40,
        f"Generated : {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        f"DZ_STYLE  : {dz_style}",
        "",
        f"Enabled ({len(enabled)}):",
    ]
    for m in enabled:
        lines.append(f"  [ON]  {m}")

    lines += ["", f"Temporarily disabled ({len(disabled)}):"]
    for m in disabled:
        lines.append(f"  [OFF] {m}")

    lines += [
        "",
        "Notes:",
        "  - All new framework/JAR/Kaorios mods are temporarily disabled (default=false).",
        "  - No Python patchers, JAR decode/rebuild, or APK/XML installs will run.",
        "  - To re-enable a mod set its flag to true, e.g. ENABLE_DEADZONE_FRAMEWORK_PATCHER=true.",
        "  - Old normal mods (OS1/OS2/OS3, Universal, existing UpdateFile mods) are unaffected.",
    ]

    out = REPORTS_DIR / "active_mods_report.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[ACTIVE_MODS] Report written -> {out}")


if __name__ == "__main__":
    write_report()
    sys.exit(0)
