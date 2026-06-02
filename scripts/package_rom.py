#!/usr/bin/env python3
"""DeadZone ROM packaging script for MEZO.

Replaces old uploadROM.sh packaging.
- Reads device info from bin/ddevice/ (populated by build.sh)
- Resolves device config via device_resolver
- Extracts DeadZone_Mezo.rar template (bin/ + Linux/macOS scripts preserved)
- Generates Windows BAT flash scripts dynamically from actual images present
- Copies .img files from build output into images/
- Validates scripts, images, and ZIP before finalising
- Creates: DeadZone_<codename>_<rom_version>_A<android>.zip
- Writes: output/reports/final_zip_path.txt
-         output/reports/device_resolve_report.txt
-         output/reports/final_zip_manifest.txt
-         output/reports/final_zip_summary.json
-         output/reports/flash_script_scan_report.txt
-         output/reports/pipeline_script_scan_report.txt

Usage:
  package_rom.py [--staging-dir <dir>]
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
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
resolve              = _drmod.resolve
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

# img files that belong in images/ (super.img handled separately)
OPTIONAL_IMGS = [
    "boot.img", "init_boot.img", "vendor_boot.img", "dtbo.img",
    "vbmeta.img", "vbmeta_system.img", "vbmeta_vendor.img",
    "vbmeta_product.img", "vbmeta_odm.img",
    "logo.img", "cust.img", "rescue.img",
    # MTK-specific
    "apusys.img", "audio_dsp.img", "ccu.img", "connsys_bt.img",
    "connsys_gnss.img", "connsys_wifi.img", "dpm.img", "gpueb.img",
    "gz.img", "lk.img", "mcf_ota.img", "mcupm.img", "md1img.img",
    "mvpu_algo.img", "pi_img.img", "scp.img", "spmfw.img", "sspm.img",
    "tee.img", "vcp.img", "preloader_raw.img",
]

# ── SoC-specific flash maps ───────────────────────────────────────────────────
# MTK: all slot images use _ab suffix; super is non-slot.
# Do NOT split into _a + _b for MTK; do NOT use preloader_a/b/1/2 for MTK.
MTK_FLASH_MAP: dict[str, str] = {
    "apusys.img":         "apusys_ab",
    "audio_dsp.img":      "audio_dsp_ab",
    "boot.img":           "boot_ab",
    "ccu.img":            "ccu_ab",
    "connsys_bt.img":     "connsys_bt_ab",
    "connsys_gnss.img":   "connsys_gnss_ab",
    "connsys_wifi.img":   "connsys_wifi_ab",
    "cust.img":           "cust",
    "dpm.img":            "dpm_ab",
    "dtbo.img":           "dtbo_ab",
    "gpueb.img":          "gpueb_ab",
    "gz.img":             "gz_ab",
    "init_boot.img":      "init_boot_ab",
    "lk.img":             "lk_ab",
    "logo.img":           "logo_ab",
    "mcf_ota.img":        "mcf_ota_ab",
    "mcupm.img":          "mcupm_ab",
    "md1img.img":         "md1img_ab",
    "mvpu_algo.img":      "mvpu_algo_ab",
    "pi_img.img":         "pi_img_ab",
    "preloader_raw.img":  "preloader_raw_ab",
    "rescue.img":         "rescue",
    "scp.img":            "scp_ab",
    "spmfw.img":          "spmfw_ab",
    "sspm.img":           "sspm_ab",
    "super.img":          "super",
    "tee.img":            "tee_ab",
    "vbmeta.img":         "vbmeta_ab",
    "vbmeta_odm.img":     "vbmeta_odm_ab",
    "vbmeta_product.img": "vbmeta_product_ab",
    "vbmeta_system.img":  "vbmeta_system_ab",
    "vbmeta_vendor.img":  "vbmeta_vendor_ab",
    "vcp.img":            "vcp_ab",
    "vendor_boot.img":    "vendor_boot_ab",
}

MTK_FLASH_ORDER: list[str] = [
    "preloader_raw.img",
    "lk.img",
    "boot.img",
    "init_boot.img",
    "dtbo.img",
    "vendor_boot.img",
    "md1img.img",
    "spmfw.img",
    "scp.img",
    "sspm.img",
    "tee.img",
    "gz.img",
    "dpm.img",
    "ccu.img",
    "apusys.img",
    "audio_dsp.img",
    "connsys_bt.img",
    "connsys_gnss.img",
    "connsys_wifi.img",
    "gpueb.img",
    "mcf_ota.img",
    "mcupm.img",
    "mvpu_algo.img",
    "pi_img.img",
    "vcp.img",
    "logo.img",
    "cust.img",
    "rescue.img",
    "vbmeta_system.img",
    "vbmeta_vendor.img",
    "vbmeta_product.img",
    "vbmeta_odm.img",
    "vbmeta.img",
    "super.img",
]

# Snapdragon: base partition names (flash to active slot; fastboot handles slotting)
SD_FLASH_MAP: dict[str, str] = {
    "boot.img":           "boot",
    "cust.img":           "cust",
    "dtbo.img":           "dtbo",
    "init_boot.img":      "init_boot",
    "logo.img":           "logo",
    "rescue.img":         "rescue",
    "super.img":          "super",
    "vbmeta.img":         "vbmeta",
    "vbmeta_odm.img":     "vbmeta_odm",
    "vbmeta_product.img": "vbmeta_product",
    "vbmeta_system.img":  "vbmeta_system",
    "vbmeta_vendor.img":  "vbmeta_vendor",
    "vendor_boot.img":    "vendor_boot",
}

SD_FLASH_ORDER: list[str] = [
    "boot.img",
    "init_boot.img",
    "vendor_boot.img",
    "dtbo.img",
    "logo.img",
    "cust.img",
    "rescue.img",
    "vbmeta_system.img",
    "vbmeta_vendor.img",
    "vbmeta_product.img",
    "vbmeta_odm.img",
    "vbmeta.img",
    "super.img",
]

# Alias used by reports that don't need per-SoC distinction
FLASH_MAP  = MTK_FLASH_MAP
FLASH_ORDER = MTK_FLASH_ORDER

# Must exist before the ZIP is built; fail hard if missing
REQUIRED_IMAGES: frozenset[str] = frozenset({"super.img", "vbmeta.img"})

FLASH_BLOCK_START = ":: BEGIN MEZO GENERATED IMAGE FLASH COMMANDS"
FLASH_BLOCK_END   = ":: END MEZO GENERATED IMAGE FLASH COMMANDS"

FORBIDDEN_ENTRIES = [
    "output/", "build/", "work/", "logs/", "reports/",
    "payload.bin", ".git", "super.img.zst",
]

# Linux/macOS scripts MUST come from the template (preserved exactly)
_TEMPLATE_SCRIPTS = [
    "linux_install_upgrade.sh", "linux_install_and_format_data.sh",
    "linux_format_data_only.sh",
    "macos_install_upgrade.sh", "macos_install_and_format_data.sh",
    "macos_format_data_only.sh",
]

# Windows scripts are generated dynamically from actual images present
_GEN_WIN_SCRIPTS = [
    "windows_install_upgrade.bat",
    "windows_install_and_format_data.bat",
    "windows_format_data_only.bat",
]

_REQUIRED_SCRIPTS = _TEMPLATE_SCRIPTS + _GEN_WIN_SCRIPTS


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


def _flatten_template(staging: Path) -> str | None:
    """If the RAR extracted into a single top-level folder, lift its contents to staging root.

    Returns the nested folder name if flattening occurred, else None.
    """
    top_entries = list(staging.iterdir())
    if len(top_entries) != 1 or not top_entries[0].is_dir():
        return None

    nested = top_entries[0]
    if not (nested / "bin").is_dir():
        return None

    print(f"[PACKAGE] Detected nested template root: {nested.name}/ — flattening into staging")
    for item in list(nested.iterdir()):
        dest = staging / item.name
        if dest.exists():
            if dest.is_dir():
                shutil.rmtree(dest)
            else:
                dest.unlink()
        shutil.move(str(item), str(dest))
    nested.rmdir()
    return nested.name


# ── Windows BAT script generation ────────────────────────────────────────────

_BAT_FAIL = "echo Flash failed. Do not disconnect the phone. & exit /B 1"

# MEZO warning block — shown at the top of both install scripts
_MEZO_WARNING = """\
echo.
echo.[i] - Read this information before flashing
echo.
echo.1. MEZO ROM, like most other custom ROMs, requires an unlocked bootloader. If your device is NOT unlocked, please close this window.
echo.2. Choose carefully. Selecting the wrong option may cause you to LOSE ALL DATA.
echo.3. MEZO ROM is FREE. If anyone sells this ROM or charges installation fees, please CONTACT MEZO ADMIN immediately.
echo.4. MEZO Team will NOT take responsibility if you brick your phone or lose your data while installing this ROM.
echo.5. Make sure you downloaded the exact MEZO build for your device. Flashing the wrong build may brick your phone.
echo.
echo.[i] - If you have read and agreed to all of the above, press any key to start the installation.
echo.[i] - Otherwise, close this window now.
pause >nul"""

_BAT_HEADER = """\
@echo off
cd %~dp0
set fastboot=bin\\windows\\fastboot.exe
if not exist "%fastboot%" set fastboot=fastboot"""


def _build_bat_flash_block(available_imgs: set[str],
                           flash_map: dict[str, str],
                           flash_order: list[str]) -> tuple[list[str], list[str]]:
    """Build %fastboot% flash command lines for each known image that exists.

    Uses SoC-specific flash_map (MTK: _ab; Snapdragon: base names).
    No _a/_b split for MTK; no preloader_a/b/1/2 for MTK.

    Returns: (bat_lines, flash_cmds_summary)
    """
    lines: list[str] = []
    cmds:  list[str] = []

    for img in flash_order:
        if img not in available_imgs:
            continue
        part = flash_map.get(img)
        if part is None:
            continue

        is_req = img in REQUIRED_IMAGES

        if is_req:
            lines += [
                f":: Required: {img} -> {part}",
                f'if not exist "images\\{img}" ( echo ERROR: images\\{img} not found. & exit /B 1 )',
                f'%fastboot% flash {part} "images\\{img}"',
                f'if errorlevel 1 ( {_BAT_FAIL} )',
                '',
            ]
        else:
            lines += [
                f'if exist "images\\{img}" (',
                f'    %fastboot% flash {part} "images\\{img}"',
                f'    if errorlevel 1 ( {_BAT_FAIL} )',
                f')',
                '',
            ]
        cmds.append(f'%fastboot% flash {part} images\\{img}')

    return lines, cmds


def _gen_windows_scripts(
    staging: Path,
    img_dir: Path,
    codename: str,
    rom_version: str,
    soc_family: str = "mtk",
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Generate 3 standalone Windows BAT flash scripts for the given SoC.

    Returns: (errors, warnings, unknown_imgs, flash_cmds_summary)
    """
    errors:   list[str] = []
    warnings: list[str] = []
    unknown:  list[str] = []

    soc = soc_family.lower().strip()
    if soc == "mtk":
        flash_map   = MTK_FLASH_MAP
        flash_order = MTK_FLASH_ORDER
        style_label = "MTK (_ab partitions)"
    else:
        flash_map   = SD_FLASH_MAP
        flash_order = SD_FLASH_ORDER
        style_label = "Snapdragon (base partitions)"

    print(f"[PACKAGE] BAT style: {style_label}")

    available = {p.name for p in img_dir.glob("*.img")}

    for req in sorted(REQUIRED_IMAGES):
        if req not in available:
            errors.append(f"Required image missing: {req}")
    if errors:
        return errors, warnings, unknown, []

    unknown = sorted(img for img in available if img not in flash_map)
    if unknown:
        warnings.append(f"Unknown images (not in {soc.upper()} map, not flashed): {', '.join(unknown)}")

    flash_lines, flash_cmds = _build_bat_flash_block(available, flash_map, flash_order)
    flash_block = "\n".join(flash_lines)

    # Common header section used by upgrade and clean-install
    def _header(title: str) -> str:
        return (
            f"{_BAT_HEADER}\n"
            f"\n"
            f"title {title}\n"
            f"\n"
            f"{_MEZO_WARNING}\n"
            f"\n"
            f"echo.\n"
            f"echo. Make sure your device is in Fastboot mode, then press any key.\n"
            f"pause >nul\n"
            f"echo.\n"
        )

    # ── windows_install_upgrade.bat ───────────────────────────────────────────
    upgrade = (
        _header(f"DeadZone ROM - Upgrade (no data wipe) | {codename} | {rom_version}")
        + f"\n{FLASH_BLOCK_START}\n"
        + flash_block
        + f"{FLASH_BLOCK_END}\n"
        + "\n"
        + "echo.\n"
        + "echo. All partitions flashed successfully. Rebooting...\n"
        + "%fastboot% reboot\n"
        + "pause\n"
        + "exit /B 0\n"
    )
    (staging / "windows_install_upgrade.bat").write_text(upgrade, encoding="utf-8")

    # ── windows_install_and_format_data.bat ───────────────────────────────────
    clean = (
        _header(f"DeadZone ROM - Clean Install (WIPES userdata) | {codename} | {rom_version}")
        + "\n"
        + "echo.\n"
        + "echo. =======================================================\n"
        + "echo.  WARNING: This will ERASE ALL YOUR USER DATA!\n"
        + "echo.  All images will be flashed first, then metadata and\n"
        + "echo.  userdata will be erased. Press any key to continue,\n"
        + "echo.  or close this window to cancel.\n"
        + "echo. =======================================================\n"
        + "echo.\n"
        + "pause >nul\n"
        + "echo.\n"
        + f"\n{FLASH_BLOCK_START}\n"
        + flash_block
        + f"{FLASH_BLOCK_END}\n"
        + "\n"
        + "echo.\n"
        + "echo. All partitions flashed. Erasing metadata...\n"
        + "%fastboot% erase metadata\n"
        + "if errorlevel 1 ( echo Erase metadata failed. Do not disconnect the phone. & exit /B 1 )\n"
        + "echo. Erasing userdata...\n"
        + "%fastboot% erase userdata\n"
        + "if errorlevel 1 ( echo Erase userdata failed. Do not disconnect the phone. & exit /B 1 )\n"
        + "echo.\n"
        + "echo. Done! Rebooting...\n"
        + "%fastboot% reboot\n"
        + "pause\n"
        + "exit /B 0\n"
    )
    (staging / "windows_install_and_format_data.bat").write_text(clean, encoding="utf-8")

    # ── windows_format_data_only.bat ──────────────────────────────────────────
    fmt = (
        f"{_BAT_HEADER}\n"
        "\n"
        f"title DeadZone ROM - Format Data Only\n"
        "\n"
        "echo.\n"
        "echo. =======================================================\n"
        "echo.  DeadZone ROM - Format Data Only\n"
        "echo.  WARNING: This will ERASE ALL YOUR USER DATA!\n"
        "echo.  No ROM images will be flashed.\n"
        "echo.  Press any key to continue or close window to cancel.\n"
        "echo. =======================================================\n"
        "echo.\n"
        "pause >nul\n"
        "\n"
        "echo. Make sure your device is in Fastboot mode, then press any key.\n"
        "pause >nul\n"
        "\n"
        "echo. Erasing metadata...\n"
        "%fastboot% erase metadata\n"
        "if errorlevel 1 ( echo Erase metadata failed. Do not disconnect the phone. & exit /B 1 )\n"
        "echo. Erasing userdata...\n"
        "%fastboot% erase userdata\n"
        "if errorlevel 1 ( echo Erase userdata failed. Do not disconnect the phone. & exit /B 1 )\n"
        "echo.\n"
        "echo. Done! Rebooting...\n"
        "%fastboot% reboot\n"
        "pause\n"
        "exit /B 0\n"
    )
    (staging / "windows_format_data_only.bat").write_text(fmt, encoding="utf-8")

    print(f"[PACKAGE] Generated 3 Windows BAT scripts ({len(flash_cmds)} flash commands, {style_label})")
    for cmd in flash_cmds:
        print(f"  {cmd}")

    return errors, warnings, unknown, flash_cmds


