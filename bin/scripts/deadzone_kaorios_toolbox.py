#!/usr/bin/env python3
"""DeadZone Kaorios Toolbox Integration

Downloads Kaorios Toolbox V2.0.4 assets and integrates them as a base feature
for all DeadZone styles (Stable, Legend, and future).

Source:  https://github.com/Wuang26/Kaorios-Toolbox  tag V2.0.4
Guide:   bin/third_party/kaorios_toolbox/docs/V2.0.3+/Guide_2.0.3+.md

Steps:
  1. Validate / download assets (APK, XML, classes.dex)
  2. Install APK  -> system_ext/priv-app/KaoriosToolbox/  (fallback: product/)
  3. Install XML  -> system_ext/etc/permissions/           (fallback: product/)
  4. Patch build.prop (persist.sys.kaorios, ro.control_privapp_permissions)
  5. Inject Kaorios classes.dex into framework.jar as next classesN.dex
  6. Apply V2.0.3+ smali hooks to framework.jar
  7. Apply V2.0.3+ SystemServer hook to services.jar

Reports:
  output/reports/kaorios_assets_report.txt
  output/reports/kaorios_toolbox_report.txt
  output/reports/kaorios_framework_patch_report.txt
  output/reports/kaorios_error_report.txt  (only on failure)
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── Paths ──────────────────────────────────────────────────────────────────────
WORK_DIR     = Path.cwd()
REPORTS_DIR  = WORK_DIR / "bin" / "output" / "reports"
DDEVICE_DIR  = WORK_DIR / "bin" / "ddevice"
BUILD_IMAGES = WORK_DIR / "build" / "baserom" / "images"
ASSET_DIR    = WORK_DIR / "bin" / "third_party" / "kaorios_toolbox"
APKTOOL_DIR  = WORK_DIR / "bin" / "apktool"
TOOLS_DIR    = WORK_DIR / "bin" / "tools"

# ── Release constants ──────────────────────────────────────────────────────────
KAORIOS_VERSION      = "2.0.4.0"
KAORIOS_TAG          = "V2.0.4"
KAORIOS_REPO         = "https://github.com/Wuang26/Kaorios-Toolbox"
_BASE_URL            = f"{KAORIOS_REPO}/releases/download/{KAORIOS_TAG}"

APK_CANON            = "KaoriosToolbox.apk"
XML_CANON            = "privapp_whitelist_com.kousei.kaorios.xml"
DEX_CANON            = "classes.dex"

ASSET_RELEASE_NAMES  = {
    APK_CANON: "KaoriosPatcher-V2.0.4.0.apk",
    XML_CANON: "com.kousei.kaorios.xml",
    DEX_CANON: "classes_V2.0.4.0.dex",
}
ASSET_URLS = {
    APK_CANON: f"{_BASE_URL}/KaoriosPatcher-V2.0.4.0.apk",
    XML_CANON: f"{_BASE_URL}/com.kousei.kaorios.xml",
    DEX_CANON: f"{_BASE_URL}/classes_V2.0.4.0.dex",
}
ASSET_PATHS = {
    APK_CANON: ASSET_DIR / "app"         / APK_CANON,
    XML_CANON: ASSET_DIR / "permissions" / XML_CANON,
    DEX_CANON: ASSET_DIR / "framework"   / DEX_CANON,
}

# ── Backup suffix ──────────────────────────────────────────────────────────────
BACKUP_SUFFIX = ".bak_deadzone_kaorios"

# ── JAR candidates ─────────────────────────────────────────────────────────────
FRAMEWORK_JAR_CANDIDATES = ["system/framework/framework.jar"]
SERVICES_JAR_CANDIDATES  = ["system/framework/services.jar"]

# ── build.prop properties ──────────────────────────────────────────────────────
BUILDPROP_HEADER = "# Kaorios Toolbox"
BUILDPROP_PROPS  = [
    ("persist.sys.kaorios", "kousei"),
    ("ro.control_privapp_permissions", ""),
]
BUILDPROP_CANDIDATES = [
    "system/build.prop",
    "product/build.prop",
    "system_ext/build.prop",
]

# ── Smali class paths ──────────────────────────────────────────────────────────
INSTRUMENTATION_CLASS = "android/app/Instrumentation"
APM_CLASS             = "android/app/ApplicationPackageManager"
KEYSTORE_GEN_CLASS    = "android/security/keystore2/AndroidKeyStoreKeyPairGeneratorSpi"
KEYSTORE_SPI_CLASS    = "android/security/keystore2/AndroidKeyStoreSpi"
SYSTEM_SERVER_CLASS   = "com/android/server/SystemServer"

KAORIOS_HOOK          = "Landroid/security/kaorios/KaoriosHook;"


# ── Data classes ───────────────────────────────────────────────────────────────

@dataclass
class HookResult:
    target:  str
    applied: bool
    note:    str = ""


@dataclass
class KaoriosRun:
    style:     str = ""
    style_tier: str = ""
    android_ver: str = ""
    codename:  str = ""

    # assets
    assets_valid:      bool = False
    assets_local:      list[str] = field(default_factory=list)   # found in repo
    assets_downloaded: list[str] = field(default_factory=list)   # fetched at build time
    asset_sizes:       dict[str, int] = field(default_factory=dict)
    asset_errors:      list[str] = field(default_factory=list)

    # install — APK
    install_partition:    str = ""
    apk_src:              str = ""
    apk_folder:           str = ""
    apk_folder_created:   bool = False
    apk_folder_perm:      str = ""
    apk_dest:             str = ""
    apk_perm:             str = ""
    # install — XML
    xml_src:              str = ""
    xml_folder:           str = ""
    xml_folder_perm:      str = ""
    xml_dest:             str = ""
    xml_perm:             str = ""
    # install validation
    install_valid:        bool = False
    install_errors:       list[str] = field(default_factory=list)

    # build.prop
    buildprop_path:     str = ""
    buildprop_added:    list[str] = field(default_factory=list)
    buildprop_skipped:  list[str] = field(default_factory=list)

    # dex injection
    framework_jar:      str = ""
    framework_backup:   str = ""
    dex_injected_name:  str = ""
    dex_inject_ok:      bool = False

    # smali hooks
    hooks_attempted:    int = 0
    hooks_patched:      int = 0
    hooks_skipped:      int = 0
    hook_results:       list[HookResult] = field(default_factory=list)

    # services.jar
    services_jar:       str = ""
    services_backup:    str = ""
    services_hook_ok:   bool = False
    services_hook_note: str = ""

    # framework rebuild
    framework_rebuild_ok: bool = False

    # tools
    tools_found:        dict[str, str] = field(default_factory=dict)
    tools_missing:      list[str] = field(default_factory=list)

    error: str = ""


# ── Helpers ────────────────────────────────────────────────────────────────────

def _dread(fname: str) -> str:
    p = DDEVICE_DIR / fname
    return p.read_text(encoding="utf-8", errors="replace").strip() if p.is_file() else ""


def _ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())


def _sep(ch: str = "=", n: int = 50) -> str:
    return ch * n


def _run(cmd: list[str], cwd: Optional[Path] = None) -> tuple[int, str, str]:
    r = subprocess.run(cmd, capture_output=True, text=True,
                       cwd=str(cwd) if cwd else None)
    return r.returncode, r.stdout or "", r.stderr or ""


def _log(msg: str) -> None:
    print(f"[KAORIOS] {msg}")


def _err(msg: str) -> None:
    print(f"[KAORIOS] ERROR: {msg}", file=sys.stderr)


# ── Tool discovery ─────────────────────────────────────────────────────────────

def find_java() -> Optional[str]:
    for cand in ["java", "/usr/bin/java", "/usr/local/bin/java"]:
        if shutil.which(cand):
            return cand
    return None


def find_apktool() -> Optional[Path]:
    candidates = [
        APKTOOL_DIR / "apktool.jar",
        TOOLS_DIR / "apktool.jar",
        WORK_DIR / "apktool.jar",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def find_zip_tool() -> Optional[str]:
    for cand in ["zip", "/usr/bin/zip"]:
        if shutil.which(cand):
            return cand
    return None


def check_tools() -> tuple[dict[str, str], list[str]]:
    found:   dict[str, str] = {}
    missing: list[str]      = []

    java = find_java()
    if java:
        found["java"] = java
    else:
        missing.append("java")

    apktool = find_apktool()
    if apktool:
        found["apktool.jar"] = str(apktool)
    else:
        missing.append("apktool.jar")

    return found, missing


# ── Asset management ───────────────────────────────────────────────────────────

def _download_asset(name: str, url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    _log(f"Downloading {name} from {url} ...")
    try:
        urllib.request.urlretrieve(url, dest)
        sz = dest.stat().st_size
        _log(f"Downloaded {name} -> {dest.name}  ({sz:,} bytes)")
        return True
    except Exception as exc:
        dest.unlink(missing_ok=True)
        _err(f"Download failed for {name}: {exc}")
        return False


def validate_assets(run: KaoriosRun) -> bool:
    """Ensure all assets are present. Prefers local repo assets; falls back to download."""
    all_ok = True
    for name, dest in ASSET_PATHS.items():
        if dest.is_file() and dest.stat().st_size > 0:
            sz = dest.stat().st_size
            run.asset_sizes[name] = sz
            run.assets_local.append(name)
            _log(f"Asset found (local): {name}  ({sz:,} bytes)  [{dest}]")
        else:
            _log(f"Asset not in repo: {name} — attempting fallback download ...")
            url = ASSET_URLS[name]
            ok  = _download_asset(name, url, dest)
            if ok:
                run.assets_downloaded.append(name)
                run.asset_sizes[name] = dest.stat().st_size
                _log(f"Fallback download OK: {name}  ({run.asset_sizes[name]:,} bytes)")
            else:
                run.asset_errors.append(f"Missing Kaorios asset: {name}")
                all_ok = False

    run.assets_valid = all_ok
    return all_ok


# ── APK / XML install ──────────────────────────────────────────────────────────

def _select_partition(images: Path) -> Optional[str]:
    """Return the first available partition name ('system_ext' or 'product'), or None."""
    for part in ("system_ext", "product"):
        if (images / part).is_dir():
            return part
    return None


def _chmod_safe(path: Path, mode: int) -> bool:
    try:
        path.chmod(mode)
        return True
    except Exception:
        return False


def install_apk(run: KaoriosRun) -> bool:
    """Install KaoriosToolbox.apk into {partition}/priv-app/KaoriosToolbox/ with correct perms.

    Structure created:
      {partition}/priv-app/KaoriosToolbox/          (0755)
      {partition}/priv-app/KaoriosToolbox/KaoriosToolbox.apk  (0644)
    """
    src = ASSET_PATHS[APK_CANON]
    run.apk_src = str(src)

    partition = _select_partition(BUILD_IMAGES)
    if partition is None:
        _err("No suitable partition found for APK (tried system_ext, product)")
        run.error = "No suitable partition found for KaoriosToolbox APK"
        return False

    # Explicit folder: {partition}/priv-app/KaoriosToolbox/
    apk_folder = BUILD_IMAGES / partition / "priv-app" / "KaoriosToolbox"
    apk_folder.mkdir(parents=True, exist_ok=True)
    run.apk_folder         = str(apk_folder)
    run.apk_folder_created = True
    run.install_partition  = partition

    # Set folder permission 0755
    ok = _chmod_safe(apk_folder, 0o755)
    run.apk_folder_perm = "0755" if ok else "0755 (chmod failed — may be OK on CI)"
    _log(f"Created APK folder:  {apk_folder}  (perm={run.apk_folder_perm})")

    # Copy APK into the folder
    dest = apk_folder / APK_CANON
    shutil.copy2(src, dest)

    # Set APK permission 0644
    ok = _chmod_safe(dest, 0o644)
    run.apk_perm = "0644" if ok else "0644 (chmod failed — may be OK on CI)"
    run.apk_dest = str(dest)

    _log(f"APK installed:")
    _log(f"  src:  {src}")
    _log(f"  dest: {dest}")
    _log(f"  folder perm: {run.apk_folder_perm}  APK perm: {run.apk_perm}")
    return True


def install_xml(run: KaoriosRun) -> bool:
    """Install privapp whitelist XML into {partition}/etc/permissions/ with correct perms.

    Uses the same partition as the APK install.
    Correct spelling: permissions  (never permissons).

    Structure created:
      {partition}/etc/permissions/                                    (0755)
      {partition}/etc/permissions/privapp_whitelist_com.kousei.kaorios.xml  (0644)
    """
    src = ASSET_PATHS[XML_CANON]
    run.xml_src = str(src)

    # Use the same partition that was chosen for APK; fall back if needed
    partition = run.install_partition
    if not partition:
        partition = _select_partition(BUILD_IMAGES) or "system_ext"

    # Correct path: etc/permissions  (not permissons)
    perm_folder = BUILD_IMAGES / partition / "etc" / "permissions"
    perm_folder.mkdir(parents=True, exist_ok=True)
    run.xml_folder = str(perm_folder)

    # Set permissions folder permission 0755
    ok = _chmod_safe(perm_folder, 0o755)
    run.xml_folder_perm = "0755" if ok else "0755 (chmod failed — may be OK on CI)"
    _log(f"Created XML folder:  {perm_folder}  (perm={run.xml_folder_perm})")

    # Copy XML
    dest = perm_folder / XML_CANON
    shutil.copy2(src, dest)

    # Set XML permission 0644
    ok = _chmod_safe(dest, 0o644)
    run.xml_perm = "0644" if ok else "0644 (chmod failed — may be OK on CI)"
    run.xml_dest = str(dest)

    _log(f"XML installed:")
    _log(f"  src:  {src}")
    _log(f"  dest: {dest}")
    _log(f"  folder perm: {run.xml_folder_perm}  XML perm: {run.xml_perm}")
    return True


def validate_install(run: KaoriosRun) -> bool:
    """Validate APK and XML are installed at correct paths. Populate run.install_errors."""
    errors: list[str] = []
    part = run.install_partition

    # 1. APK must exist inside the KaoriosToolbox subfolder
    if run.apk_dest:
        apk_path = Path(run.apk_dest)
        if not apk_path.is_file():
            errors.append(f"APK not found at dest: {run.apk_dest}")
        else:
            # Must NOT be directly in priv-app — parent must be KaoriosToolbox/
            if apk_path.parent.name != "KaoriosToolbox":
                errors.append(
                    f"APK parent dir is '{apk_path.parent.name}' — must be 'KaoriosToolbox'"
                )
            # Check no rogue APK directly in priv-app
            priv_app_root = BUILD_IMAGES / part / "priv-app" / APK_CANON if part else None
            if priv_app_root and priv_app_root.is_file():
                errors.append(f"Rogue APK found directly in priv-app: {priv_app_root}")
    else:
        errors.append("APK destination not recorded")

    # 2. XML must exist in etc/permissions (correct spelling)
    if run.xml_dest:
        xml_path = Path(run.xml_dest)
        if not xml_path.is_file():
            errors.append(f"XML not found at dest: {run.xml_dest}")
        else:
            # Parent folder name must be 'permissions' (not 'permissons')
            if xml_path.parent.name != "permissions":
                errors.append(
                    f"XML parent dir is '{xml_path.parent.name}' — must be 'permissions'"
                )
    else:
        errors.append("XML destination not recorded")

    # 3. Misspelled 'permissons' must not exist
    if part:
        bad = BUILD_IMAGES / part / "etc" / "permissons"
        if bad.is_dir():
            errors.append(f"Misspelled 'permissons' dir exists: {bad}")

    run.install_errors = errors
    run.install_valid  = len(errors) == 0

    if run.install_valid:
        _log("Install validation: PASS")
    else:
        for e in errors:
            _err(f"Install validation: {e}")

    return run.install_valid


# ── build.prop patching ────────────────────────────────────────────────────────

def _find_buildprop(images: Path) -> Optional[Path]:
    for rel in BUILDPROP_CANDIDATES:
        p = images / rel
        if p.is_file():
            return p
    return None


def patch_buildprop(run: KaoriosRun) -> bool:
    bp = _find_buildprop(BUILD_IMAGES)
    if bp is None:
        _err("build.prop not found in ROM tree (checked system, product, system_ext)")
        run.error = "build.prop not found"
        return False

    run.buildprop_path = str(bp)
    content = bp.read_text(encoding="utf-8", errors="replace")
    lines   = content.splitlines()

    # Collect existing keys
    existing_keys = set()
    for line in lines:
        stripped = line.strip()
        if "=" in stripped and not stripped.startswith("#"):
            existing_keys.add(stripped.split("=", 1)[0])

    additions: list[str] = []
    for key, val in BUILDPROP_PROPS:
        if key in existing_keys:
            run.buildprop_skipped.append(key)
            _log(f"build.prop: {key} already present, skipping")
        else:
            additions.append(f"{key}={val}")
            run.buildprop_added.append(key)

    if not additions:
        _log("build.prop: all Kaorios properties already present")
        return True

    # Append block
    new_content = content.rstrip() + "\n\n" + BUILDPROP_HEADER + "\n"
    new_content += "\n".join(additions) + "\n"
    bp.write_text(new_content, encoding="utf-8")
    _log(f"build.prop patched: added {run.buildprop_added}  at {bp}")
    return True


# ── Framework.jar DEX injection ────────────────────────────────────────────────

def _find_jar(candidates: list[str]) -> Optional[Path]:
    for rel in candidates:
        p = BUILD_IMAGES / rel
        if p.is_file():
            return p
    return None


def _next_dex_slot(jar_path: Path) -> str:
    """Return the next free classesN.dex name (classes2.dex, classes3.dex, ...)."""
    with zipfile.ZipFile(jar_path, "r") as zf:
        names = set(zf.namelist())
    if "classes.dex" not in names:
        return "classes2.dex"
    n = 2
    while f"classes{n}.dex" in names:
        n += 1
    return f"classes{n}.dex"


def _create_backup(path: Path) -> Path:
    bak = Path(str(path) + BACKUP_SUFFIX)
    if not bak.is_file():
        shutil.copy2(path, bak)
        _log(f"Backup: {bak.name}")
    else:
        _log(f"Backup already exists: {bak.name}")
    return bak


def inject_kaorios_dex(jar_path: Path, kaorios_dex: Path) -> str:
    """Inject kaorios_dex into jar_path as next free classesN.dex. Returns injected name."""
    target_name = _next_dex_slot(jar_path)

    # Verify we won't overwrite
    with zipfile.ZipFile(jar_path, "r") as zf:
        if target_name in zf.namelist():
            raise RuntimeError(f"Would overwrite existing {target_name} — abort")

    # Append entry (ZIP_STORED for dex, as ART expects it uncompressed for perf)
    with zipfile.ZipFile(jar_path, "a", compression=zipfile.ZIP_STORED) as zf:
        zf.write(kaorios_dex, target_name)

    _log(f"Injected Kaorios classes.dex as {target_name} into {jar_path.name}")
    return target_name


# ── apktool decompile / rebuild ────────────────────────────────────────────────

def _decompile(jar_path: Path, out_dir: Path, apktool: Path, java: str) -> None:
    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    cmd = [java, "-jar", str(apktool), "d", "-q", "-f",
           str(jar_path), "-o", str(out_dir)]
    rc, stdout, stderr = _run(cmd)
    if rc != 0:
        raise RuntimeError(
            f"apktool decompile failed (rc={rc})\n"
            f"stdout: {stdout[-1000:]}\nstderr: {stderr[-1000:]}"
        )
    _log(f"Decompiled {jar_path.name} -> {out_dir.name}/")


def _rebuild(decompile_dir: Path, out_jar: Path, apktool: Path, java: str) -> None:
    cmd = [java, "-jar", str(apktool), "b", "-q", "-f",
           str(decompile_dir), "-o", str(out_jar)]
    rc, stdout, stderr = _run(cmd)
    if rc != 0:
        raise RuntimeError(
            f"apktool rebuild failed (rc={rc})\n"
            f"stdout: {stdout[-1000:]}\nstderr: {stderr[-1000:]}"
        )
    _log(f"Rebuilt -> {out_jar.name}")


# ── Smali helpers ──────────────────────────────────────────────────────────────

def _smali_dirs(decompile_dir: Path) -> list[Path]:
    dirs = []
    for d in sorted(decompile_dir.iterdir()):
        if not d.is_dir():
            continue
        n = d.name
        if n in ("smali", "classes") or re.match(r"smali_classes\d+", n) or re.match(r"classes\d+", n):
            dirs.append(d)
    return dirs


def _find_class_file(decompile_dir: Path, class_path: str) -> Optional[Path]:
    """Find smali file for class_path (e.g. 'android/app/Instrumentation')."""
    target = class_path.replace("\\", "/") + ".smali"
    for sd in _smali_dirs(decompile_dir):
        candidate = sd / target
        if candidate.is_file():
            return candidate
    return None


def _find_method_bounds(lines: list[str], sig_fragment: str) -> Optional[tuple[int, int]]:
    pattern = re.compile(r"^\s*\.method\s+.*" + re.escape(sig_fragment))
    start = None
    for i, line in enumerate(lines):
        if pattern.search(line):
            start = i
            break
    if start is None:
        return None
    for i in range(start + 1, len(lines)):
        if ".end method" in lines[i]:
            return start, i
    return None


def _find_all_method_bounds(lines: list[str], sig_fragment: str) -> list[tuple[int, int]]:
    pattern = re.compile(r"^\s*\.method\s+.*" + re.escape(sig_fragment))
    result  = []
    i = 0
    while i < len(lines):
        if pattern.search(lines[i]):
            start = i
            for j in range(i + 1, len(lines)):
                if ".end method" in lines[j]:
                    result.append((start, j))
                    i = j + 1
                    break
            else:
                i += 1
        else:
            i += 1
    return result


def _already_patched(lines: list[str], start: int, end: int) -> bool:
    """Return True if the method body already contains KaoriosHook references."""
    for ln in lines[start:end + 1]:
        if "KaoriosHook" in ln or "kaorios" in ln.lower():
            return True
    return False


def _has_invoke_custom_in_method(lines: list[str], start: int, end: int) -> bool:
    return any("invoke-custom" in lines[i] for i in range(start + 1, end + 1))


def _get_registers_val(lines: list[str], start: int, end: int) -> tuple[int, int]:
    """Return (registers_value, line_index) or (-1, -1)."""
    for i in range(start + 1, end + 1):
        m = re.match(r"\s*\.registers\s+(\d+)", lines[i])
        if m:
            return int(m.group(1)), i
    return -1, -1


def _indent(line: str) -> str:
    return "    " if not line.startswith(" ") else ""


# ── invoke-custom safety (reuses same logic as framework patcher) ──────────────

def _handle_invoke_custom_in_method(
    smali_path: Path, lines: list[str], start: int, end: int
) -> str:
    """Remove invoke-custom from equals/hashCode/toString in the target file.
    Returns 'handled', 'not_needed', or 'failed'."""
    target_methods = [
        ("equals(",   "const/4 v0, 0x0", "return v0",  ".registers 2"),
        ("hashCode(", "const/4 v0, 0x0", "return v0",  ".registers 2"),
        ("toString(", "const/4 v0, 0x0", "return-object v0", ".registers 1"),
    ]
    changed = False
    try:
        for sig, const_line, ret_line, reg_decl in target_methods:
            all_bounds = _find_all_method_bounds(lines, sig)
            for ms, me in reversed(all_bounds):
                body = lines[ms + 1: me]
                if not any("invoke-custom" in ln for ln in body):
                    continue
                head  = lines[ms]
                new_body = [f"    {reg_decl}", f"    {const_line}", f"    {ret_line}"]
                lines = lines[:ms] + [head] + new_body + [".end method"] + lines[me + 1:]
                changed = True
        if changed:
            smali_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return "handled" if changed else "not_needed"
    except Exception as exc:
        return f"failed:{exc}"


# ── Framework.jar hook patches ─────────────────────────────────────────────────

def patch_instrumentation(decompile_dir: Path) -> list[HookResult]:
    """Patch android/app/Instrumentation — two newApplication variants."""
    results: list[HookResult] = []
    sf = _find_class_file(decompile_dir, INSTRUMENTATION_CLASS)
    if sf is None:
        return [HookResult("Instrumentation.newApplication[1]", False, "class file not found"),
                HookResult("Instrumentation.newApplication[2]", False, "class file not found")]

    lines = sf.read_text(encoding="utf-8", errors="replace").splitlines()

    # Variants: (method_sig_fragment, context_param, label)
    variants = [
        ("newApplication(Ljava/lang/Class;Landroid/content/Context;)Landroid/app/Application;",
         "p1", "Instrumentation.newApplication[1]"),
        ("newApplication(Ljava/lang/ClassLoader;Ljava/lang/String;Landroid/content/Context;)Landroid/app/Application;",
         "p3", "Instrumentation.newApplication[2]"),
    ]

    changed = False
    for sig, param, label in variants:
        bounds = _find_method_bounds(lines, sig)
        if bounds is None:
            results.append(HookResult(label, False, "method not found"))
            continue

        start, end = bounds
        if _already_patched(lines, start, end):
            results.append(HookResult(label, True, "already patched"))
            continue

        # invoke-custom safety check
        if _has_invoke_custom_in_method(lines, start, end):
            ic_status = _handle_invoke_custom_in_method(sf, lines, start, end)
            lines = sf.read_text(encoding="utf-8", errors="replace").splitlines()
            bounds = _find_method_bounds(lines, sig)
            if bounds is None:
                results.append(HookResult(label, False, f"method lost after invoke-custom handling ({ic_status})"))
                continue
            start, end = bounds

        # Insert before each return-object in method body
        hook_line = (
            f"    invoke-static {{{param}}}, "
            f"{KAORIOS_HOOK}->initContext(Landroid/content/Context;)V"
        )
        return_indices = [
            i for i in range(start + 1, end)
            if re.match(r"\s*return-object\s+", lines[i])
        ]
        if not return_indices:
            results.append(HookResult(label, False, "no return-object found in method"))
            continue

        for idx in reversed(return_indices):
            lines = lines[:idx] + [hook_line] + lines[idx:]
            end += 1  # adjust end after insertion

        changed = True
        results.append(HookResult(label, True, f"inserted before {len(return_indices)} return(s)"))

    if changed:
        sf.write_text("\n".join(lines) + "\n", encoding="utf-8")
        _log(f"Patched Instrumentation in {sf.name}")

    return results


def patch_appm_has_system_feature(decompile_dir: Path) -> HookResult:
    """Patch android/app/ApplicationPackageManager.hasSystemFeature."""
    label = "ApplicationPackageManager.hasSystemFeature"
    sig   = "hasSystemFeature(Ljava/lang/String;I)Z"

    sf = _find_class_file(decompile_dir, APM_CLASS)
    if sf is None:
        return HookResult(label, False, "class file not found")

    lines  = sf.read_text(encoding="utf-8", errors="replace").splitlines()
    bounds = _find_method_bounds(lines, sig)
    if bounds is None:
        return HookResult(label, False, "method not found")

    start, end = bounds
    if _already_patched(lines, start, end):
        return HookResult(label, True, "already patched")

    if _has_invoke_custom_in_method(lines, start, end):
        ic_status = _handle_invoke_custom_in_method(sf, lines, start, end)
        lines  = sf.read_text(encoding="utf-8", errors="replace").splitlines()
        bounds = _find_method_bounds(lines, sig)
        if bounds is None:
            return HookResult(label, False, f"method lost after invoke-custom handling ({ic_status})")
        start, end = bounds

    reg_val, reg_idx = _get_registers_val(lines, start, end)
    if reg_idx == -1:
        return HookResult(label, False, ".registers line not found")

    hook_block = [
        f"    invoke-static {{p1, p2}}, {KAORIOS_HOOK}->hasSystemFeature(Ljava/lang/String;I)Ljava/lang/Boolean;",
        "    move-result-object v0",
        "",
        "    if-eqz v0, :cond_kaorios",
        "    invoke-virtual {v0}, Ljava/lang/Boolean;->booleanValue()Z",
        "    move-result v0",
        "    return v0",
        "",
        "    :cond_kaorios",
    ]

    lines = lines[:reg_idx + 1] + hook_block + lines[reg_idx + 1:]
    sf.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _log(f"Patched hasSystemFeature in {sf.name}")
    return HookResult(label, True, "hook inserted after .registers")


def patch_keystore_generate_keypair(decompile_dir: Path) -> HookResult:
    """Patch AndroidKeyStoreKeyPairGeneratorSpi.generateKeyPair."""
    label = "AndroidKeyStoreKeyPairGeneratorSpi.generateKeyPair"
    sig   = "generateKeyPair()Ljava/security/KeyPair;"

    sf = _find_class_file(decompile_dir, KEYSTORE_GEN_CLASS)
    if sf is None:
        return HookResult(label, False, "class file not found")

    lines  = sf.read_text(encoding="utf-8", errors="replace").splitlines()
    bounds = _find_method_bounds(lines, sig)
    if bounds is None:
        return HookResult(label, False, "method not found")

    start, end = bounds
    if _already_patched(lines, start, end):
        return HookResult(label, True, "already patched")

    if _has_invoke_custom_in_method(lines, start, end):
        ic_status = _handle_invoke_custom_in_method(sf, lines, start, end)
        lines  = sf.read_text(encoding="utf-8", errors="replace").splitlines()
        bounds = _find_method_bounds(lines, sig)
        if bounds is None:
            return HookResult(label, False, f"method lost after invoke-custom ({ic_status})")
        start, end = bounds

    reg_val, reg_idx = _get_registers_val(lines, start, end)
    if reg_idx == -1 or reg_val <= 0:
        return HookResult(label, False, ".registers not found or invalid")

    # vX = new_registers - 2 = (reg_val + 1) - 2 = reg_val - 1
    vX = f"v{reg_val - 1}"

    # Increment .registers
    new_reg_line = re.sub(r"(\s*\.registers\s+)\d+", rf"\g<1>{reg_val + 1}", lines[reg_idx])
    lines[reg_idx] = new_reg_line

    hook_block = [
        f"    invoke-static {{p0}}, {KAORIOS_HOOK}->initGenerateSoftwareKeyPair(Ljava/lang/Object;)Ljava/security/KeyPair;",
        f"    move-result-object {vX}",
        "",
        f"    if-eqz {vX}, :cond_kaorios",
        f"    return-object {vX}",
        "",
        "    :cond_kaorios",
    ]

    lines = lines[:reg_idx + 1] + hook_block + lines[reg_idx + 1:]
    sf.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _log(f"Patched generateKeyPair in {sf.name} (registers {reg_val}->{reg_val+1}, vX={vX})")
    return HookResult(label, True, f"hook inserted, registers {reg_val}->{reg_val+1}, vX={vX}")


def patch_keystore_cert_chain(decompile_dir: Path) -> HookResult:
    """Patch AndroidKeyStoreSpi.engineGetCertificateChain."""
    label = "AndroidKeyStoreSpi.engineGetCertificateChain"
    sig   = "engineGetCertificateChain(Ljava/lang/String;)[Ljava/security/cert/Certificate;"

    sf = _find_class_file(decompile_dir, KEYSTORE_SPI_CLASS)
    if sf is None:
        return HookResult(label, False, "class file not found")

    lines  = sf.read_text(encoding="utf-8", errors="replace").splitlines()
    bounds = _find_method_bounds(lines, sig)
    if bounds is None:
        return HookResult(label, False, "method not found")

    start, end = bounds
    if _already_patched(lines, start, end):
        return HookResult(label, True, "already patched")

    if _has_invoke_custom_in_method(lines, start, end):
        ic_status = _handle_invoke_custom_in_method(sf, lines, start, end)
        lines  = sf.read_text(encoding="utf-8", errors="replace").splitlines()
        bounds = _find_method_bounds(lines, sig)
        if bounds is None:
            return HookResult(label, False, f"method lost after invoke-custom ({ic_status})")
        start, end = bounds

    # Find aput-object + return-object pattern in the method body.
    # Pattern: line with "aput-object" followed (possibly with blank lines) by "return-object"
    aput_idx    = None
    return_idx  = None
    array_reg   = None
    return_reg  = None

    stripped_body = [(i, lines[i].strip()) for i in range(start + 1, end)]

    # Find the LAST aput-object that is followed by a return-object
    for pos, (i, s) in enumerate(stripped_body):
        if s.startswith("aput-object"):
            # Extract array register (2nd operand: aput-object vB, vC, vA)
            m = re.match(r"aput-object\s+(\S+),\s*(\S+),\s*(\S+)", s)
            if not m:
                continue
            arr_reg = m.group(2)  # vC (the array)
            # Look ahead for a return-object
            for pos2, (i2, s2) in enumerate(stripped_body[pos + 1:], pos + 1):
                if not s2:  # skip blank lines
                    continue
                if s2.startswith("return-object"):
                    m2 = re.match(r"return-object\s+(\S+)", s2)
                    ret_reg = m2.group(1) if m2 else None
                    aput_idx   = i
                    return_idx = i2
                    array_reg  = arr_reg
                    return_reg = ret_reg
                    break
                else:
                    break  # non-blank, non-return line — not our pattern

    if aput_idx is None or return_idx is None:
        return HookResult(label, False, "aput-object + return-object pattern not found in method")

    if array_reg is None or return_reg is None:
        return HookResult(label, False, "could not parse registers from pattern")

    # Insert after aput-object (before return-object):
    # The return-object vD becomes move-result-object vD after our invoke, then return-object vD
    hook_block = [
        f"    invoke-static {{{array_reg}}}, {KAORIOS_HOOK}->CertificateChainIfNeeded([Ljava/security/cert/Certificate;)[Ljava/security/cert/Certificate;",
        f"    move-result-object {return_reg}",
    ]

    # Insert after aput_idx
    lines = lines[:aput_idx + 1] + hook_block + lines[aput_idx + 1:]
    sf.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _log(f"Patched engineGetCertificateChain in {sf.name} "
         f"(array={array_reg}, return={return_reg})")
    return HookResult(label, True,
                      f"CertificateChainIfNeeded injected (array={array_reg}, return={return_reg})")


# ── Services.jar hook ──────────────────────────────────────────────────────────

def patch_system_server(decompile_dir: Path) -> HookResult:
    """Patch com/android/server/SystemServer — insert initSystemServer before startOtherServices."""
    label = "SystemServer.initSystemServer"

    sf = _find_class_file(decompile_dir, SYSTEM_SERVER_CLASS)
    if sf is None:
        return HookResult(label, False, "com/android/server/SystemServer.smali not found")

    lines = sf.read_text(encoding="utf-8", errors="replace").splitlines()

    if any("KaoriosHook" in ln for ln in lines):
        return HookResult(label, True, "already patched")

    # Find the line containing ->startOtherServices( invocation
    target_idx = None
    for i, line in enumerate(lines):
        if "->startOtherServices(" in line:
            target_idx = i
            break

    if target_idx is None:
        return HookResult(label, False, "->startOtherServices invocation not found")

    hook_line = f"    invoke-static {{}}, {KAORIOS_HOOK}->initSystemServer()V"
    lines = lines[:target_idx] + [hook_line] + lines[target_idx:]
    sf.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _log(f"Patched SystemServer in {sf.name} (inserted initSystemServer before startOtherServices)")
    return HookResult(label, True, "initSystemServer inserted before startOtherServices")


# ── Full JAR pipeline ──────────────────────────────────────────────────────────

def process_framework_jar(run: KaoriosRun, apktool: Path, java: str) -> bool:
    jar_path = _find_jar(FRAMEWORK_JAR_CANDIDATES)
    if jar_path is None:
        _log("framework.jar not found — skipping framework hooks")
        run.hooks_skipped += 4
        return True  # Not a fatal error; ROM might not be extracted yet

    run.framework_jar = str(jar_path)
    _log(f"framework.jar: {jar_path}")

    # Backup
    bak = _create_backup(jar_path)
    run.framework_backup = str(bak)

    work_dir     = jar_path.parent
    decompile_dir = work_dir / "framework_kaorios_decompile"
    patched_jar  = work_dir / "framework_kaorios_patched.jar"

    try:
        # 1. Decompile
        _decompile(jar_path, decompile_dir, apktool, java)

        # 2. Apply smali hooks
        hook_fns = [
            lambda: patch_instrumentation(decompile_dir),
            lambda: [patch_appm_has_system_feature(decompile_dir)],
            lambda: [patch_keystore_generate_keypair(decompile_dir)],
            lambda: [patch_keystore_cert_chain(decompile_dir)],
        ]

        for fn in hook_fns:
            results = fn()
            for hr in results:
                run.hooks_attempted += 1
                run.hook_results.append(hr)
                if hr.applied:
                    run.hooks_patched += 1
                else:
                    run.hooks_skipped += 1
                    _log(f"  SKIP {hr.target}: {hr.note}")

        # 3. Rebuild
        _rebuild(decompile_dir, patched_jar, apktool, java)
        run.framework_rebuild_ok = True

        # 4. Replace original with rebuilt jar
        shutil.copy2(patched_jar, jar_path)
        patched_jar.unlink(missing_ok=True)
        _log(f"Replaced {jar_path.name} with patched version")

    except Exception as exc:
        run.error = f"framework.jar processing failed: {exc}"
        _err(run.error)
        shutil.rmtree(decompile_dir, ignore_errors=True)
        return False

    finally:
        shutil.rmtree(decompile_dir, ignore_errors=True)

    # 5. Inject Kaorios classes.dex
    kaorios_dex = ASSET_PATHS[DEX_CANON]
    try:
        injected_name = inject_kaorios_dex(jar_path, kaorios_dex)
        run.dex_injected_name = injected_name
        run.dex_inject_ok     = True
        _log(f"Kaorios DEX injected as {injected_name} into {jar_path.name}")
    except Exception as exc:
        run.error = f"DEX injection failed: {exc}"
        _err(run.error)
        return False

    return True


def process_services_jar(run: KaoriosRun, apktool: Path, java: str) -> bool:
    jar_path = _find_jar(SERVICES_JAR_CANDIDATES)
    if jar_path is None:
        _log("services.jar not found — skipping SystemServer hook")
        run.services_hook_note = "services.jar not found"
        return True

    run.services_jar = str(jar_path)
    _log(f"services.jar: {jar_path}")

    bak = _create_backup(jar_path)
    run.services_backup = str(bak)

    work_dir      = jar_path.parent
    decompile_dir = work_dir / "services_kaorios_decompile"
    patched_jar   = work_dir / "services_kaorios_patched.jar"

    try:
        _decompile(jar_path, decompile_dir, apktool, java)
        hr = patch_system_server(decompile_dir)
        run.services_hook_ok   = hr.applied
        run.services_hook_note = hr.note

        _rebuild(decompile_dir, patched_jar, apktool, java)
        shutil.copy2(patched_jar, jar_path)
        patched_jar.unlink(missing_ok=True)
        _log(f"Replaced {jar_path.name} with patched version")

    except Exception as exc:
        run.services_hook_note = f"FAILED: {exc}"
        _err(f"services.jar processing failed: {exc}")
        shutil.rmtree(decompile_dir, ignore_errors=True)
        return False

    finally:
        shutil.rmtree(decompile_dir, ignore_errors=True)

    return True


# ── Reports ────────────────────────────────────────────────────────────────────

def write_assets_report(run: KaoriosRun) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    val = "PASS" if run.assets_valid else "FAIL"
    fallback_needed = bool(run.assets_downloaded)
    lines = [
        "Kaorios Assets Report",
        _sep(),
        f"Generated:        {_ts()}",
        "",
        f"Release/tag:      KaoriosToolbox - {KAORIOS_TAG}  (version {KAORIOS_VERSION})",
        f"Build date:       23-05-2026",
        f"Source repo:      {KAORIOS_REPO}",
        f"Guide:            Toolbox-docs/V2.0.3+",
        "",
        f"Fallback download needed: {'YES' if fallback_needed else 'NO (all assets present in repo)'}",
        "",
        "Assets:",
    ]
    for name, path in ASSET_PATHS.items():
        sz     = run.asset_sizes.get(name, 0)
        status = "OK" if (path.is_file() and sz > 0) else "MISSING"
        if name in run.assets_local:
            source = "local repo"
        elif name in run.assets_downloaded:
            source = "fallback download"
        else:
            source = "MISSING"
        lines.append(f"  {status}  {name:<50s}  {sz:>10,} bytes  [{source}]")
        lines.append(f"        path: {path}")
    lines += [
        "",
        "Install paths:",
        f"  Selected partition:  {run.install_partition or '(not set)'}",
        f"  APK source:         {run.apk_src or '(not set)'}",
        f"  APK folder:         {run.apk_folder or '(not set)'}",
        f"  APK folder perm:    {run.apk_folder_perm or '(not set)'}",
        f"  APK destination:    {run.apk_dest or '(not installed)'}",
        f"  APK perm:           {run.apk_perm or '(not set)'}",
        f"  XML source:         {run.xml_src or '(not set)'}",
        f"  XML folder:         {run.xml_folder or '(not set)'}",
        f"  XML folder perm:    {run.xml_folder_perm or '(not set)'}",
        f"  XML destination:    {run.xml_dest or '(not installed)'}",
        f"  XML perm:           {run.xml_perm or '(not set)'}",
        f"  Install valid:      {'PASS' if run.install_valid else 'FAIL' if run.install_errors else '(not run)'}",
    ]
    if run.install_errors:
        lines += ["", "Install errors:"]
        for e in run.install_errors:
            lines.append(f"  ! {e}")
    if run.asset_errors:
        lines += ["", "Asset errors:"]
        for e in run.asset_errors:
            lines.append(f"  ! {e}")
    lines += ["", f"Validation: {val}"]
    out = REPORTS_DIR / "kaorios_assets_report.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _log(f"Assets report -> {out}")


def write_toolbox_report(run: KaoriosRun) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    install_status = "PASS" if run.install_valid else ("FAIL" if run.install_errors else "(not validated)")
    lines = [
        "Kaorios Toolbox Integration Report",
        _sep(),
        f"Generated:           {_ts()}",
        "",
        f"Style:               {run.style}",
        f"Tier:                {run.style_tier}",
        f"Android:             {run.android_ver}",
        f"Device:              {run.codename}",
        "",
        "Stable/base enabled: YES  (runs for all styles via UpdateFile)",
        "",
        _sep("-"),
        "APK Install",
        _sep("-"),
        f"  Selected partition: {run.install_partition or '(not set)'}",
        f"  Source path:        {run.apk_src or '(not set)'}",
        f"  App folder:         {run.apk_folder or '(not set)'}",
        f"  App folder created: {run.apk_folder_created}",
        f"  App folder perm:    {run.apk_folder_perm or '(not set)'}",
        f"  APK destination:    {run.apk_dest or '(not installed)'}",
        f"  APK permission:     {run.apk_perm or '(not set)'}",
        "",
        _sep("-"),
        "XML Install",
        _sep("-"),
        f"  Source path:        {run.xml_src or '(not set)'}",
        f"  Permissions folder: {run.xml_folder or '(not set)'}",
        f"  Folder perm:        {run.xml_folder_perm or '(not set)'}",
        f"  XML destination:    {run.xml_dest or '(not installed)'}",
        f"  XML permission:     {run.xml_perm or '(not set)'}",
        "",
        _sep("-"),
        "Install Validation",
        _sep("-"),
        f"  Result:             {install_status}",
    ]
    if run.install_errors:
        for e in run.install_errors:
            lines.append(f"  ! {e}")
    else:
        lines += [
            "  [OK] APK at correct subfolder path",
            "  [OK] XML at correct permissions path",
            "  [OK] No APK directly in priv-app root",
            "  [OK] Spelling: permissions (not permissons)",
        ]
    lines += [
        "",
        _sep("-"),
        "build.prop",
        _sep("-"),
        f"  Path:               {run.buildprop_path or '(not found)'}",
        f"  Properties added:   {run.buildprop_added or '(none)'}",
        f"  Properties skipped: {run.buildprop_skipped or '(none — already present)'}",
        "",
    ]
    if run.error:
        lines += [f"Error: {run.error}", ""]
    overall = "PASS" if (run.install_valid and run.apk_dest and run.xml_dest and not run.error) \
              else "PARTIAL" if run.apk_dest else "FAIL"
    lines.append(f"Overall status: {overall}")
    out = REPORTS_DIR / "kaorios_toolbox_report.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _log(f"Toolbox report -> {out}")


def write_framework_patch_report(run: KaoriosRun) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "Kaorios Framework Patch Report",
        _sep(),
        f"Generated:          {_ts()}",
        "",
        f"framework.jar:      {run.framework_jar or '(not found)'}",
        f"framework backup:   {run.framework_backup or '(none)'}",
        f"services.jar:       {run.services_jar or '(not found)'}",
        f"services backup:    {run.services_backup or '(none)'}",
        "",
        f"classes.dex injected as: {run.dex_injected_name or '(not injected)'}",
        f"DEX inject OK:      {run.dex_inject_ok}",
        "",
        f"Hooks attempted:    {run.hooks_attempted}",
        f"Hooks patched:      {run.hooks_patched}",
        f"Hooks skipped:      {run.hooks_skipped}",
        "",
        "Hook details:",
    ]
    for hr in run.hook_results:
        mark = "OK  " if hr.applied else "SKIP"
        note = f"  ({hr.note})" if hr.note else ""
        lines.append(f"  [{mark}] {hr.target}{note}")

    lines += [
        "",
        f"SystemServer hook:  {'OK' if run.services_hook_ok else 'SKIP'}  {run.services_hook_note}",
        "",
        f"framework.jar rebuild OK:  {run.framework_rebuild_ok}",
        f"Backups created:    {bool(run.framework_backup or run.services_backup)}",
        "",
    ]
    if run.error:
        lines.append(f"Error: {run.error}")
    val = "PASS" if (run.dex_inject_ok and run.framework_rebuild_ok) else "PARTIAL" if run.framework_rebuild_ok else "FAIL"
    lines.append(f"Validation: {val}")
    out = REPORTS_DIR / "kaorios_framework_patch_report.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _log(f"Framework patch report -> {out}")


def write_error_report(stage: str, exc_str: str) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "Kaorios Error Report",
        _sep(),
        f"Generated:     {_ts()}",
        "",
        f"Failed stage:  {stage}",
        f"Exception:     {exc_str}",
        "",
        "=== Suggested actions ===",
        "1. Check that java is installed: java -version",
        "2. Check that apktool.jar is in bin/apktool/ or bin/tools/",
        "3. Verify assets exist under bin/third_party/kaorios_toolbox/",
        "4. Check kaorios_assets_report.txt for asset validation details",
        "5. Check kaorios_framework_patch_report.txt for patch details",
    ]
    out = REPORTS_DIR / "kaorios_error_report.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    _log(f"Error report -> {out}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    import argparse
    ap = argparse.ArgumentParser(description="DeadZone Kaorios Toolbox Integration")
    ap.add_argument("--style", default=os.environ.get("DZ_STYLE_ID", "plus"),
                    help="DeadZone style (lite/plus/legend/ninja)")
    ap.add_argument("--work-dir", default=None,
                    help="Project root (work directory). Defaults to repo root.")
    args = ap.parse_args()

    _log("===== DeadZone Kaorios Toolbox Integration =====")
    _log(f"Time:    {_ts()}")
    _log(f"Version: {KAORIOS_VERSION}  (tag {KAORIOS_TAG})")

    run = KaoriosRun(
        style      = args.style,
        style_tier = os.environ.get("DZ_STYLE_TIER", "Free"),
        android_ver = _dread("androidver.txt") or "unknown",
        codename   = _dread("device_f.txt") or _dread("device_code.txt") or "unknown",
    )

    _log(f"Style:   {run.style} ({run.style_tier})")
    _log(f"Android: {run.android_ver}")
    _log(f"Device:  {run.codename}")

    # ── Step 0: Check tools ────────────────────────────────────────────────────
    tools_found, tools_missing = check_tools()
    run.tools_found   = tools_found
    run.tools_missing = tools_missing

    for tool in tools_missing:
        _err(f"Missing required Kaorios integration tool: {tool}")

    if "java" in tools_missing or "apktool.jar" in tools_missing:
        run.error = f"Missing required tools: {tools_missing}"
        write_assets_report(run)
        write_toolbox_report(run)
        write_framework_patch_report(run)
        write_error_report("tool-check", run.error)
        sys.exit(1)

    java_bin    = tools_found["java"]
    apktool_jar = Path(tools_found["apktool.jar"])

    # ── Step 1: Assets ─────────────────────────────────────────────────────────
    _log("--- Step 1: Asset validation ---")
    if not validate_assets(run):
        write_assets_report(run)
        write_toolbox_report(run)
        write_framework_patch_report(run)
        for err in run.asset_errors:
            write_error_report("asset-validation", err)
        _err("Asset validation failed — cannot continue")
        sys.exit(1)
    write_assets_report(run)

    # ── Step 2: Install APK ────────────────────────────────────────────────────
    _log("--- Step 2: Install APK ---")
    if not install_apk(run):
        write_toolbox_report(run)
        write_framework_patch_report(run)
        write_error_report("apk-install", run.error)
        sys.exit(1)

    # ── Step 3: Install XML ────────────────────────────────────────────────────
    _log("--- Step 3: Install XML ---")
    install_xml(run)

    # ── Step 3b: Validate install ──────────────────────────────────────────────
    _log("--- Step 3b: Validate install ---")
    validate_install(run)

    # ── Step 4: Patch build.prop ───────────────────────────────────────────────
    _log("--- Step 4: Patch build.prop ---")
    patch_buildprop(run)
    write_toolbox_report(run)

    # ── Steps 5-7: framework.jar + services.jar ────────────────────────────────
    _log("--- Steps 5-7: Framework / Services JAR patching ---")

    framework_ok = process_framework_jar(run, apktool_jar, java_bin)
    services_ok  = process_services_jar(run, apktool_jar, java_bin)

    write_framework_patch_report(run)

    if not framework_ok:
        write_error_report("framework-jar", run.error)
        sys.exit(1)

    # ── Summary ────────────────────────────────────────────────────────────────
    _log("===== Summary =====")
    _log(f"APK installed:       {bool(run.apk_dest)}")
    _log(f"XML installed:       {bool(run.xml_dest)}")
    _log(f"build.prop patched:  added={run.buildprop_added}")
    _log(f"DEX injected:        {run.dex_injected_name or '(none)'}")
    _log(f"Hooks patched:       {run.hooks_patched}/{run.hooks_attempted}")
    _log(f"SystemServer hook:   {run.services_hook_ok}")
    _log("===== Done =====")


if __name__ == "__main__":
    main()
