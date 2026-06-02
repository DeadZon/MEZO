#!/usr/bin/env python3
"""DeadZone ROM packaging script for MEZO.

Replaces old uploadROM.sh packaging.
- Reads device info from bin/ddevice/ (populated by build.sh)
- Resolves device config via device_resolver
- Extracts DeadZone_Mezo.rar template (if present) or builds minimal structure
- Copies .img files from build output into images/
- Generates safe fastboot flash scripts
- Creates: DeadZone_<codename>_<rom_version>_A<android>.zip
- Writes: output/reports/final_zip_path.txt
-         output/reports/device_resolve_report.txt
-         output/reports/final_zip_manifest.txt
-         output/reports/final_zip_summary.json

Usage:
  package_rom.py [--no-template] [--staging-dir <dir>]
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

# ── Bootstrap: import device_resolver from same dir ──────────────────────────
_spec = importlib.util.spec_from_file_location(
    "device_resolver", Path(__file__).parent / "device_resolver.py"
)
_drmod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_drmod)
resolve         = _drmod.resolve
resolve_from_ddevice = _drmod.resolve_from_ddevice

# ── Paths ─────────────────────────────────────────────────────────────────────
WORK_DIR     = Path.cwd()
DDEVICE_DIR  = WORK_DIR / "bin" / "ddevice"
BUILD_IMAGES = WORK_DIR / "build" / "baserom" / "images"
BUILD_FW     = WORK_DIR / "build" / "baserom" / "firmware-update"
TEMPLATE_RAR = WORK_DIR / "DeadZone_Mezo.rar"
STAGING_BASE = WORK_DIR / "out" / "dz_staging"
REPORTS_DIR  = WORK_DIR / "output" / "reports"
OUT_DIR      = WORK_DIR / "out"

# Images that go INSIDE images/ in the ZIP
OPTIONAL_IMGS = [
    "boot.img", "init_boot.img", "vendor_boot.img", "dtbo.img",
    "vbmeta.img", "vbmeta_system.img", "vbmeta_vendor.img",
    "vbmeta_product.img", "vbmeta_odm.img",
    "logo.img", "cust.img",
    # MTK-specific
    "apusys.img", "audio_dsp.img", "ccu.img", "connsys_bt.img",
    "connsys_gnss.img", "connsys_wifi.img", "dpm.img", "gpueb.img",
    "gz.img", "lk.img", "mcf_ota.img", "mcupm.img", "md1img.img",
    "mvpu_algo.img", "pi_img.img", "scp.img", "spmfw.img", "sspm.img",
    "tee.img", "vcp.img", "preloader_raw.img",
]
FORBIDDEN_ENTRIES = [
    "output/", "build/", "work/", "logs/", "reports/",
    "payload.bin", ".git", "super.img.zst",
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def _read(fname: str) -> str:
    p = DDEVICE_DIR / fname
    return p.read_text(encoding="utf-8", errors="replace").strip() if p.is_file() else ""


def _sanitize_name(s: str) -> str:
    return re.sub(r'[^A-Za-z0-9._\-]', '_', s.strip())


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_rar(rar: Path, dest: Path) -> bool:
    """Extract RAR using unrar, 7z, or bsdtar — whichever is available."""
    dest.mkdir(parents=True, exist_ok=True)
    for cmd in [
        ["unrar", "x", "-y", str(rar), str(dest) + "/"],
        ["7z", "x", str(rar), f"-o{dest}", "-y"],
        ["bsdtar", "-xf", str(rar), "-C", str(dest)],
    ]:
        try:
            r = subprocess.run(cmd, capture_output=True)
            if r.returncode == 0:
                print(f"[PACKAGE] Extracted template using {cmd[0]}")
                return True
        except FileNotFoundError:
            continue
    return False


# ── Flash script generation ───────────────────────────────────────────────────

_LINUX_UPGRADE = """\
#!/usr/bin/env bash
# DeadZone ROM Flasher — Upgrade (no data wipe)
# Auto-generated — do not edit manually.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IMG="$SCRIPT_DIR/images"

