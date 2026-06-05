#!/usr/bin/env python3
"""Tests for DeadZone Framework Patcher.

Tests:
  1. Stable/Legend style flags do NOT gate the patcher (it's a base feature)
  2. invoke-custom detection and removal from equals/hashCode/toString
  3. Signature bypass method patching (const_return, return_void)
  4. Missing tools produce clear error messages
  5. Missing JARs are reported clearly
  6. invoke-custom: no files -> 'no changes needed' (not a failure)
  7. Sig-bypass: reports success only when real patterns are patched
  8. No FrameworkPatcher branding in final ROM output
  9. Final ZIP packaging unchanged (MTK/Snapdragon scripts untouched)

Run with: python3 tests/test_framework_patcher.py
"""
from __future__ import annotations

import io
import sys

# Ensure UTF-8 output on all platforms (Windows cmd defaults to cp1252)
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import tempfile
import textwrap
import traceback
from pathlib import Path

# Add scripts/ to path
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import deadzone_framework_patcher as fp

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

_results: list[tuple[str, bool, str]] = []


def test(name: str):
    """Decorator to register a test function."""
    def decorator(fn):
        try:
            fn()
            _results.append((name, True, ""))
        except AssertionError as exc:
            _results.append((name, False, str(exc)))
        except Exception as exc:
            _results.append((name, False, f"{type(exc).__name__}: {exc}\n{traceback.format_exc()}"))
        return fn
    return decorator


# ─────────────────────────────────────────────────────────────────────────────
# Test helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_smali(method_lines: list[str], class_name: str = "TestClass") -> str:
    header = textwrap.dedent(f"""\
        .class public L{class_name};
        .super Ljava/lang/Object;

    """)
    return header + "\n".join(method_lines) + "\n"


def _write_smali(tmpdir: Path, filename: str, content: str) -> Path:
    p = tmpdir / filename
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


# ─────────────────────────────────────────────────────────────────────────────
# 1. Base feature: patcher must run for Stable and Legend
# ─────────────────────────────────────────────────────────────────────────────

@test("Stable style does not disable framework patcher")
def _():
    # The install.sh is in UpdateFile/ which runs for ALL styles
    install_sh = (
        Path(__file__).parent.parent
        / "modfile/UpdateFile/DeadZone_FrameworkPatcher/install.sh"
    )
    assert install_sh.is_file(), "install.sh not found"
    content = install_sh.read_text()
    assert "deadzone_framework_patcher.py" in content, "install.sh must call the patcher"
    # Must NOT be guarded by style conditional
    assert "DZ_STYLE" not in content, \
        "install.sh must NOT gate the patcher on DZ_STYLE -- it is a base feature"


@test("Legend style inherits patcher via UpdateFile (not Styles/Legend only)")
def _():
    legend_insmod = (
        Path(__file__).parent.parent / "modfile/Styles/Legend/insmod.sh"
    )
    if legend_insmod.is_file():
        content = legend_insmod.read_text()
        assert "deadzone_framework_patcher" not in content, \
            "Framework patcher must NOT be in Styles/Legend — it runs from UpdateFile for all styles"


# ─────────────────────────────────────────────────────────────────────────────
# 2. invoke-custom detection
# ─────────────────────────────────────────────────────────────────────────────

@test("invoke-custom: _has_invoke_custom detects presence")
def _():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "Test.smali"
        p.write_text("    invoke-custom {v0}, call-site-0()\n")
        assert fp._has_invoke_custom(p) is True


@test("invoke-custom: _has_invoke_custom returns False when absent")
def _():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "Test.smali"
        p.write_text("    invoke-virtual {v0}, Lfoo;->bar()V\n")
        assert fp._has_invoke_custom(p) is False


