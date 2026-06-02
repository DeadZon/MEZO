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

# img filename → base fastboot partition name (no slot suffix).
# Slot images flash as both _a and _b for AB devices (see _build_bat_flash_block).
# super is non-slot (flashes once as 'super').
# cust flashes as 'cust' (non-slot, silent).
# preloader_raw flashes to 4 targets (see PRELOADER_IMGS).
FLASH_MAP: dict[str, str] = {
    # Boot / kernel slot images
    "boot.img":             "boot",
    "init_boot.img":        "init_boot",
    "vendor_boot.img":      "vendor_boot",
    "dtbo.img":             "dtbo",
    # vbmeta slot images
    "vbmeta.img":           "vbmeta",
    "vbmeta_system.img":    "vbmeta_system",
    "vbmeta_vendor.img":    "vbmeta_vendor",
    "vbmeta_product.img":   "vbmeta_product",
    "vbmeta_odm.img":       "vbmeta_odm",
    # super — non-slot (logical partition)
    "super.img":            "super",
    # Display / misc
    "logo.img":             "logo",
    "cust.img":             "cust",
    "rescue.img":           "rescue",
    # MTK firmware slot images
    "lk.img":               "lk",
    "md1img.img":           "md1img",
    "spmfw.img":            "spmfw",
    "scp.img":              "scp",
    "sspm.img":             "sspm",
    "tee.img":              "tee",
    "gz.img":               "gz",
    "dpm.img":              "dpm",
    "ccu.img":              "ccu",
    "apusys.img":           "apusys",
    "audio_dsp.img":        "audio_dsp",
    "connsys_bt.img":       "connsys_bt",
    "connsys_gnss.img":     "connsys_gnss",
    "connsys_wifi.img":     "connsys_wifi",
    "gpueb.img":            "gpueb",
    "mcf_ota.img":          "mcf_ota",
    "mcupm.img":            "mcupm",
    "mvpu_algo.img":        "mvpu_algo",
    "pi_img.img":           "pi_img",
    "preloader_raw.img":    "preloader",   # handled specially via PRELOADER_IMGS
    "vcp.img":              "vcp",
}

# Images that flash as a single partition (not _a / _b slot pairs).
# Matches the template's special-case logic.
NON_SLOT_IMGS: frozenset[str] = frozenset({"super.img", "cust.img"})

# Images that flash to 4 preloader targets (from template logic).
PRELOADER_IMGS: frozenset[str] = frozenset({"preloader_raw.img"})

# Must exist before the ZIP is built; fail hard if missing
REQUIRED_IMAGES: frozenset[str] = frozenset({"super.img", "vbmeta.img"})

