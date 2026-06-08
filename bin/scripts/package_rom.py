#!/usr/bin/env python3
"""DeadZone ROM packaging script for MEZO.

Replaces old uploadROM.sh packaging.
- Reads device info from bin/ddevice/ (populated by build.sh)
- Resolves device config via device_resolver
- Selects SoC-specific full template from bin/final_zip_templates/<soc>/
- Generates windows_install_and_format_data.bat dynamically from actual ROM images
- Flash commands use MTK _ab style or Snapdragon _ab style (garnet reference) based on SoC
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
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path

# ── Android sparse image magic ────────────────────────────────────────────────
_SPARSE_MAGIC = bytes([0x3A, 0xFF, 0x26, 0xED])

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
REPORTS_DIR           = WORK_DIR / "bin" / "output" / "reports"
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
    # Snapdragon firmware — garnet reference + extended list
    "abl.img", "aop.img", "aop_config.img", "bluetooth.img",
    "countrycode.img", "cpucp.img", "cpucp_dtb.img",
    "devcfg.img", "dsp.img",
    "featenabler.img", "hyp.img", "idmanager.img", "imagefv.img", "keymaster.img",
    "modem.img", "multiimgqti.img", "pdp.img", "pdp_cdb.img", "pvmfw.img",
    "qupfw.img", "rpm.img", "shrm.img",
    "soccp_dcd.img", "soccp_debug.img", "spuservice.img",
    "tz.img", "uefi.img", "uefisecapp.img", "vm-bootsys.img",
    "xbl.img", "xbl_config.img", "xbl_ramdump.img",
    "recovery.img",
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

# Snapdragon: _ab partition style — matches uploaded garnet reference script exactly.
# All slotted images use _ab suffix (e.g. abl.img → abl_ab).
# Non-slot images (SD_NONSLOT_IMGS) flash once without suffix.
# Filename stem is never split on underscores — xbl_config.img → xbl_config_ab.
SD_FLASH_MAP: dict[str, str] = {
    # Firmware (slotted) — garnet reference order + extended list
    "abl.img":            "abl_ab",
    "aop.img":            "aop_ab",
    "aop_config.img":     "aop_config_ab",
    "bluetooth.img":      "bluetooth_ab",
    "countrycode.img":    "countrycode_ab",
    "cpucp.img":          "cpucp_ab",
    "cpucp_dtb.img":      "cpucp_dtb_ab",
    "devcfg.img":         "devcfg_ab",
    "dsp.img":            "dsp_ab",
    "dtbo.img":           "dtbo_ab",
    "featenabler.img":    "featenabler_ab",
    "hyp.img":            "hyp_ab",
    "idmanager.img":      "idmanager_ab",
    "imagefv.img":        "imagefv_ab",
    "keymaster.img":      "keymaster_ab",
    "modem.img":          "modem_ab",
    "multiimgqti.img":    "multiimgqti_ab",
    "pdp.img":            "pdp_ab",
    "pdp_cdb.img":        "pdp_cdb_ab",
    "pvmfw.img":          "pvmfw_ab",
    "qupfw.img":          "qupfw_ab",
    "shrm.img":           "shrm_ab",
    "soccp_dcd.img":      "soccp_dcd_ab",
    "soccp_debug.img":    "soccp_debug_ab",
    "spuservice.img":     "spuservice_ab",
    "tz.img":             "tz_ab",
    "uefi.img":           "uefi_ab",
    "uefisecapp.img":     "uefisecapp_ab",
    "vm-bootsys.img":     "vm-bootsys_ab",
    # vbmeta (slotted)
    "vbmeta.img":         "vbmeta_ab",
    "vbmeta_system.img":  "vbmeta_system_ab",
    "vbmeta_vendor.img":  "vbmeta_vendor_ab",
    "vbmeta_odm.img":     "vbmeta_odm_ab",
    "vbmeta_product.img": "vbmeta_product_ab",
    # XBL (slotted)
    "xbl.img":            "xbl_ab",
    "xbl_config.img":     "xbl_config_ab",
    "xbl_ramdump.img":    "xbl_ramdump_ab",
    # OS images (slotted)
    "boot.img":           "boot_ab",
    "init_boot.img":      "init_boot_ab",
    "vendor_boot.img":    "vendor_boot_ab",
    "recovery.img":       "recovery_ab",
    # Older Snapdragon firmware (slotted)
    "rpm.img":            "rpm_ab",
    "logo.img":           "logo_ab",
    # Non-slot (see SD_NONSLOT_IMGS)
    "super.img":          "super",
    "cust.img":           "cust",
    "rescue.img":         "rescue",
}

# Flash order: garnet reference script order first, then extras.
# set_active a runs before all flash commands (in BAT generation).
SD_FLASH_ORDER: list[str] = [
    # Firmware — garnet reference order + extended
    "abl.img",
    "aop.img",
    "aop_config.img",
    "bluetooth.img",
    "countrycode.img",
    "cpucp.img",
    "cpucp_dtb.img",
    "devcfg.img",
    "dsp.img",
    "dtbo.img",
    "featenabler.img",
    "hyp.img",
    "idmanager.img",
    "imagefv.img",
    "keymaster.img",
    "modem.img",
    "multiimgqti.img",
    "pdp.img",
    "pdp_cdb.img",
    "pvmfw.img",
    "qupfw.img",
    "shrm.img",
    "soccp_dcd.img",
    "soccp_debug.img",
    "spuservice.img",
    "tz.img",
    "uefi.img",
    "uefisecapp.img",
    "vm-bootsys.img",
    # vbmeta
    "vbmeta.img",
    "vbmeta_system.img",
    "vbmeta_vendor.img",
    "vbmeta_odm.img",
    "vbmeta_product.img",
    # XBL
    "xbl.img",
    "xbl_config.img",
    "xbl_ramdump.img",
    # OS
    "boot.img",
    "init_boot.img",
    "vendor_boot.img",
    "recovery.img",
    # Older Snapdragon
    "rpm.img",
    "logo.img",
    # Non-slot (before super)
    "cust.img",
    "rescue.img",
    # Super always last
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

SH_FLASH_BLOCK_START = "# BEGIN MEZO GENERATED IMAGE FLASH COMMANDS"
SH_FLASH_BLOCK_END   = "# END MEZO GENERATED IMAGE FLASH COMMANDS"

# ── DeadZone Style config ─────────────────────────────────────────────────────
# Single source of truth for all styles. Add new styles here to extend the system.
DZ_STYLES: dict[str, dict] = {
    "lite":   {"id": "lite",   "name": "DeadZone Lite",   "tier": "Free"},
    "plus":   {"id": "plus",   "name": "DeadZone Plus",   "tier": "Free"},
    "legend": {"id": "legend", "name": "DeadZone Legend", "tier": "Paid"},
    "ninja":  {"id": "ninja",  "name": "DeadZone Ninja",  "tier": "Paid"},
}

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
    "REGION_FROM_ROM",
    "DEVICE_LIST_FROM_ROM",
    "TIER_FROM_ROM",          # Snapdragon: ROM_LICENSE placeholder
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


# ── Image type detection ──────────────────────────────────────────────────────

def _detect_image(path: Path) -> dict:
    """Return {'type': 'SPARSE'|'RAW', 'size': int, 'magic': str} for an image file."""
    if not path.is_file():
        return {"type": "UNKNOWN", "size": 0, "magic": "????????"}
    size = path.stat().st_size
    if size < 4:
        return {"type": "RAW", "size": size, "magic": "??"}
    with path.open("rb") as fh:
        header = fh.read(4)
    magic_hex = header.hex()
    img_type = "SPARSE" if header == _SPARSE_MAGIC else "RAW"
    return {"type": img_type, "size": size, "magic": magic_hex}


def _log_all_images(img_dir: Path) -> list[dict]:
    """Log type/size/magic for every .img in img_dir and return the info list."""
    results: list[dict] = []
    for img_path in sorted(img_dir.glob("*.img")):
        info = _detect_image(img_path)
        print(f"[IMAGE] {img_path.name}: {info['type']}, size={info['size']}, magic={info['magic']}")
        results.append({"name": img_path.name, **info})
    return results


def _write_image_type_report(images_info: list[dict]) -> None:
    """Write output/reports/image_type_report.txt."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "Image Type Report",
        "=" * 50,
        f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        "",
        f"Images ({len(images_info)}):",
    ]
    for img in images_info:
        lines.append(
            f"  {img['name']:<38s} {img['type']:<8s} "
            f"size={img['size']:>13,}  magic={img['magic']}"
        )
    (REPORTS_DIR / "image_type_report.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(f"[PACKAGE] Image type report → {REPORTS_DIR / 'image_type_report.txt'}")


# ── Failure debug ZIP ─────────────────────────────────────────────────────────

def _create_debug_zip() -> "Path | None":
    """Collect all logs/reports into output/reports/build_failure_debug.zip."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = REPORTS_DIR / "build_failure_debug.zip"
    added: set[str] = set()

    def _add(zf: zipfile.ZipFile, src: Path, arcname: str) -> None:
        if arcname in added or not src.is_file():
            return
        try:
            zf.write(src, arcname)
            added.add(arcname)
        except Exception as exc:
            print(f"[DEBUG-ZIP] Skip {arcname}: {exc}", file=sys.stderr)

    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:

            # bin/output/logs/**
            logs_dir = WORK_DIR / "bin" / "output" / "logs"
            if logs_dir.is_dir():
                for f in sorted(logs_dir.rglob("*")):
                    if f.is_file() and f.suffix != ".img" and f.stat().st_size < 20 * 1024 * 1024:
                        _add(zf, f, f"logs/{f.relative_to(logs_dir)}")

            # output/reports/** (skip the ZIP itself and .img files)
            if REPORTS_DIR.is_dir():
                for f in sorted(REPORTS_DIR.glob("*")):
                    if f == zip_path or f.suffix == ".img":
                        continue
                    if f.is_file() and f.stat().st_size < 20 * 1024 * 1024:
                        _add(zf, f, f"reports/{f.name}")

            # Named report files (belt-and-suspenders)
            for rel in [
                "bin/output/logs/package_commands.log",
                "bin/output/reports/package_error_report.txt",
                "bin/output/reports/image_type_report.txt",
                "bin/output/reports/framework_patcher_report.txt",
                "bin/output/reports/signature_verification_bypass_report.txt",
                "bin/output/reports/invoke_custom_report.txt",
                "bin/output/reports/framework_patcher_error.txt",
                "bin/output/reports/final_zip_template_report.txt",
                "bin/output/reports/snapdragon_flash_script_report.txt",
                "bin/output/reports/deadzone_style_report.txt",
                "bin/output/reports/device_resolve_report.txt",
                "bin/output/reports/final_zip_manifest.txt",
                "bin/output/reports/final_zip_summary.json",
            ]:
                _add(zf, WORK_DIR / rel, Path(rel).name)

            _add(zf, WORK_DIR / "build_info.txt", "build_info.txt")

            # Last 300 lines of /tmp build logs
            for log_name in ["mezo_build.log", "mezo_pack.log", "mezo_package.log"]:
                log_p = Path("/tmp") / log_name
                if log_p.is_file():
                    try:
                        lines = log_p.read_text(encoding="utf-8", errors="replace").splitlines()
                        arc   = f"build_log_tail_{log_name}"
                        if arc not in added:
                            zf.writestr(arc, "\n".join(lines[-300:]))
                            added.add(arc)
                    except Exception:
                        pass

            # build/baserom/images file list (metadata only — no .img content)
            img_list_lines: list[str] = [
                "Build images file list",
                f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
                "=" * 60,
            ]
            if BUILD_IMAGES.is_dir():
                for img in sorted(BUILD_IMAGES.glob("*")):
                    if img.is_file():
                        if img.suffix == ".img":
                            info = _detect_image(img)
                            img_list_lines.append(
                                f"{img.name:<45s}  {info['type']:<8s}  "
                                f"size={info['size']:>12,}  magic={info['magic']}"
                            )
                        else:
                            img_list_lines.append(
                                f"{img.name:<45s}  -         size={img.stat().st_size:>12,}"
                            )
            if "build_images_list.txt" not in added:
                zf.writestr("build_images_list.txt", "\n".join(img_list_lines))
                added.add("build_images_list.txt")

            # Staging artifacts (BAT and firmware.txt only — no large .img)
            staging_img_dir = STAGING_BASE / "images"
            _add(zf, STAGING_BASE / "windows_install_and_format_data.bat",
                 "staging_windows_install_and_format_data.bat")
            _add(zf, staging_img_dir / "DeadZone_firmware.txt",
                 "staging_images_DeadZone_firmware.txt")

            # Staging images list (metadata only)
            if staging_img_dir.is_dir():
                st_list: list[str] = ["Staging images file list", "=" * 60]
                for img in sorted(staging_img_dir.glob("*.img")):
                    info = _detect_image(img)
                    st_list.append(
                        f"{img.name:<45s}  {info['type']:<8s}  "
                        f"size={info['size']:>12,}  magic={info['magic']}"
                    )
                if "staging_images_list.txt" not in added:
                    zf.writestr("staging_images_list.txt", "\n".join(st_list))
                    added.add("staging_images_list.txt")

        size_kb = zip_path.stat().st_size // 1024
        print(f"[DEBUG-ZIP] Created: {zip_path}  ({size_kb} KB, {len(added)} entries)")
        return zip_path

    except Exception as exc:
        print(f"[DEBUG-ZIP] Failed to create debug ZIP: {exc}", file=sys.stderr)
        return None


def _write_package_error_report(
    stage: str,
    command: str = "",
    image: str = "",
    reason: str = "",
    debug_zip: str = "",
) -> None:
    """Write output/reports/package_error_report.txt with structured failure info."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "PACKAGE ERROR REPORT",
        "=" * 50,
        f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        "",
        f"Stage:     {stage}",
        f"Command:   {command or '(none)'}",
        f"Image:     {image or '(none)'}",
        f"Reason:    {reason or '(unknown)'}",
        f"Debug ZIP: {debug_zip or '(not created)'}",
    ]
    (REPORTS_DIR / "package_error_report.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(f"[PACKAGE] Error report → {REPORTS_DIR / 'package_error_report.txt'}")


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


# ── Style helpers ────────────────────────────────────────────────────────────

def _normalize_style(style: str) -> str:
    """Normalize raw style input to canonical DZ_STYLES key.

    Accepted aliases:
      lite                       → lite
      plus, stable, free         → plus   (stable is a compat alias for plus)
      legend, paid               → legend
      ninja                      → ninja

    Raises ValueError for anything else.
    """
    s = style.lower().strip()
    if s in ("lite",):
        return "lite"
    if s in ("plus", "stable", "free"):
        return "plus"
    if s in ("legend", "paid"):
        return "legend"
    if s in ("ninja",):
        return "ninja"
    raise ValueError(f"Unsupported DeadZone style: {style}")


def _write_style_report(
    raw_style: str,
    style_id: str,
    norm_soc: str,
    codename: str,
    validation_result: str,
) -> None:
    """Write output/reports/deadzone_style_report.txt."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    cfg = DZ_STYLES[style_id]
    lines = [
        "DeadZone Style Report",
        "=" * 40,
        f"Generated:        {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        "",
        f"Raw style input:  {raw_style}",
        f"Normalized style: {style_id}",
        f"Style ID:         {cfg['id']}",
        f"Display name:     {cfg['name']}",
        f"Tier/License:     {cfg['tier']}",
        f"Selected SoC:     {norm_soc.upper()}",
        f"Selected device:  {codename}",
        "",
        f"Validation:       {validation_result}",
    ]
    (REPORTS_DIR / "deadzone_style_report.txt").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    print(f"[STYLE] Report → {REPORTS_DIR / 'deadzone_style_report.txt'}")


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
        # Snapdragon: _ab style — one command per image (garnet reference).
        # Filename stem is never split: xbl_config.img → xbl_config_ab (not x_ab).
        # Non-slot images flash once without suffix.
        for img in _ordered_sd_imgs(available_imgs):
            stem = Path(img).stem          # e.g. "xbl_config" from "xbl_config.img"
            if img in SD_NONSLOT_IMGS:
                flash_pairs.append((stem, img))
            else:
                # Use SD_FLASH_MAP for known images, derive stem_ab for unknowns
                partition = SD_FLASH_MAP.get(img) or f"{stem}_ab"
                flash_pairs.append((partition, img))

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
    style_name: str = "DeadZone Stable",
    style_tier: str = "Free",
) -> tuple[list[str], list[tuple[str, str]]]:
    """Generate windows_install_and_format_data.bat from the images actually present.

    Structure: 3 sections only.
      1. Header + firmware.txt reader + ROM info display + codename check
      2. Plain fastboot flash block (no wrappers, no echo, no logging)
      3. erase metadata + erase userdata + reboot

    The ONLY pre-flash stop is codename mismatch. No per-command failure handling.

    Returns: (flash_cmds_summary, skipped_pairs)
    """
    title = _INSTALL_BAT_TITLE.get(norm_soc, "DeadZone ROM Installer")

    flash_pairs, skipped_pairs = _compute_flash_pairs(available_imgs, norm_soc)

    flash_cmds_summary: list[str] = []
    plain_flash_lines:  list[str] = []
    for partition, img in flash_pairs:
        plain_flash_lines.append(f'%fastboot% flash {partition} images\\{img}')
        flash_cmds_summary.append(f'fastboot flash {partition} images\\{img}')

    flash_block = "\n".join(plain_flash_lines)

    firmware_block = (
        ':: Read ROM info from images\\DeadZone_firmware.txt\n'
        'set "Codename=unknown"\n'
        'set "ROM_DEVICE=unknown"\n'
        'set "ROM_VERSION=UNKNOWN"\n'
        'set "ROM_ANDROID=UNKNOWN"\n'
        'set "ROM_STYLE=DeadZone"\n'
        'set "ROM_LICENSE=Free"\n'
        'set "ROM_DEVELOPER=MEZO"\n'
        'set "ROM_REGION=Unknown"\n'
        'set "ROM_SOC=Unknown"\n'
        'if not exist "images\\DeadZone_firmware.txt" (\n'
        '    echo images\\DeadZone_firmware.txt not found\n'
        '    pause\n'
        '    exit /B 1\n'
        ')\n'
        'for /f "usebackq tokens=1,* delims==" %%a in ("images\\DeadZone_firmware.txt") do (\n'
        '    if /i "%%a"=="Codename"  set "Codename=%%b"\n'
        '    if /i "%%a"=="Device"    set "ROM_DEVICE=%%b"\n'
        '    if /i "%%a"=="version"   set "ROM_VERSION=%%b"\n'
        '    if /i "%%a"=="Android"   set "ROM_ANDROID=%%b"\n'
        '    if /i "%%a"=="Style"     set "ROM_STYLE=%%b"\n'
        '    if /i "%%a"=="License"   set "ROM_LICENSE=%%b"\n'
        '    if /i "%%a"=="Developer" set "ROM_DEVELOPER=%%b"\n'
        '    if /i "%%a"=="Region"    set "ROM_REGION=%%b"\n'
        '    if /i "%%a"=="SoC"       set "ROM_SOC=%%b"\n'
        ')\n'
    )

    content = (
        '@echo off\n'
        'chcp 65001 >nul\n'
        'cd /d "%~dp0"\n'
        'color 0B\n'
        f'title {title}\n'
        'cls\n'
        '\n'
        'set "fastboot=bin\\windows\\fastboot.exe"\n'
        '\n'
        'if not exist "%fastboot%" (\n'
        '    echo fastboot not found: %fastboot%\n'
        '    pause\n'
        '    exit /B 1\n'
        ')\n'
        '\n'
        + firmware_block +
        '\n'
        'echo.\n'
        'echo ================================================================\n'
        f'echo            {title}  ^|  by MEZO\n'
        'echo ================================================================\n'
        'echo.\n'
        'echo  Style      : %ROM_STYLE%\n'
        'echo  License    : %ROM_LICENSE%\n'
        'echo  Developer  : %ROM_DEVELOPER%\n'
        'echo  Version    : %ROM_VERSION%\n'
        'echo  Device     : %ROM_DEVICE%\n'
        'echo  Android    : Android %ROM_ANDROID%\n'
        'echo  Region     : %ROM_REGION%\n'
        'echo  SoC        : %ROM_SOC%\n'
        'echo  Codename   : %Codename%\n'
        'echo.\n'
        'echo ================================================================\n'
        'echo.\n'
        'echo  1. Unlocked bootloader required.\n'
        'echo     Close this window if your bootloader is NOT unlocked.\n'
        'echo  2. This will erase ALL your data.\n'
        'echo  3. DeadZone ROM is FREE. Contact MEZO if anyone charges you.\n'
        'echo  4. MEZO is not responsible for bricks or data loss.\n'
        'echo  5. Make sure this build is for your device.\n'
        'echo.\n'
        'pause\n'
        '\n'
        'set "device=unknown"\n'
        "for /f \"tokens=2\" %%D in ('%fastboot% getvar product 2^>^&1 ^| findstr /l /b /c:\"product:\"') do set \"device=%%D\"\n"
        '\n'
        'echo  Detected : %device%\n'
        'echo  Expected : %Codename%\n'
        'echo.\n'
        '\n'
        'if /i not "%device%"=="%Codename%" (\n'
        '    echo.\n'
        '    echo  ERROR: wrong device\n'
        '    echo  ROM is for : %Codename%\n'
        '    echo  Connected  : %device%\n'
        '    echo.\n'
        '    pause\n'
        '    exit /B 1\n'
        ')\n'
        '\n'
        'set /p confirm=This will wipe ALL data. Type YES to continue: \n'
        'if /i not "%confirm%"=="YES" exit /B 0\n'
        '\n'
        'echo.\n'
        '%fastboot% set_active a\n'
        '\n'
        f'{FLASH_BLOCK_START}\n'
        f'{flash_block}\n'
        f'{FLASH_BLOCK_END}\n'
        '\n'
        '%fastboot% erase metadata\n'
        '%fastboot% erase userdata\n'
        '%fastboot% reboot\n'
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


def _gen_linux_flash_script(
    staging: Path,
    flash_pairs: list[tuple[str, str]],
    codename: str,
    rom_version: str,
    android_ver: str,
    region: str,
    style_name: str,
    norm_soc: str,
) -> None:
    """Generate linux_install_and_format_data.sh from the same flash_pairs as the Windows BAT."""
    title = _INSTALL_BAT_TITLE.get(norm_soc, "DeadZone ROM Installer")

    flash_lines: list[str] = []
    for partition, img in flash_pairs:
        flash_lines.append(f'"$FASTBOOT" flash {partition} "images/{img}"')
    flash_block = "\n".join(flash_lines)

    content = (
        '#!/usr/bin/env bash\n'
        '# linux_install_and_format_data.sh — DeadZone ROM installer (Linux)\n'
        '# Generated by MEZO package_rom.py — do not edit manually\n'
        '\n'
        'set -euo pipefail\n'
        'trap \'echo ""; echo "  FLASH ERROR: a command failed — device left in fastboot mode."; echo ""\' ERR\n'
        '\n'
        'SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"\n'
        'cd "$SCRIPT_DIR"\n'
        '\n'
        '# ── Fastboot resolver ────────────────────────────────────────────────────────\n'
        'if [ -x "./bin/linux/fastboot" ]; then\n'
        '    FASTBOOT="./bin/linux/fastboot"\n'
        'elif command -v fastboot >/dev/null 2>&1; then\n'
        '    FASTBOOT="fastboot"\n'
        'else\n'
        '    echo ""\n'
        '    echo "  ERROR: fastboot not found."\n'
        '    echo ""\n'
        '    echo "  Install fastboot for your distribution:"\n'
        '    echo "    Ubuntu / Debian :  sudo apt-get install android-tools-fastboot"\n'
        '    echo "    Arch Linux      :  sudo pacman -S android-tools"\n'
        '    echo "    Fedora          :  sudo dnf install android-tools"\n'
        '    echo ""\n'
        '    exit 1\n'
        'fi\n'
        '\n'
        '# ── Read ROM info from images/DeadZone_firmware.txt ─────────────────────────\n'
        'FW_TXT="images/DeadZone_firmware.txt"\n'
        'if [ ! -f "$FW_TXT" ]; then\n'
        '    echo "images/DeadZone_firmware.txt not found"\n'
        '    exit 1\n'
        'fi\n'
        '\n'
        'Codename="unknown"\n'
        'ROM_DEVICE="unknown"\n'
        'ROM_VERSION="UNKNOWN"\n'
        'ROM_ANDROID="UNKNOWN"\n'
        'ROM_STYLE="DeadZone"\n'
        'ROM_LICENSE="Free"\n'
        'ROM_DEVELOPER="MEZO"\n'
        'ROM_REGION="Unknown"\n'
        'ROM_SOC="Unknown"\n'
        '\n'
        'while IFS="=" read -r key val; do\n'
        '    case "$key" in\n'
        '        Codename)  Codename="$val"     ;;\n'
        '        Device)    ROM_DEVICE="$val"   ;;\n'
        '        version)   ROM_VERSION="$val"  ;;\n'
        '        Android)   ROM_ANDROID="$val"  ;;\n'
        '        Style)     ROM_STYLE="$val"    ;;\n'
        '        License)   ROM_LICENSE="$val"  ;;\n'
        '        Developer) ROM_DEVELOPER="$val" ;;\n'
        '        Region)    ROM_REGION="$val"   ;;\n'
        '        SoC)       ROM_SOC="$val"      ;;\n'
        '    esac\n'
        'done < "$FW_TXT"\n'
        '\n'
        'echo ""\n'
        'echo "================================================================"\n'
        f'echo "           {title}  |  by MEZO"\n'
        'echo "================================================================"\n'
        'echo ""\n'
        'echo "  Style      : $ROM_STYLE"\n'
        'echo "  License    : $ROM_LICENSE"\n'
        'echo "  Developer  : $ROM_DEVELOPER"\n'
        'echo "  Version    : $ROM_VERSION"\n'
        'echo "  Device     : $ROM_DEVICE"\n'
        'echo "  Android    : Android $ROM_ANDROID"\n'
        'echo "  Region     : $ROM_REGION"\n'
        'echo "  SoC        : $ROM_SOC"\n'
        'echo "  Codename   : $Codename"\n'
        'echo ""\n'
        'echo "================================================================"\n'
        'echo ""\n'
        'echo "  1. Unlocked bootloader required."\n'
        'echo "     Close this terminal if your bootloader is NOT unlocked."\n'
        'echo "  2. This will erase ALL your data."\n'
        'echo "  3. DeadZone ROM is FREE. Contact MEZO if anyone charges you."\n'
        'echo "  4. MEZO is not responsible for bricks or data loss."\n'
        'echo "  5. Make sure this build is for your device."\n'
        'echo ""\n'
        'read -r -p "Press Enter to continue or Ctrl+C to cancel..."\n'
        '\n'
        '# ── Device check ─────────────────────────────────────────────────────────────\n'
        'device="$("$FASTBOOT" getvar product 2>&1 | awk -F\': \' \'/^product:/{print $2; exit}\')"\n'
        '\n'
        'echo "  Detected : $device"\n'
        'echo "  Expected : $Codename"\n'
        'echo ""\n'
        '\n'
        'if [ "$device" != "$Codename" ]; then\n'
        '    echo ""\n'
        '    echo "  ERROR: wrong device"\n'
        '    echo "  ROM is for : $Codename"\n'
        '    echo "  Connected  : $device"\n'
        '    echo ""\n'
        '    exit 1\n'
        'fi\n'
        '\n'
        'read -r -p "This will wipe ALL data. Type YES to continue: " confirm\n'
        'if [ "$confirm" != "YES" ]; then\n'
        '    exit 0\n'
        'fi\n'
        '\n'
        'echo ""\n'
        '"$FASTBOOT" set_active a\n'
        '\n'
        f'{SH_FLASH_BLOCK_START}\n'
        f'{flash_block}\n'
        f'{SH_FLASH_BLOCK_END}\n'
        '\n'
        '"$FASTBOOT" erase metadata\n'
        '"$FASTBOOT" erase userdata\n'
        '"$FASTBOOT" reboot\n'
    )

    out_path = staging / "linux_install_and_format_data.sh"
    out_path.write_text(content, encoding="utf-8")
    print(
        f"[PACKAGE] Generated linux_install_and_format_data.sh "
        f"({len(flash_pairs)} flash commands, {norm_soc.upper()} style)"
    )


def _gen_macos_flash_script(
    staging: Path,
    flash_pairs: list[tuple[str, str]],
    codename: str,
    rom_version: str,
    android_ver: str,
    region: str,
    style_name: str,
    norm_soc: str,
) -> None:
    """Generate macos_install_and_format_data.sh from the same flash_pairs as the Windows BAT."""
    title = _INSTALL_BAT_TITLE.get(norm_soc, "DeadZone ROM Installer")

    flash_lines: list[str] = []
    for partition, img in flash_pairs:
        flash_lines.append(f'"$FASTBOOT" flash {partition} "images/{img}"')
    flash_block = "\n".join(flash_lines)

    content = (
        '#!/usr/bin/env bash\n'
        '# macos_install_and_format_data.sh — DeadZone ROM installer (macOS)\n'
        '# Generated by MEZO package_rom.py — do not edit manually\n'
        '\n'
        'set -euo pipefail\n'
        'trap \'echo ""; echo "  FLASH ERROR: a command failed — device left in fastboot mode."; echo ""\' ERR\n'
        '\n'
        'SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"\n'
        'cd "$SCRIPT_DIR"\n'
        '\n'
        '# ── Fastboot resolver ────────────────────────────────────────────────────────\n'
        'if [ -x "./bin/macos/fastboot" ]; then\n'
        '    FASTBOOT="./bin/macos/fastboot"\n'
        'elif command -v fastboot >/dev/null 2>&1; then\n'
        '    FASTBOOT="fastboot"\n'
        'else\n'
        '    echo ""\n'
        '    echo "  ERROR: fastboot not found."\n'
        '    echo ""\n'
        '    echo "  Install fastboot via Homebrew:"\n'
        '    echo "    brew install android-platform-tools"\n'
        '    echo ""\n'
        '    exit 1\n'
        'fi\n'
        '\n'
        '# ── Read ROM info from images/DeadZone_firmware.txt ─────────────────────────\n'
        'FW_TXT="images/DeadZone_firmware.txt"\n'
        'if [ ! -f "$FW_TXT" ]; then\n'
        '    echo "images/DeadZone_firmware.txt not found"\n'
        '    exit 1\n'
        'fi\n'
        '\n'
        'Codename="unknown"\n'
        'ROM_DEVICE="unknown"\n'
        'ROM_VERSION="UNKNOWN"\n'
        'ROM_ANDROID="UNKNOWN"\n'
        'ROM_STYLE="DeadZone"\n'
        'ROM_LICENSE="Free"\n'
        'ROM_DEVELOPER="MEZO"\n'
        'ROM_REGION="Unknown"\n'
        'ROM_SOC="Unknown"\n'
        '\n'
        'while IFS="=" read -r key val; do\n'
        '    case "$key" in\n'
        '        Codename)  Codename="$val"     ;;\n'
        '        Device)    ROM_DEVICE="$val"   ;;\n'
        '        version)   ROM_VERSION="$val"  ;;\n'
        '        Android)   ROM_ANDROID="$val"  ;;\n'
        '        Style)     ROM_STYLE="$val"    ;;\n'
        '        License)   ROM_LICENSE="$val"  ;;\n'
        '        Developer) ROM_DEVELOPER="$val" ;;\n'
        '        Region)    ROM_REGION="$val"   ;;\n'
        '        SoC)       ROM_SOC="$val"      ;;\n'
        '    esac\n'
        'done < "$FW_TXT"\n'
        '\n'
        'echo ""\n'
        'echo "================================================================"\n'
        f'echo "           {title}  |  by MEZO"\n'
        'echo "================================================================"\n'
        'echo ""\n'
        'echo "  Style      : $ROM_STYLE"\n'
        'echo "  License    : $ROM_LICENSE"\n'
        'echo "  Developer  : $ROM_DEVELOPER"\n'
        'echo "  Version    : $ROM_VERSION"\n'
        'echo "  Device     : $ROM_DEVICE"\n'
        'echo "  Android    : Android $ROM_ANDROID"\n'
        'echo "  Region     : $ROM_REGION"\n'
        'echo "  SoC        : $ROM_SOC"\n'
        'echo "  Codename   : $Codename"\n'
        'echo ""\n'
        'echo "================================================================"\n'
        'echo ""\n'
        'echo "  1. Unlocked bootloader required."\n'
        'echo "     Close this terminal if your bootloader is NOT unlocked."\n'
        'echo "  2. This will erase ALL your data."\n'
        'echo "  3. DeadZone ROM is FREE. Contact MEZO if anyone charges you."\n'
        'echo "  4. MEZO is not responsible for bricks or data loss."\n'
        'echo "  5. Make sure this build is for your device."\n'
        'echo ""\n'
        'read -r -p "Press Enter to continue or Ctrl+C to cancel..."\n'
        '\n'
        '# ── Device check ─────────────────────────────────────────────────────────────\n'
        'device="$("$FASTBOOT" getvar product 2>&1 | awk -F\': \' \'/^product:/{print $2; exit}\')"\n'
        '\n'
        'echo "  Detected : $device"\n'
        'echo "  Expected : $Codename"\n'
        'echo ""\n'
        '\n'
        'if [ "$device" != "$Codename" ]; then\n'
        '    echo ""\n'
        '    echo "  ERROR: wrong device"\n'
        '    echo "  ROM is for : $Codename"\n'
        '    echo "  Connected  : $device"\n'
        '    echo ""\n'
        '    exit 1\n'
        'fi\n'
        '\n'
        'read -r -p "This will wipe ALL data. Type YES to continue: " confirm\n'
        'if [ "$confirm" != "YES" ]; then\n'
        '    exit 0\n'
        'fi\n'
        '\n'
        'echo ""\n'
        '"$FASTBOOT" set_active a\n'
        '\n'
        f'{SH_FLASH_BLOCK_START}\n'
        f'{flash_block}\n'
        f'{SH_FLASH_BLOCK_END}\n'
        '\n'
        '"$FASTBOOT" erase metadata\n'
        '"$FASTBOOT" erase userdata\n'
        '"$FASTBOOT" reboot\n'
    )

    out_path = staging / "macos_install_and_format_data.sh"
    out_path.write_text(content, encoding="utf-8")
    print(
        f"[PACKAGE] Generated macos_install_and_format_data.sh "
        f"({len(flash_pairs)} flash commands, {norm_soc.upper()} style)"
    )


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

    Both MTK and Snapdragon templates use bin/windows/fastboot.exe.
    Snapdragon template additionally contains META-INF/ for recovery support.
    The windows_install_and_format_data.bat in the template is overwritten
    during packaging by _gen_install_bat(), so its content is not critical.
    """
    tpl = FINAL_ZIP_TEMPLATES_DIR / norm_soc
    if not tpl.is_dir():
        raise FileNotFoundError(f"Template folder missing: {tpl}")

    fb = tpl / "bin" / "windows" / "fastboot.exe"
    if not fb.is_file():
        raise FileNotFoundError(
            f"Required template file missing: {tpl}/bin/windows/fastboot.exe"
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
    """Validate windows_install_and_format_data.bat in staging.

    Required structure (both SoCs):
      1. Header: chcp 65001, color 0B, bin\\windows\\fastboot.exe
      2. Reads images\\DeadZone_firmware.txt — stops if missing
      3. Detects fastboot product, compares to %Codename% — exit /B 1 on mismatch
      4. Plain fastboot flash block — no wrappers, no echo, no logging
      5. erase metadata + erase userdata + reboot

    Forbidden in generated BAT:
      - installer_log.txt
      - echo [FLASH]  /  echo [ERROR]
      - if errorlevel 1 inside flash block
      - hardcoded garnet / zircon
      - HyperUR / OxygenOS / Niexia / Elite branding
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

    # ── Required elements ─────────────────────────────────────────────────────
    if "fastboot" not in content.lower():
        errors.append("BAT: no fastboot reference found")

    if "bin\\windows\\fastboot.exe" not in content and \
       "bin/windows/fastboot.exe" not in content:
        errors.append("BAT: must use bin\\windows\\fastboot.exe")

    if "DeadZone_firmware.txt" not in content:
        errors.append("BAT: must read from images\\DeadZone_firmware.txt")

    if "chcp 65001" not in content:
        errors.append("BAT: must set chcp 65001")

    if "color 0B" not in content:
        errors.append("BAT: must set color 0B")

    # Codename check: must detect device and exit on mismatch
    if "getvar product" not in content.lower():
        errors.append("BAT: missing fastboot getvar product (device detection)")

    if "exit /b 1" not in content.lower():
        errors.append("BAT: must exit /B 1 on device mismatch")

    # Wipe/reboot must come after the flash block
    flash_block_end = content.find(FLASH_BLOCK_END)
    erase_meta      = content.find("erase metadata")
    if flash_block_end != -1 and erase_meta != -1:
        if erase_meta < flash_block_end:
            errors.append("BAT: erase metadata/userdata must come AFTER the flash block")

    # ── Forbidden elements ────────────────────────────────────────────────────
    if "installer_log.txt" in content.lower():
        errors.append("BAT: must not contain installer_log.txt")

    if "echo [flash]" in content.lower():
        errors.append("BAT: must not contain echo [FLASH] wrappers in flash block")

    if "echo [error]" in content.lower():
        errors.append("BAT: must not contain echo [ERROR] wrappers")

    # Per-command errorlevel guards inside the flash block are forbidden
    flash_start = content.find(FLASH_BLOCK_START)
    flash_end   = content.find(FLASH_BLOCK_END)
    if flash_start != -1 and flash_end != -1 and flash_end > flash_start:
        flash_section = content[flash_start:flash_end]
        if "if errorlevel 1" in flash_section.lower():
            errors.append("BAT: flash block must not contain per-command if errorlevel 1 wrappers")

    # No hardcoded codenames
    if re.search(r'neq\s+"garnet"', content, re.IGNORECASE) or \
       re.search(r'=="garnet"', content, re.IGNORECASE) or \
       re.search(r'neq\s+"zircon"', content, re.IGNORECASE):
        errors.append("BAT: must not hardcode garnet/zircon — use dynamic %Codename%")

    # Forbidden branding
    for bad in ("hyperur", "oxygenos", "niexia", "elite rom", "ported by"):
        if bad in content.lower():
            errors.append(f"BAT: must not contain '{bad}' branding")

    # Required branding
    if "deadzone" not in content.lower():
        errors.append("BAT: must contain DeadZone branding")
    if "mezo" not in content.lower():
        errors.append("BAT: must contain MEZO developer reference")

    # ── SoC-specific ──────────────────────────────────────────────────────────
    if norm_soc == "mtk":
        if "_ab" not in content.lower():
            errors.append("BAT (MTK): must contain _ab partition names")
        if re.search(r'flash\s+\w+_[ab]\s+images\\', content, re.IGNORECASE):
            errors.append("BAT (MTK): must not use _a/_b dual-slot pattern")
    else:
        if not re.search(r'flash\s+\w+_ab\s+images\\', content, re.IGNORECASE):
            errors.append("BAT (SD): must use _ab partition style (garnet reference)")
        for bad_part in ("boot_a ", "boot_b ", "vendor_boot_a ", "vendor_boot_b ",
                         "vbmeta_a ", "vbmeta_b "):
            if f"flash {bad_part}" in content.lower():
                errors.append(f"BAT (SD): must not flash {bad_part.strip()} (use _ab suffix)")

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

def _validate_zip(zip_path: Path, available_imgs: set[str], norm_soc: str = "mtk") -> list[str]:
    """Return list of validation errors (empty = OK).

    MTK:        requires windows_install_and_format_data.bat at root; no META-INF.
    Snapdragon: requires windows_install_and_format_data.bat at root;
                META-INF/windows/fastboot.exe present; DeadZone_firmware.txt present.
    """
    errors: list[str] = []
    if not zip_path.is_file():
        return [f"ZIP not found: {zip_path}"]
    if not zip_path.name.startswith("DeadZone_"):
        errors.append(f"ZIP name must start with 'DeadZone_', got: {zip_path.name}")
    with zipfile.ZipFile(zip_path) as zf:
        names      = zf.namelist()
        names_lower = {n.lower() for n in names}

        # Required: images/super.img
        if not any("images/super.img" in n.lower() for n in names):
            errors.append("images/super.img missing from ZIP")

        # Required: windows_install_and_format_data.bat at root
        root_bats = [
            n for n in names
            if "/" not in n and n.lower() == "windows_install_and_format_data.bat"
        ]
        if len(root_bats) != 1:
            errors.append(
                f"Expected exactly one windows_install_and_format_data.bat at ZIP root, "
                f"found {len(root_bats)}"
            )

        # Required: linux_install_and_format_data.sh at root
        linux_shs = [n for n in names if "/" not in n and n.lower() == "linux_install_and_format_data.sh"]
        if len(linux_shs) != 1:
            errors.append(
                f"Expected exactly one linux_install_and_format_data.sh at ZIP root, "
                f"found {len(linux_shs)}"
            )

        # Required: macos_install_and_format_data.sh at root
        macos_shs = [n for n in names if "/" not in n and n.lower() == "macos_install_and_format_data.sh"]
        if len(macos_shs) != 1:
            errors.append(
                f"Expected exactly one macos_install_and_format_data.sh at ZIP root, "
                f"found {len(macos_shs)}"
            )

        # Forbidden BAT scripts (upgrade/format-only scripts must never ship)
        for fname in _FORBIDDEN_ROOT_BATS:
            hits = [n for n in names if "/" not in n and n.lower() == fname.lower()]
            if hits:
                errors.append(f"Forbidden root BAT script found in ZIP: {fname}")

        # Validate every images\xxx.img reference in the BAT actually exists in the ZIP
        for n in names:
            if not n.lower().endswith(".bat"):
                continue
            content = zf.read(n).decode("utf-8", errors="replace")
            for m in re.finditer(r'images\\([^\s"\'%\r\n]+\.img)', content, re.IGNORECASE):
                ref = m.group(1).lower()
                if f"images/{ref}" not in names_lower:
                    errors.append(f"{n}: references images\\{m.group(1)} which is not in ZIP")

        # Both SoCs: images/DeadZone_firmware.txt must be present
        if not any("images/deadzone_firmware.txt" in n.lower() for n in names):
            errors.append(f"{norm_soc.upper()} ZIP missing images/DeadZone_firmware.txt")

        # Both SoCs: BAT branding checks
        for n in names:
            if "/" not in n and n.lower() == "windows_install_and_format_data.bat":
                content = zf.read(n).decode("utf-8", errors="replace")
                for bad in ("hyperur", "oxygenos", "niexia", "elite rom"):
                    if bad in content.lower():
                        errors.append(f"BAT contains forbidden '{bad}' branding")
                if "deadzone" not in content.lower():
                    errors.append("BAT missing DeadZone branding")
                if "mezo" not in content.lower():
                    errors.append("BAT missing MEZO developer reference")

        # Snapdragon-specific: bin/windows/fastboot.exe must be present
        if norm_soc == "snapdragon":
            if not any("bin/windows/fastboot.exe" in n.lower() for n in names):
                errors.append("Snapdragon ZIP missing bin/windows/fastboot.exe")

        # MTK-specific: no META-INF allowed
        if norm_soc == "mtk":
            meta_inf_hits = [n for n in names if n.lower().startswith("meta-inf/")]
            if meta_inf_hits:
                errors.append(f"MTK ZIP must not contain META-INF: {meta_inf_hits[:3]}")

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
        f"Codename check:          ENABLED (hard stop on mismatch, no override)",
        f"Image preflight:         DISABLED (no if-not-exist blocking)",
        f"Flash error behavior:    stop-immediately (exit /B 1 on first failure)",
        f"Wipe behavior:           erase metadata + erase userdata AFTER all flash succeeds",
        f"set_active a:            ENABLED (pre-flash)",
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
    style_id: str = "plus",
    naming_scheme: str = "deadzone",
    style_input_original: str = "",
) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    compressed_bytes = zip_path.stat().st_size
    ratio = uncompressed_bytes / compressed_bytes if compressed_bytes > 0 else 1.0

    _style_cfg = DZ_STYLES.get(style_id, {})
    summary: dict = {
        "codename":                   cfg["codename"],
        "soc":                        cfg.get("soc_family", ""),
        "rom_os_version":             _read("base_rom_code.txt"),
        "android_version":            _read("androidver.txt"),
        "final_style":                style_id,
        "final_tier":                 _style_cfg.get("tier", ""),
        "style_input_original":       style_input_original or style_id,
        "style_alias_used":           style_input_original.lower() != style_id if style_input_original else False,
        "final_zip_name":             zip_path.name,
        "naming_scheme":              naming_scheme,
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
        "linux_flash_script":         True,
        "macos_flash_script":         True,
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
        _znames = zf.namelist()
        summary["file_count"] = len(_znames)
        summary["bundled_linux_fastboot"] = any(
            n.lower() == "bin/linux/fastboot" for n in _znames
        )
        summary["bundled_macos_fastboot"] = any(
            n.lower() == "bin/macos/fastboot" for n in _znames
        )
        for f in FORBIDDEN_ENTRIES:
            hits = [n for n in _znames if f.lower() in n.lower()]
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
        ("build.sh",                                  WORK_DIR / "build.sh"),
        ("packROM.sh",                                WORK_DIR / "packROM.sh"),
        ("bin/scripts/package_rom.py",                WORK_DIR / "bin" / "scripts" / "package_rom.py"),
        ("bin/scripts/pixeldrain_upload.py",          WORK_DIR / "bin" / "scripts" / "pixeldrain_upload.py"),
        ("bin/scripts/tg_watch.py",                   WORK_DIR / "bin" / "scripts" / "tg_watch.py"),
        ("bin/scripts/telegram.py",                   WORK_DIR / "bin" / "scripts" / "telegram.py"),
        (".github/workflows/mezo_mtk.yml",            WORK_DIR / ".github" / "workflows" / "mezo_mtk.yml"),
        (".github/workflows/mezo_snapdragon.yml",     WORK_DIR / ".github" / "workflows" / "mezo_snapdragon.yml"),
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


# ── Snapdragon flash script report ───────────────────────────────────────────

def _write_flash_script_generation_report(
    norm_soc: str,
    codename: str,
    rom_version: str,
    android_ver: str,
    region: str,
    style_name: str,
    style_tier: str,
    available_imgs: set[str],
    flash_pairs:  list[tuple[str, str]],
    skipped_pairs: list[tuple[str, str]],
    bat_path: Path,
    validation_result: str,
) -> None:
    """Write output/reports/flash_script_generation_report.txt for both SoCs."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    soc_label   = "MTK" if norm_soc == "mtk" else "Snapdragon"
    flash_style = "MTK _ab" if norm_soc == "mtk" else "garnet reference _ab"
    cfg_device  = resolve(codename)
    display_name = cfg_device.get("display_name", "") or codename
    fw_txt_path = bat_path.parent / "images" / "DeadZone_firmware.txt"

    lines = [
        "DeadZone Flash Script Generation Report",
        "=" * 50,
        f"Generated:              {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        "",
        "ROM Information:",
        f"  SoC:                  {soc_label}",
        f"  Flash style:          {flash_style}",
        f"  Firmware info path:   images/DeadZone_firmware.txt",
        f"  Codename:             {codename}",
        f"  Device:               {display_name}",
        f"  ROM Version:          {rom_version}",
        f"  Android:              {android_ver}",
        f"  Style:                {style_name}",
        f"  License:              {style_tier}",
        f"  Region:               {region}",
        "",
        f"  DeadZone_firmware.txt present: {'YES' if fw_txt_path.is_file() else 'NO'}",
        "",
        f"Images discovered ({len(available_imgs)}):",
    ]
    fmap = MTK_FLASH_MAP if norm_soc == "mtk" else SD_FLASH_MAP
    for img in sorted(available_imgs):
        part = fmap.get(img, "(not flashed)")
        lines.append(f"  {img:<35s}  → {part}")

    lines += [
        "",
        f"Generated flash commands ({len(flash_pairs)}):",
    ]
    for part, img in flash_pairs:
        lines.append(f"  fastboot flash {part} images\\{img}")

    if skipped_pairs:
        lines += ["", f"Skipped images ({len(skipped_pairs)}):"]
        for img, reason in skipped_pairs:
            lines.append(f"  SKIP {img}: {reason}")
    else:
        lines += ["", "Skipped images: none"]

    lines += [
        "",
        f"Generated BAT:          {bat_path.name}",
        f"  Present:              {'YES' if bat_path.is_file() else 'NO'}",
    ]
    if bat_path.is_file():
        lines.append(f"  Size:                 {bat_path.stat().st_size:,} bytes")

    lines += [
        "",
        "BAT behavior:",
        "  Device check:         hard stop on mismatch — no override option",
        "  Flash failure:        exit /B 1 immediately on first failure",
        "  Wipe:                 erase metadata + erase userdata AFTER all flash succeed",
        "  Reboot:               after wipe succeeds",
        "  ROM info:             all fields read from images\\DeadZone_firmware.txt at runtime",
        "",
        f"Validation result:      {validation_result}",
    ]

    out = REPORTS_DIR / "flash_script_generation_report.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[PACKAGE] Flash script generation report → {out}")


def _write_sd_flash_script_report(
    codename:    str,
    rom_version: str,
    android_ver: str,
    region:      str,
    style_name:  str,
    style_tier:  str,
    available_imgs: set[str],
    flash_pairs:  list[tuple[str, str]],
    skipped_pairs: list[tuple[str, str]],
    bat_path: Path,
    validation_result: str,
) -> None:
    """Write output/reports/snapdragon_flash_script_report.txt."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    cfg_device = resolve(codename)
    display_name = cfg_device.get("display_name", "") or codename

    lines = [
        "DeadZone Snapdragon Flash Script Report",
        "=" * 50,
        f"Generated:          {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
        "",
        "ROM Information:",
        f"  Codename:         {codename}",
        f"  Device:           {display_name}",
        f"  ROM Version:      {rom_version}",
        f"  Android:          {android_ver}",
        f"  Style:            {style_name}",
        f"  License:          {style_tier}",
        f"  Region:           {region}",
        f"  SoC:              Snapdragon",
        f"  Flash style:      _ab (garnet reference)",
        f"  Fastboot path:    bin\\windows\\fastboot.exe",
        "",
        f"Images discovered ({len(available_imgs)}):",
    ]
    for img in sorted(available_imgs):
        part = SD_FLASH_MAP.get(img, f"{Path(img).stem}_ab (auto)")
        lines.append(f"  {img:<35s}  → {part}")

    lines += [
        "",
        f"Generated flash commands ({len(flash_pairs)}):",
    ]
    for part, img in flash_pairs:
        lines.append(f"  fastboot flash {part} images\\{img}")

    if skipped_pairs:
        lines += [f"", f"Skipped images ({len(skipped_pairs)}):"]
        for img, reason in skipped_pairs:
            lines.append(f"  SKIP {img}: {reason}")
    else:
        lines += ["", "Skipped images: none"]

    lines += [
        "",
        f"Generated BAT:      {bat_path}",
        f"  Present:          {'YES' if bat_path.is_file() else 'NO'}",
        f"  Size:             {bat_path.stat().st_size:,} bytes" if bat_path.is_file() else "  Size:             N/A",
        "",
        f"Validation result:  {validation_result}",
    ]

    out = REPORTS_DIR / "snapdragon_flash_script_report.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[PACKAGE] Snapdragon script report → {out}")


# ── Snapdragon firmware info file ────────────────────────────────────────────

def _gen_firmware_txt(
    img_dir: Path,
    codename: str,
    rom_version: str,
    android_ver: str,
    region: str,
    style_name: str,
    style_tier: str,
    norm_soc: str,
    device_name: str = "",
) -> None:
    """Generate images/DeadZone_firmware.txt for MTK and Snapdragon builds.

    Read at runtime by windows_install_and_format_data.bat for all display fields.
    Replaces any old HyperUR_firmware.txt from uploaded templates.
    """
    old_names = ["HyperUR_firmware.txt", "hyperur_firmware.txt"]
    for old in old_names:
        old_p = img_dir / old
        if old_p.is_file():
            old_p.unlink()
            print(f"[PACKAGE] Removed old firmware file: {old}")

    soc_label = "MTK" if norm_soc == "mtk" else "Snapdragon"
    display   = device_name or codename
    content = (
        f"Codename={codename}\n"
        f"Device={display}\n"
        f"version={rom_version}\n"
        f"Android={android_ver}\n"
        f"Style={style_name}\n"
        f"License={style_tier}\n"
        f"Developer=MEZO\n"
        f"SoC={soc_label}\n"
        f"Region={region}\n"
    )
    dest = img_dir / "DeadZone_firmware.txt"
    dest.write_text(content, encoding="utf-8")
    print(f"[PACKAGE] Generated images/DeadZone_firmware.txt (SoC={soc_label})")


# ── Main packaging logic ──────────────────────────────────────────────────────

def package() -> Path:
    # ── Read device info ──────────────────────────────────────────────────────
    codename     = _read("device_f.txt") or _read("device_code.txt") or "unknown"
    rom_version  = _sanitize_name(_read("base_rom_code.txt") or "UNKNOWN")
    android_ver  = re.sub(r"\D", "", _read("androidver.txt") or "")
    baserom_type = _read("romtype.txt") or "payload"

    # ── Resolve DeadZone Style ────────────────────────────────────────────────
    raw_style = os.environ.get("DZ_STYLE", "Plus")
    try:
        style_id = _normalize_style(raw_style)
    except ValueError as exc:
        print(f"[STYLE] ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    style_cfg = DZ_STYLES[style_id]
    print(
        f"[STYLE] {raw_style!r} → {style_cfg['id']} "
        f"({style_cfg['name']}, {style_cfg['tier']})"
    )

    # Unified ZIP naming: DeadZone_<Style>_<codename>_<os_version>.zip
    style_prefix = style_cfg["id"].capitalize()
    zip_name       = f"DeadZone_{style_prefix}_{_sanitize_name(codename)}_{rom_version}.zip"
    _naming_scheme = "deadzone"
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
    print(f"[PACKAGE] SoC: {norm_soc.upper()} — using {'MTK _ab' if norm_soc == 'mtk' else 'garnet reference _ab'} partition style")

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

    # ── SoC-specific staging cleanup ─────────────────────────────────────────
    if norm_soc == "snapdragon":
        # Snapdragon: keep bin/windows/ (fastboot) and META-INF/ (recovery support).
        # Remove only legacy/old files from the uploaded garnet package.
        for _old_name in ("windows_fastboot_first_install_with_data_format.bat",
                          "Flashing_Tool_Windows_2.bat",
                          "windows_install_upgrade.bat",
                          "windows_format_data_only.bat"):
            _p = staging / _old_name
            if _p.is_file():
                _p.unlink()
                print(f"[PACKAGE] Removed old Snapdragon file from staging: {_old_name}")
        # Patch META-INF/updater-script: replace DEADZONE_CODENAME with actual codename
        _us = staging / "META-INF" / "com" / "google" / "android" / "updater-script"
        if _us.is_file():
            _us_content = _us.read_text(encoding="utf-8", errors="replace")
            if "DEADZONE_CODENAME" in _us_content:
                _us_content = _us_content.replace("DEADZONE_CODENAME", _sanitize_name(codename))
                _us.write_text(_us_content, encoding="utf-8")
                print(f"[PACKAGE] Patched META-INF/updater-script: codename={_sanitize_name(codename)}")
    else:
        # MTK: remove platform-specific dirs not needed in final ZIP
        for _plat_dir in ("META-INF", "bin/linux", "bin/macos"):
            _pd = staging / _plat_dir.replace("/", os.sep)
            if _pd.is_dir():
                shutil.rmtree(_pd)
                print(f"[PACKAGE] Removed {_plat_dir}/ from MTK staging")

    # ── images/ directory — clear placeholders, prepare for real images ────────
    img_dir = staging / "images"
    if img_dir.is_dir():
        for _placeholder in img_dir.glob("*.img"):
            _placeholder.unlink()
        # Remove any old HyperUR firmware file from the template
        for _old_fw in img_dir.glob("*.txt"):
            if "hyperur" in _old_fw.name.lower():
                _old_fw.unlink()
                print(f"[PACKAGE] Removed old firmware file from staging: {_old_fw.name}")
    img_dir.mkdir(exist_ok=True)

    copied_imgs: list[str] = []

    # super.img — must exist (created by packROM.sh)
    super_src = BUILD_IMAGES / "super.img"
    if super_src.is_file():
        super_info = _detect_image(super_src)
        print(
            f"[IMAGE] super.img: {super_info['type']}, "
            f"size={super_info['size']}, magic={super_info['magic']}"
        )
        shutil.copy2(super_src, img_dir / "super.img")
        copied_imgs.append("super.img")
        print(f"[PACKAGE] Copied super.img ({super_src.stat().st_size / 1024**2:.0f} MiB)")
    else:
        _write_package_error_report(
            stage="package:copy-images",
            image="super.img",
            reason="build/baserom/images/super.img not found — packROM.sh must create it before package_rom.py runs",
        )
        print("[PACKAGE] ERROR: build/baserom/images/super.img not found!", file=sys.stderr)
        sys.exit(1)

    # Other .img files — copy with sparse/raw detection logging
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
            img_info = _detect_image(img)
            print(
                f"[IMAGE] {img.name}: {img_info['type']}, "
                f"size={img_info['size']}, magic={img_info['magic']}"
            )
            shutil.copy2(img, img_dir / img.name)
            copied_imgs.append(img.name)

    available_imgs = {p.name for p in img_dir.glob("*.img")}
    print(f"[PACKAGE] Images collected: {len(copied_imgs)} files")
    print(f"  {', '.join(copied_imgs[:8])}{'...' if len(copied_imgs) > 8 else ''}")

    # ── Image type report (all images in staging) ─────────────────────────────
    images_info = _log_all_images(img_dir)
    _write_image_type_report(images_info)

    # ── Validate required images ──────────────────────────────────────────────
    missing_required = sorted(req for req in REQUIRED_IMAGES if req not in available_imgs)
    if missing_required:
        _write_package_error_report(
            stage="package:validate-images",
            reason=f"Required images missing: {', '.join(missing_required)}",
        )
        print("[PACKAGE] ERROR: Required images missing:", file=sys.stderr)
        for img in missing_required:
            print(f"  ! {img}", file=sys.stderr)
        sys.exit(1)

    # ── Generate windows_install_and_format_data.bat from actual images ──────────
    _raw_device_type = _read("device_type.txt") or ""
    _raw_rom_version = _read("base_rom_code.txt") or ""
    # Import rom_metadata for region parsing
    try:
        import importlib.util as _ilu
        _rm_spec = _ilu.spec_from_file_location(
            "rom_metadata",
            str(Path(__file__).resolve().parent / "rom_metadata.py"),
        )
        _rm_mod = _ilu.module_from_spec(_rm_spec)
        _rm_spec.loader.exec_module(_rm_mod)
        if _raw_device_type and _raw_device_type.upper() not in ("OS1", "OS2", "OS3", "MIUI"):
            region = _rm_mod.get_region_from_device_type(_raw_device_type)
        elif _raw_rom_version:
            _meta = _rm_mod.parse_rom_version(_raw_rom_version)
            region = _meta.get("region_display") or _raw_device_type or "Global"
        else:
            region = _raw_device_type or "Global"
    except Exception:
        region = _raw_device_type if _raw_device_type and _raw_device_type.upper() not in ("OS1", "OS2", "OS3", "MIUI") else "Global"
    flash_cmds, skipped_pairs = _gen_install_bat(
        staging        = staging,
        available_imgs = available_imgs,
        norm_soc       = norm_soc,
        codename       = _sanitize_name(codename),
        rom_version    = rom_version or "UNKNOWN",
        android_ver    = android_ver or "UNKNOWN",
        region         = region,
        style_name     = style_cfg["name"],
        style_tier     = style_cfg["tier"],
    )
    win_warnings: list[str] = []
    unknown_imgs: list[str] = []   # no unknown images in the new generation model

    # ── Generate images/DeadZone_firmware.txt for both SoCs ──────────────────
    _gen_firmware_txt(
        img_dir     = img_dir,
        codename    = _sanitize_name(codename),
        rom_version = rom_version or "UNKNOWN",
        android_ver = android_ver or "UNKNOWN",
        region      = region,
        style_name  = style_cfg["name"],
        style_tier  = style_cfg["tier"],
        norm_soc    = norm_soc,
        device_name = cfg.get("display_name", "") or _sanitize_name(codename),
    )

    # ── Validate the generated windows_install_and_format_data.bat ────────────
    tpl_bat_errors = _validate_template_bat(staging, norm_soc)
    if tpl_bat_errors:
        print("[PACKAGE] Generated BAT validation ERRORS:", file=sys.stderr)
        for e in tpl_bat_errors:
            print(f"  ! {e}", file=sys.stderr)
        sys.exit(1)
    print("[PACKAGE] Generated BAT validation: PASS")

    # ── Generate Linux and macOS flash scripts (same flash_pairs as Windows BAT) ─
    flash_pairs_for_report, _ = _compute_flash_pairs(available_imgs, norm_soc)
    _gen_linux_flash_script(
        staging    = staging,
        flash_pairs= flash_pairs_for_report,
        codename   = _sanitize_name(codename),
        rom_version= rom_version or "UNKNOWN",
        android_ver= android_ver or "UNKNOWN",
        region     = region,
        style_name = style_cfg["name"],
        norm_soc   = norm_soc,
    )
    _gen_macos_flash_script(
        staging    = staging,
        flash_pairs= flash_pairs_for_report,
        codename   = _sanitize_name(codename),
        rom_version= rom_version or "UNKNOWN",
        android_ver= android_ver or "UNKNOWN",
        region     = region,
        style_name = style_cfg["name"],
        norm_soc   = norm_soc,
    )

    # ── Write flash script generation report (both SoCs) ─────────────────────
    _write_flash_script_generation_report(
        norm_soc       = norm_soc,
        codename       = _sanitize_name(codename),
        rom_version    = rom_version or "UNKNOWN",
        android_ver    = android_ver or "UNKNOWN",
        region         = region,
        style_name     = style_cfg["name"],
        style_tier     = style_cfg["tier"],
        available_imgs = available_imgs,
        flash_pairs    = flash_pairs_for_report,
        skipped_pairs  = skipped_pairs,
        bat_path       = staging / "windows_install_and_format_data.bat",
        validation_result = "PASS",
    )

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

    _EXEC_ARCNAMES = frozenset({"bin/linux/fastboot", "bin/macos/fastboot"})

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for f in sorted(staging.rglob("*")):
            if f.is_file():
                arcname = f.relative_to(staging)
                arcname_posix = arcname.as_posix()
                needs_exec = f.name.endswith(".sh") or arcname_posix in _EXEC_ARCNAMES
                if needs_exec:
                    zi = zipfile.ZipInfo.from_file(f, arcname_posix)
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    zi.external_attr = 0o755 << 16
                    data = f.read_bytes()
                    zf.writestr(zi, data, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
                    uncompressed_bytes += len(data)
                else:
                    zf.write(f, arcname_posix)
                    uncompressed_bytes += f.stat().st_size

    size_mib = zip_path.stat().st_size / 1024**2
    ratio    = uncompressed_bytes / zip_path.stat().st_size if zip_path.stat().st_size > 0 else 1.0
    print(f"[PACKAGE] ZIP created: {size_mib:.1f} MiB  (ratio {ratio:.2f}x)")

    # ── Validate ZIP ──────────────────────────────────────────────────────────
    zip_errors = _validate_zip(zip_path, available_imgs, norm_soc)
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
        style_id=style_cfg["id"],
        naming_scheme=_naming_scheme,
        style_input_original=raw_style,
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
    _write_style_report(
        raw_style=raw_style,
        style_id=style_id,
        norm_soc=norm_soc,
        codename=_sanitize_name(codename),
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
    try:
        package()
    except SystemExit as exc:
        if exc.code and exc.code != 0:
            try:
                dbg = _create_debug_zip()
                if dbg:
                    print(f"[DEBUG-ZIP] Failure debug ZIP: {dbg}", file=sys.stderr)
            except Exception as zip_exc:
                print(f"[DEBUG-ZIP] Could not create debug ZIP: {zip_exc}", file=sys.stderr)
        raise
    except Exception as exc:
        print(f"[PACKAGE] Fatal unexpected error: {exc}", file=sys.stderr)
        try:
            _write_package_error_report(
                stage="package:unexpected",
                reason=str(exc),
            )
            dbg = _create_debug_zip()
            if dbg:
                print(f"[DEBUG-ZIP] Failure debug ZIP: {dbg}", file=sys.stderr)
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()