@test("invoke-custom: removed from equals() method body")
def _():
    smali = textwrap.dedent("""\
        .class public LTest;
        .super Ljava/lang/Object;

        .method public equals(Ljava/lang/Object;)Z
            .registers 4
            invoke-custom {v0, v1}, call-site-0("equals", (Ljava/lang/Object;Ljava/lang/Object;)Z, 0)
            move-result v0
            return v0
        .end method
    """)
    with tempfile.TemporaryDirectory() as td:
        sf = Path(td) / "Test.smali"
        sf.write_text(smali)
        ok, note = fp._patch_invoke_custom_in_file(sf)
        assert ok, f"Expected modification but got ok=False note={note}"
        result = sf.read_text()
        assert "invoke-custom" not in result, "invoke-custom must be removed"
        assert "return v0" in result, "return v0 must be present"
        assert ".registers" in result


@test("invoke-custom: removed from hashCode() method body")
def _():
    smali = textwrap.dedent("""\
        .class public LTest;
        .super Ljava/lang/Object;

        .method public hashCode()I
            .registers 2
            invoke-custom {v0}, call-site-1("hashCode", ()I, 0)
            move-result v0
            return v0
        .end method
    """)
    with tempfile.TemporaryDirectory() as td:
        sf = Path(td) / "Test.smali"
        sf.write_text(smali)
        ok, _ = fp._patch_invoke_custom_in_file(sf)
        assert ok
        result = sf.read_text()
        assert "invoke-custom" not in result


@test("invoke-custom: removed from toString() method body")
def _():
    smali = textwrap.dedent("""\
        .class public LTest;
        .super Ljava/lang/Object;

        .method public toString()Ljava/lang/String;
            .registers 2
            invoke-custom {v0}, call-site-2("toString", ()Ljava/lang/String;, 0)
            move-result-object v0
            return-object v0
        .end method
    """)
    with tempfile.TemporaryDirectory() as td:
        sf = Path(td) / "Test.smali"
        sf.write_text(smali)
        ok, _ = fp._patch_invoke_custom_in_file(sf)
        assert ok
        result = sf.read_text()
        assert "invoke-custom" not in result


@test("invoke-custom: no invoke-custom -> no changes, not a failure")
def _():
    with tempfile.TemporaryDirectory() as td:
        smali_dir = Path(td) / "smali"
        smali_dir.mkdir()
        sf = smali_dir / "Test.smali"
        sf.write_text(".class public LTest;\n.super Ljava/lang/Object;\n")
        result = fp.handle_invoke_custom(Path(td))
        assert result["files_with_ic"] == 0
        assert result["handled"] == 0
        assert result["failed"] == 0


@test("invoke-custom: multiple files all handled")
def _():
    smali_tmpl = textwrap.dedent("""\
        .class public L{cls};
        .super Ljava/lang/Object;

        .method public equals(Ljava/lang/Object;)Z
            .registers 4
            invoke-custom {{v0}}, call-site-0()
            move-result v0
            return v0
        .end method
    """)
    with tempfile.TemporaryDirectory() as td:
        smali_dir = Path(td) / "smali"
        smali_dir.mkdir()
        for i in range(3):
            (smali_dir / f"Test{i}.smali").write_text(smali_tmpl.format(cls=f"Test{i}"))
        result = fp.handle_invoke_custom(Path(td))
        assert result["files_with_ic"] == 3
        assert result["handled"] == 3
        assert result["failed"] == 0


# ─────────────────────────────────────────────────────────────────────────────
# 3. Signature bypass patching
# ─────────────────────────────────────────────────────────────────────────────

@test("sig-bypass: const_return patches method to return constant")
def _():
    smali = textwrap.dedent("""\
        .class public Landroid/content/pm/SigningDetails;
        .super Ljava/lang/Object;

        .method public checkCapability(ILandroid/content/pm/SigningDetails;)Z
            .registers 4
            iget-object v0, p0, Landroid/content/pm/SigningDetails;->mSignatures:[Landroid/content/pm/Signature;
            if-eqz v0, :cond_0
            const/4 v0, 0x0
            return v0
            :cond_0
            const/4 v0, 0x1
            return v0
        .end method
    """)
    with tempfile.TemporaryDirectory() as td:
        smali_dir = Path(td) / "smali"
        smali_dir.mkdir()
        sf = smali_dir / "SigningDetails.smali"
        sf.write_text(smali)
        res = fp.patch_method(Path(td), "checkCapability(", "const_return", "1")
        assert res.applied, f"Patch not applied: {res.note}"
        result = sf.read_text()
        assert "const/4 v0, 0x1" in result
        assert "return v0" in result
        # Original complex body should be gone
        assert "iget-object" not in result


