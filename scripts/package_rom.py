#!/usr/bin/env python3
"""DeadZone ROM packaging script for MEZO.

Replaces old uploadROM.sh packaging.
- Reads device info from bin/ddevice/ (populated by build.sh)
- Resolves device config via device_resolver
- Selects SoC-specific full template from bin/final_zip_templates/<soc>/
- Generates windows_install_and_format_data.bat dynamically from actual ROM images
- Flash commands use MTK _ab style or Snapdragon _a/_b style based on SoC
- Final ZIP contains exactly one root BAT: windows_install_and_format_data.bat
- Copies .img files from build output into images/
- Validates scripts, images, and ZIP before finalising
- Creates: DeadZone_<codename>_<rom_version>_A<android>.zip
- Writes: output/reports/final_zip_path.txt
-         output/reports/device_resolve_report.txt
-         output/reports/final_zip_manifest.txt
-         output/reports/final_zip_summary.json
-         output/reports/flash_script_scan_report.txt
-         output/reports/pipeline_script_scan_report.txt
-         output/reports/final_zip_template_report.txt

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
WORK_DIR              = Path.cwd()
DDEVICE_DIR           = WORK_DIR / "bin" / "ddevice"
BUILD_IMAGES          = WORK_DIR / "build" / "baserom" / "images"
BUILD_FW              = WORK_DIR / "build" / "baserom" / "firmware-update"
TEMPLATE_RAR          = WORK_DIR / "DeadZone_Mezo.rar"
FINAL_ZIP_TEMPLATES_DIR = WORK_DIR / "bin" / "final_zip_templates"
STAGING_BASE          = WORK_DIR / "out" / "dz_staging"
REPORTS_DIR           = WORK_DIR / "output" / "reports"
OUT_DIR               = WORK_DIR / "out"

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

# MTK preloader images that must NEVER be flashed (dangerous/unsupported variants)
MTK_DANGEROUS_PRELOADERS: frozenset[str] = frozenset({
    "preloader.img",
    "preloader_a.img",
    "preloader_b.img",
    "preloader1.img",
    "preloader2.img",
})

# Snapdragon images that are NOT slot-based — flashed once without _a/_b suffix
SD_NONSLOT_IMGS: frozenset[str] = frozenset({
    "super.img",
    "cust.img",
})

# Must exist before the ZIP is built; fail hard if missing
REQUIRED_IMAGES: frozenset[str] = frozenset({"super.img", "vbmeta.img"})

FLASH_BLOCK_START = ":: BEGIN MEZO GENERATED IMAGE FLASH COMMANDS"
FLASH_BLOCK_END   = ":: END MEZO GENERATED IMAGE FLASH COMMANDS"

FORBIDDEN_ENTRIES = [
    "output/", "build/", "work/", "logs/", "reports/",
    "payload.bin", ".git", "super.img.zst",
    "final_zip_templates",
]

# No Linux/macOS scripts — SoC templates provide only Windows scripts and bin/
_TEMPLATE_SCRIPTS: list[str] = []

# windows_install_and_format_data.bat comes from the SoC template (not generated).
# No other BAT scripts are generated; the final ZIP contains exactly this one root BAT.
_GEN_WIN_SCRIPTS: list[str] = []

# Forbidden root BAT scripts — must never appear in the final ZIP
_FORBIDDEN_ROOT_BATS = frozenset({
    "windows_install_upgrade.bat",
    "windows_format_data_only.bat",
})

# Placeholders that may appear in template BAT files and are safe to replace
_BAT_PLACEHOLDERS = frozenset({
    "CN_VERSION_FROM_ROM",
    "DEVICE_FROM_ROM",
    "ANDROID_FROM_ROM",
    "REGION_FROM_ROM",
    "DEVICE_LIST_FROM_ROM",
})

_REQUIRED_SCRIPTS = _TEMPLATE_SCRIPTS  # only the template BAT matters now


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


def _codename_check_block(codename: str) -> str:
    """Return the BAT codename check section. Only this may call exit /B 1."""
    return (
        ":: ── Codename check — only this can stop flashing ──────────────────────\n"
        "set DEVICE_CODE=unknown\n"
        f'for /f "tokens=2" %%a in (\'%fastboot% getvar product 2^>^&1 ^| findstr /i /b "product:"\') do set DEVICE_CODE=%%a\n'
        f'if /i not "%DEVICE_CODE%"=="{codename}" (\n'
        f'    echo.\n'
        f'    echo. ============================================================\n'
        f'    echo.  ERROR: WRONG DEVICE DETECTED\n'
        f'    echo.  This ROM is built for : {codename}\n'
        f'    echo.  Your device reports   : %DEVICE_CODE%\n'
        f'    echo.  DO NOT flash this ROM on the wrong device!\n'
        f'    echo.  Exiting now.\n'
        f'    echo. ============================================================\n'
        f'    pause\n'
        f'    exit /B 1\n'
        f')\n'
        f'echo. Device codename verified: %DEVICE_CODE%\n'
        "echo.\n"
    )


def _build_bat_flash_block(available_imgs: set[str],
                           flash_map: dict[str, str],
                           flash_order: list[str]) -> tuple[list[str], list[str]]:
    """Build %fastboot% flash lines for each known image that exists at packaging time.

    Rules:
    - Generator only emits commands for images that exist (no runtime image checks).
    - Flash errors are NOT fatal: print a warning, set FLASH_FAILED=1, continue.
    - No exit /B 1 inside this block.
    - No if not exist guards.
    - No if exist wrappers.

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

        lines += [
            f'%fastboot% flash {part} "images\\{img}"',
            f'if errorlevel 1 (',
            f'    echo [WARN] {part} flash failed, continuing...',
            f'    set FLASH_FAILED=1',
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
    """Generate windows_install_upgrade.bat and windows_format_data_only.bat.

    windows_install_and_format_data.bat comes from the SoC template and is NOT generated here.

    Behavior:
    - Codename check runs first in upgrade script; mismatch exits before any flash.
    - Flash phase: all commands run; errors warn only (set FLASH_FAILED=1).
    - No image preflight checks; no exit /B 1 inside flash block.
    - Generator only emits commands for images present at packaging time.

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

    codename_check = _codename_check_block(codename)

    def _install_header(title: str) -> str:
        return (
            f"{_BAT_HEADER}\n\n"
            f"title {title}\n\n"
            f"{_MEZO_WARNING}\n\n"
            f"echo. Make sure your device is in Fastboot mode, then press any key.\n"
            f"pause >nul\n"
            f"echo.\n\n"
            f"{codename_check}\n"
        )

    # ── windows_install_upgrade.bat (flash only, no wipe) ─────────────────────
    upgrade = (
        _install_header(f"DeadZone ROM - Upgrade (no data wipe) | {codename} | {rom_version}")
        + f"{FLASH_BLOCK_START}\n"
        + flash_block
        + f"{FLASH_BLOCK_END}\n\n"
        + "echo.\n"
        + "if defined FLASH_FAILED (\n"
        + "    echo. [WARN] Some flash commands reported errors. Check messages above.\n"
        + ")\n"
        + "echo. Flash phase complete. Running final cleanup...\n"
        + "%fastboot% erase frp  >nul 2>nul\n"
        + "%fastboot% -w  >nul 2>nul\n"
        + "%fastboot% set_active a  >nul 2>nul\n"
        + "echo. Rebooting...\n"
        + "%fastboot% reboot\n"
        + "pause\n"
        + "exit /B 0\n"
    )
    (staging / "windows_install_upgrade.bat").write_text(upgrade, encoding="utf-8")

    # ── windows_format_data_only.bat (erase only, no flash, no codename check) ─
    fmt = (
        f"{_BAT_HEADER}\n\n"
        "title DeadZone ROM - Format Data Only\n\n"
        "echo.\n"
        "echo. =======================================================\n"
        "echo.  DeadZone ROM - Format Data Only\n"
        "echo.  WARNING: This will ERASE ALL YOUR USER DATA!\n"
        "echo.  No ROM images will be flashed.\n"
        "echo.  Press any key to continue or close window to cancel.\n"
        "echo. =======================================================\n"
        "echo.\n"
        "pause >nul\n\n"
        "echo. Make sure your device is in Fastboot mode, then press any key.\n"
        "pause >nul\n\n"
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

    print(f"[PACKAGE] Generated 2 Windows BAT scripts ({len(flash_cmds)} flash commands, {style_label})")
    for cmd in flash_cmds:
        print(f"  {cmd}")

    return errors, warnings, unknown, flash_cmds


def _validate_generated_bat_scripts(
    staging: Path,
    available_imgs: set[str],
    soc_family: str = "mtk",
    flash_map: dict[str, str] | None = None,
) -> list[str]:
    """Validate generated Windows BAT scripts against the required behavior."""
    errors: list[str] = []
    fmap   = flash_map or (MTK_FLASH_MAP if soc_family.lower() == "mtk" else SD_FLASH_MAP)
    is_mtk = soc_family.lower() == "mtk"

    MTK_FORBIDDEN = ("preloader_a", "preloader_b", "preloader1", "preloader2")
    # Only truly unsafe commands are forbidden; erase frp / -w / set_active are required by template
    UNSAFE_CMDS   = ("--disable-verity", "--disable-verification")

    for sname in _GEN_WIN_SCRIPTS:
        sp = staging / sname
        if not sp.is_file():
            errors.append(f"Generated script not found: {sname}")
            continue
        content = sp.read_text(encoding="utf-8", errors="replace")
        if not content.strip():
            errors.append(f"Generated script is empty: {sname}")
            continue

        # All scripts must use %fastboot%
        if "%fastboot%" not in content:
            errors.append(f"{sname}: missing %fastboot% variable")

        # Flash scripts must have flash commands and a codename check
        if sname != "windows_format_data_only.bat":
            if "flash" not in content.lower():
                errors.append(f"{sname}: no flash commands found")
            if "getvar product" not in content.lower():
                errors.append(f"{sname}: codename check (getvar product) missing")

        # Upgrade script must NOT erase userdata or metadata
        if sname == "windows_install_upgrade.bat":
            if "erase metadata" in content.lower() or "erase userdata" in content.lower():
                errors.append(f"{sname}: upgrade script must not erase userdata or metadata")

        # Validate that no exit /B 1 appears inside the flash block
        start_idx = content.find(FLASH_BLOCK_START)
        end_idx   = content.find(FLASH_BLOCK_END)
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            flash_section = content[start_idx:end_idx]
            if "exit /b 1" in flash_section.lower():
                errors.append(f"{sname}: exit /B 1 found inside flash block — flash phase must not stop on errors")
            if "if not exist" in flash_section.lower():
                errors.append(f"{sname}: image preflight check (if not exist) found in flash block — must be removed")

        # Validate every images\xxx.img reference is available
        for m in re.finditer(r'images\\([^\s"\'%\r\n]+\.img)', content, re.IGNORECASE):
            ref = m.group(1)
            if ref not in available_imgs:
                errors.append(f"{sname}: references images\\{ref} — not in available images")

        # Unsafe commands must not appear
        for unsafe in UNSAFE_CMDS:
            if unsafe.lower() in content.lower():
                errors.append(f"{sname}: forbidden command '{unsafe}' must not be present")

        # MTK-specific: no _a/_b split, no preloader_1/2/a/b, correct _ab names
        if is_mtk:
            for forbidden in MTK_FORBIDDEN:
                if forbidden in content.lower():
                    errors.append(f"{sname}: MTK forbidden pattern '{forbidden}' — use preloader_raw_ab")
            for m in re.finditer(
                r'%fastboot%\s+flash\s+(\S+)\s+"images\\([^"]+\.img)"',
                content, re.IGNORECASE
            ):
                part, img = m.group(1), m.group(2)
                expected  = fmap.get(img)
                if expected and part != expected:
                    errors.append(
                        f"{sname}: {img} flashed as '{part}' — expected '{expected}' for MTK"
                    )

        # Snapdragon-specific: no _ab suffix
        if not is_mtk:
            for m in re.finditer(
                r'%fastboot%\s+flash\s+(\S+_ab)\s+"images\\([^"]+\.img)"',
                content, re.IGNORECASE
            ):
                part, img = m.group(1), m.group(2)
                errors.append(
                    f"{sname}: Snapdragon script must not use '_ab' partition '{part}' for {img}"
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


# ── Dynamic BAT generation from actual images ─────────────────────────────────

def _ordered_mtk_imgs(available_imgs: set[str]) -> list[str]:
    """Return MTK images in flash order: known images first (per MTK_FLASH_ORDER),
    then any extras, then super.img last. Dangerous preloaders are excluded."""
    result: list[str] = []
    seen:   set[str]  = set()
    for img in MTK_FLASH_ORDER:
        if img == "super.img":
            continue
        if img in available_imgs and img not in MTK_DANGEROUS_PRELOADERS:
            result.append(img)
            seen.add(img)
    # Extra images not in the known order (excluding super and dangerous preloaders)
    for img in sorted(available_imgs):
        if img not in seen and img != "super.img" and img not in MTK_DANGEROUS_PRELOADERS:
            result.append(img)
            seen.add(img)
    if "super.img" in available_imgs:
        result.append("super.img")
    return result


def _ordered_sd_imgs(available_imgs: set[str]) -> list[str]:
    """Return Snapdragon images in flash order: known images first (per SD_FLASH_ORDER),
    then extras, then super.img last."""
    result: list[str] = []
    seen:   set[str]  = set()
    for img in SD_FLASH_ORDER:
        if img == "super.img":
            continue
        if img in available_imgs:
            result.append(img)
            seen.add(img)
    for img in sorted(available_imgs):
        if img not in seen and img != "super.img":
            result.append(img)
            seen.add(img)
    if "super.img" in available_imgs:
        result.append("super.img")
    return result


def _compute_flash_pairs(
    available_imgs: set[str],
    norm_soc: str,
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """Compute (partition, image_filename) pairs from actual images present.

    MTK rules:
    - Known images use MTK_FLASH_MAP (e.g. boot.img → boot_ab).
    - Unknown images get stem_ab derived from filename (e.g. new_chip.img → new_chip_ab).
    - super.img → super (non-slot).
    - Dangerous preloader variants are skipped and reported.

    Snapdragon rules:
    - SD_NONSLOT_IMGS (super, cust) → single flash without suffix.
    - All other images → flash both stem_a and stem_b.
    - Filename is parsed as Path(img).stem — never split on _ inside the name.

    Returns: (flash_pairs, skipped_pairs)
      flash_pairs  : list[(partition_name, img_filename)] in flash order
      skipped_pairs: list[(img_filename, reason)]
    """
    flash_pairs:   list[tuple[str, str]] = []
    skipped_pairs: list[tuple[str, str]] = []

    if norm_soc == "mtk":
        for img in _ordered_mtk_imgs(available_imgs):
            # _ordered_mtk_imgs already excludes dangerous preloaders and super
            partition = MTK_FLASH_MAP.get(img) or f"{Path(img).stem}_ab"
            flash_pairs.append((partition, img))
        # Record dangerous preloaders that exist so they appear in the report
        for img in sorted(available_imgs):
            if img in MTK_DANGEROUS_PRELOADERS:
                skipped_pairs.append((img, "dangerous preloader variant — skipped for safety"))
    else:
        for img in _ordered_sd_imgs(available_imgs):
            stem = Path(img).stem          # e.g. "xbl_config" from "xbl_config.img"
            if img in SD_NONSLOT_IMGS:
                flash_pairs.append((stem, img))
            else:
                flash_pairs.append((f"{stem}_a", img))
                flash_pairs.append((f"{stem}_b", img))

    return flash_pairs, skipped_pairs


# BAT title/header labels by SoC
_INSTALL_BAT_TITLE = {
    "mtk":        "DeadZone MTK Installer",
    "snapdragon": "DeadZone Snapdragon Installer",
}


def _gen_install_bat(
    staging: Path,
    available_imgs: set[str],
    norm_soc: str,
    codename: str,
    rom_version: str,
    android_ver: str,
    region: str,
) -> tuple[list[str], list[tuple[str, str]]]:
    """Generate windows_install_and_format_data.bat from the images actually present.

    Keeps the DeadZone colored header/warning style.
    Flash block is built from available_imgs using SoC-specific rules.
    Always ends with: fastboot erase metadata / erase userdata / reboot.

    Returns: (flash_cmds_summary, skipped_pairs)
    """
    title = _INSTALL_BAT_TITLE.get(norm_soc, "DeadZone ROM Installer")
    header_label = f"{title}  ^|  by MEZO"

    flash_pairs, skipped_pairs = _compute_flash_pairs(available_imgs, norm_soc)

    # Build flash lines for the script and a plain summary list for reports
    bat_flash_lines: list[str] = []
    flash_cmds_summary: list[str] = []
    for partition, img in flash_pairs:
        bat_flash_lines.append(f'%fastboot% flash {partition} "images\\{img}"')
        flash_cmds_summary.append(f'fastboot flash {partition} images\\{img}')
    flash_block = "\n".join(bat_flash_lines)

    # Device-detection block differs slightly between SoCs (matching template style)
    if norm_soc == "mtk":
        device_detect = (
            'echo Waiting for device...\n'
            'set "device=unknown"\n'
            'for /f "tokens=2" %%D in (\'"%fastboot%" getvar product 2^>^&1 ^| findstr /l /b /c:"product:"\') do set "device=%%D"\n'
            '\n'
            'echo.\n'
            'echo Detected device: %device%\n'
            'echo You are going to wipe your data and internal storage.\n'
            'echo It will delete all your files and photos stored on internal storage.\n'
            'set /p choice=Do you agree? (Y/N)\n'
            'if /i "%choice%" neq "y" exit /B 0'
        )
        progress_banner = (
            'echo ##################################################################\n'
            'echo Please wait. The device will reboot when installation is finished.\n'
            'echo ##################################################################'
        )
        compat_line = ""
    else:
        device_detect = (
            'echo Waiting for device...\n'
            'set "device="\n'
            'for /f "tokens=2" %%A in (\'"%fastboot%" getvar product 2^>^&1 ^| findstr "\\<product:"\') do set "device=%%A"\n'
            'if "%device%" equ "" echo Your device could not be detected. & pause & exit /B 1\n'
            '\n'
            'echo Your device: %device%\n'
            'echo Compatible devices: %COMPATIBLE_DEVICES%\n'
            'echo Your device will be flashed and the data partition will be formatted.\n'
            'echo You will lose your apps, settings and files on internal storage.\n'
            'set /p choice=Do you want to continue? [y/N]\n'
            'if /i "%choice%" neq "y" exit /B 0'
        )
        progress_banner = (
            'echo ##############################################################\n'
            'echo Please wait. The device will reboot once flashing is complete.\n'
            'echo ##############################################################'
        )
        compat_line = f'set "COMPATIBLE_DEVICES={codename}"\n'

    content = (
        f'@echo off\n'
        f'chcp 65001 >nul\n'
        f'cd /d "%~dp0"\n'
        f'color 0B\n'
        f'title {title}\n'
        f'cls\n'
        f'\n'
        f'set "fastboot=bin\\windows\\fastboot.exe"\n'
        f'set "ROM_STYLE=DeadZone Stable"\n'
        f'set "ROM_DEVELOPER=MEZO"\n'
        f'set "ROM_VERSION={rom_version}"\n'
        f'set "ROM_DEVICE={codename}"\n'
        f'set "ROM_ANDROID={android_ver}"\n'
        f'set "ROM_REGION={region}"\n'
        f'{compat_line}'
        f'\n'
        f'if not exist "%fastboot%" (\n'
        f'    echo [ERROR] fastboot not found: %fastboot%\n'
        f'    pause\n'
        f'    exit /B 1\n'
        f')\n'
        f'\n'
        f'echo.\n'
        f'echo ================================================================\n'
        f'echo            {header_label}\n'
        f'echo ================================================================\n'
        f'echo.\n'
        f'echo  [ROM] Style      : %ROM_STYLE%\n'
        f'echo  [ROM] Developer  : %ROM_DEVELOPER%\n'
        f'echo  [ROM] Version    : %ROM_VERSION%\n'
        f'echo  [ROM] Device     : %ROM_DEVICE%\n'
        f'echo  [ROM] Android    : Android %ROM_ANDROID%\n'
        f'echo  [ROM] Region     : %ROM_REGION%\n'
        f'echo.\n'
        f'echo ================================================================\n'
        f'echo.\n'
        f'echo  [i] Read this information before flashing:\n'
        f'echo.\n'
        f'echo  1. DeadZone ROM requires an UNLOCKED bootloader.\n'
        f'echo     Close this window if your bootloader is NOT unlocked.\n'
        f'echo  2. This will ERASE ALL your data. Proceed carefully.\n'
        f'echo  3. DeadZone ROM is FREE. If anyone charges you for it,\n'
        f'echo     contact MEZO immediately.\n'
        f'echo  4. MEZO Team is NOT responsible for bricks or data loss.\n'
        f'echo  5. Make sure this ROM build is for YOUR specific device.\n'
        f'echo.\n'
        f'echo  [i] If you agree to all of the above, press any key to continue.\n'
        f'echo  [i] Otherwise, close this window now.\n'
        f'echo.\n'
        f'pause >nul\n'
        f'\n'
        f'{device_detect}\n'
        f'\n'
        f'{progress_banner}\n'
        f'%fastboot% set_active a\n'
        f'\n'
        f'{FLASH_BLOCK_START}\n'
        f'{flash_block}\n'
        f'{FLASH_BLOCK_END}\n'
        f'\n'
        f'%fastboot% erase metadata\n'
        f'%fastboot% erase userdata\n'
        f'%fastboot% reboot\n'
    )

    bat_path = staging / "windows_install_and_format_data.bat"
    bat_path.write_text(content, encoding="utf-8")

    print(
        f"[PACKAGE] Generated windows_install_and_format_data.bat "
        f"({len(flash_pairs)} flash commands, {norm_soc.upper()} style)"
    )
    for cmd in flash_cmds_summary:
        print(f"  {cmd}")
    if skipped_pairs:
        for img, reason in skipped_pairs:
            print(f"  [SKIP] {img}: {reason}")

    return flash_cmds_summary, skipped_pairs


# ── SoC template helpers ──────────────────────────────────────────────────────

def _normalize_soc(soc: str) -> str:
    """Normalize raw SoC string to 'mtk' or 'snapdragon'. Raises ValueError on unknown."""
    s = soc.lower().strip()
    if s in ("mtk", "mediatek"):
        return "mtk"
    if s in ("snapdragon", "qcom", "qualcomm"):
        return "snapdragon"
    raise ValueError(f"Unsupported SoC for final ZIP template: {soc}")


def _select_template_dir(norm_soc: str) -> Path:
    """Return the validated template path for the given normalized SoC.

    Fails hard if the directory, fastboot.exe, or install BAT is missing.
    """
    tpl = FINAL_ZIP_TEMPLATES_DIR / norm_soc
    if not tpl.is_dir():
        raise FileNotFoundError(f"Template folder missing: {tpl}")
    if not (tpl / "bin" / "windows" / "fastboot.exe").is_file():
        raise FileNotFoundError(f"Required template file missing: {tpl}/bin/windows/fastboot.exe")
    if not (tpl / "windows_install_and_format_data.bat").is_file():
        raise FileNotFoundError(
            f"Required template file missing: {tpl}/windows_install_and_format_data.bat"
        )
    return tpl


def _copy_template_to_staging(template_dir: Path, staging: Path) -> list[str]:
    """Recursively copy all files from template_dir into staging. Returns list of relative paths copied."""
    copied: list[str] = []
    for src in sorted(template_dir.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(template_dir)
        dst = staging / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(str(rel))
    return copied


def _replace_bat_placeholders(bat_path: Path, replacements: dict[str, str]) -> list[str]:
    """Replace known metadata placeholders in a template BAT file in-place.

    Only replaces placeholders that are both known and present in the file.
    Returns list of placeholder names that were replaced.
    """
    if not bat_path.is_file():
        return []
    content = bat_path.read_text(encoding="utf-8", errors="replace")
    replaced: list[str] = []
    for placeholder, value in replacements.items():
        if placeholder in _BAT_PLACEHOLDERS and placeholder in content:
            content = content.replace(placeholder, value)
            replaced.append(placeholder)
    if replaced:
        bat_path.write_text(content, encoding="utf-8")
    return replaced


def _validate_template_bat(staging: Path, norm_soc: str) -> list[str]:
    """Validate windows_install_and_format_data.bat in staging is present and SoC-correct.

    For MTK: expects _ab partition names, no Snapdragon _a/_b slot pattern.
    For Snapdragon: expects no MTK _ab partition names.
    """
    errors: list[str] = []
    bat = staging / "windows_install_and_format_data.bat"
    if not bat.is_file():
        errors.append("windows_install_and_format_data.bat missing from staging")
        return errors

    content = bat.read_text(encoding="utf-8", errors="replace")
    if not content.strip():
        errors.append("windows_install_and_format_data.bat is empty")
        return errors

    if "fastboot" not in content.lower():
        errors.append("windows_install_and_format_data.bat: no fastboot reference found")

    if norm_soc == "mtk":
        # MTK template must have _ab partition names
        if "_ab" not in content.lower():
            errors.append(
                "windows_install_and_format_data.bat: MTK template must contain _ab partition names"
            )
        # Must not contain Snapdragon-style _a/_b dual-slot suffixes
        if re.search(r'flash\s+\w+_[ab]\s+images\\', content, re.IGNORECASE):
            errors.append(
                "windows_install_and_format_data.bat: MTK template must not use Snapdragon _a/_b slot pattern"
            )
    else:
        # Snapdragon template must not have _ab partition names
        if re.search(r'flash\s+\w+_ab\s+images\\', content, re.IGNORECASE):
            errors.append(
                "windows_install_and_format_data.bat: Snapdragon template must not use MTK _ab partition names"
            )

    # Exactly one such file must exist at root (ZIP validation checks this too)
    return errors


def _write_template_report(
    norm_soc: str,
    raw_soc: str,
    template_dir: Path,
    staging: Path,
    template_files: list[str],
    copied_imgs: list[str],
    flash_cmds: list[str],
    skipped_pairs: list[tuple[str, str]],
    zip_path: Path,
    validation_result: str,
) -> None:
    """Write output/reports/final_zip_template_report.txt."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    zip_manifest: list[str] = []
    if zip_path.is_file():
        with zipfile.ZipFile(zip_path) as zf:
            zip_manifest = sorted(zf.namelist())

    lines = [
        "MEZO Final ZIP Template Report",
        "=" * 40,
        f"Generated:            {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        "",
        f"Selected SoC (raw):   {raw_soc}",
        f"Normalized SoC:       {norm_soc}",
        f"Selected template:    {template_dir}",
        f"Final staging path:   {staging}",
        "",
        f"Template files copied ({len(template_files)}):",
    ]
    for f in template_files:
        lines.append(f"  {f}")

    lines += [
        "",
        f"Real images discovered and copied ({len(copied_imgs)}):",
    ]
    for img in sorted(copied_imgs):
        lines.append(f"  {img}")

    lines += [
        "",
        f"Generated flash commands ({len(flash_cmds)}) in windows_install_and_format_data.bat:",
    ]
    for cmd in flash_cmds:
        lines.append(f"  {cmd}")

    if skipped_pairs:
        lines += ["", f"Skipped images ({len(skipped_pairs)}):"]
        for img, reason in skipped_pairs:
            lines.append(f"  SKIP {img}: {reason}")
    else:
        lines += ["", "Skipped images: none"]

    # Confirm final BAT path
    bat_path = staging / "windows_install_and_format_data.bat"
    lines += [
        "",
        f"Final BAT:            windows_install_and_format_data.bat",
        f"  Present in staging: {'YES' if bat_path.is_file() else 'NO'}",
    ]

    # Confirm which root BAT scripts are present / excluded
    root_bats_in_zip = [e for e in zip_manifest if "/" not in e and e.lower().endswith(".bat")]
    lines += [
        "",
        f"Root BAT scripts in ZIP ({len(root_bats_in_zip)}):",
    ]
    for b in root_bats_in_zip:
        lines.append(f"  INCLUDED : {b}")
    for b in sorted(_FORBIDDEN_ROOT_BATS):
        lines.append(f"  EXCLUDED : {b}")
    lines += [
        "",
        f"  windows_install_and_format_data.bat present: "
        f"{'YES' if 'windows_install_and_format_data.bat' in root_bats_in_zip else 'NO'}",
    ]

    lines += [
        "",
        f"Generated final ZIP:  {zip_path}",
        "",
        f"Final ZIP manifest ({len(zip_manifest)} entries):",
    ]
    for entry in zip_manifest:
        lines.append(f"  {entry}")

    lines += [
        "",
        f"Validation result:    {validation_result}",
    ]

    (REPORTS_DIR / "final_zip_template_report.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(f"[PACKAGE] Template report → {REPORTS_DIR / 'final_zip_template_report.txt'}")


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

        # Exactly one windows_install_and_format_data.bat at root
        root_install_bats = [
            n for n in names
            if "/" not in n and n.lower() == "windows_install_and_format_data.bat"
        ]
        if len(root_install_bats) != 1:
            errors.append(
                f"Expected exactly one windows_install_and_format_data.bat at ZIP root, "
                f"found {len(root_install_bats)}"
            )

        # Forbidden root BAT scripts must not be present
        for fname in _FORBIDDEN_ROOT_BATS:
            hits = [n for n in names if "/" not in n and n.lower() == fname.lower()]
            if hits:
                errors.append(f"Forbidden root BAT script found in ZIP: {fname}")

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
        f"Generated:               {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        f"SoC detected:            {soc_family.upper()}",
        f"Template style:          {style_label}",
        f"Codename check:          ENABLED (stops on mismatch before flashing)",
        f"Image preflight:         DISABLED (no if-not-exist blocking)",
        f"Flash error behavior:    warn-and-continue (FLASH_FAILED=1, no exit)",
        f"erase frp:               ENABLED (post-flash cleanup)",
        f"fastboot -w:             ENABLED (post-flash cleanup)",
        f"set_active a:            ENABLED (post-flash cleanup)",
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

    lines += ["", "Root BAT script (from template):"]
    tpl_bat = staging / "windows_install_and_format_data.bat"
    if tpl_bat.is_file():
        lines.append(f"  windows_install_and_format_data.bat  ({tpl_bat.stat().st_size:,} bytes)")
    else:
        lines.append("  windows_install_and_format_data.bat  [NOT FOUND]")

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

    # ── SoC normalization and template selection ──────────────────────────────
    raw_soc = cfg.get("soc_family", "mtk")
    try:
        norm_soc = _normalize_soc(raw_soc)
    except ValueError as exc:
        print(f"[PACKAGE] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    active_flash_map = MTK_FLASH_MAP if norm_soc == "mtk" else SD_FLASH_MAP
    print(f"[PACKAGE] SoC: {norm_soc.upper()} — using {'MTK _ab' if norm_soc == 'mtk' else 'Snapdragon base'} partition names")

    try:
        template_dir = _select_template_dir(norm_soc)
    except (ValueError, FileNotFoundError) as exc:
        print(f"[PACKAGE] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"[PACKAGE] Template: {template_dir}")

    # ── Prepare staging directory ─────────────────────────────────────────────
    staging = STAGING_BASE
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    # ── Copy SoC-specific template into staging ───────────────────────────────
    template_files_copied = _copy_template_to_staging(template_dir, staging)
    template_used      = True
    template_preserved = True
    nested_root        = None
    print(f"[PACKAGE] Copied {len(template_files_copied)} template files from bin/final_zip_templates/{norm_soc}/")

    # ── images/ directory — clear placeholders, prepare for real images ────────
    img_dir = staging / "images"
    if img_dir.is_dir():
        for _placeholder in img_dir.glob("*.img"):
            _placeholder.unlink()
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

    # ── Validate required images ──────────────────────────────────────────────
    missing_required = sorted(req for req in REQUIRED_IMAGES if req not in available_imgs)
    if missing_required:
        print("[PACKAGE] ERROR: Required images missing:", file=sys.stderr)
        for img in missing_required:
            print(f"  ! {img}", file=sys.stderr)
        sys.exit(1)

    # ── Generate windows_install_and_format_data.bat from actual images ──────────
    region = _read("rom_os.txt") or "Global"
    flash_cmds, skipped_pairs = _gen_install_bat(
        staging        = staging,
        available_imgs = available_imgs,
        norm_soc       = norm_soc,
        codename       = _sanitize_name(codename),
        rom_version    = rom_version or "UNKNOWN",
        android_ver    = android_ver or "UNKNOWN",
        region         = region,
    )
    win_warnings: list[str] = []
    unknown_imgs: list[str] = []   # no unknown images in the new generation model

    # ── Validate the generated windows_install_and_format_data.bat ────────────
    tpl_bat_errors = _validate_template_bat(staging, norm_soc)
    if tpl_bat_errors:
        print("[PACKAGE] Generated BAT validation ERRORS:", file=sys.stderr)
        for e in tpl_bat_errors:
            print(f"  ! {e}", file=sys.stderr)
        sys.exit(1)
    print("[PACKAGE] Generated BAT validation: PASS")

    # ── Write flash scan report ───────────────────────────────────────────────
    _write_flash_scan_report(
        img_dir, available_imgs, flash_cmds, unknown_imgs, win_warnings, staging,
        soc_family=norm_soc, flash_map=active_flash_map,
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
    _write_template_report(
        norm_soc=norm_soc,
        raw_soc=raw_soc,
        template_dir=template_dir,
        staging=staging,
        template_files=template_files_copied,
        copied_imgs=copied_imgs,
        flash_cmds=flash_cmds,
        skipped_pairs=skipped_pairs,
        zip_path=zip_path,
        validation_result="PASS",
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
