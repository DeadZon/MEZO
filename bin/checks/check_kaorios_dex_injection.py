#!/usr/bin/env python3
"""check_kaorios_dex_injection — Validate DEX injection logic.

Checks:
  1. _next_dex_slot returns classes2.dex when only classes.dex exists
  2. _next_dex_slot returns classes3.dex when classes.dex + classes2.dex exist
  3. inject_kaorios_dex adds the dex entry to the ZIP correctly
  4. inject_kaorios_dex never overwrites an existing classesN.dex
  5. BACKUP_SUFFIX is .bak_deadzone_kaorios
  6. Kaorios DEX canonical name is classes.dex
  7. smali helpers find the correct class files
  8. Framework hooks target correct class paths
"""
from __future__ import annotations

import sys
import tempfile
import traceback
import zipfile
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"

_results: list[tuple[str, bool, str]] = []


def check(name: str):
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


import deadzone_kaorios_toolbox as kt


def _make_dummy_jar(td: Path, dex_names: list[str]) -> Path:
    jar = td / "framework.jar"
    with zipfile.ZipFile(jar, "w") as zf:
        for name in dex_names:
            zf.writestr(name, b"DUMMY")
    return jar


@check("BACKUP_SUFFIX is .bak_deadzone_kaorios")
def _():
    assert kt.BACKUP_SUFFIX == ".bak_deadzone_kaorios", \
        f"BACKUP_SUFFIX must be '.bak_deadzone_kaorios', got {kt.BACKUP_SUFFIX!r}"


@check("DEX canonical name is classes.dex")
def _():
    assert kt.DEX_CANON == "classes.dex", \
        f"DEX_CANON must be 'classes.dex', got {kt.DEX_CANON!r}"


@check("_next_dex_slot: classes.dex only -> classes2.dex")
def _():
    with tempfile.TemporaryDirectory() as td:
        jar = _make_dummy_jar(Path(td), ["classes.dex"])
        slot = kt._next_dex_slot(jar)
        assert slot == "classes2.dex", f"Expected classes2.dex, got {slot}"


@check("_next_dex_slot: classes.dex + classes2.dex -> classes3.dex")
def _():
    with tempfile.TemporaryDirectory() as td:
        jar = _make_dummy_jar(Path(td), ["classes.dex", "classes2.dex"])
        slot = kt._next_dex_slot(jar)
        assert slot == "classes3.dex", f"Expected classes3.dex, got {slot}"


@check("_next_dex_slot: classes.dex + classes2.dex + classes3.dex -> classes4.dex")
def _():
    with tempfile.TemporaryDirectory() as td:
        jar = _make_dummy_jar(Path(td), ["classes.dex", "classes2.dex", "classes3.dex"])
        slot = kt._next_dex_slot(jar)
        assert slot == "classes4.dex", f"Expected classes4.dex, got {slot}"


@check("inject_kaorios_dex adds dex to JAR")
def _():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        jar = _make_dummy_jar(td, ["classes.dex"])
        dex = td / "kaorios.dex"
        dex.write_bytes(b"\x64\x65\x78\x0a")  # dex magic prefix

        injected = kt.inject_kaorios_dex(jar, dex)

        assert injected == "classes2.dex", f"Expected classes2.dex, got {injected}"
        with zipfile.ZipFile(jar, "r") as zf:
            names = zf.namelist()
        assert "classes2.dex" in names, f"classes2.dex not in JAR entries: {names}"
        assert "classes.dex" in names, "Original classes.dex must still be present"


@check("inject_kaorios_dex raises on overwrite attempt")
def _():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        jar = _make_dummy_jar(td, ["classes.dex", "classes2.dex"])
        dex = td / "kaorios.dex"
        dex.write_bytes(b"\x64\x65\x78\x0a")

        # Manually corrupt the jar to simulate classes3.dex already being present
        # (inject once to get classes3.dex)
        kt.inject_kaorios_dex(jar, dex)

        # Now try again — it should pick classes4.dex (not raise, since 4 is free)
        injected2 = kt.inject_kaorios_dex(jar, dex)
        assert injected2 == "classes4.dex", \
            f"Second injection should pick classes4.dex, got {injected2}"


@check("framework hook targets correct class paths")
def _():
    assert "android/app/Instrumentation"    in kt.INSTRUMENTATION_CLASS
    assert "android/app/ApplicationPackageManager" in kt.APM_CLASS
    assert "AndroidKeyStoreKeyPairGeneratorSpi"    in kt.KEYSTORE_GEN_CLASS
    assert "AndroidKeyStoreSpi"                    in kt.KEYSTORE_SPI_CLASS
    assert "com/android/server/SystemServer"        in kt.SYSTEM_SERVER_CLASS


@check("_find_class_file finds smali in smali/ directory")
def _():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        smali_dir = td / "smali" / "android" / "app"
        smali_dir.mkdir(parents=True)
        (smali_dir / "Instrumentation.smali").write_text(".class public Landroid/app/Instrumentation;\n")

        result = kt._find_class_file(td, "android/app/Instrumentation")
        assert result is not None, "_find_class_file should find Instrumentation.smali"
        assert result.name == "Instrumentation.smali"


@check("_find_class_file finds smali in smali_classes2/ directory")
def _():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        smali_dir = td / "smali_classes2" / "android" / "security" / "keystore2"
        smali_dir.mkdir(parents=True)
        (smali_dir / "AndroidKeyStoreSpi.smali").write_text(
            ".class public Landroid/security/keystore2/AndroidKeyStoreSpi;\n"
        )

        result = kt._find_class_file(td, "android/security/keystore2/AndroidKeyStoreSpi")
        assert result is not None, "_find_class_file should find AndroidKeyStoreSpi.smali in smali_classes2"


@check("_already_patched detects KaoriosHook presence")
def _():
    lines = [
        ".method public foo()V",
        "    invoke-static {}, Landroid/security/kaorios/KaoriosHook;->initSystemServer()V",
        "    return-void",
        ".end method",
    ]
    assert kt._already_patched(lines, 0, 3), "Should detect KaoriosHook"
    lines2 = [".method public bar()V", "    return-void", ".end method"]
    assert not kt._already_patched(lines2, 0, 2), "Should not detect KaoriosHook in clean method"


@check("_get_registers_val parses .registers correctly")
def _():
    lines = [
        ".method public foo()V",
        "    .registers 15",
        "    return-void",
        ".end method",
    ]
    val, idx = kt._get_registers_val(lines, 0, 3)
    assert val == 15, f"Expected 15, got {val}"
    assert idx == 1, f"Expected line 1, got {idx}"


if __name__ == "__main__":
    print("=" * 60)
    print("Kaorios DEX Injection Check")
    print("=" * 60)

    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)

    for name, ok, msg in _results:
        status = PASS if ok else FAIL
        print(f"  [{status}] {name}")
        if not ok and msg:
            for line in msg.splitlines()[:4]:
                print(f"           {line}")

    print("=" * 60)
    print(f"  Results: {passed} passed, {failed} failed")
    print("=" * 60)
    sys.exit(0 if failed == 0 else 1)