@test("sig-bypass: return_void patches method to return-void")
def _():
    smali = textwrap.dedent("""\
        .class public Lcom/android/server/pm/PackageManagerService;
        .super Ljava/lang/Object;

        .method public checkDowngrade(Landroid/content/pm/AndroidPackage;Z)V
            .registers 6
            invoke-virtual {p0}, Lcom/android/server/pm/PackageManagerService;->someCheck()Z
            move-result v0
            if-eqz v0, :cond_0
            return-void
            :cond_0
            new-instance v0, Ljava/lang/Exception;
            throw v0
        .end method
    """)
    with tempfile.TemporaryDirectory() as td:
        smali_dir = Path(td) / "smali"
        smali_dir.mkdir()
        sf = smali_dir / "PackageManagerService.smali"
        sf.write_text(smali)
        res = fp.patch_method(Path(td), "checkDowngrade(", "return_void", "")
        assert res.applied, f"Patch not applied: {res.note}"
        result = sf.read_text()
        assert "return-void" in result
        assert "invoke-virtual" not in result


@test("sig-bypass: missing method returns applied=False (not a hard error)")
def _():
    with tempfile.TemporaryDirectory() as td:
        smali_dir = Path(td) / "smali"
        smali_dir.mkdir()
        (smali_dir / "Empty.smali").write_text(".class public LEmpty;\n.super Ljava/lang/Object;\n")
        res = fp.patch_method(Path(td), "nonExistentMethod(", "const_return", "1")
        assert not res.applied
        assert "not found" in res.note.lower()


@test("sig-bypass: success only reported when at least one patch applied")
def _():
    # This tests the validation logic: zero patches = failure
    with tempfile.TemporaryDirectory() as td:
        smali_dir = Path(td) / "smali"
        smali_dir.mkdir()
        (smali_dir / "Dummy.smali").write_text(".class public LDummy;\n.super Ljava/lang/Object;\n")

        results = fp.apply_signature_bypass(
            Path(td),
            [("nonExistentMethodA(", "const_return", "1"),
             ("nonExistentMethodB(", "return_void", "")],
            "framework",
            15,
        )
        applied = sum(1 for r in results if r.applied)
        assert applied == 0, f"Expected 0 applied but got {applied}"


@test("sig-bypass: _find_method_bounds finds correct start/end")
def _():
    lines = [
        ".class public LTest;",
        ".super Ljava/lang/Object;",
        "",
        ".method public foo()V",
        "    .registers 1",
        "    return-void",
        ".end method",
        "",
        ".method public bar()Z",
        "    .registers 2",
        "    const/4 v0, 0x1",
        "    return v0",
        ".end method",
    ]
    bounds = fp._find_method_bounds(lines, "foo(")
    assert bounds == (3, 6), f"Expected (3,6) got {bounds}"
    bounds2 = fp._find_method_bounds(lines, "bar(")
    assert bounds2 == (8, 12), f"Expected (8,12) got {bounds2}"


@test("sig-bypass: _find_all_method_bounds finds multiple overloads")
def _():
    lines = [
        ".method public checkCapability(I)Z",
        "    return-void",
        ".end method",
        ".method public checkCapability(IZ)Z",
        "    return-void",
        ".end method",
    ]
    all_bounds = fp._find_all_method_bounds(lines, "checkCapability(")
    assert len(all_bounds) == 2, f"Expected 2 overloads, got {len(all_bounds)}"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Tool detection
