#!/usr/bin/env python3
"""check_kaorios_buildprop — Validate build.prop patching logic.

Checks:
  1. patch_buildprop function is importable and callable
  2. Properties are added without duplicates
  3. Correct properties: persist.sys.kaorios=kousei, ro.control_privapp_permissions=
  4. build.prop search order: system > product > system_ext
  5. Header comment '# Kaorios Toolbox' is written
  6. Existing properties are not duplicated on second run
"""
from __future__ import annotations

import sys
import tempfile
import textwrap
import traceback
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


@check("BUILDPROP_PROPS contains persist.sys.kaorios=kousei")
def _():
    keys = {k for k, _ in kt.BUILDPROP_PROPS}
    assert "persist.sys.kaorios" in keys, f"Missing persist.sys.kaorios in BUILDPROP_PROPS: {kt.BUILDPROP_PROPS}"
    vals = {k: v for k, v in kt.BUILDPROP_PROPS}
    assert vals["persist.sys.kaorios"] == "kousei", \
        f"Expected persist.sys.kaorios=kousei, got ={vals['persist.sys.kaorios']!r}"


@check("BUILDPROP_PROPS contains ro.control_privapp_permissions")
def _():
    keys = {k for k, _ in kt.BUILDPROP_PROPS}
    assert "ro.control_privapp_permissions" in keys, \
        "Missing ro.control_privapp_permissions in BUILDPROP_PROPS"


@check("build.prop search order starts with system/build.prop")
def _():
    assert kt.BUILDPROP_CANDIDATES[0] == "system/build.prop", \
        f"First candidate must be system/build.prop, got {kt.BUILDPROP_CANDIDATES[0]}"


@check("patch_buildprop adds properties to empty build.prop")
def _():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        bp = td / "system" / "build.prop"
        bp.parent.mkdir(parents=True)
        bp.write_text("ro.product.model=TestDevice\n", encoding="utf-8")

        # Monkeypatch BUILD_IMAGES
        orig = kt.BUILD_IMAGES
        kt.BUILD_IMAGES = td
        try:
            run = kt.KaoriosRun()
            result = kt.patch_buildprop(run)
        finally:
            kt.BUILD_IMAGES = orig

        assert result, "patch_buildprop should return True"
        content = bp.read_text()
        assert "persist.sys.kaorios=kousei" in content, "Missing persist.sys.kaorios=kousei"
        assert "ro.control_privapp_permissions=" in content, "Missing ro.control_privapp_permissions"
        assert "# Kaorios Toolbox" in content, "Missing header comment"


@check("patch_buildprop does not duplicate properties")
def _():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        bp = td / "system" / "build.prop"
        bp.parent.mkdir(parents=True)
        existing = textwrap.dedent("""\
            ro.product.model=TestDevice
            persist.sys.kaorios=kousei
            ro.control_privapp_permissions=
        """)
        bp.write_text(existing, encoding="utf-8")

        orig = kt.BUILD_IMAGES
        kt.BUILD_IMAGES = td
        try:
            run = kt.KaoriosRun()
            kt.patch_buildprop(run)
        finally:
            kt.BUILD_IMAGES = orig

        content = bp.read_text()
        # Count occurrences — must not be duplicated
        assert content.count("persist.sys.kaorios=kousei") == 1, \
            "persist.sys.kaorios must not be duplicated"
        assert content.count("ro.control_privapp_permissions=") == 1, \
            "ro.control_privapp_permissions must not be duplicated"
        assert run.buildprop_skipped, "skipped list must be non-empty when props already present"


@check("patch_buildprop uses product/build.prop fallback when system missing")
def _():
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        bp = td / "product" / "build.prop"
        bp.parent.mkdir(parents=True)
        bp.write_text("ro.product.model=TestDevice\n", encoding="utf-8")

        orig = kt.BUILD_IMAGES
        kt.BUILD_IMAGES = td
        try:
            run = kt.KaoriosRun()
            kt.patch_buildprop(run)
        finally:
            kt.BUILD_IMAGES = orig

        content = bp.read_text()
        assert "persist.sys.kaorios=kousei" in content, \
            "Should patch product/build.prop when system/build.prop missing"


if __name__ == "__main__":
    print("=" * 60)
    print("Kaorios build.prop Check")
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