def _validate_generated_bat_scripts(
    staging: Path,
    available_imgs: set[str],
    soc_family: str = "mtk",
    flash_map: dict[str, str] | None = None,
) -> list[str]:
    """Sanity-check the generated Windows BAT scripts."""
    errors: list[str] = []
    fmap = flash_map or (MTK_FLASH_MAP if soc_family.lower() == "mtk" else SD_FLASH_MAP)
    is_mtk = soc_family.lower() == "mtk"

    # MTK-specific forbidden patterns
    MTK_FORBIDDEN = ("preloader_a", "preloader_b", "preloader1", "preloader2")

    for sname in _GEN_WIN_SCRIPTS:
        sp = staging / sname
        if not sp.is_file():
            errors.append(f"Generated script not found: {sname}")
            continue
        content = sp.read_text(encoding="utf-8", errors="replace")
        if not content.strip():
            errors.append(f"Generated script is empty: {sname}")
            continue

        # Flash/erase scripts must use %fastboot%
        if sname != "windows_format_data_only.bat":
            if "%fastboot%" not in content:
                errors.append(f"{sname}: missing %fastboot% variable")
            if "flash" not in content.lower():
                errors.append(f"{sname}: no flash commands found")

        # Upgrade script must NOT erase userdata or metadata
        if sname == "windows_install_upgrade.bat":
            if "erase metadata" in content.lower() or "erase userdata" in content.lower():
                errors.append(f"{sname}: upgrade script must not erase userdata or metadata")

        # Validate every images\xxx.img reference is available
        for m in re.finditer(r'images\\([^\s"\'%\r\n]+\.img)', content, re.IGNORECASE):
            ref = m.group(1)
            if ref not in available_imgs:
                errors.append(f"{sname}: references images\\{ref} — not in available images")

        # MTK-specific: no invented _a/_b split or preloader_1/2/a/b patterns
        if is_mtk:
            for forbidden in MTK_FORBIDDEN:
                if forbidden in content.lower():
                    errors.append(
                        f"{sname}: MTK script must not contain '{forbidden}' — "
                        f"use preloader_raw_ab instead"
                    )
            # Check that slot images use _ab (not _a or _b as separate flashes)
            for m in re.finditer(
                r'%fastboot%\s+flash\s+(\S+)\s+"images\\([^"]+\.img)"',
                content, re.IGNORECASE
            ):
                part, img = m.group(1), m.group(2)
                expected  = fmap.get(img)
                if expected is None:
                    continue
                if part != expected:
                    errors.append(
                        f"{sname}: {img} flashed as '{part}' — "
                        f"expected '{expected}' for MTK"
                    )

    return errors


