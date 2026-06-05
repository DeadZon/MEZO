#!/usr/bin/env python3
"""Check: smali_utils helpers and report utilities work correctly."""
import sys
import tempfile
from pathlib import Path

ROOT    = Path(__file__).parent.parent.parent
SCRIPTS = ROOT / "bin" / "scripts"
CHECKS_FAILED: list[str] = []

sys.path.insert(0, str(SCRIPTS))


def fail(msg: str) -> None:
    CHECKS_FAILED.append(msg)
    print(f"  FAIL: {msg}")


def ok(msg: str) -> None:
    print(f"  OK  : {msg}")


print("=== check_jar_patch_reports ===")

# 1. Import smali_utils
try:
    from jar_patches.common import smali_utils as su
    ok("smali_utils imports OK")
except Exception as exc:
    fail(f"smali_utils import failed: {exc}")
    print(f"FAILED")
    sys.exit(1)

# 2. get_method_bounds
TEST_SMALI = """\
.class public Ltest/Foo;
.super Ljava/lang/Object;

.method public testMethod()V
    .registers 1

    return-void
.end method

.method public otherMethod()V
    .registers 1

    return-void
.end method
"""

bounds = su.get_method_bounds(TEST_SMALI, "testMethod()V")
if bounds and TEST_SMALI[bounds[0]:bounds[1]].strip().startswith(".method"):
    ok("get_method_bounds finds testMethod")
else:
    fail(f"get_method_bounds returned: {bounds}")

bounds2 = su.get_method_bounds(TEST_SMALI, "nonexistent()V")
if bounds2 is None:
    ok("get_method_bounds returns None for missing method")
else:
    fail("get_method_bounds should return None for missing method")

# 3. get_registers_val
method_text = ".method public foo()V\n    .registers 5\n    return-void\n.end method\n"
val = su.get_registers_val(method_text)
if val == 5:
    ok("get_registers_val returns 5")
else:
    fail(f"get_registers_val returned {val}, expected 5")

# 4. set_registers_val
new_method = su.set_registers_val(method_text, 7)
if ".registers 7" in new_method:
    ok("set_registers_val changes to 7")
else:
    fail("set_registers_val did not change to 7")

# 5. already_patched
if su.already_patched(TEST_SMALI, "testMethod"):
    ok("already_patched finds marker")
else:
    fail("already_patched should find 'testMethod'")

if not su.already_patched(TEST_SMALI, "neverPresent"):
    ok("already_patched returns False for missing marker")
else:
    fail("already_patched should return False for 'neverPresent'")

# 6. replace_method_body
new_body = "    .registers 1\n\n    const/4 v0, 0x1\n\n    return v0\n"
result = su.replace_method_body(TEST_SMALI, "testMethod()V", new_body)
if "const/4 v0, 0x1" in result and "return-void" not in result.split("testMethod")[1].split("otherMethod")[0]:
    ok("replace_method_body substitutes body correctly")
else:
    fail("replace_method_body did not work correctly")

# 7. delete_method
result2 = su.delete_method(TEST_SMALI, "testMethod()V")
if "testMethod" not in result2 and "otherMethod" in result2:
    ok("delete_method removes method, keeps other")
else:
    fail("delete_method did not work correctly")

# 8. insert_after_registers
ins_method = ".method public foo()V\n    .registers 3\n    return-void\n.end method\n"
result3 = su.insert_after_registers(ins_method, "    const/4 v0, 0x1\n")
if ".registers 3\n    const/4 v0, 0x1\n    return-void" in result3:
    ok("insert_after_registers inserts correctly")
else:
    fail(f"insert_after_registers result: {result3!r}")

# 9. find_smali_file with temp workspace
with tempfile.TemporaryDirectory() as tmp:
    tp = Path(tmp)
    smali_dir = tp / "smali"
    class_dir = smali_dir / "android" / "os"
    class_dir.mkdir(parents=True)
    smali_file = class_dir / "Build.smali"
    smali_file.write_text(TEST_SMALI)
    found = su.find_smali_file(tp, "Landroid/os/Build;")
    if found and found.name == "Build.smali":
        ok("find_smali_file locates Build.smali")
    else:
        fail(f"find_smali_file returned: {found}")

# 10. report_utils
try:
    from jar_patches.common import report_utils as ru
    ts = ru.ts()
    assert len(ts) > 10
    ok("report_utils.ts() works")
    sec = ru.section("Test")
    assert "Test" in sec
    ok("report_utils.section() works")
except Exception as exc:
    fail(f"report_utils error: {exc}")

print()
if CHECKS_FAILED:
    print(f"FAILED ({len(CHECKS_FAILED)} checks)")
    sys.exit(1)
print("ALL PASSED")
sys.exit(0)
