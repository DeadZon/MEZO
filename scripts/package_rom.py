#!/usr/bin/env python3
"""DeadZone ROM packaging script for MEZO.

Replaces old uploadROM.sh packaging.
- Reads device info from bin/ddevice/ (populated by build.sh)
- Resolves device config via device_resolver
- Extracts DeadZone_Mezo.rar template exactly as-is (required)
- Copies .img files from build output into images/
- Does NOT generate or overwrite any flash scripts
- Creates: DeadZone_<codename>_<rom_version>_A<android>.zip
- Writes: output/reports/final_zip_path.txt
-         output/reports/device_resolve_report.txt
-         output/reports/final_zip_manifest.txt
-         output/reports/final_zip_summary.json

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


def _flatten_template(staging: Path) -> str | None:
    """If the RAR extracted into a single top-level folder, lift its contents to staging root.

    Returns the nested folder name if flattening occurred, else None.
    """
    top_entries = list(staging.iterdir())
    if len(top_entries) != 1 or not top_entries[0].is_dir():
        return None  # already flat or multiple entries

    nested = top_entries[0]
    # Only flatten when the nested dir looks like the template root
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


def _write_summary(zip_path: Path, sha: str, cfg: dict, images: list[str], scripts: list[str],
                   template_used: bool = True, template_preserved: bool = True,
                   nested_root: str | None = None) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    summary = {
        "codename":                cfg["codename"],
        "rom_os_version":          _read("base_rom_code.txt"),
        "android_version":         _read("androidver.txt"),
        "final_zip_name":          zip_path.name,
        "final_zip_path":          str(zip_path),
        "size_bytes":              zip_path.stat().st_size,
        "sha256":                  sha,
        "file_count":              0,
        "images_included":         images,
        "scripts_included":        scripts,
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

    # Extract template RAR — required, no fallback
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

    # Verify template is intact: bin/ and all flash scripts must be present
    _REQUIRED_SCRIPTS = [
        "windows_install_upgrade.bat", "windows_install_and_format_data.bat",
        "windows_format_data_only.bat",
        "linux_install_upgrade.sh", "linux_install_and_format_data.sh",
        "linux_format_data_only.sh",
        "macos_install_upgrade.sh", "macos_install_and_format_data.sh",
        "macos_format_data_only.sh",
    ]
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
    _write_summary(zip_path, sha, cfg, copied_imgs, scripts_in_zip,
                   template_used=template_used, template_preserved=template_preserved,
                   nested_root=nested_root)

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