# ── Template script validation ────────────────────────────────────────────────

def _validate_template_scripts(staging: Path, img_dir: Path) -> tuple[list[str], list[str]]:
    """Validate Linux/macOS template scripts: non-empty and have fastboot commands.

    Returns: (errors, warnings)
    """
    errors:   list[str] = []
    warnings: list[str] = []

    available_imgs = {f.name for f in img_dir.glob("*.img")}
    any_has_commands = False

    for sname in _TEMPLATE_SCRIPTS:
        sp = staging / sname
        if not sp.is_file():
            errors.append(f"Template script missing: {sname}")
            continue
        try:
            content = sp.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            errors.append(f"Cannot read {sname}: {exc}")
            continue
        stripped = content.strip()
        if not stripped:
            errors.append(f"Template script is empty: {sname}")
            continue
        non_comment = [
            ln for ln in stripped.splitlines()
            if ln.strip() and not ln.strip().startswith("#")
        ]
        if len(non_comment) < 2:
            warnings.append(f"Template script looks empty: {sname}")
        elif "fastboot" in content.lower():
            any_has_commands = True

    if not any_has_commands and not errors:
        warnings.append("No Linux/macOS template script contains 'fastboot' — verify template")

    return errors, warnings


# ── Validation ────────────────────────────────────────────────────────────────

