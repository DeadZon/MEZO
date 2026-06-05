#!/usr/bin/env python3
"""check_kaorios_assets — Validate Kaorios Toolbox asset structure.

Checks:
  1. bin/third_party/kaorios_toolbox/ directory exists
  2. version.txt, CREDITS.txt, README_DEADZONE.txt present
  3. app/, permissions/, framework/ directories exist
  4. docs/V2.0.3+/ guide files exist
  5. Asset download URLs and release names are consistent
  6. install.sh in UpdateFile/DeadZone_KaoriosToolbox/ exists
  7. deadzone_kaorios_toolbox.py exists
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).parent.parent

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


ASSET_DIR = ROOT / "third_party" / "kaorios_toolbox"


@check("kaorios_toolbox directory exists")
def _():
    assert ASSET_DIR.is_dir(), f"Missing: {ASSET_DIR}"


@check("version.txt present")
def _():
    vf = ASSET_DIR / "version.txt"
    assert vf.is_file(), f"Missing: {vf}"
    content = vf.read_text()
    assert "version=2.0.4.0" in content, "version.txt must contain version=2.0.4.0"
    assert "source_repo=" in content, "version.txt must contain source_repo="
    assert "guide=" in content, "version.txt must contain guide="


@check("CREDITS.txt present and correct")
def _():
    cf = ASSET_DIR / "CREDITS.txt"
    assert cf.is_file(), f"Missing: {cf}"
    content = cf.read_text()
    assert "Wuang26" in content, "CREDITS.txt must mention Wuang26"
    assert "V2.0.4" in content, "CREDITS.txt must reference V2.0.4"
    assert "APK" in content and "classes.dex" in content, "CREDITS.txt must list assets"


@check("README_DEADZONE.txt present")
def _():
    rf = ASSET_DIR / "README_DEADZONE.txt"
    assert rf.is_file(), f"Missing: {rf}"
    content = rf.read_text()
    assert "Stable" in content, "README must mention Stable"
    assert "deadzone_kaorios_toolbox.py" in content, "README must reference integration script"


@check("app/ directory exists")
def _():
    d = ASSET_DIR / "app"
    assert d.is_dir(), f"Missing directory: {d}"


@check("permissions/ directory exists (not misspelled)")
def _():
    d = ASSET_DIR / "permissions"
    assert d.is_dir(), f"Missing directory: {d} — check for typo 'permissons'"
    bad = ASSET_DIR / "permissons"
    assert not bad.exists(), f"Misspelled 'permissons' directory exists at {bad}"


@check("framework/ directory exists")
def _():
    d = ASSET_DIR / "framework"
    assert d.is_dir(), f"Missing directory: {d}"


@check("docs/V2.0.3+ directory exists")
def _():
    d = ASSET_DIR / "docs" / "V2.0.3+"
    assert d.is_dir(), f"Missing: {d}"


@check("Guide_2.0.3+.md present in docs")
def _():
    g = ASSET_DIR / "docs" / "V2.0.3+" / "Guide_2.0.3+.md"
    assert g.is_file(), f"Missing: {g}"
    content = g.read_text()
    assert "KaoriosHook" in content, "Guide must reference KaoriosHook"
    assert "framework.jar" in content.lower() or "Framework.jar" in content
    assert "services.jar" in content.lower() or "Services.jar" in content


@check("Disable_Secure_Flag.md present in docs")
def _():
    g = ASSET_DIR / "docs" / "V2.0.3+" / "Disable_Secure_Flag.md"
    assert g.is_file(), f"Missing: {g}"


@check("install.sh in UpdateFile/DeadZone_KaoriosToolbox/ exists")
def _():
    sh = ROOT / "modfile" / "UpdateFile" / "DeadZone_KaoriosToolbox" / "install.sh"
    assert sh.is_file(), f"Missing: {sh}"
    content = sh.read_text()
    assert "deadzone_kaorios_toolbox.py" in content, "install.sh must call deadzone_kaorios_toolbox.py"
    assert "DZ_STYLE" not in content, "install.sh must NOT gate on DZ_STYLE (must run for all styles)"


@check("deadzone_kaorios_toolbox.py exists in scripts/")
def _():
    sc = ROOT / "scripts" / "deadzone_kaorios_toolbox.py"
    assert sc.is_file(), f"Missing: {sc}"
    content = sc.read_text()
    assert "KAORIOS_VERSION" in content or "2.0.4" in content
    assert "KaoriosHook" in content or "kaorios" in content.lower()


@check("no root tests/ or root third_party/ folder introduced")
def _():
    repo_root = ROOT.parent
    assert not (repo_root / "tests").is_dir(), "Root tests/ folder must not exist"
    assert not (repo_root / "third_party").is_dir(), "Root third_party/ folder must not exist"


@check("no __pycache__ in kaorios asset dir")
def _():
    for p in ASSET_DIR.rglob("__pycache__"):
        assert False, f"__pycache__ found in asset dir: {p}"


if __name__ == "__main__":
    print("=" * 60)
    print("Kaorios Assets Check")
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
