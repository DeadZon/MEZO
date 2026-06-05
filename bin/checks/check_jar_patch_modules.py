#!/usr/bin/env python3
"""Check: jar_patches module structure and assets."""
import sys
from pathlib import Path

ROOT    = Path(__file__).parent.parent.parent
SCRIPTS = ROOT / "bin" / "scripts"
JAR_PATCHES = SCRIPTS / "jar_patches"
CHECKS_FAILED: list[str] = []


def fail(msg: str) -> None:
    CHECKS_FAILED.append(msg)
    print(f"  FAIL: {msg}")


def ok(msg: str) -> None:
    print(f"  OK  : {msg}")


print("=== check_jar_patch_modules ===")

# 1. Module directories exist
for d in [
    "jar_patches",
    "jar_patches/common",
    "jar_patches/deadzone_mezo_jar_mods",
    "jar_patches/assets/miui_framework/eu/xiaomi/util",
    "jar_patches/assets/miui_wifi/com/android/server/wifi",
]:
    p = SCRIPTS / d
    if p.is_dir():
        ok(f"dir exists: {d}")
    else:
        fail(f"dir missing: {d}")

# 2. Core files exist
REQUIRED_FILES = [
    "jar_patches/__init__.py",
    "jar_patches/common/__init__.py",
    "jar_patches/common/smali_utils.py",
    "jar_patches/common/jar_workspace.py",
    "jar_patches/common/report_utils.py",
    "jar_patches/deadzone_mezo_jar_mods/__init__.py",
    "jar_patches/deadzone_mezo_jar_mods/registry.py",
    "jar_patches/deadzone_mezo_jar_mods/framework_patch.py",
    "jar_patches/deadzone_mezo_jar_mods/services_patch.py",
    "jar_patches/deadzone_mezo_jar_mods/miui_framework_patch.py",
    "jar_patches/deadzone_mezo_jar_mods/miui_services_patch.py",
    "jar_patches/deadzone_mezo_jar_mods/telephony_patch.py",
    "jar_patches/deadzone_mezo_jar_mods/mediatek_telephony_patch.py",
    "jar_patches/deadzone_mezo_jar_mods/miui_wifi_patch.py",
    "jar_patches/deadzone_mezo_jar_mods/report.py",
]
for rel in REQUIRED_FILES:
    p = SCRIPTS / rel
    if p.is_file():
        ok(f"file exists: {rel}")
    else:
        fail(f"file missing: {rel}")

# 3. Assets exist
REQUIRED_ASSETS = [
    "jar_patches/assets/miui_framework/eu/xiaomi/util/FileUtil.smali",
    "jar_patches/assets/miui_framework/eu/xiaomi/util/JSONTranslator.smali",
    "jar_patches/assets/miui_framework/eu/xiaomi/util/Translator.smali",
    "jar_patches/assets/miui_wifi/com/android/server/wifi/MiuiWifiService$7.smali",
]
for rel in REQUIRED_ASSETS:
    p = SCRIPTS / rel
    if p.is_file() and p.stat().st_size > 0:
        ok(f"asset exists: {p.name} ({p.stat().st_size}B)")
    else:
        fail(f"asset missing or empty: {rel}")

# 4. No .mtcr or MyMezo artifacts anywhere in jar_patches tree
for bad in JAR_PATCHES.rglob("*.mtcr"):
    fail(f".mtcr file found: {bad.relative_to(ROOT)}")
# (__pycache__ is runtime-generated and covered by .gitignore — not checked here)

# 5. No MTCR/MyMezo naming in module files
for py_file in JAR_PATCHES.rglob("*.py"):
    text = py_file.read_text(encoding="utf-8", errors="replace")
    for forbidden_name in ["mtcr", "mymezo", "MyMezo", ".mtcr", "MTCR"]:
        if forbidden_name in text:
            fail(f"{py_file.name} contains forbidden name '{forbidden_name}'")

print()
if CHECKS_FAILED:
    print(f"FAILED ({len(CHECKS_FAILED)} checks)")
    sys.exit(1)
print("ALL PASSED")
sys.exit(0)