def _validate_zip(zip_path: Path, available_imgs: set[str]) -> list[str]:
    """Return list of validation errors (empty = OK)."""
    errors: list[str] = []
    if not zip_path.is_file():
        return [f"ZIP not found: {zip_path}"]
    if not zip_path.name.startswith("DeadZone_"):
        errors.append(f"ZIP name must start with 'DeadZone_', got: {zip_path.name}")
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        names_lower = {n.lower() for n in names}

        if not any("images/super.img" in n.lower() for n in names):
            errors.append("images/super.img missing from ZIP")
        if not any(n.lower().endswith(".sh") or n.lower().endswith(".bat") for n in names):
            errors.append("No flash scripts (.sh/.bat) found at ZIP root")

        # Validate every images\xxx.img reference in BAT scripts exists in the ZIP
        for n in names:
            if not n.lower().endswith(".bat"):
                continue
            content = zf.read(n).decode("utf-8", errors="replace")
            for m in re.finditer(r'images\\([^\s"\'%\r\n]+\.img)', content, re.IGNORECASE):
                ref = m.group(1).lower()
                if f"images/{ref}" not in names_lower:
                    errors.append(f"{n}: references images\\{m.group(1)} which is not in ZIP")

        for forbidden in FORBIDDEN_ENTRIES:
            hits = [n for n in names if forbidden.lower() in n.lower()]
            if hits:
                errors.append(f"Forbidden entry '{forbidden}' found: {hits[:3]}")
    return errors


