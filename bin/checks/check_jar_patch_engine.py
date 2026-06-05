#!/usr/bin/env python3
"""Check: deadzone_jar_patch_engine.py structure and install.sh wiring."""
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
SCRIPTS = ROOT / "bin" / "scripts"
CHECKS_FAILED: list[str] = []


def fail(msg: str) -> None:
    CHECKS_FAILED.append(msg)
    print(f"  FAIL: {msg}")


def ok(msg: str) -> None:
    print(f"  OK  : {msg}")


print("=== check_jar_patch_engine ===")

# 1. Engine file exists and is non-trivial
engine = SCRIPTS / "deadzone_jar_patch_engine.py"
if not engine.is_file():
    fail("deadzone_jar_patch_engine.py not found")
else:
    ok("deadzone_jar_patch_engine.py exists")
    text = engine.read_text(encoding="utf-8")
    for check in ["jar_patches.common.jar_workspace", "jar_patches.deadzone_mezo_jar_mods",
                  "registry.get_all_jar_names", "decompile_jar", "rebuild_jar", "replace_jar"]:
        if check in text:
            ok(f"  engine imports/calls {check!r}")
        else:
            fail(f"  engine missing reference to {check!r}")

# 2. install.sh exists and has no DZ_STYLE gate
install_sh = ROOT / "bin" / "modfile" / "UpdateFile" / "DeadZone_JarMods" / "install.sh"
if not install_sh.is_file():
    fail("bin/modfile/UpdateFile/DeadZone_JarMods/install.sh not found")
else:
    ok("install.sh exists")
    sh_text = install_sh.read_text(encoding="utf-8")
    if "DZ_STYLE" in sh_text:
        fail("install.sh has DZ_STYLE gate (must run for all styles)")
    else:
        ok("install.sh has no DZ_STYLE gate")
    if "deadzone_jar_patch_engine.py" in sh_text:
        ok("install.sh calls deadzone_jar_patch_engine.py")
    else:
        fail("install.sh does not call deadzone_jar_patch_engine.py")

# 3. install.sh is NOT under Styles/Legend/
sh_str = str(install_sh)
if "Styles" in sh_str or "Legend" in sh_str:
    fail("install.sh is under Styles/Legend/ — must be in UpdateFile/")
else:
    ok("install.sh is correctly placed in UpdateFile/")

# 4. No forbidden dirs at repo root
for forbidden in ["tests", "mymezo_mtcr", "_DeadZoneRefs"]:
    if (ROOT / forbidden).exists():
        fail(f"Forbidden directory found at repo root: {forbidden}/")
    else:
        ok(f"No forbidden dir: {forbidden}/")

# 5. Engine reports dir reference
if "jar_patches" in text and "deadzone_mezo_jar_mods_report" in text:
    ok("engine references jar_patches report path")
else:
    fail("engine missing jar_patches report path reference")

print()
if CHECKS_FAILED:
    print(f"FAILED ({len(CHECKS_FAILED)} checks)")
    sys.exit(1)
print("ALL PASSED")
sys.exit(0)