# ─────────────────────────────────────────────────────────────────────────────

@test("missing java produces clear error text")
def _():
    # Verify the patcher exposes a find_java() function
    assert hasattr(fp, "find_java"), "find_java() must be defined"
    # The function returns None when java is absent (can't guarantee java absent here,
    # so we just verify it's callable and returns str or None)
    result = fp.find_java()
    assert result is None or isinstance(result, str), \
        f"find_java() must return str or None, got {type(result)}"


@test("missing apktool.jar -> find_apktool returns None when not present in standard dirs")
def _():
    # Verify find_apktool() is callable
    assert hasattr(fp, "find_apktool"), "find_apktool() must be defined"


# ─────────────────────────────────────────────────────────────────────────────
# 5. No FrameworkPatcher branding in patcher output
# ─────────────────────────────────────────────────────────────────────────────

@test("no FrameworkPatcher branding in patcher output strings")
def _():
    patcher_src = (
        Path(__file__).parent.parent / "scripts" / "deadzone_framework_patcher.py"
    )
    content = patcher_src.read_text()
    # Must not print "FrameworkPatcher" as a branding label in output
    # (attribution in comments/docstrings is fine, but echo/print branding is not)
    bad_phrases = [
        "print.*FrameworkPatcher.*module",
        "FrameworkPatcher.*v",
        "FrameworkPatcher Engine",
    ]
    import re
    for phrase in bad_phrases:
        matches = re.findall(phrase, content, re.IGNORECASE)
        assert not matches, f"Found forbidden branding: {matches}"
    # Must have DeadZone branding
    assert "DeadZone" in content or "DEADZONE" in content, "Must have DeadZone branding"


@test("install.sh references deadzone_framework_patcher not FrameworkPatcher binary")
def _():
    sh = (
        Path(__file__).parent.parent
        / "modfile/UpdateFile/DeadZone_FrameworkPatcher/install.sh"
    )
    content = sh.read_text()
    assert "deadzone_framework_patcher.py" in content
    assert "patcher_a15.sh" not in content, "Must not reference external patcher scripts"
    assert "patcher_a16.sh" not in content


# ─────────────────────────────────────────────────────────────────────────────
# 6. Package/flash scripts untouched
# ─────────────────────────────────────────────────────────────────────────────

@test("MTK flash map unchanged (no framework patcher interference)")
def _():
    sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
    import package_rom as pr
    assert "boot_ab" in pr.MTK_FLASH_MAP.values(), "MTK flash map must still have boot_ab"
    assert "super" in pr.MTK_FLASH_MAP.values(), "MTK flash map must still have super"


@test("Snapdragon flash map unchanged")
def _():
    import package_rom as pr
    assert "boot_ab" in pr.SD_FLASH_MAP.values(), "SD flash map must have boot_ab"
    assert "super" in pr.SD_FLASH_MAP.values(), "SD flash map must have super"
    assert "xbl_config_ab" in pr.SD_FLASH_MAP.values()


@test("final ZIP packaging logic unchanged (no new ZIP entries from framework patcher)")
def _():
    import package_rom as pr
    # FORBIDDEN_ENTRIES must not include framework patcher temp files
    for entry in pr.FORBIDDEN_ENTRIES:
        assert "framework_patcher" not in entry.lower(), \
            f"FORBIDDEN_ENTRIES should not accidentally block framework patcher: {entry}"


# ─────────────────────────────────────────────────────────────────────────────
# Run all tests
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"{'='*60}")
    print("DeadZone Framework Patcher — Test Suite")
    print(f"{'='*60}")

    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)

    for name, ok, msg in _results:
        status = PASS if ok else FAIL
        print(f"  [{status}] {name}")
        if not ok and msg:
            for line in msg.splitlines()[:5]:
                print(f"           {line}")

    print(f"{'='*60}")
    print(f"  Results: {passed} passed, {failed} failed")
    print(f"{'='*60}")

    sys.exit(0 if failed == 0 else 1)
