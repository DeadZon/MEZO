#!/usr/bin/env python3
"""Create a failure debug ZIP with all useful logs, reports, and diagnostics.

Output: output/reports/build_failure_debug.zip

Includes (if present):
  output/logs/**
  output/reports/**
  Last 300 lines of /tmp/mezo_*.log build logs
  List of build/baserom/images files with size/type/magic
  Staging BAT and firmware.txt (if staging exists)

Excludes:
  Large *.img files (actual images)
  ROM ZIP file
  Secrets
"""
from __future__ import annotations

import sys
import time
import zipfile
from pathlib import Path

WORK_DIR    = Path.cwd()
REPORTS_DIR = WORK_DIR / "output" / "reports"
LOGS_DIR    = WORK_DIR / "output" / "logs"
BUILD_IMAGES = WORK_DIR / "build" / "baserom" / "images"
STAGING_BASE = WORK_DIR / "out" / "dz_staging"

# Android sparse magic
_SPARSE_MAGIC = bytes([0x3A, 0xFF, 0x26, 0xED])


def _detect_image(path: Path) -> dict:
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


def create_debug_zip() -> Path | None:
    """Build output/reports/build_failure_debug.zip and return its path."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = REPORTS_DIR / "build_failure_debug.zip"

    added: set[str] = set()

    def _add(zf: zipfile.ZipFile, src: Path, arcname: str) -> None:
        if arcname not in added and src.is_file():
            try:
                zf.write(src, arcname)
                added.add(arcname)
            except Exception as exc:
                print(f"[DEBUG-ZIP] Cannot add {arcname}: {exc}", file=sys.stderr)

    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:

            # ── output/logs/** ────────────────────────────────────────────────
            if LOGS_DIR.is_dir():
                for f in sorted(LOGS_DIR.rglob("*")):
                    if f.is_file() and f.suffix != ".img":
                        if f.stat().st_size < 20 * 1024 * 1024:
                            _add(zf, f, f"logs/{f.relative_to(LOGS_DIR)}")

            # ── output/reports/** (skip the ZIP itself and large files) ──────
            if REPORTS_DIR.is_dir():
                for f in sorted(REPORTS_DIR.rglob("*")):
                    if f == zip_path:
                        continue
                    if f.is_file() and f.suffix != ".img":
                        if f.stat().st_size < 20 * 1024 * 1024:
                            _add(zf, f, f"reports/{f.relative_to(REPORTS_DIR)}")

            # ── Extra named report files (belt-and-suspenders) ────────────────
            for rel in [
                "output/logs/package_commands.log",
                "output/reports/package_error_report.txt",
                "output/reports/image_type_report.txt",
                "output/reports/framework_patcher_report.txt",
                "output/reports/signature_verification_bypass_report.txt",
                "output/reports/invoke_custom_report.txt",
                "output/reports/framework_patcher_error.txt",
                "output/reports/final_zip_template_report.txt",
                "output/reports/snapdragon_flash_script_report.txt",
                "output/reports/flash_script_generation_report.txt",
                "output/reports/deadzone_style_report.txt",
                "output/reports/device_resolve_report.txt",
                "output/reports/final_zip_manifest.txt",
                "output/reports/final_zip_summary.json",
                # Kaorios Toolbox reports
                "output/reports/kaorios_assets_report.txt",
                "output/reports/kaorios_toolbox_report.txt",
                "output/reports/kaorios_framework_patch_report.txt",
                "output/reports/kaorios_error_report.txt",
                # JAR Mods engine reports
                "output/reports/jar_patches/deadzone_mezo_jar_mods_report.txt",
                "output/reports/jar_patches/deadzone_mezo_jar_mods_error.txt",
            ]:
                p = WORK_DIR / rel
                arcname = Path(rel).name
                _add(zf, p, arcname)

            # ── build_info.txt (if present) ───────────────────────────────────
            _add(zf, WORK_DIR / "build_info.txt", "build_info.txt")

            # ── Last 300 lines of build logs ──────────────────────────────────
            for log_name in ["mezo_build.log", "mezo_pack.log", "mezo_package.log"]:
                log_p = Path("/tmp") / log_name
                if log_p.is_file():
                    try:
                        lines = log_p.read_text(encoding="utf-8", errors="replace").splitlines()
                        tail  = "\n".join(lines[-300:])
                        arc   = f"build_log_tail_{log_name}"
                        if arc not in added:
                            zf.writestr(arc, tail)
                            added.add(arc)
                    except Exception:
                        pass

            # ── build/baserom/images file list (no actual .img content) ───────
            img_list: list[str] = [
                "Build images file list",
                f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}",
                "=" * 60,
            ]
            if BUILD_IMAGES.is_dir():
                for img in sorted(BUILD_IMAGES.glob("*")):
                    if img.is_file():
                        info = _detect_image(img) if img.suffix == ".img" else {"type": "-", "size": img.stat().st_size, "magic": "-"}
                        img_list.append(
                            f"{img.name:<45s}  {info['type']:<8s}  size={info['size']:>12,}  magic={info['magic']}"
                        )
            if "build_images_list.txt" not in added:
                zf.writestr("build_images_list.txt", "\n".join(img_list))
                added.add("build_images_list.txt")

            # ── Staging directory artifacts (BAT + firmware.txt only) ─────────
            staging_img_dir = STAGING_BASE / "images"

            bat_p = STAGING_BASE / "windows_install_and_format_data.bat"
            _add(zf, bat_p, "staging_windows_install_and_format_data.bat")

            fw_p = staging_img_dir / "DeadZone_firmware.txt"
            _add(zf, fw_p, "staging_images_DeadZone_firmware.txt")

            # Staging images list (no content)
            st_list: list[str] = ["Staging images file list", "=" * 60]
            if staging_img_dir.is_dir():
                for img in sorted(staging_img_dir.glob("*.img")):
                    info = _detect_image(img)
                    st_list.append(
                        f"{img.name:<45s}  {info['type']:<8s}  size={info['size']:>12,}  magic={info['magic']}"
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


if __name__ == "__main__":
    result = create_debug_zip()
    sys.exit(0 if result else 1)
