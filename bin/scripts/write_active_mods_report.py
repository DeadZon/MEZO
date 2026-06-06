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
REPORTS_DIR = WORK_DIR / "bin" / "output" / "reports"

# Feature flags — Lite-based mods (sig bypass, invoke-custom, bootloop, Kaorios) are ON by default.
# JAR mods and experimental mods remain opt-in.
_FLAGS: dict[str, tuple[str, bool]] = {
    # (env_var, default_enabled)
    "ENABLE_SIGNATURE_VERIFICATION_BYPASS": ("ENABLE_SIGNATURE_VERIFICATION_BYPASS", True),
    "ENABLE_INVOKE_CUSTOM":                 ("ENABLE_INVOKE_CUSTOM",                 True),
    "ENABLE_FIX_BOOTLOOP_A15":              ("ENABLE_FIX_BOOTLOOP_A15",              True),
    "ENABLE_DEADZONE_KAORIOS_TOOLBOX":      ("ENABLE_DEADZONE_KAORIOS_TOOLBOX",      True),
    "ENABLE_POCO_LAUNCHER_SPOOF":           ("ENABLE_POCO_LAUNCHER_SPOOF",           True),
    "ENABLE_DEADZONE_JAR_MODS":             ("ENABLE_DEADZONE_JAR_MODS",             False),
    "ENABLE_DEADZONE_MEZO_FRAMEWORK_MODS":  ("ENABLE_DEADZONE_MEZO_FRAMEWORK_MODS",  False),
    "ENABLE_MYMEZO_DERIVED_PATCHES":        ("ENABLE_MYMEZO_DERIVED_PATCHES",        False),
    "ENABLE_EXPERIMENTAL_JAR_PATCH_ENGINE": ("ENABLE_EXPERIMENTAL_JAR_PATCH_ENGINE", False),
}

# Human-readable labels for each flag
_LABELS: dict[str, str] = {
    "ENABLE_SIGNATURE_VERIFICATION_BYPASS": "Signature Verification Bypass",
    "ENABLE_INVOKE_CUSTOM":                 "invoke-custom handling",
    "ENABLE_FIX_BOOTLOOP_A15":              "fix bootloop A15",
    "ENABLE_DEADZONE_KAORIOS_TOOLBOX":      "Kousei / Kaorios Toolbox",
    "ENABLE_POCO_LAUNCHER_SPOOF":           "POCO Launcher To MiuiHome Spoofing",
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

    lite_report = WORK_DIR / "bin" / "output" / "reports" / "lite_mod_report.json"
    lines += [
        "",
        "Notes:",
        "  - Signature Verification Bypass, invoke-custom, fix bootloop A15, and Kaorios",
        "    Toolbox are ON by default — run by the Lite style engine (style_mod_runner.py).",
        "  - JAR mods and experimental mods remain opt-in via env flags.",
        "  - OS1/OS2/OS3/Universal/UpdateFile mods are routed through the Lite style engine.",
        f"  - Lite mod runner report: {lite_report}",
    ]

    out = REPORTS_DIR / "active_mods_report.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[ACTIVE_MODS] Report written -> {out}")


if __name__ == "__main__":
    write_report()
    sys.exit(0)
