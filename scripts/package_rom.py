#!/usr/bin/env python3
"""DeadZone ROM packaging script for MEZO.

Replaces old uploadROM.sh packaging.
- Reads device info from bin/ddevice/ (populated by build.sh)
- Resolves device config via device_resolver
- Extracts DeadZone_Mezo.rar template exactly as-is (required)
- Copies .img files from build output into images/
- Does NOT generate or overwrite any flash scripts
- Validates scripts, images, and ZIP before finalising
- Creates: DeadZone_<codename>_<rom_version>_A<android>.zip
- Writes: output/reports/final_zip_path.txt
-         output/reports/device_resolve_report.txt
-         output/reports/final_zip_manifest.txt
-         output/reports/final_zip_summary.json
-         output/reports/pipeline_script_scan_report.txt

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

# All .img files that belong in images/ (super.img handled separately)
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

# img filename → fastboot partition name
FLASH_MAP: dict[str, str] = {
    "boot.img":           "boot",
    "init_boot.img":      "init_boot",
    "vendor_boot.img":    "vendor_boot",
    "dtbo.img":           "dtbo",
    "logo.img":           "logo",
    "cust.img":           "cust",
    "super.img":          "super",
    "vbmeta.img":         "vbmeta",
    "vbmeta_system.img":  "vbmeta_system",
    "vbmeta_vendor.img":  "vbmeta_vendor",
    "vbmeta_product.img": "vbmeta_product",
    "vbmeta_odm.img":     "vbmeta_odm",
}

FORBIDDEN_ENTRIES = [
    "output/", "build/", "work/", "logs/", "reports/",
    "payload.bin", ".git", "super.img.zst",
]

_REQUIRED_SCRIPTS = [
    "windows_install_upgrade.bat", "windows_install_and_format_data.bat",
    "windows_format_data_only.bat",
    "linux_install_upgrade.sh", "linux_install_and_format_data.sh",
    "linux_format_data_only.sh",
    "macos_install_upgrade.sh", "macos_install_and_format_data.sh",
    "macos_format_data_only.sh",
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


def _validate_scripts_against_images(
    staging: Path, img_dir: Path
) -> tuple[list[str], list[str], list[str]]:
    """Validate template flash scripts: non-empty, have commands, no missing image refs.

    Returns: (errors, warnings, missing_image_refs)
    """
    errors:   list[str] = []
    warnings: list[str] = []
    missing:  list[str] = []

    available_imgs = {f.name for f in img_dir.glob("*.img")}
    any_has_commands = False

    for sname in _REQUIRED_SCRIPTS:
        sp = staging / sname
        if not sp.is_file():
            errors.append(f"Script missing: {sname}")
            continue
        try:
            content = sp.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            errors.append(f"Cannot read {sname}: {exc}")
            continue
        stripped = content.strip()
        if not stripped:
            errors.append(f"Script is empty: {sname}")
            continue
        # Check for actual flash/command content (beyond just comments)
        non_comment_lines = [
            ln for ln in stripped.splitlines()
            if ln.strip() and not ln.strip().startswith(("#", "::"))
        ]
        if len(non_comment_lines) < 3:
            errors.append(f"Script has no real commands: {sname}")
            continue
        if "fastboot" in content.lower():
            any_has_commands = True
        # Find references to images/xxx.img
        for m in re.finditer(r'images[\\/]([^\s"\'\\;]+\.img)', content, re.IGNORECASE):
            ref = m.group(1).replace("\\", "/").split("/")[-1]
            if ref not in available_imgs:
                msg = f"{sname}: references images/{ref} — file not in images/"
                warnings.append(msg)
                missing.append(ref)

    if not any_has_commands:
        warnings.append("No flash script contains 'fastboot' — check template scripts")

    return errors, warnings, missing


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

def _write_manifest(
    zip_path: Path, sha: str,
    imgs_detected: list[str],
    unknown_imgs: list[str],
    missing_refs: list[str],
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
        "",
        f"Images detected ({len(imgs_detected)}):",
    ]
    for img in sorted(imgs_detected):
        part = FLASH_MAP.get(img, "(extra)")
        lines.append(f"  {img:<35s}  → fastboot flash {part}")
    if unknown_imgs:
        lines.append("")
        lines.append(f"Unknown extra images ({len(unknown_imgs)}) — not flashed by template:")
        for img in sorted(unknown_imgs):
            lines.append(f"  {img}")
    if missing_refs:
        lines.append("")
        lines.append(f"Flash script references to missing images ({len(missing_refs)}):")
        for ref in sorted(set(missing_refs)):
            lines.append(f"  images/{ref}  [MISSING]")

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
    template_used: bool = True, template_preserved: bool = True,
    nested_root: str | None = None,
    missing_refs: list[str] | None = None,
    uncompressed_bytes: int = 0,
    zip_tool: str = "python-zipfile",
) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    compressed_bytes = zip_path.stat().st_size
    ratio = uncompressed_bytes / compressed_bytes if compressed_bytes > 0 else 1.0

    summary: dict = {
        "codename":                cfg["codename"],
        "soc":                     cfg.get("soc_family", ""),
        "rom_os_version":          _read("base_rom_code.txt"),
        "android_version":         _read("androidver.txt"),
        "final_zip_name":          zip_path.name,
        "final_zip_path":          str(zip_path),
        "sha256":                  sha,
        "size_bytes":              compressed_bytes,
        "file_count":              0,
        "images_detected":         images,
        "flash_scripts_checked":   scripts,
        "flash_commands_generated": False,
        "missing_images_referenced": list(set(missing_refs or [])),
        "scripts_empty":           False,
        "template_archive":        TEMPLATE_RAR.name,
        "template_nested_root":    nested_root or "",
        "template_flattened":      nested_root is not None,
        "template_used":           template_used,
        "template_preserved":      template_preserved,
        "bin_exists":              True,
        "scripts_preserved":       True,
        "scripts_generated":       False,
        "bin_renamed":             False,
        "images_added":            len(images) > 0,
        "compression_method":      "deflate9",
        "compressed_size_bytes":   compressed_bytes,
        "uncompressed_size_bytes": uncompressed_bytes,
        "compression_ratio":       round(ratio, 4),
        "zip_tool_used":           zip_tool,
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
        ("build.sh",                            WORK_DIR / "build.sh"),
        ("packROM.sh",                          WORK_DIR / "packROM.sh"),
        ("scripts/package_rom.py",              WORK_DIR / "scripts" / "package_rom.py"),
        ("scripts/pixeldrain_upload.py",        WORK_DIR / "scripts" / "pixeldrain_upload.py"),
        ("scripts/tg_watch.py",                 WORK_DIR / "scripts" / "tg_watch.py"),
        ("scripts/telegram.py",                 WORK_DIR / "scripts" / "telegram.py"),
        (".github/workflows/mezo_mtk.yml",      WORK_DIR / ".github" / "workflows" / "mezo_mtk.yml"),
        (".github/workflows/mezo_snapdragon.yml", WORK_DIR / ".github" / "workflows" / "mezo_snapdragon.yml"),
    ]

    _LOG_MARKER_RE = re.compile(
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

        markers = sorted(set(_LOG_MARKER_RE.findall(content)))
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

        # Workflow-specific checks
        if label.endswith(".yml"):
            issues: list[str] = []
            if "build_rom" in content:
                issues.append("deprecated stage 'build_rom' — use 'unpack'/'mods'")
            if "pack_rom" in content:
                issues.append("deprecated stage 'pack_rom' — use 'rebuild'/'super'/'vbmeta'")
            for sid in ("unpack", "mods", "rebuild", "super", "vbmeta", "zip", "upload_pixeldrain"):
                if f"update {sid}" in content:
                    lines.append(f"  stage tracked: {sid}")
            if issues:
                lines.append("  WARNINGS:")
                for iss in issues:
                    lines.append(f"    ! {iss}")
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

    # ── Extract template RAR — required, no fallback ──────────────────────────
    if not TEMPLATE_RAR.is_file():
        print(f"[PACKAGE] ERROR: Template RAR not found: {TEMPLATE_RAR}", file=sys.stderr)
        sys.exit(1)

    print(f"[PACKAGE] Extracting template: {TEMPLATE_RAR}")
    template_used = _extract_rar(TEMPLATE_RAR, staging)
    if not template_used:
        print("[PACKAGE] ERROR: RAR extraction failed — unrar, 7z, or bsdtar required", file=sys.stderr)
        sys.exit(1)

    # Flatten if RAR extracted into a single nested folder (e.g. DeadZone_Mezo/)
    nested_root = _flatten_template(staging)

    # ── Verify template is intact ─────────────────────────────────────────────
    missing_scripts = [s for s in _REQUIRED_SCRIPTS if not (staging / s).is_file()]
    bin_ok = (staging / "bin").is_dir()
    if missing_scripts or not bin_ok:
        print("[PACKAGE] ERROR: Template extraction incomplete!", file=sys.stderr)
        if not bin_ok:
            print("  bin/ directory missing from template", file=sys.stderr)
        for s in missing_scripts:
            print(f"  Missing flash script: {s}", file=sys.stderr)
        sys.exit(1)
    template_preserved = True
    print(f"[PACKAGE] Template verified: bin/ present, {len(_REQUIRED_SCRIPTS)} flash scripts intact")

    # ── images/ directory ─────────────────────────────────────────────────────
    img_dir = staging / "images"
    img_dir.mkdir(exist_ok=True)

    copied_imgs: list[str] = []

    # 1. super.img — must exist
    super_src = BUILD_IMAGES / "super.img"
    if super_src.is_file():
        shutil.copy2(super_src, img_dir / "super.img")
        copied_imgs.append("super.img")
        print(f"[PACKAGE] Copied super.img ({super_src.stat().st_size / 1024**2:.0f} MiB)")
    else:
        print("[PACKAGE] ERROR: build/baserom/images/super.img not found!", file=sys.stderr)
        sys.exit(1)

    # 2. Other .img files from build output
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

    print(f"[PACKAGE] Images collected: {len(copied_imgs)} files")
    print(f"  {', '.join(copied_imgs[:8])}{'...' if len(copied_imgs) > 8 else ''}")

    # Classify known vs unknown images
    known_imgs   = [n for n in copied_imgs if n in FLASH_MAP]
    unknown_imgs = [n for n in copied_imgs if n not in FLASH_MAP]
    if unknown_imgs:
        print(f"[PACKAGE] Extra images (not in FLASH_MAP, not flashed by default): {unknown_imgs}")

    # ── Validate flash scripts against available images ───────────────────────
    script_errors, script_warnings, missing_refs = _validate_scripts_against_images(staging, img_dir)
    if script_errors:
        print("[PACKAGE] SCRIPT VALIDATION ERRORS:", file=sys.stderr)
        for e in script_errors:
            print(f"  ! {e}", file=sys.stderr)
        sys.exit(1)
    for w in script_warnings:
        print(f"[PACKAGE] WARN: {w}", file=sys.stderr)
    print(f"[PACKAGE] Script validation: PASS ({len(_REQUIRED_SCRIPTS)} scripts checked)")

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
    errors = _validate_zip(zip_path)
    if errors:
        print("[PACKAGE] VALIDATION ERRORS:", file=sys.stderr)
        for e in errors:
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
        missing_refs=missing_refs,
        template_preserved=template_preserved,
        uncompressed_bytes=uncompressed_bytes,
    )
    _write_summary(
        zip_path, sha, cfg,
        images=copied_imgs,
        scripts=scripts_in_zip,
        template_used=template_used,
        template_preserved=template_preserved,
        nested_root=nested_root,
        missing_refs=missing_refs,
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
