#!/usr/bin/env python3
"""
DeadZone MEZO Lite APK/App Patches
Applies targeted patches to three APKs:
  1. Provision.apk            — MEZO branding strings
  2. MiuiSystemUI.apk         — Hide 4G / Show VoLTE (OS2/OS3 CN only)
  3. PowerKeeper.apk          — CN/Global Build flag patches

All patches are idempotent and SKIPPED-safe (missing files never fail the build).
APKs are decompiled to *_unpacked/ dirs; if pre-decompiled dirs already exist they
are used directly (enables unit-testing without apktool/Java).
Reports written to output/reports/lite_apk_patches_report.{txt,json}.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Project paths ───────────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).resolve().parent           # bin/scripts
PROJECT_ROOT = SCRIPT_DIR.parent.parent                  # project root
APKTOOL_JAR  = SCRIPT_DIR.parent / "apktool" / "apktool.jar"
REPORT_DIR   = PROJECT_ROOT / "bin" / "output" / "reports"

# ── rom_patch_helpers ────────────────────────────────────────────────────────────
sys.path.insert(0, str(SCRIPT_DIR))
try:
    import rom_patch_helpers as _rph
except ImportError:
    _rph = None  # type: ignore[assignment]

# ── Target strings for Provision.apk ───────────────────────────────────────────
_PROVISION_STRINGS: dict[str, str] = {
    "miui14_global_start_up_slogan": "Lets rock with MEZO Development Project",
    "miui14_start_up_slogan":        "Lets rock with MEZO Development Project",
    "provision_complete_text":       "Ready to Rock with DeadZoneROM!",
}

# ── Provision APK search paths (relative to work_dir and build/baserom/images) ─
_PROVISION_APK_PATHS = [
    "system_ext/priv-app/Provision/Provision.apk",
    "system_ext/system_ext/priv-app/Provision/Provision.apk",
    "product/priv-app/Provision/Provision.apk",
    "product/product/priv-app/Provision/Provision.apk",
]

# ── MiuiSystemUI APK search paths ──────────────────────────────────────────────
_SYSUI_APK_PATHS = [
    "system_ext/priv-app/MiuiSystemUI/MiuiSystemUI.apk",
    "system_ext/system_ext/priv-app/MiuiSystemUI/MiuiSystemUI.apk",
    "system_ext/app/MiuiSystemUI/MiuiSystemUI.apk",
    "system_ext/system_ext/app/MiuiSystemUI/MiuiSystemUI.apk",
]

# ── MiuiSystemUI target classes ─────────────────────────────────────────────────
_SYSUI_TARGET_CLASSES = [
    "MiuiOperatorCustomizedPolicy",
    "MiuiCarrierTextController",
    "MiuiCellularIconVM$special$$inlined$combine$1$3",
    "MiuiMobileIconBinder$bind$1$1$10",
]

# ── PowerKeeper APK search paths ────────────────────────────────────────────────
_PK_APK_PATHS = [
    "system_ext/priv-app/PowerKeeper/PowerKeeper.apk",
    "system_ext/app/PowerKeeper/PowerKeeper.apk",
    "system/priv-app/PowerKeeper/PowerKeeper.apk",
    "system/app/PowerKeeper/PowerKeeper.apk",
]

# ── PowerKeeper target classes for Patch A ──────────────────────────────────────
_PK_PATCH_A_CLASSES = frozenset([
    "CloudUpdateHideMode",
    "CloudUpdateReceiver",
    "LocalUpdateUtils",
    "DeviceIdleController$1",
    "CustomerPowerCheck",
    "UsageAppTracker",
    "ThermalLogUploader",
    "MilletConfig",
    "PowerCheckerCloudPolicy",
    "DisplayFrameSetting",
    "SleepModeControllerNew",
    "SleepModeControllerNew$SleepHandler",
    "TrackerManager$PrivacyPolicy",
    "UnionPowerConfig",
    "GmsObserver",
    "Utils",
    "PaymentManager",
    "ExtraNetwork",
    "ThemeManagerHelper",
    "HostManager",
    "YellowPageUtils",
])

_INTL_FLAG = "Lmiui/os/Build;->IS_INTERNATIONAL_BUILD:Z"
_MIUI_FLAG  = "Lmiui/os/Build;->IS_MIUI:Z"

# ── Report entry builders ───────────────────────────────────────────────────────

def _prov_entry(
    target: str,
    *,
    found: bool,
    status: str,
    detail: str = "",
    error: Optional[str] = None,
    searched_paths: Optional[list] = None,
    original_path: Optional[str] = None,
    rebuilt_path: Optional[str] = None,
    restored_path: Optional[str] = None,
    restore_in_place: bool = False,
    permission: Optional[str] = None,
) -> dict:
    return {
        "patch_name": "provision_mezo_strings",
        "target_file": target,
        "found": found,
        "status": status,
        "detail": detail,
        "error": error,
        "searched_paths": searched_paths or [],
        "original_path": original_path,
        "rebuilt_path": rebuilt_path,
        "restored_path": restored_path,
        "restore_in_place": restore_in_place,
        "permission": permission,
    }


def _sysui_entry(
    target_class: str,
    target_file: str,
    *,
    found: bool,
    status: str,
    const_insertions: int = 0,
    detail: str = "",
    error: Optional[str] = None,
    original_path: Optional[str] = None,
    rebuilt_path: Optional[str] = None,
    restored_path: Optional[str] = None,
    restore_in_place: bool = False,
    permission: Optional[str] = None,
    os_detection: Optional[str] = None,
) -> dict:
    return {
        "patch_name": "miuisystemui_volte_cn",
        "target_class": target_class,
        "target_file": target_file,
        "found": found,
        "status": status,
        "const_insertions_count": const_insertions,
        "detail": detail,
        "error": error,
        "original_path": original_path,
        "rebuilt_path": rebuilt_path,
        "restored_path": restored_path,
        "restore_in_place": restore_in_place,
        "permission": permission,
        "os_detection": os_detection,
    }


def _pk_entry(
    target_class: str,
    target_file: str,
    *,
    found: bool,
    status: str,
    replacements: int = 0,
    const_insertions: int = 0,
    methods_patched: int = 0,
    skipped_reason: str = "",
    detail: str = "",
    error: Optional[str] = None,
    original_path: Optional[str] = None,
    rebuilt_path: Optional[str] = None,
    restored_path: Optional[str] = None,
    restore_in_place: bool = False,
    permission: Optional[str] = None,
) -> dict:
    return {
        "patch_name": "powerkeeper_cn_global_patches",
        "target_class": target_class,
        "target_file": target_file,
        "found": found,
        "status": status,
        "replacements_count": replacements,
        "const_insertions_count": const_insertions,
        "methods_patched": methods_patched,
        "files_modified": [target_file] if status == "changed" else [],
        "skipped_reason": skipped_reason,
        "detail": detail,
        "error": error,
        "original_path": original_path,
        "rebuilt_path": rebuilt_path,
        "restored_path": restored_path,
        "restore_in_place": restore_in_place,
        "permission": permission,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Shared smali helpers
# ══════════════════════════════════════════════════════════════════════════════

def _extract_sget_register(line: str) -> Optional[str]:
    m = re.match(r'\s*sget-boolean\s+(v\d+|p\d+)\s*,', line)
    return m.group(1) if m else None


def _replace_flag(content: str, old_flag: str, new_flag: str) -> tuple[str, int]:
    count = content.count(old_flag)
    return (content.replace(old_flag, new_flag), count) if count else (content, 0)


def _insert_const_below_sget(content: str, flag: str, const_value: str = "0x1") -> tuple[str, int]:
    """Insert const/4 vX, const_value below sget-boolean lines referencing flag. Idempotent."""
    lines = content.splitlines(True)
    out: list[str] = []
    insertions = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("sget-boolean") and flag in stripped:
            reg = _extract_sget_register(stripped)
            if reg:
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                next_s = lines[j].strip() if j < len(lines) else ""
                if next_s != f"const/4 {reg}, {const_value}":
                    out.append(line)
                    indent = len(line) - len(line.lstrip())
                    out.append(" " * indent + f"const/4 {reg}, {const_value}\n")
                    insertions += 1
                    i += 1
                    continue
        out.append(line)
        i += 1
    return "".join(out), insertions


def _find_smali_class(smali_dirs: list[Path], class_name: str) -> Optional[Path]:
    for sd in smali_dirs:
        for p in sd.rglob(f"{class_name}.smali"):
            return p
    return None


def _collect_smali_dirs(unpacked_dir: Path) -> list[Path]:
    return sorted(
        [d for d in unpacked_dir.iterdir() if d.is_dir() and d.name.startswith("smali")],
        key=lambda d: d.name,
    )


# ══════════════════════════════════════════════════════════════════════════════
# apktool helpers
# ══════════════════════════════════════════════════════════════════════════════

def _find_apktool() -> Optional[Path]:
    if APKTOOL_JAR.exists():
        return APKTOOL_JAR
    apktool_dir = SCRIPT_DIR.parent / "apktool"
    if apktool_dir.is_dir():
        for jar in apktool_dir.glob("apktool*.jar"):
            return jar
    return None


def _decompile_apk(apk_path: Path, out_dir: Path) -> tuple[bool, str, str]:
    """Returns (ok, stdout, stderr)."""
    if _rph is not None:
        r = _rph.decompile_apk(apk_path, out_dir)
        return r["ok"], r["stdout"], r["stderr"]
    apktool = _find_apktool()
    if not apktool:
        return False, "", "apktool.jar not found"
    try:
        r = subprocess.run(
            ["java", "-jar", str(apktool), "d", "-f", str(apk_path), "-o", str(out_dir)],
            capture_output=True, text=True, timeout=300,
        )
        return r.returncode == 0, r.stdout[-2000:], r.stderr[-2000:]
    except Exception as exc:
        return False, "", str(exc)


def _recompile_apk(unpacked_dir: Path, out_apk: Path) -> tuple[bool, str, str]:
    """Returns (ok, stdout, stderr)."""
    if _rph is not None:
        r = _rph.rebuild_apk(unpacked_dir, out_apk)
        return r["ok"], r["stdout"], r["stderr"]
    apktool = _find_apktool()
    if not apktool:
        return False, "", "apktool.jar not found"
    try:
        r = subprocess.run(
            ["java", "-jar", str(apktool), "b", "-f", str(unpacked_dir), "-o", str(out_apk)],
            capture_output=True, text=True, timeout=300,
        )
        return r.returncode == 0, r.stdout[-2000:], r.stderr[-2000:]
    except Exception as exc:
        return False, "", str(exc)


def _find_apk(work_dir: Path, search_paths: list[str], apk_name: str) -> Optional[tuple[Path, list[str]]]:
    """Returns (apk_path, searched_paths) or None if not found."""
    if _rph is not None:
        result = _rph.find_file_in_rom(work_dir, search_paths)
        if result["found"]:
            return Path(result["found_path"]), result["searched_paths"]
        return None
    searched: list[str] = []
    for rel in search_paths:
        p = work_dir / rel
        searched.append(str(p))
        if p.exists():
            return p, searched
    # rglob fallback
    for p in work_dir.rglob(apk_name):
        return p, searched
    return None


def _get_or_decompile(
    work_dir: Path,
    unpacked_name: str,
    apk_search_paths: list[str],
    apk_name: str,
) -> tuple[Optional[Path], bool, Optional[Path], list[str]]:
    """
    Returns (unpacked_dir, we_decompiled, apk_path, searched_paths).
    If pre-decompiled dir exists: (dir, False, None, []).
    If APK found: decompile to tmp dir → (tmp_dir, True, apk_path, searched).
    Otherwise: (None, False, None, searched).
    """
    pre = work_dir / unpacked_name
    if pre.is_dir():
        return pre, False, None, []
    found = _find_apk(work_dir, apk_search_paths, apk_name)
    if found:
        apk, searched = found
        tmp = Path(tempfile.mkdtemp(prefix=f"dz_{unpacked_name}_"))
        ok, _out, _err = _decompile_apk(apk, tmp)
        if ok:
            return tmp, True, apk, searched
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
        return None, False, apk, searched
    return None, False, None, []


def _rebuild_and_restore(
    unpacked_dir: Path,
    original_apk: Path,
    expected_name: str,
) -> dict:
    """Rebuild APK to a temp file then restore in place via rom_patch_helpers.

    Returns {ok, rebuilt_path, restored_path, restore_in_place, permission, stdout, stderr, error}.
    The original file is never touched unless rebuild succeeds.
    """
    import shutil as _sh
    tmp_out = Path(tempfile.mktemp(suffix=f"_{expected_name}", dir=str(unpacked_dir.parent)))
    try:
        ok, stdout, stderr = _recompile_apk(unpacked_dir, tmp_out)
        if not ok:
            tmp_out.unlink(missing_ok=True)
            return {
                "ok": False,
                "rebuilt_path": str(tmp_out),
                "restored_path": None,
                "restore_in_place": False,
                "permission": None,
                "stdout": stdout,
                "stderr": stderr,
                "error": f"rebuild failed — stdout={stdout[-300:]} stderr={stderr[-300:]}",
            }

        # Restore in place
        if _rph is not None:
            restore = _rph.restore_patched_file_in_place(tmp_out, original_apk, expected_name)
        else:
            try:
                if original_apk.exists():
                    original_apk.unlink()
                _sh.move(str(tmp_out), str(original_apk))
                try:
                    original_apk.chmod(0o644)
                    perm = "0644"
                except Exception:
                    perm = "0644 (chmod failed)"
                restore = {
                    "restored": True, "restored_path": str(original_apk),
                    "rebuilt_path": str(tmp_out), "permission": perm, "error": None,
                }
            except Exception as exc:
                restore = {
                    "restored": False, "restored_path": None,
                    "rebuilt_path": str(tmp_out), "permission": None, "error": str(exc),
                }

        return {
            "ok": restore["restored"],
            "rebuilt_path": restore.get("rebuilt_path", str(tmp_out)),
            "restored_path": restore.get("restored_path"),
            "restore_in_place": restore["restored"],
            "permission": restore.get("permission"),
            "stdout": stdout,
            "stderr": stderr,
            "error": restore.get("error"),
        }
    except Exception as exc:
        try:
            tmp_out.unlink(missing_ok=True)
        except Exception:
            pass
        return {
            "ok": False, "rebuilt_path": str(tmp_out), "restored_path": None,
            "restore_in_place": False, "permission": None,
            "stdout": "", "stderr": "", "error": str(exc),
        }


# ══════════════════════════════════════════════════════════════════════════════
# PART 1 — Provision.apk strings patch
# ══════════════════════════════════════════════════════════════════════════════

def _patch_strings_xml(xml_path: Path, strings: dict[str, str]) -> tuple[bool, dict]:
    """
    Patch string values in a strings.xml file.
    Returns (changed, {name: "updated"|"unchanged"}).
    """
    content = xml_path.read_text(encoding="utf-8", errors="ignore")
    orig = content
    results: dict[str, str] = {}
    for name, value in strings.items():
        pat = rf'(<string\s+name="{re.escape(name)}"[^>]*>)(.*?)(</string>)'
        m = re.search(pat, content, re.DOTALL)
        if m:
            if m.group(2) != value:
                content = content[: m.start(2)] + value + content[m.end(2) :]
                # Re-search after replacement to keep offsets valid for next iteration
                results[name] = "updated"
            else:
                results[name] = "unchanged"
        else:
            results[name] = "missing"
    changed = content != orig
    if changed:
        xml_path.write_text(content, encoding="utf-8")
    return changed, results


def _add_missing_strings_to_xml(xml_path: Path, to_add: dict[str, str]) -> bool:
    """Insert missing strings before </resources> in strings.xml."""
    if not to_add:
        return False
    content = xml_path.read_text(encoding="utf-8", errors="ignore")
    new_lines = "\n".join(
        f'    <string name="{name}">{value}</string>'
        for name, value in to_add.items()
    )
    new_content, n = re.subn(
        r'(</resources>)',
        new_lines + "\n" + r"\1",
        content,
        count=1,
    )
    if n:
        xml_path.write_text(new_content, encoding="utf-8")
        return True
    # Fallback: append before end of file
    xml_path.write_text(content.rstrip() + "\n" + new_lines + "\n</resources>\n",
                        encoding="utf-8")
    return True


def _patch_provision_strings_in_dir(provision_dir: Path, report: list) -> None:
    """Patch Provision strings in a pre-decompiled APK directory."""
    xml_files = sorted(provision_dir.glob("res/values*/strings.xml"))
    if not xml_files:
        report.append(_prov_entry(
            str(provision_dir / "res/values/strings.xml"),
            found=False, status="skipped",
            detail="No res/values*/strings.xml found in provision dir",
        ))
        return

    # Track which string names exist across all value dirs
    name_found_in: dict[str, list[Path]] = {n: [] for n in _PROVISION_STRINGS}

    for xml_path in xml_files:
        content = xml_path.read_text(encoding="utf-8", errors="ignore")
        for name in _PROVISION_STRINGS:
            if f'name="{name}"' in content:
                name_found_in[name].append(xml_path)

    # Update existing strings in all files where they appear
    for xml_path in xml_files:
        strings_in_this_file = {
            name: val
            for name, val in _PROVISION_STRINGS.items()
            if xml_path in name_found_in[name]
        }
        if not strings_in_this_file:
            continue
        try:
            changed, results = _patch_strings_xml(xml_path, strings_in_this_file)
            updated = [n for n, r in results.items() if r == "updated"]
            unchanged = [n for n, r in results.items() if r == "unchanged"]
            if updated:
                report.append(_prov_entry(
                    str(xml_path), found=True, status="changed",
                    detail=f"Updated: {updated}; unchanged: {unchanged}",
                ))
            else:
                report.append(_prov_entry(
                    str(xml_path), found=True, status="skipped",
                    detail=f"All strings already correct: {unchanged}",
                ))
        except Exception as exc:
            report.append(_prov_entry(str(xml_path), found=True, status="failed", error=str(exc)))

    # Add strings that were missing from all value dirs
    missing_names = {n: v for n, v in _PROVISION_STRINGS.items() if not name_found_in[n]}
    if missing_names:
        base_strings = provision_dir / "res" / "values" / "strings.xml"
        if not base_strings.exists():
            base_strings.parent.mkdir(parents=True, exist_ok=True)
            base_strings.write_text('<?xml version="1.0" encoding="utf-8"?>\n<resources>\n</resources>\n',
                                    encoding="utf-8")
        try:
            _add_missing_strings_to_xml(base_strings, missing_names)
            report.append(_prov_entry(
                str(base_strings), found=True, status="changed",
                detail=f"Added missing strings: {list(missing_names)}",
            ))
        except Exception as exc:
            report.append(_prov_entry(str(base_strings), found=True, status="failed", error=str(exc)))


def apply_provision_strings(work_dir: Path, report: list) -> None:
    """Patch Provision.apk MEZO branding strings."""
    unpacked, we_decompiled, apk_path, searched = _get_or_decompile(
        work_dir, "provision_unpacked",
        _PROVISION_APK_PATHS, "Provision.apk",
    )

    if unpacked is None:
        report.append(_prov_entry(
            str(work_dir / "system_ext/priv-app/Provision/Provision.apk"),
            found=False, status="skipped_not_found",
            detail="Provision.apk not found and no provision_unpacked dir — SKIPPED_NOT_FOUND",
            searched_paths=searched,
        ))
        return

    try:
        _patch_provision_strings_in_dir(unpacked, report)
        if we_decompiled and apk_path:
            rr = _rebuild_and_restore(unpacked, apk_path, "Provision.apk")
            if not rr["ok"]:
                report.append(_prov_entry(
                    str(apk_path), found=True, status="failed_optional",
                    error=rr["error"],
                    searched_paths=searched,
                    original_path=str(apk_path),
                    rebuilt_path=rr["rebuilt_path"],
                ))
            else:
                report.append(_prov_entry(
                    str(apk_path), found=True, status="changed",
                    detail="Provision.apk patched and restored in place",
                    searched_paths=searched,
                    original_path=str(apk_path),
                    rebuilt_path=rr["rebuilt_path"],
                    restored_path=rr["restored_path"],
                    restore_in_place=True,
                    permission=rr["permission"],
                ))
    finally:
        if we_decompiled:
            import shutil
            shutil.rmtree(unpacked, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# PART 2 — MiuiSystemUI Hide 4G / Show VoLTE (OS2/OS3 CN)
# ══════════════════════════════════════════════════════════════════════════════

def _iter_build_props(work_dir: Path):
    for rel in ("system/build.prop", "vendor/build.prop",
                "system_ext/etc/build.prop", "product/etc/build.prop"):
        p = work_dir / rel
        if p.exists():
            yield p


def _detect_rom_os(work_dir: Path) -> str:
    """Detect OS version from build.prop. Returns 'OS1', 'OS2', 'OS3', or ''."""
    for p in _iter_build_props(work_dir):
        content = p.read_text(encoding="utf-8", errors="ignore")
        for line in content.splitlines():
            low = line.lower()
            if ("os3" in low or "hyperos3" in low or "hyper.os.version=3" in low
                    or "ro.mi.os.version.release=os3" in low):
                return "OS3"
            if ("os2" in low or "hyperos2" in low or "hyper.os.version=2" in low
                    or "ro.mi.os.version.release=os2" in low):
                return "OS2"
            if "miui" in low and ("v14" in low or "v13" in low or "v12" in low):
                return "OS1"
    return os.environ.get("DZ_ROM_OS", "")


def _detect_rom_region(work_dir: Path) -> str:
    """Detect region from build.prop. Returns 'CN' or 'Global'."""
    for p in _iter_build_props(work_dir):
        content = p.read_text(encoding="utf-8", errors="ignore")
        if ("IS_INTERNATIONAL_BUILD=true" in content
                or "IS_GLOBAL_BUILD=true" in content
                or "ro.product.locale=en-US" in content):
            return "Global"
        if ("ro.product.locale=zh-CN" in content
                or "IS_CN_BUILD=true" in content
                or "ro.miui.region=CN" in content):
            return "CN"
    return os.environ.get("DZ_ROM_REGION", "")


def _patch_sysui_in_dir(sysui_dir: Path, report: list) -> None:
    """Patch MiuiSystemUI smali: insert const/4 vX, 0x1 below IS_INTERNATIONAL_BUILD sget."""
    smali_dirs = _collect_smali_dirs(sysui_dir)
    if not smali_dirs:
        report.append(_sysui_entry(
            "MiuiSystemUI", str(sysui_dir),
            found=True, status="skipped",
            detail="No smali dirs found in MiuiSystemUI unpacked dir",
        ))
        return

    for cls in _SYSUI_TARGET_CLASSES:
        path = _find_smali_class(smali_dirs, cls)
        if not path:
            report.append(_sysui_entry(
                cls, f"{sysui_dir}/**/{cls}.smali",
                found=False, status="skipped",
                detail=f"{cls}: class not found — SKIPPED",
            ))
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            new_content, insertions = _insert_const_below_sget(content, _INTL_FLAG)
            if insertions:
                path.write_text(new_content, encoding="utf-8")
                report.append(_sysui_entry(
                    cls, str(path), found=True, status="changed",
                    const_insertions=insertions,
                    detail=f"{cls}: {insertions} const/4 inserted (same register)",
                ))
            else:
                report.append(_sysui_entry(
                    cls, str(path), found=True, status="skipped",
                    detail=f"{cls}: IS_INTERNATIONAL_BUILD not found or already patched",
                ))
        except Exception as exc:
            report.append(_sysui_entry(cls, str(path), found=True, status="failed", error=str(exc)))


def apply_miuisystemui_volte_cn_patch(
    work_dir: Path,
    report: list,
    *,
    rom_os: Optional[str] = None,
    rom_region: Optional[str] = None,
) -> None:
    """
    Patch MiuiSystemUI to hide 4G icon and show VoLTE on CN OS2/OS3 ROMs.
    Skipped automatically on non-CN or non-OS2/OS3 ROMs.
    """
    if rom_os is None:
        rom_os = _detect_rom_os(work_dir)
    if rom_region is None:
        rom_region = _detect_rom_region(work_dir)

    # Skip only when OS or region is KNOWN and does not match — unknown means attempt patch
    if rom_os and rom_os not in ("OS2", "OS3"):
        report.append(_sysui_entry(
            "MiuiSystemUI", str(work_dir),
            found=False, status="skipped",
            detail=f"ROM OS is {rom_os!r} — patch applies only to OS2/OS3 — SKIPPED",
            os_detection=rom_os,
        ))
        return

    if rom_region and rom_region not in ("CN",):
        report.append(_sysui_entry(
            "MiuiSystemUI", str(work_dir),
            found=False, status="skipped",
            detail=f"ROM region is {rom_region!r} — patch applies only to CN — SKIPPED",
            os_detection=rom_os or "unknown",
        ))
        return

    # Record detection state for the report
    os_det = rom_os if rom_os else "unknown"

    unpacked, we_decompiled, apk_path, searched = _get_or_decompile(
        work_dir, "miuisystemui_unpacked",
        _SYSUI_APK_PATHS, "MiuiSystemUI.apk",
    )

    if unpacked is None:
        report.append(_sysui_entry(
            "MiuiSystemUI", str(work_dir),
            found=False, status="skipped_not_found",
            detail="MiuiSystemUI.apk not found and no miuisystemui_unpacked dir — SKIPPED_NOT_FOUND",
            os_detection=os_det,
        ))
        return

    try:
        _patch_sysui_in_dir(unpacked, report)
        if we_decompiled and apk_path:
            rr = _rebuild_and_restore(unpacked, apk_path, "MiuiSystemUI.apk")
            if not rr["ok"]:
                report.append(_sysui_entry(
                    "MiuiSystemUI", str(apk_path), found=True, status="failed_optional",
                    error=rr["error"],
                    original_path=str(apk_path),
                    rebuilt_path=rr["rebuilt_path"],
                    os_detection=os_det,
                ))
            else:
                report.append(_sysui_entry(
                    "MiuiSystemUI", str(apk_path), found=True, status="changed",
                    detail=f"MiuiSystemUI.apk patched and restored in place (os={os_det})",
                    original_path=str(apk_path),
                    rebuilt_path=rr["rebuilt_path"],
                    restored_path=rr["restored_path"],
                    restore_in_place=True,
                    permission=rr["permission"],
                    os_detection=os_det,
                ))
    finally:
        if we_decompiled:
            import shutil
            shutil.rmtree(unpacked, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# PART 4 — PowerKeeper.apk patches
# ══════════════════════════════════════════════════════════════════════════════

def _patch_gms_control_enabled(content: str) -> tuple[str, int]:
    """
    In method isGmsControlEnabled()Z, insert const/4 vX, 0x0 before every return vX.
    Idempotent. Returns (new_content, count).
    """
    lines = content.splitlines(True)
    out: list[str] = []
    in_method = False
    patched = 0
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(".method") and "isGmsControlEnabled()Z" in stripped:
            in_method = True
        elif in_method and stripped.startswith(".end method"):
            in_method = False

        if in_method:
            m = re.match(r'^(\s*)return\s+(v\d+|p\d+)\s*$', line)
            if m:
                reg = m.group(2)
                prev = ""
                for prev_line in reversed(out):
                    s = prev_line.strip()
                    if s:
                        prev = s
                        break
                if prev != f"const/4 {reg}, 0x0":
                    indent = m.group(1)
                    out.append(f"{indent}const/4 {reg}, 0x0\n")
                    patched += 1

        out.append(line)
    return "".join(out), patched


def _patch_powerkeeper_in_dir(pk_dir: Path, report: list) -> None:
    """Apply PowerKeeper patches to a pre-decompiled APK directory."""
    smali_dirs = _collect_smali_dirs(pk_dir)
    if not smali_dirs:
        report.append(_pk_entry(
            "PowerKeeper", str(pk_dir),
            found=True, status="skipped",
            detail="No smali dirs found",
        ))
        return

    # ── Patch A: IS_INTERNATIONAL_BUILD → IS_MIUI in listed classes ─────────────
    for cls in sorted(_PK_PATCH_A_CLASSES):
        path = _find_smali_class(smali_dirs, cls)
        if not path:
            report.append(_pk_entry(
                cls, f"{pk_dir}/**/{cls}.smali",
                found=False, status="skipped",
                skipped_reason="class not found",
                detail=f"{cls}: class not found — SKIPPED",
            ))
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            new_content, count = _replace_flag(content, _INTL_FLAG, _MIUI_FLAG)

            # ── Patch B: MilletConfig — insert const/4 below IS_MIUI ──────────
            milletconfig_insertions = 0
            if cls == "MilletConfig":
                new_content, milletconfig_insertions = _insert_const_below_sget(
                    new_content, _MIUI_FLAG
                )

            # ── Patch C: isGmsControlEnabled()Z → returns false ───────────────
            gms_patched = 0
            if "isGmsControlEnabled()Z" in new_content:
                new_content, gms_patched = _patch_gms_control_enabled(new_content)

            changed = (count > 0 or milletconfig_insertions > 0 or gms_patched > 0)
            if changed:
                path.write_text(new_content, encoding="utf-8")

            report.append(_pk_entry(
                cls, str(path), found=True,
                status="changed" if changed else "skipped",
                replacements=count,
                const_insertions=milletconfig_insertions,
                methods_patched=gms_patched,
                detail=(
                    f"{cls}: replacements={count} "
                    f"const_insertions={milletconfig_insertions} "
                    f"gms_patched={gms_patched}"
                ),
            ))
        except Exception as exc:
            report.append(_pk_entry(cls, str(path), found=True, status="failed", error=str(exc)))

    # ── Search all classes for isGmsControlEnabled (if not in Patch A classes) ──
    gms_classes_already_seen = {
        cls for cls in _PK_PATCH_A_CLASSES
        if _find_smali_class(smali_dirs, cls) is not None
    }
    # Scan remaining smali for isGmsControlEnabled
    for sd in smali_dirs:
        for smali_file in sd.rglob("*.smali"):
            cls = smali_file.stem
            if cls in gms_classes_already_seen:
                continue
            if cls in _PK_PATCH_A_CLASSES:
                continue
            try:
                content = smali_file.read_text(encoding="utf-8", errors="ignore")
                if "isGmsControlEnabled()Z" not in content:
                    continue
                new_content, gms_patched = _patch_gms_control_enabled(content)
                if gms_patched:
                    smali_file.write_text(new_content, encoding="utf-8")
                    report.append(_pk_entry(
                        cls, str(smali_file), found=True, status="changed",
                        methods_patched=gms_patched,
                        detail=f"{cls}: isGmsControlEnabled forced false ({gms_patched} return(s))",
                    ))
                else:
                    report.append(_pk_entry(
                        cls, str(smali_file), found=True, status="skipped",
                        detail=f"{cls}: isGmsControlEnabled already patched",
                    ))
            except Exception as exc:
                report.append(_pk_entry(cls, str(smali_file), found=True,
                                        status="failed", error=str(exc)))


def apply_powerkeeper_cn_global_patches(work_dir: Path, report: list) -> None:
    """Apply PowerKeeper CN/Global Build flag patches."""
    unpacked, we_decompiled, apk_path, searched = _get_or_decompile(
        work_dir, "powerkeeper_unpacked",
        _PK_APK_PATHS, "PowerKeeper.apk",
    )

    if unpacked is None:
        report.append(_pk_entry(
            "PowerKeeper", str(work_dir),
            found=False, status="skipped_not_found",
            skipped_reason="PowerKeeper.apk not found",
            detail="PowerKeeper.apk not found and no powerkeeper_unpacked dir — SKIPPED_NOT_FOUND",
        ))
        return

    try:
        _patch_powerkeeper_in_dir(unpacked, report)
        if we_decompiled and apk_path:
            rr = _rebuild_and_restore(unpacked, apk_path, "PowerKeeper.apk")
            if not rr["ok"]:
                report.append(_pk_entry(
                    "PowerKeeper", str(apk_path), found=True, status="failed_optional",
                    error=rr["error"],
                    original_path=str(apk_path),
                    rebuilt_path=rr["rebuilt_path"],
                ))
            else:
                report.append(_pk_entry(
                    "PowerKeeper", str(apk_path), found=True, status="changed",
                    detail="PowerKeeper.apk patched and restored in place",
                    original_path=str(apk_path),
                    rebuilt_path=rr["rebuilt_path"],
                    restored_path=rr["restored_path"],
                    restore_in_place=True,
                    permission=rr["permission"],
                ))
    finally:
        if we_decompiled:
            import shutil
            shutil.rmtree(unpacked, ignore_errors=True)


# ══════════════════════════════════════════════════════════════════════════════
# Main entry point — runs all three APK patches
# ══════════════════════════════════════════════════════════════════════════════

def apply_lite_apk_patches(
    work_dir: Path,
    *,
    rom_os: Optional[str] = None,
    rom_region: Optional[str] = None,
) -> dict:
    """Run all Lite APK patches and write reports. Returns the full report dict."""
    work_dir = Path(work_dir).resolve()

    prov_entries:  list[dict] = []
    sysui_entries: list[dict] = []
    pk_entries:    list[dict] = []

    apply_provision_strings(work_dir, prov_entries)
    apply_miuisystemui_volte_cn_patch(work_dir, sysui_entries,
                                      rom_os=rom_os, rom_region=rom_region)
    apply_powerkeeper_cn_global_patches(work_dir, pk_entries)

    all_entries = prov_entries + sysui_entries + pk_entries

    _SKIPPED_STATUSES = {"skipped", "skipped_not_found", "skipped_not_target_rom"}
    _FAILED_STATUSES  = {"failed", "failed_optional", "failed_fatal"}

    def _summary(entries: list[dict]) -> dict:
        return {
            "enabled": True,
            "total_scanned":          len(entries),
            "total_modified":         sum(1 for e in entries if e["status"] == "changed"),
            "total_skipped":          sum(1 for e in entries if e["status"] in _SKIPPED_STATUSES),
            "total_skipped_not_found": sum(1 for e in entries if e["status"] == "skipped_not_found"),
            "total_failed":           sum(1 for e in entries if e["status"] in _FAILED_STATUSES),
            "total_failed_optional":  sum(1 for e in entries if e["status"] == "failed_optional"),
            "results": entries,
        }

    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "work_dir":  str(work_dir),
        "patches": {
            "provision_mezo_strings":    _summary(prov_entries),
            "miuisystemui_volte_cn":     _summary(sysui_entries),
            "powerkeeper_cn_global":     _summary(pk_entries),
        },
        "totals": {
            "total_scanned":          len(all_entries),
            "total_modified":         sum(1 for e in all_entries if e["status"] == "changed"),
            "total_skipped":          sum(1 for e in all_entries if e["status"] in _SKIPPED_STATUSES),
            "total_skipped_not_found": sum(1 for e in all_entries if e["status"] == "skipped_not_found"),
            "total_failed":           sum(1 for e in all_entries if e["status"] in _FAILED_STATUSES),
            "total_failed_optional":  sum(1 for e in all_entries if e["status"] == "failed_optional"),
        },
    }

    _write_reports(report)
    return report


def _write_reports(report: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    json_path = REPORT_DIR / "lite_apk_patches_report.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    txt_path = REPORT_DIR / "lite_apk_patches_report.txt"
    lines = [
        "=" * 72,
        "DeadZone MEZO Lite APK Patches Report",
        f"Generated : {report['generated']}",
        f"Work dir  : {report['work_dir']}",
        "=" * 72,
        "",
    ]
    for patch_key, patch_data in report["patches"].items():
        lines += [
            f"[{patch_key.upper()}]",
            f"  Scanned        : {patch_data['total_scanned']}",
            f"  Modified       : {patch_data['total_modified']}",
            f"  Skipped        : {patch_data['total_skipped']}",
            f"  Skipped (NF)   : {patch_data.get('total_skipped_not_found', 0)}",
            f"  Failed         : {patch_data['total_failed']}",
            f"  Failed (opt.)  : {patch_data.get('total_failed_optional', 0)}",
            "",
        ]
        for e in patch_data["results"]:
            tag = e["status"].upper().ljust(16)
            found_tag = "FOUND" if e["found"] else "MISSING"
            cls = e.get("target_class", "")
            tf = e.get("target_file", "")
            lines.append(f"  [{tag}] [{found_tag}] {cls or tf}")
            if e.get("detail"):
                lines.append(f"           {e['detail']}")
            if e.get("error"):
                lines.append(f"           ERROR: {e['error']}")
            sp = e.get("searched_paths")
            if sp:
                lines.append(f"           Searched paths ({len(sp)}):")
                for sp_item in sp:
                    lines.append(f"             - {sp_item}")
        lines.append("")

    t = report["totals"]
    lines += [
        "=" * 72,
        "TOTALS",
        f"  Scanned        : {t['total_scanned']}",
        f"  Modified       : {t['total_modified']}",
        f"  Skipped        : {t['total_skipped']}",
        f"  Skipped (NF)   : {t.get('total_skipped_not_found', 0)}",
        f"  Failed         : {t['total_failed']}",
        f"  Failed (opt.)  : {t.get('total_failed_optional', 0)}",
        "=" * 72,
    ]
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[LiteAPK] Report written: {json_path}")
    print(f"[LiteAPK] Report written: {txt_path}")


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="DeadZone MEZO Lite APK Patches")
    parser.add_argument("--work-dir", required=True,
                        help="ROM work directory root")
    parser.add_argument("--style", choices=["lite", "plus", "stable", "legend", "ninja"], default="lite")
    parser.add_argument("--rom-os", default=None,
                        help="Override ROM OS detection (OS1/OS2/OS3)")
    parser.add_argument("--rom-region", default=None,
                        help="Override ROM region detection (CN/Global)")
    args = parser.parse_args()

    work_dir = Path(args.work_dir)
    if not work_dir.exists():
        print(f"[LiteAPK][ERROR] work-dir does not exist: {work_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"[LiteAPK] Applying Lite APK patches to: {work_dir}")
    report = apply_lite_apk_patches(work_dir,
                                    rom_os=args.rom_os,
                                    rom_region=args.rom_region)
    t = report["totals"]
    print(f"[LiteAPK] Done — scanned={t['total_scanned']} "
          f"modified={t['total_modified']} "
          f"skipped={t['total_skipped']} "
          f"failed={t['total_failed']}")
    if t["total_failed"] > 0:
        sys.exit(2)


if __name__ == "__main__":
    main()