# ── Reports ───────────────────────────────────────────────────────────────────

def _write_flash_scan_report(
    img_dir: Path,
    available_imgs: set[str],
    flash_cmds: list[str],
    unknown_imgs: list[str],
    warnings: list[str],
    staging: Path,
    soc_family: str = "mtk",
    flash_map: dict[str, str] | None = None,
) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    fmap        = flash_map or (MTK_FLASH_MAP if soc_family.lower() == "mtk" else SD_FLASH_MAP)
    flash_order = MTK_FLASH_ORDER if soc_family.lower() == "mtk" else SD_FLASH_ORDER
    style_label = "MTK (_ab partitions)" if soc_family.lower() == "mtk" else "Snapdragon (base partitions)"
    skipped     = [img for img in flash_order if img not in available_imgs]
    missing_req = sorted(img for img in REQUIRED_IMAGES if img not in available_imgs)

    lines = [
        "MEZO Flash Script Scan Report",
        "=" * 40,
        f"Generated:       {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        f"SoC detected:    {soc_family.upper()}",
        f"Template style:  {style_label}",
        "",
        f"Images folder:   {img_dir}",
        f"Images found:    {len(available_imgs)}",
        "",
        "Found images:",
    ]
    for img in sorted(available_imgs):
        part   = fmap.get(img, "(unknown — not flashed)")
        marker = "✓" if img in fmap else "?"
        lines.append(f"  {marker} {img:<35s}  → {part}")

    lines += ["", f"Generated flash commands ({len(flash_cmds)}):"]
    for cmd in flash_cmds:
        lines.append(f"  {cmd}")

    if skipped:
        lines += ["", f"Skipped (not present, {len(skipped)}):"]
        for img in skipped:
            lines.append(f"  {img}")

    if missing_req:
        lines += ["", f"MISSING REQUIRED images ({len(missing_req)}):"]
        for img in missing_req:
            lines.append(f"  ! {img}")
    else:
        lines += ["", "Required images: ALL PRESENT"]

    if unknown_imgs:
        lines += ["", f"Unknown images ({len(unknown_imgs)}) — not flashed:"]
        for img in unknown_imgs:
            lines.append(f"  ? {img}")

    if warnings:
        lines += ["", "Warnings:"]
        for w in warnings:
            lines.append(f"  ! {w}")

    lines += ["", "Generated scripts:"]
    for name in _GEN_WIN_SCRIPTS:
        p = staging / name
        if p.is_file():
            lines.append(f"  {name}  ({p.stat().st_size:,} bytes)")
        else:
            lines.append(f"  {name}  [NOT FOUND]")

    (REPORTS_DIR / "flash_script_scan_report.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(f"[PACKAGE] Flash scan report → {REPORTS_DIR / 'flash_script_scan_report.txt'}")


def _write_manifest(
    zip_path: Path, sha: str,
    imgs_detected: list[str],
    unknown_imgs: list[str],
    flash_cmds: list[str],
    template_preserved: bool,
    uncompressed_bytes: int,
    flash_map: dict[str, str] | None = None,
) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    compressed_bytes = zip_path.stat().st_size
    ratio = uncompressed_bytes / compressed_bytes if compressed_bytes > 0 else 1.0

    lines = [
        "MEZO Final ZIP Manifest",
        "=" * 40,
        f"ZIP name:               {zip_path.name}",
        f"ZIP path:               {zip_path}",
        f"SHA256:                 {sha}",
        f"Compressed size:        {compressed_bytes:,} bytes ({compressed_bytes / 1024**2:.1f} MiB)",
        f"Uncompressed size:      {uncompressed_bytes:,} bytes ({uncompressed_bytes / 1024**2:.1f} MiB)",
        f"Compression ratio:      {ratio:.3f}x",
        f"Template preserved:     {'YES' if template_preserved else 'NO'}",
        f"Win scripts generated:  YES (from actual images)",
        "",
        f"Images detected ({len(imgs_detected)}):",
    ]
    fmap = flash_map or MTK_FLASH_MAP
    for img in sorted(imgs_detected):
        part = fmap.get(img, "(extra — not flashed)")
        lines.append(f"  {img:<35s}  → fastboot flash {part}")

    if unknown_imgs:
        lines += ["", f"Unknown images ({len(unknown_imgs)}) — not flashed:"]
        for img in sorted(unknown_imgs):
            lines.append(f"  {img}")

    if flash_cmds:
        lines += ["", f"Generated flash commands ({len(flash_cmds)}):"]
        for cmd in flash_cmds:
            lines.append(f"  {cmd}")

    forbidden_found: list[str] = []
    lines += ["", "Files inside ZIP:"]
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


def _write_summary(
    zip_path: Path, sha: str, cfg: dict,
    images: list[str], scripts: list[str],
    flash_cmds: list[str],
    unknown_imgs: list[str],
    template_used: bool = True, template_preserved: bool = True,
    nested_root: str | None = None,
    uncompressed_bytes: int = 0,
    zip_tool: str = "python-zipfile",
) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    compressed_bytes = zip_path.stat().st_size
    ratio = uncompressed_bytes / compressed_bytes if compressed_bytes > 0 else 1.0

    summary: dict = {
        "codename":                   cfg["codename"],
        "soc":                        cfg.get("soc_family", ""),
        "rom_os_version":             _read("base_rom_code.txt"),
        "android_version":            _read("androidver.txt"),
        "final_zip_name":             zip_path.name,
        "final_zip_path":             str(zip_path),
        "sha256":                     sha,
        "size_bytes":                 compressed_bytes,
        "file_count":                 0,
        "images_detected":            images,
        "flash_scripts_checked":      scripts,
        "flash_commands_generated":   True,
        "generated_flash_commands":   flash_cmds,
        "unknown_images":             unknown_imgs,
        "missing_images_referenced":  [],
        "scripts_empty":              False,
        "template_archive":           TEMPLATE_RAR.name,
        "template_nested_root":       nested_root or "",
        "template_flattened":         nested_root is not None,
        "template_used":              template_used,
        "template_preserved":         template_preserved,
        "linux_scripts_preserved":    True,
        "macos_scripts_preserved":    True,
        "win_scripts_generated":      True,
        "scripts_generated":          True,
        "bin_exists":                 True,
        "bin_renamed":                False,
        "images_added":               len(images) > 0,
        "compression_method":         "deflate9",
        "compressed_size_bytes":      compressed_bytes,
        "uncompressed_size_bytes":    uncompressed_bytes,
        "compression_ratio":          round(ratio, 4),
        "zip_tool_used":              zip_tool,
        "forbidden_entries_found":    [],
    }
    with zipfile.ZipFile(zip_path) as zf:
        summary["file_count"] = len(zf.namelist())
        for f in FORBIDDEN_ENTRIES:
            hits = [n for n in zf.namelist() if f.lower() in n.lower()]
            summary["forbidden_entries_found"].extend(hits)

    (REPORTS_DIR / "final_zip_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _gen_pipeline_scan_report() -> None:
    """Scan key pipeline scripts and workflows; write a static analysis report."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "MEZO Pipeline Script Scan Report",
        "=" * 40,
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        "",
    ]

    files_to_scan = [
        ("build.sh",                              WORK_DIR / "build.sh"),
        ("packROM.sh",                            WORK_DIR / "packROM.sh"),
        ("scripts/package_rom.py",                WORK_DIR / "scripts" / "package_rom.py"),
        ("scripts/pixeldrain_upload.py",          WORK_DIR / "scripts" / "pixeldrain_upload.py"),
        ("scripts/tg_watch.py",                   WORK_DIR / "scripts" / "tg_watch.py"),
        ("scripts/telegram.py",                   WORK_DIR / "scripts" / "telegram.py"),
        (".github/workflows/mezo_mtk.yml",        WORK_DIR / ".github" / "workflows" / "mezo_mtk.yml"),
        (".github/workflows/mezo_snapdragon.yml", WORK_DIR / ".github" / "workflows" / "mezo_snapdragon.yml"),
    ]

    _MARKER_RE = re.compile(
        r'\[(?:UNPACK|MODS|PATCH|REPACK|VBMETA|PACKAGE|ZIP|UPLOAD|ERROR|DONE|TELEGRAM)\]'
    )

    for label, fpath in files_to_scan:
        lines.append(f"── {label} ──")
        if not fpath.is_file():
            lines.append("  [NOT FOUND]")
            lines.append("")
            continue

        content = fpath.read_text(encoding="utf-8", errors="replace")
        lines.append(f"  size: {fpath.stat().st_size:,} bytes")

        tg_calls = [
            ln.strip() for ln in content.splitlines()
            if "telegram.py" in ln and any(k in ln for k in ("start", "update", "finish", "heartbeat"))
        ]
        if tg_calls:
            lines.append("  telegram calls:")
            for t in tg_calls[:12]:
                lines.append(f"    {t}")

        markers = sorted(set(_MARKER_RE.findall(content)))
        if markers:
            lines.append(f"  log markers: {', '.join(markers)}")

        refs: list[str] = []
        if "final_zip_path.txt" in content:
            refs.append("final_zip_path.txt")
        if "PixelDrain" in content or "pixeldrain" in content.lower():
            refs.append("PixelDrain")
        if "telegram" in content.lower():
            refs.append("Telegram")
        if refs:
            lines.append(f"  references: {', '.join(refs)}")

        if label.endswith(".yml"):
            issues: list[str] = []
            if "build_rom" in content:
                issues.append("deprecated stage 'build_rom'")
            if "pack_rom" in content:
                issues.append("deprecated stage 'pack_rom'")
            for sid in ("unpack", "mods", "rebuild", "super", "vbmeta", "zip", "upload_pixeldrain"):
                if f"update {sid}" in content:
                    lines.append(f"  stage tracked: {sid}")
            if issues:
                lines.append("  WARNINGS: " + ", ".join(issues))
            else:
                lines.append("  stage IDs: OK")

        lines.append("")

    (REPORTS_DIR / "pipeline_script_scan_report.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(f"[PACKAGE] Pipeline scan → {REPORTS_DIR / 'pipeline_script_scan_report.txt'}")


# ── Main packaging logic ──────────────────────────────────────────────────────

def package() -> Path:
    # ── Read device info ──────────────────────────────────────────────────────
    codename     = _read("device_f.txt") or _read("device_code.txt") or "unknown"
    rom_version  = _sanitize_name(_read("base_rom_code.txt") or "UNKNOWN")
    android_ver  = re.sub(r"\D", "", _read("androidver.txt") or "")
    baserom_type = _read("romtype.txt") or "payload"

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

    # ── Extract template RAR — required ───────────────────────────────────────
    if not TEMPLATE_RAR.is_file():
        print(f"[PACKAGE] ERROR: Template RAR not found: {TEMPLATE_RAR}", file=sys.stderr)
        sys.exit(1)

    print(f"[PACKAGE] Extracting template: {TEMPLATE_RAR}")
    template_used = _extract_rar(TEMPLATE_RAR, staging)
    if not template_used:
        print("[PACKAGE] ERROR: RAR extraction failed — unrar, 7z, or bsdtar required", file=sys.stderr)
        sys.exit(1)

    nested_root = _flatten_template(staging)

    # ── Verify template: bin/ + Linux/macOS scripts ───────────────────────────
    # Windows scripts are generated; only Linux/macOS scripts must come from template.
    missing_template = [s for s in _TEMPLATE_SCRIPTS if not (staging / s).is_file()]
    bin_ok = (staging / "bin").is_dir()
    if missing_template or not bin_ok:
        print("[PACKAGE] ERROR: Template extraction incomplete!", file=sys.stderr)
        if not bin_ok:
            print("  bin/ directory missing from template", file=sys.stderr)
        for s in missing_template:
            print(f"  Missing template script: {s}", file=sys.stderr)
        sys.exit(1)
    template_preserved = True
    print(f"[PACKAGE] Template verified: bin/ present, {len(_TEMPLATE_SCRIPTS)} Linux/macOS scripts intact")

    # ── images/ directory ─────────────────────────────────────────────────────
    img_dir = staging / "images"
    img_dir.mkdir(exist_ok=True)

    copied_imgs: list[str] = []

    # super.img — must exist (created by packROM.sh)
    super_src = BUILD_IMAGES / "super.img"
    if super_src.is_file():
        shutil.copy2(super_src, img_dir / "super.img")
        copied_imgs.append("super.img")
        print(f"[PACKAGE] Copied super.img ({super_src.stat().st_size / 1024**2:.0f} MiB)")
    else:
        print("[PACKAGE] ERROR: build/baserom/images/super.img not found!", file=sys.stderr)
        sys.exit(1)

    # Other .img files
    src_dirs = [BUILD_IMAGES]
    if baserom_type == "br" and BUILD_FW.is_dir():
        src_dirs.append(BUILD_FW)

    for src_dir in src_dirs:
        if not src_dir.is_dir():
            continue
        for img in sorted(src_dir.glob("*.img")):
            if img.name == "super.img":
                continue
            if img.name.endswith(".zst"):
                continue
            shutil.copy2(img, img_dir / img.name)
            copied_imgs.append(img.name)

    available_imgs = {p.name for p in img_dir.glob("*.img")}
    print(f"[PACKAGE] Images collected: {len(copied_imgs)} files")
    print(f"  {', '.join(copied_imgs[:8])}{'...' if len(copied_imgs) > 8 else ''}")

    # ── SoC-specific flash map ────────────────────────────────────────────────
    soc_family = cfg.get("soc_family", "mtk").lower()
    active_flash_map = MTK_FLASH_MAP if soc_family == "mtk" else SD_FLASH_MAP
    print(f"[PACKAGE] SoC: {soc_family.upper()} — using {'MTK _ab' if soc_family == 'mtk' else 'Snapdragon base'} partition names")

    # ── Validate required images ──────────────────────────────────────────────
    missing_required = sorted(req for req in REQUIRED_IMAGES if req not in available_imgs)
    if missing_required:
        print("[PACKAGE] ERROR: Required images missing:", file=sys.stderr)
        for img in missing_required:
            print(f"  ! {img}", file=sys.stderr)
        sys.exit(1)

    # ── Generate Windows BAT scripts from actual images ───────────────────────
    win_errors, win_warnings, unknown_imgs, flash_cmds = _gen_windows_scripts(
        staging, img_dir, _sanitize_name(codename), rom_version, soc_family=soc_family
    )
    if win_errors:
        print("[PACKAGE] Windows script generation ERRORS:", file=sys.stderr)
        for e in win_errors:
            print(f"  ! {e}", file=sys.stderr)
        sys.exit(1)
    for w in win_warnings:
        print(f"[PACKAGE] WARN: {w}", file=sys.stderr)

    # ── Validate generated BAT scripts ────────────────────────────────────────
    bat_errors = _validate_generated_bat_scripts(
        staging, available_imgs, soc_family=soc_family, flash_map=active_flash_map
    )
    if bat_errors:
        print("[PACKAGE] BAT script validation ERRORS:", file=sys.stderr)
        for e in bat_errors:
            print(f"  ! {e}", file=sys.stderr)
        sys.exit(1)
    print(f"[PACKAGE] BAT validation: PASS ({soc_family.upper()} style)")

    # ── Validate Linux/macOS template scripts ─────────────────────────────────
    tmpl_errors, tmpl_warnings = _validate_template_scripts(staging, img_dir)
    if tmpl_errors:
        print("[PACKAGE] Template script validation ERRORS:", file=sys.stderr)
        for e in tmpl_errors:
            print(f"  ! {e}", file=sys.stderr)
        sys.exit(1)
    for w in tmpl_warnings:
        print(f"[PACKAGE] WARN: {w}", file=sys.stderr)

    # ── Write flash scan report ───────────────────────────────────────────────
    _write_flash_scan_report(
        img_dir, available_imgs, flash_cmds, unknown_imgs, win_warnings, staging,
        soc_family=soc_family, flash_map=active_flash_map,
    )

    # ── Create ZIP ────────────────────────────────────────────────────────────
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = OUT_DIR / zip_name

    print(f"[ZIP] Creating final ZIP: {zip_path}")
    uncompressed_bytes = 0
    zip_tool = "python-zipfile-deflate9"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for f in sorted(staging.rglob("*")):
            if f.is_file():
                arcname = f.relative_to(staging)
                zf.write(f, arcname)
                uncompressed_bytes += f.stat().st_size

    size_mib = zip_path.stat().st_size / 1024**2
    ratio    = uncompressed_bytes / zip_path.stat().st_size if zip_path.stat().st_size > 0 else 1.0
    print(f"[PACKAGE] ZIP created: {size_mib:.1f} MiB  (ratio {ratio:.2f}x)")

    # ── Validate ZIP ──────────────────────────────────────────────────────────
    zip_errors = _validate_zip(zip_path, available_imgs)
    if zip_errors:
        print("[PACKAGE] VALIDATION ERRORS:", file=sys.stderr)
        for e in zip_errors:
            print(f"  ! {e}", file=sys.stderr)
        sys.exit(1)
    print("[PACKAGE] Validation: PASS")

    # ── Reports ───────────────────────────────────────────────────────────────
    sha = _sha256(zip_path)
    scripts_in_zip = [
        n for n in zipfile.ZipFile(zip_path).namelist()
        if n.endswith((".sh", ".bat")) and "/" not in n
    ]

    _write_manifest(
        zip_path, sha,
        imgs_detected=copied_imgs,
        unknown_imgs=unknown_imgs,
        flash_cmds=flash_cmds,
        template_preserved=template_preserved,
        uncompressed_bytes=uncompressed_bytes,
        flash_map=active_flash_map,
    )
    _write_summary(
        zip_path, sha, cfg,
        images=copied_imgs,
        scripts=scripts_in_zip,
        flash_cmds=flash_cmds,
        unknown_imgs=unknown_imgs,
        template_used=template_used,
        template_preserved=template_preserved,
        nested_root=nested_root,
        uncompressed_bytes=uncompressed_bytes,
        zip_tool=zip_tool,
    )
    _gen_pipeline_scan_report()

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
    ap.parse_args()
    package()


if __name__ == "__main__":
    main()
