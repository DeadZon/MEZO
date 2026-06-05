#!/usr/bin/env python3
"""Check: mod registry structure and mod function signatures."""
import sys
from pathlib import Path

ROOT    = Path(__file__).parent.parent.parent
SCRIPTS = ROOT / "bin" / "scripts"
CHECKS_FAILED: list[str] = []


def fail(msg: str) -> None:
    CHECKS_FAILED.append(msg)
    print(f"  FAIL: {msg}")


def ok(msg: str) -> None:
    print(f"  OK  : {msg}")


print("=== check_jar_patch_registry ===")

registry_file = SCRIPTS / "jar_patches" / "deadzone_mezo_jar_mods" / "registry.py"
if not registry_file.is_file():
    fail("registry.py not found")
    print(f"FAILED")
    sys.exit(1)

text = registry_file.read_text(encoding="utf-8")

# 1. Registry must define get_mods_for_jar and get_all_jar_names
for fn in ["get_mods_for_jar", "get_all_jar_names"]:
    if f"def {fn}" in text:
        ok(f"registry defines {fn}()")
    else:
        fail(f"registry missing {fn}()")

# 2. All expected JARs registered
EXPECTED_JARS = [
    "framework", "services", "telephony-common",
    "mediatek-telephony-common", "miui-framework",
    "miui-services", "miui-wifi",
]
for jar in EXPECTED_JARS:
    if f'"{jar}"' in text:
        ok(f"JAR registered: {jar}")
    else:
        fail(f"JAR not registered: {jar}")

# 3. Imports all patch modules
for mod in [
    "framework_patch", "services_patch", "miui_framework_patch",
    "miui_services_patch", "telephony_patch", "mediatek_telephony_patch",
    "miui_wifi_patch",
]:
    if mod in text:
        ok(f"imports {mod}")
    else:
        fail(f"missing import for {mod}")

# 4. No MTCR/MyMezo references
for bad in ["mtcr", "mymezo", "MyMezo", "MTCR"]:
    if bad in text:
        fail(f"registry contains forbidden name: {bad}")

# 5. Each _reg call uses a function reference (not a string)
import re
# Only look at actual _reg("...) calls (not the def _reg(...) signature)
reg_calls = re.findall(r'_reg\("[^"]+",\s*"[^"]+",\s*(\S+)', text)
for fn_ref in reg_calls:
    fn_ref = fn_ref.rstrip(",)")
    if "_patch." in fn_ref:
        ok(f"_reg call uses function reference: {fn_ref}")
    else:
        fail(f"_reg call may not use function reference: {fn_ref}")

print()
if CHECKS_FAILED:
    print(f"FAILED ({len(CHECKS_FAILED)} checks)")
    sys.exit(1)
print("ALL PASSED")
sys.exit(0)
