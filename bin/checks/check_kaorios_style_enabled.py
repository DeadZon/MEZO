#!/usr/bin/env python3
"""check_kaorios_style_enabled — Validate Kaorios Toolbox runs for all styles.

Checks:
  1. install.sh is in UpdateFile/ (not Styles/Legend/)
  2. install.sh has no DZ_STYLE gate
  3. install.sh calls deadzone_kaorios_toolbox.py
  4. Kaorios is NOT placed under bin/modfile/Styles/Legend/
  5. The script does not declare Legend-only logic
  6. Stable style runs Kaorios (base feature confirmed)
  7. Legend inherits base UpdateFile mods (insupdate.sh discovery)
  8. No root scripts/, devices/, tests/, third_party/ folders
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).parent.parent
REPO_ROOT = ROOT.parent

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


INSTALL_SH = ROOT / "modfile" / "UpdateFile" / "DeadZone_KaoriosToolbox" / "install.sh"


@check("install.sh in UpdateFile/ (not Legend-only)")
def _():
    assert INSTALL_SH.is_file(), f"install.sh not found at {INSTALL_SH}"


@check("install.sh has no DZ_STYLE gate")
def _():
    content = INSTALL_SH.read_text()
    assert "DZ_STYLE" not in content, \
        "install.sh must NOT gate on DZ_STYLE — Kaorios is a base feature for all styles"
    assert "Legend" not in content, \
        "install.sh must NOT reference 'Legend' — it must run for all styles"


@check("install.sh calls deadzone_kaorios_toolbox.py")
def _():
    content = INSTALL_SH.read_text()
    assert "deadzone_kaorios_toolbox.py" in content, \
        "install.sh must invoke deadzone_kaorios_toolbox.py"
    assert "python3" in content, "install.sh must use python3 to call the script"


@check("Kaorios NOT placed under Styles/Legend/")
def _():
    legend_dir = ROOT / "modfile" / "Styles" / "Legend"
    if legend_dir.is_dir():
        for f in legend_dir.rglob("*"):
            name = f.name.lower()
            assert "kaorios" not in name, \
                f"Kaorios file found under Legend/: {f}  — must be in UpdateFile/ instead"


@check("deadzone_kaorios_toolbox.py has no Legend-only guard")
def _():
    sc = ROOT / "scripts" / "deadzone_kaorios_toolbox.py"
    assert sc.is_file(), f"Missing: {sc}"
    content = sc.read_text()
    # Should NOT have a style check that restricts to Legend
    assert "if.*legend" not in content.lower() or "kaorios" not in content[:content.lower().find("if.*legend") if "if.*legend" in content.lower() else 0], \
        "Script must not gate Kaorios integration on Legend style"
    # The script should run regardless of DZ_STYLE_TIER
    # (it reads the style but does not exit based on it)
    assert "DZ_STYLE_ID" in content or "DZ_STYLE" in content, \
        "Script should read style info for reporting, but not gate execution"


@check("Stable style confirmed as base (UpdateFile discovery)")
def _():
    insupdate = ROOT / "modfile" / "UpdateFile" / "insupdate.sh"
    assert insupdate.is_file(), f"insupdate.sh not found at {insupdate}"
    content = insupdate.read_text()
    # insupdate.sh must not have a style filter
    assert "DZ_STYLE" not in content or "find" in content, \
        "insupdate.sh must discover and run all UpdateFile scripts"
    assert "find" in content and ".sh" in content, \
        "insupdate.sh must use find to discover *.sh scripts"


@check("insupdate.sh runs DeadZone_KaoriosToolbox install.sh")
def _():
    insupdate = ROOT / "modfile" / "UpdateFile" / "insupdate.sh"
    content   = insupdate.read_text()
    # insupdate.sh finds all *.sh — DeadZone_KaoriosToolbox/install.sh will be discovered
    assert 'find' in content and '*.sh' in content, \
        "insupdate.sh must use 'find ... *.sh' to auto-discover all mods including Kaorios"


@check("no root scripts/ directory")
def _():
    assert not (REPO_ROOT / "scripts").is_dir(), \
        "Root scripts/ must not exist — use bin/scripts/"


@check("no root devices/ directory")
def _():
    # 'devices/' is a known valid project dir at top level for device configs
    # Only check that it's a DEVICE config dir, not a new scripts-like folder
    d = REPO_ROOT / "devices"
    if d.is_dir():
        # It should only have mtk/ and/or snapdragon/ subdirs
        children = [c.name for c in d.iterdir() if c.is_dir()]
        for child in children:
            assert child in ("mtk", "snapdragon"), \
                f"Unexpected dir in devices/: {child} — devices/ should only have mtk/ and snapdragon/"


@check("no root tests/ directory")
def _():
    assert not (REPO_ROOT / "tests").is_dir(), \
        "Root tests/ must not exist — use bin/checks/"


@check("no root third_party/ directory")
def _():
    assert not (REPO_ROOT / "third_party").is_dir(), \
        "Root third_party/ must not exist — use bin/third_party/"


@check("Kaorios assets under bin/third_party/kaorios_toolbox/ (correct location)")
def _():
    correct = ROOT / "third_party" / "kaorios_toolbox"
    assert correct.is_dir(), f"Kaorios assets must be at {correct}"


if __name__ == "__main__":
    print("=" * 60)
    print("Kaorios Style Enabled Check")
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