die() {{ echo ""; echo "══════════════════════════════════════════════"; echo "  FLASH FAILED: $1"; echo "  Do NOT disconnect your device!"; echo "  Phone remains in fastboot — fix the issue first."; echo "══════════════════════════════════════════════"; exit 1; }}

echo "═══════════════════════════════════════════"
echo "  DeadZone ROM Flasher — Upgrade"
echo "  Device: {codename}  ROM: {rom_version}"
echo "  DO NOT disconnect during flashing!"
echo "═══════════════════════════════════════════"

# Required: super.img
[ -f "$IMG/super.img" ] || die "images/super.img not found"
fastboot flash super "$IMG/super.img" || die "super.img"

# Optional images — flash if present
for img in {optional_list}; do
    [ -f "$IMG/$img" ] && {{ fastboot flash "${{img%.img}}" "$IMG/$img" || die "$img"; }}
done

echo ""
echo "All partitions flashed successfully!"
echo "Rebooting to system..."
fastboot reboot
"""

_LINUX_CLEAN = """\
#!/usr/bin/env bash
# DeadZone ROM Flasher — Clean Install (WIPES userdata)
# Auto-generated — do not edit manually.
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
IMG="$SCRIPT_DIR/images"

die() {{ echo ""; echo "══════════════════════════════════════════════"; echo "  FLASH FAILED: $1"; echo "  Do NOT disconnect your device!"; echo "  Phone remains in fastboot."; echo "══════════════════════════════════════════════"; exit 1; }}

echo "═══════════════════════════════════════════"
echo "  DeadZone ROM Flasher — Clean Install"
echo "  Device: {codename}  ROM: {rom_version}"
echo "  WARNING: userdata WILL be wiped!"
echo "  DO NOT disconnect during flashing!"
echo "═══════════════════════════════════════════"
echo ""
echo "Starting in 5 seconds... Ctrl-C to cancel."
sleep 5

[ -f "$IMG/super.img" ] || die "images/super.img not found"
fastboot flash super "$IMG/super.img" || die "super.img"

for img in {optional_list}; do
    [ -f "$IMG/$img" ] && {{ fastboot flash "${{img%.img}}" "$IMG/$img" || die "$img"; }}
done

echo ""
echo "All partitions flashed — wiping userdata..."
fastboot erase metadata 2>/dev/null || true
fastboot erase userdata || die "erase userdata"
echo ""
echo "Done! Rebooting..."
fastboot reboot
"""

_LINUX_WIPE = """\
#!/usr/bin/env bash
# DeadZone ROM Flasher — Format Data Only (no ROM flash)
set -euo pipefail
die() {{ echo "FAILED: $1 — do NOT disconnect!"; exit 1; }}
echo "Erasing metadata and userdata..."
fastboot erase metadata 2>/dev/null || true
fastboot erase userdata || die "erase userdata"
echo "Done! Rebooting..."
fastboot reboot
"""

_WIN_UPGRADE = """\
@echo off
setlocal enabledelayedexpansion
:: DeadZone ROM Flasher - Upgrade (no data wipe)
:: Auto-generated
set SCRIPT_DIR=%~dp0
set IMG=%SCRIPT_DIR%images
set FASTBOOT=%SCRIPT_DIR%bin\\windows\\fastboot.exe
if not exist "%FASTBOOT%" set FASTBOOT=fastboot

echo ============================================================
echo   DeadZone ROM Flasher - Upgrade
echo   Device: {codename}  ROM: {rom_version}
echo   DO NOT disconnect during flashing!
echo ============================================================

if not exist "%IMG%\\super.img" (
    echo ERROR: images\\super.img not found & pause & exit /b 1
)
"%FASTBOOT%" flash super "%IMG%\\super.img"
if errorlevel 1 ( echo FAILED: super.img - DO NOT disconnect! & pause & exit /b 1 )

{win_optional}