# Flash order matching script2flash template logic:
# preloader → bootloader → boot images → MTK firmware → misc → vbmeta → super
FLASH_ORDER: list[str] = [
    "preloader_raw.img",   # 4 targets via PRELOADER_IMGS
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

# Path to the script2flash Windows template
SCRIPT2FLASH_TEMPLATE = Path("bin/script2flash/Windows_FastbootInstall.bat")
FLASH_BLOCK_START     = ":: BEGIN MEZO GENERATED IMAGE FLASH COMMANDS"
FLASH_BLOCK_END       = ":: END MEZO GENERATED IMAGE FLASH COMMANDS"

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


# ── Windows BAT script generation (template-based) ───────────────────────────

_BAT_FAIL = "echo Flash failed. Do not disconnect the phone. & pause & exit /b 1"


def _build_bat_flash_block(available_imgs: set[str]) -> tuple[list[str], list[str]]:
    """Build flash command lines in script2flash template style.

    Uses !fastboot! (delayed expansion) and the template's AB logic:
      - PRELOADER_IMGS  → 4 fixed targets (preloader_a/b/1/2)
      - NON_SLOT_IMGS   → single partition (super, cust)
      - everything else → _a + _b for AB devices, base name for A-only

    Returns: (bat_lines, flash_cmds_summary)
    """
    lines: list[str] = []
    cmds:  list[str] = []

    for img in FLASH_ORDER:
        if img not in available_imgs:
            continue
        part = FLASH_MAP.get(img)
        if part is None:
            continue

        is_req = img in REQUIRED_IMAGES
        is_pre = img in PRELOADER_IMGS
        is_non = img in NON_SLOT_IMGS

        req_guard = (
            f'if not exist "images\\{img}" ( echo ERROR: images\\{img} not found. & pause & exit /b 1 )'
        )

        if is_pre:
            # preloader_raw: 4 targets (mirrors template logic)
            lines += [
                f'if exist "images\\{img}" (',
                f'    !fastboot! flash preloader_a "images\\{img}"',
                f'    if errorlevel 1 ( {_BAT_FAIL} )',
                f'    !fastboot! flash preloader_b "images\\{img}"',
                f'    if errorlevel 1 ( {_BAT_FAIL} )',
                f'    !fastboot! flash preloader1 "images\\{img}"',
                f'    if errorlevel 1 ( {_BAT_FAIL} )',
                f'    !fastboot! flash preloader2 "images\\{img}"',
                f'    if errorlevel 1 ( {_BAT_FAIL} )',
                f')',
                '',
            ]
            cmds.append(f'!fastboot! flash preloader_a/b/1/2 images\\{img}')

        elif is_non:
            # Non-slot: single flash
            if is_req:
                lines += [
                    f':: Required: {img}',
                    req_guard,
                    f'!fastboot! flash {part} "images\\{img}"',
                    f'if errorlevel 1 ( {_BAT_FAIL} )',
                    '',
                ]
            else:
                lines += [
                    f'if exist "images\\{img}" (',
                    f'    !fastboot! flash {part} "images\\{img}"',
                    f'    if errorlevel 1 ( {_BAT_FAIL} )',
                    f')',
                    '',
                ]
            cmds.append(f'!fastboot! flash {part} images\\{img}')

        else:
            # Slot image: _a + _b for AB; base name for A-only (mirrors template for loop)
            if is_req:
                lines += [
                    f':: Required: {img}',
                    req_guard,
                    f'if "!fqlx!" == "AB" (',
                    f'    !fastboot! flash {part}_a "images\\{img}"',
                    f'    if errorlevel 1 ( {_BAT_FAIL} )',
                    f'    !fastboot! flash {part}_b "images\\{img}"',
                    f'    if errorlevel 1 ( {_BAT_FAIL} )',
                    f') else (',
                    f'    !fastboot! flash {part} "images\\{img}"',
                    f'    if errorlevel 1 ( {_BAT_FAIL} )',
                    f')',
                    '',
                ]
            else:
                lines += [
                    f'if exist "images\\{img}" (',
                    f'    if "!fqlx!" == "AB" (',
                    f'        !fastboot! flash {part}_a "images\\{img}"',
                    f'        if errorlevel 1 ( {_BAT_FAIL} )',
                    f'        !fastboot! flash {part}_b "images\\{img}"',
                    f'        if errorlevel 1 ( {_BAT_FAIL} )',
                    f'    ) else (',
                    f'        !fastboot! flash {part} "images\\{img}"',
                    f'        if errorlevel 1 ( {_BAT_FAIL} )',
                    f'    )',
                    f')',
                    '',
                ]
            cmds.append(f'!fastboot! flash {part}_a/_b images\\{img}')

    return lines, cmds


def _inject_flash_block(template_text: str, flash_lines: list[str]) -> str:
    """Replace content between MEZO markers with generated flash commands."""
    start_idx = template_text.find(FLASH_BLOCK_START)
    end_idx   = template_text.find(FLASH_BLOCK_END)
    if start_idx == -1 or end_idx == -1:
        raise ValueError(
            f"MEZO markers not found in template — "
            f"expected '{FLASH_BLOCK_START}' and '{FLASH_BLOCK_END}'"
        )
    start_eol = template_text.index("\n", start_idx) + 1
    block = "\n".join(flash_lines) + "\n" if flash_lines else ""
    return template_text[:start_eol] + block + template_text[end_idx:]


def _strip_choice_prompt(lines: list[str]) -> list[str]:
    """Remove the 'Please Choose Format Option' section from a script."""
    result: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if "Please Choose Format Option" in line:
            # Also remove the preceding separator line if present
            while result and "=========================" in result[-1]:
                result.pop()
            # Skip until (and including) the set /p CHOICE= line
            while i < len(lines) and 'set /p CHOICE=' not in lines[i]:
                i += 1
            i += 1  # skip the CHOICE line itself
            continue
        result.append(line)
        i += 1
    return result


def _strip_wipe_block(lines: list[str]) -> list[str]:
    """Remove the conditional wipe block (if /I "%CHOICE%"=="y" ...)."""
    result: list[str] = []
    depth = 0
    skipping = False
    for line in lines:
        stripped = line.rstrip()
        if not skipping and 'if /I "%CHOICE%"' in line and '==' in line:
            skipping = True
            depth = stripped.count('(') - stripped.count(')')
            continue
        if skipping:
            depth += stripped.count('(') - stripped.count(')')
            if depth <= 0:
                skipping = False
            continue
        result.append(line)
    return result


def _make_wipe_unconditional(lines: list[str]) -> list[str]:
    """Replace the conditional wipe block with an unconditional wipe + error checks."""
    result:    list[str] = []
    depth      = 0
    replacing  = False
    injected   = False

    for line in lines:
        stripped = line.rstrip()
        if not replacing and 'if /I "%CHOICE%"' in line and '==' in line:
            replacing = True
            depth = stripped.count('(') - stripped.count(')')
            if not injected:
                result += [
                    'echo.  Formatting...\n',
                    '!fastboot! erase frp  >NUL 2>NUL\n',
                    '!fastboot! erase userdata  >NUL 2>NUL\n',
                    'if errorlevel 1 ( echo Erase userdata failed. Do not disconnect. & pause & exit /b 1 )\n',
                    '!fastboot! erase metadata  >NUL 2>NUL\n',
                    'if errorlevel 1 ( echo Erase metadata failed. Do not disconnect. & pause & exit /b 1 )\n',
                    'echo.\n',
                ]
                injected = True
            continue
        if replacing:
            depth += stripped.count('(') - stripped.count(')')
            if depth <= 0:
                replacing = False
            continue
        result.append(line)
    return result


def _gen_windows_scripts(
    staging: Path,
    img_dir: Path,
    codename: str,
    rom_version: str,
) -> tuple[list[str], list[str], list[str], list[str]]:
    """Generate 3 Windows BAT scripts from script2flash template + actual images.

    Returns: (errors, warnings, unknown_imgs, flash_cmds_summary)
    """
    errors:   list[str] = []
    warnings: list[str] = []
    unknown:  list[str] = []

    available = {p.name for p in img_dir.glob("*.img")}

    for req in sorted(REQUIRED_IMAGES):
        if req not in available:
            errors.append(f"Required image missing: {req}")
    if errors:
        return errors, warnings, unknown, []

    unknown = sorted(img for img in available if img not in FLASH_MAP)
    if unknown:
        warnings.append(f"Unknown images (not flashed): {', '.join(unknown)}")

    flash_lines, flash_cmds = _build_bat_flash_block(available)

    # Read the script2flash template — required
    tpl_path = WORK_DIR / SCRIPT2FLASH_TEMPLATE
    if not tpl_path.is_file():
        errors.append(f"script2flash template not found: {tpl_path}")
        return errors, warnings, unknown, []

    template = tpl_path.read_text(encoding="utf-8", errors="replace")

    # Inject generated flash block between MEZO markers
    try:
        injected = _inject_flash_block(template, flash_lines)
    except ValueError as exc:
        errors.append(str(exc))
        return errors, warnings, unknown, []

    # ── windows_install_upgrade.bat (dirty flash — no wipe) ───────────────────
    upgrade_lines = injected.splitlines(keepends=True)
    upgrade_lines = _strip_choice_prompt(upgrade_lines)
    upgrade_lines = _strip_wipe_block(upgrade_lines)
    # Update title
    upgrade_lines = [
        l.replace("title DeadZone ROM Installer",
                  f"title DeadZone ROM - Upgrade (no data wipe) | {codename}")
        for l in upgrade_lines
    ]
    (staging / "windows_install_upgrade.bat").write_text(
        "".join(upgrade_lines), encoding="utf-8"
    )

    # ── windows_install_and_format_data.bat (clean flash — always wipes) ──────
    clean_lines = injected.splitlines(keepends=True)
    clean_lines = _strip_choice_prompt(clean_lines)
    clean_lines = _make_wipe_unconditional(clean_lines)
    clean_lines = [
        l.replace("title DeadZone ROM Installer",
                  f"title DeadZone ROM - Clean Install (WIPES) | {codename}")
        for l in clean_lines
    ]
    (staging / "windows_install_and_format_data.bat").write_text(
        "".join(clean_lines), encoding="utf-8"
    )

    # ── windows_format_data_only.bat (erase only, no flash) ───────────────────
    fmt_lines = [
        "@echo off&setlocal enabledelayedexpansion\n",
        "title DeadZone ROM - Format Data Only\n",
        "cd %~dp0\n",
        "set fastboot=bin\\windows\\fastboot.exe\n",
        'if not exist "%fastboot%" set fastboot=fastboot\n',
        "echo.\n",
        "echo.=========================================================================================\n",
        "echo.  DeadZone ROM - Format Data Only\n",
        "echo.  WARNING: This will erase all user data!\n",
        "echo.  DO NOT disconnect during operation!\n",
        "echo.=========================================================================================\n",
        "echo.\n",
        "echo.Make Sure Your Devices Is On Fastboot Mode\n",
        "pause >NUL 2>NUL\n",
        "\n",
        "echo.  Erasing metadata...\n",
        "!fastboot! erase metadata  >NUL 2>NUL\n",
        "if errorlevel 1 ( echo Erase metadata failed. Do not disconnect. & pause & exit /b 1 )\n",
        "\n",
        "echo.  Erasing userdata...\n",
        "!fastboot! erase userdata  >NUL 2>NUL\n",
        "if errorlevel 1 ( echo Erase userdata failed. Do not disconnect. & pause & exit /b 1 )\n",
        "\n",
        "echo.  Done! Rebooting...\n",
        "!fastboot! reboot\n",
        "pause\n",
        "exit\n",
    ]
    (staging / "windows_format_data_only.bat").write_text(
        "".join(fmt_lines), encoding="utf-8"
    )

    print(f"[PACKAGE] Generated Windows scripts from template: {tpl_path.name}")
    print(f"[PACKAGE]   flash commands injected: {len(flash_cmds)}")
    for cmd in flash_cmds:
        print(f"  {cmd}")

    return errors, warnings, unknown, flash_cmds


def _validate_generated_bat_scripts(staging: Path, available_imgs: set[str]) -> list[str]:
    """Sanity-check the generated Windows BAT scripts."""
    errors: list[str] = []

    for sname in _GEN_WIN_SCRIPTS:
        sp = staging / sname
        if not sp.is_file():
            errors.append(f"Generated script not found: {sname}")
            continue
        content = sp.read_text(encoding="utf-8", errors="replace")
        if not content.strip():
            errors.append(f"Generated script is empty: {sname}")
            continue

        # Upgrade/clean-install scripts must use !fastboot! (delayed expansion)
        if sname != "windows_format_data_only.bat":
            if "!fastboot!" not in content and "%fastboot%" not in content.lower():
                errors.append(f"{sname}: no fastboot variable reference found")
            if "flash" not in content.lower():
                errors.append(f"{sname}: no flash commands found")

        # Upgrade script must NOT erase userdata or metadata
        if sname == "windows_install_upgrade.bat":
            if "erase metadata" in content.lower() or "erase userdata" in content.lower():
                errors.append(f"{sname}: upgrade script must not erase userdata")

        # Validate every images\xxx.img reference points to an available image
        for m in re.finditer(r'images\\([^\s"\'!\r\n]+\.img)', content, re.IGNORECASE):
            ref = m.group(1)
            if ref not in available_imgs:
                errors.append(f"{sname}: references images\\{ref} — not in available images")

        # Validate slot images use _a/_b (not _ab), super uses 'super'
        # Match: !fastboot! flash <part> "images\<img>"
        for m in re.finditer(
            r'!fastboot!\s+flash\s+(\S+)\s+"images\\([^"]+\.img)"',
            content, re.IGNORECASE
        ):
            part, img = m.group(1), m.group(2)
            if img == "super.img" and part != "super":
                errors.append(f"{sname}: super.img must flash as 'super', got '{part}'")
            if img not in NON_SLOT_IMGS and img not in PRELOADER_IMGS:
                base = FLASH_MAP.get(img, "")
                if base and part not in (f"{base}_a", f"{base}_b", base):
                    errors.append(
                        f"{sname}: {img} flashed as '{part}' — "
                        f"expected '{base}_a'/'{base}_b' (AB) or '{base}' (A)"
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
) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    skipped = [img for img in FLASH_ORDER if img not in available_imgs]
    missing_req = sorted(img for img in REQUIRED_IMAGES if img not in available_imgs)

    lines = [
        "MEZO Flash Script Scan Report",
        "=" * 40,
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        "",
        f"Images folder:   {img_dir}",
        f"Images found:    {len(available_imgs)}",
        "",
        "Found images:",
    ]
    for img in sorted(available_imgs):
        part   = FLASH_MAP.get(img, "(unknown — not flashed)")
        marker = "✓" if img in FLASH_MAP else "?"
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
    for img in sorted(imgs_detected):
        part = FLASH_MAP.get(img, "(extra — not flashed)")
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

    # ── Validate required images ──────────────────────────────────────────────
    missing_required = sorted(req for req in REQUIRED_IMAGES if req not in available_imgs)
    if missing_required:
        print("[PACKAGE] ERROR: Required images missing:", file=sys.stderr)
        for img in missing_required:
            print(f"  ! {img}", file=sys.stderr)
        sys.exit(1)

    # ── Generate Windows BAT scripts from actual images ───────────────────────
    win_errors, win_warnings, unknown_imgs, flash_cmds = _gen_windows_scripts(
        staging, img_dir, _sanitize_name(codename), rom_version
    )
    if win_errors:
        print("[PACKAGE] Windows script generation ERRORS:", file=sys.stderr)
        for e in win_errors:
            print(f"  ! {e}", file=sys.stderr)
        sys.exit(1)
    for w in win_warnings:
        print(f"[PACKAGE] WARN: {w}", file=sys.stderr)

    # ── Validate generated BAT scripts ────────────────────────────────────────
    bat_errors = _validate_generated_bat_scripts(staging, available_imgs)
    if bat_errors:
        print("[PACKAGE] BAT script validation ERRORS:", file=sys.stderr)
        for e in bat_errors:
            print(f"  ! {e}", file=sys.stderr)
        sys.exit(1)
    print(f"[PACKAGE] BAT validation: PASS")

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
        img_dir, available_imgs, flash_cmds, unknown_imgs, win_warnings, staging
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