echo.
echo All partitions flashed successfully!
echo Rebooting to system...
"%FASTBOOT%" reboot
pause
"""

_WIN_CLEAN = """\
@echo off
setlocal enabledelayedexpansion
:: DeadZone ROM Flasher - Clean Install (WIPES userdata)
set SCRIPT_DIR=%~dp0
set IMG=%SCRIPT_DIR%images
set FASTBOOT=%SCRIPT_DIR%bin\\windows\\fastboot.exe
if not exist "%FASTBOOT%" set FASTBOOT=fastboot

echo ============================================================
echo   DeadZone ROM Flasher - Clean Install
echo   Device: {codename}  ROM: {rom_version}
echo   WARNING: userdata WILL be wiped!
echo   DO NOT disconnect during flashing!
echo ============================================================
echo Starting in 10 seconds... Close window to cancel.
timeout /t 10

if not exist "%IMG%\\super.img" (
    echo ERROR: images\\super.img not found & pause & exit /b 1
)
"%FASTBOOT%" flash super "%IMG%\\super.img"
if errorlevel 1 ( echo FAILED: super.img - DO NOT disconnect! & pause & exit /b 1 )

{win_optional}

echo.
echo All partitions flashed - wiping userdata...
"%FASTBOOT%" erase metadata 2>nul
"%FASTBOOT%" erase userdata
if errorlevel 1 ( echo FAILED: erase userdata - DO NOT disconnect! & pause & exit /b 1 )
echo Done! Rebooting...
"%FASTBOOT%" reboot
pause
"""

_WIN_WIPE = """\
@echo off
set SCRIPT_DIR=%~dp0
set FASTBOOT=%SCRIPT_DIR%bin\\windows\\fastboot.exe
if not exist "%FASTBOOT%" set FASTBOOT=fastboot
echo Erasing metadata and userdata...
"%FASTBOOT%" erase metadata 2>nul
"%FASTBOOT%" erase userdata
if errorlevel 1 ( echo FAILED: erase userdata - DO NOT disconnect! & pause & exit /b 1 )
echo Done! Rebooting...
"%FASTBOOT%" reboot
pause
"""


def _gen_scripts(staging: Path, codename: str, rom_version: str, avail_imgs: list[str]) -> None:
    """Write all platform flash scripts into staging/."""
    opt = [i for i in OPTIONAL_IMGS if i != "super.img"]
    opt_list = " ".join(opt)

    win_opt_lines = "\n".join(
        f'if exist "%IMG%\\{img}" ( "%FASTBOOT%" flash {img[:-4]} "%IMG%\\{img}"\n'
        f'  if errorlevel 1 ( echo FAILED: {img} - DO NOT disconnect! & pause & exit /b 1 ) )'
        for img in opt
    )

    subs = dict(codename=codename, rom_version=rom_version,
                optional_list=opt_list, win_optional=win_opt_lines)

    pairs = [
        ("linux_install_upgrade.sh",          _LINUX_UPGRADE.format(**subs)),
        ("linux_install_and_format_data.sh",  _LINUX_CLEAN.format(**subs)),
        ("linux_format_data_only.sh",         _LINUX_WIPE),
        ("macos_install_upgrade.sh",          _LINUX_UPGRADE.format(**subs)),
        ("macos_install_and_format_data.sh",  _LINUX_CLEAN.format(**subs)),
        ("macos_format_data_only.sh",         _LINUX_WIPE),
        ("windows_install_upgrade.bat",        _WIN_UPGRADE.format(**subs)),
        ("windows_install_and_format_data.bat",_WIN_CLEAN.format(**subs)),
        ("windows_format_data_only.bat",       _WIN_WIPE),
    ]
    for name, content in pairs:
        dest = staging / name
        dest.write_text(content, encoding="utf-8")
        if name.endswith(".sh"):
            dest.chmod(0o755)
    print(f"[PACKAGE] Flash scripts written ({len(pairs)} files)")


# ── Validation ────────────────────────────────────────────────────────────────

def _validate_zip(zip_path: Path) -> list[str]:
    """Return list of validation errors (empty = OK)."""
    errors: list[str] = []
    if not zip_path.is_file():
        return [f"ZIP not found: {zip_path}"]
    if not zip_path.name.startswith("DeadZone_"):
        errors.append(f"ZIP name must start with 'DeadZone_', got: {zip_path.name}")
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        inner = {n.lower() for n in names}
        if not any("images/super.img" in n.lower() for n in names):
            errors.append("images/super.img missing from ZIP")
        if not any(n.lower().endswith(".sh") or n.lower().endswith(".bat") for n in names):
            errors.append("No flash scripts (.sh/.bat) found at ZIP root")
        for forbidden in FORBIDDEN_ENTRIES:
            hits = [n for n in names if forbidden.lower() in n.lower()]
            if hits:
                errors.append(f"Forbidden entry '{forbidden}' found: {hits[:3]}")
    return errors


# ── Reports ───────────────────────────────────────────────────────────────────

def _write_manifest(zip_path: Path, sha: str) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "MEZO Final ZIP Manifest",
        "=" * 40,
        f"ZIP name:   {zip_path.name}",
        f"ZIP path:   {zip_path}",
        f"SHA256:     {sha}",
        f"Size:       {zip_path.stat().st_size:,} bytes ({zip_path.stat().st_size / 1024**2:.1f} MiB)",
        "",
        "Files inside ZIP:",
    ]
    forbidden_found: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        infos = sorted(zf.infolist(), key=lambda i: i.filename)
        lines.append(f"  total: {len(infos)}")
        for info in infos:
            lines.append(f"  {info.compress_size:>12,}  {info.file_size:>12,}  {info.filename}")
            for f in FORBIDDEN_ENTRIES:
                if f.lower() in info.filename.lower():
                    forbidden_found.append(info.filename)
    lines += ["", f"Forbidden entry check: {'PASS' if not forbidden_found else 'FAIL'}"]
    if forbidden_found:
        lines += [f"  ! {e}" for e in forbidden_found]
    (REPORTS_DIR / "final_zip_manifest.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_summary(zip_path: Path, sha: str, cfg: dict, images: list[str], scripts: list[str]) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    summary = {
        "codename":          cfg["codename"],
        "rom_os_version":    _read("base_rom_code.txt"),
        "android_version":   _read("androidver.txt"),
        "final_zip_name":    zip_path.name,
        "final_zip_path":    str(zip_path),
        "size_bytes":        zip_path.stat().st_size,
        "sha256":            sha,
        "file_count":        0,
        "images_included":   images,
        "scripts_included":  scripts,
        "forbidden_entries_found": [],
    }
    with zipfile.ZipFile(zip_path) as zf:
        summary["file_count"] = len(zf.namelist())
        for f in FORBIDDEN_ENTRIES:
            hits = [n for n in zf.namelist() if f.lower() in n.lower()]
            summary["forbidden_entries_found"].extend(hits)
    (REPORTS_DIR / "final_zip_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ── Main packaging logic ──────────────────────────────────────────────────────

def _read(fname: str) -> str:
    p = DDEVICE_DIR / fname
    return p.read_text(encoding="utf-8", errors="replace").strip() if p.is_file() else ""


def package() -> Path:
    # ── Read device info ──────────────────────────────────────────────────────
    codename    = _read("device_f.txt") or _read("device_code.txt") or "unknown"
    rom_version = _sanitize_name(_read("base_rom_code.txt") or "UNKNOWN")
    android_ver = re.sub(r"\D", "", _read("androidver.txt") or "")
    rom_os      = _read("rom_os.txt") or "HyperOS"
    baserom_type= _read("romtype.txt") or "payload"

    zip_name = f"DeadZone_{_sanitize_name(codename)}_{rom_version}_A{android_ver}.zip"
    print(f"[PACKAGE] Building: {zip_name}")

    # ── Resolve device ────────────────────────────────────────────────────────
    cfg = resolve(codename)
    _drmod.write_report(cfg)
    if cfg["warnings"]:
        for w in cfg["warnings"]:
            print(f"[PACKAGE] WARN: {w}", file=sys.stderr)

    # ── Prepare staging directory ─────────────────────────────────────────────
    staging = STAGING_BASE
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    # Try template RAR first
    template_used = False
    if TEMPLATE_RAR.is_file():
        print(f"[PACKAGE] Extracting template: {TEMPLATE_RAR}")
        template_used = _extract_rar(TEMPLATE_RAR, staging)
        if not template_used:
            print("[PACKAGE] WARNING: RAR extraction failed — building minimal package", file=sys.stderr)

    # If no template or extraction failed: create minimal structure
    if not template_used:
        print("[PACKAGE] Building minimal package structure")
        (staging / "bin" / "windows").mkdir(parents=True)
        (staging / "bin" / "linux").mkdir(parents=True)
        (staging / "bin" / "macos").mkdir(parents=True)

    # ── images/ directory ─────────────────────────────────────────────────────
    img_dir = staging / "images"
    img_dir.mkdir(exist_ok=True)

    copied_imgs: list[str] = []
    skipped: list[str] = []

    # 1. super.img — must exist (created by packROM.sh)
    super_src = BUILD_IMAGES / "super.img"
    if super_src.is_file():
        shutil.copy2(super_src, img_dir / "super.img")
        copied_imgs.append("super.img")
        print(f"[PACKAGE] Copied super.img ({super_src.stat().st_size / 1024**2:.0f} MiB)")
    else:
        print("[PACKAGE] ERROR: build/baserom/images/super.img not found!", file=sys.stderr)
        sys.exit(1)

    # 2. Other .img from build output (skip super.img.zst and directories)
    src_dirs = [BUILD_IMAGES]
    if baserom_type == "br" and BUILD_FW.is_dir():
        src_dirs.append(BUILD_FW)

    for src_dir in src_dirs:
        if not src_dir.is_dir():
            continue
        for img in sorted(src_dir.glob("*.img")):
            if img.name == "super.img":
                continue  # already copied
            if img.name.endswith(".zst"):
                continue
            dest = img_dir / img.name
            shutil.copy2(img, dest)
            copied_imgs.append(img.name)

    print(f"[PACKAGE] Images collected: {len(copied_imgs)} files")
    print(f"  {', '.join(copied_imgs[:8])}{'...' if len(copied_imgs) > 8 else ''}")

    # ── Flash scripts ─────────────────────────────────────────────────────────
    _gen_scripts(staging, _sanitize_name(codename), rom_version, copied_imgs)

    # ── Create ZIP ────────────────────────────────────────────────────────────
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = OUT_DIR / zip_name

    print(f"[PACKAGE] Zipping → {zip_path}")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=1) as zf:
        for f in sorted(staging.rglob("*")):
            if f.is_file():
                arcname = f.relative_to(staging)
                zf.write(f, arcname)

    size_mib = zip_path.stat().st_size / 1024**2
    print(f"[PACKAGE] ZIP created: {size_mib:.1f} MiB")

    # ── Validate ──────────────────────────────────────────────────────────────
    errors = _validate_zip(zip_path)
    if errors:
        print("[PACKAGE] VALIDATION ERRORS:", file=sys.stderr)
        for e in errors:
            print(f"  ! {e}", file=sys.stderr)
        sys.exit(1)
    print("[PACKAGE] Validation: PASS")

    # ── Reports ───────────────────────────────────────────────────────────────
    sha = _sha256(zip_path)
    scripts_in_zip = [n for n in zipfile.ZipFile(zip_path).namelist()
                      if n.endswith((".sh", ".bat")) and "/" not in n]
    _write_manifest(zip_path, sha)
    _write_summary(zip_path, sha, cfg, copied_imgs, scripts_in_zip)

    # ── Save path for downstream steps ───────────────────────────────────────
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / "final_zip_path.txt").write_text(str(zip_path), encoding="utf-8")
    print(f"[PACKAGE] final_zip_path.txt → {zip_path}")

    # ── Cleanup staging ───────────────────────────────────────────────────────
    shutil.rmtree(staging, ignore_errors=True)

    return zip_path


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.parse_args()  # accepts --help; no required args
    package()


if __name__ == "__main__":
    main()
