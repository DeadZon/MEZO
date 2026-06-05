#!/usr/bin/env python3
"""DeadZone Framework Patcher

Ports and integrates from FrameworksForge/FrameworkPatcher:
  - Signature Verification Bypass
  - invoke-custom handling

Runs as a base mod for ALL DeadZone styles (Stable, Legend, and future).
Called automatically via bin/modfile/UpdateFile/DeadZone_FrameworkPatcher/install.sh
which is discovered and executed by bin/modfile/UpdateFile/insupdate.sh.

Supports Android 15 (API 35) and Android 16 (API 36).
Patch targets found by method-signature search across all smali directories
produced by apktool decompilation.

Reports written to:
  output/reports/framework_patcher_report.txt
  output/reports/signature_verification_bypass_report.txt
  output/reports/invoke_custom_report.txt
  output/reports/framework_patcher_error.txt  (only on failure)

Attribution:
  Patch logic ported from FrameworksForge/FrameworkPatcher (MIT License).
  See third_party/FrameworkPatcher_CREDITS.txt
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ── Paths ─────────────────────────────────────────────────────────────────────
WORK_DIR     = Path.cwd()
REPORTS_DIR  = WORK_DIR / "output" / "reports"
LOGS_DIR     = WORK_DIR / "output" / "logs"
TOOLS_DIR    = WORK_DIR / "bin" / "tools"
DDEVICE_DIR  = WORK_DIR / "bin" / "ddevice"
BUILD_IMAGES = WORK_DIR / "build" / "baserom" / "images"

APKTOOL_JAR_URL = (
    "https://github.com/iBotPeaches/Apktool/releases/download/v2.9.3/apktool_2.9.3.jar"
)
APKTOOL_SHA256 = "effb69dab2f93806cafc0d232f6be32c2551b8d51c67650f575e46c016908fdd"

# Backup suffix — never overwrite an existing backup
BACKUP_SUFFIX = ".bak_deadzone_framework_patcher"

# ── JAR search paths (ordered by preference) ─────────────────────────────────
# Searched under BUILD_IMAGES/ in the extracted ROM partition directories.
JAR_CANDIDATES: dict[str, list[str]] = {
    "framework": [
        "system/framework/framework.jar",
    ],
    "services": [
        "system/framework/services.jar",
    ],
    "miui-services": [
        "system_ext/framework/miui-services.jar",
        "system/framework/miui-services.jar",
        "product/framework/miui-services.jar",
    ],
}

# ── Patch definitions ─────────────────────────────────────────────────────────
# Each entry: (method_signature_fragment, patch_type, return_value)
#   patch_type: "const_return" → const/4 v0, 0xN / return v0
#               "return_void"  → return-void
# Method signature fragment is matched with: \.method.*<fragment>
# If the method appears in multiple smali files the first match wins,
# which matches the reference patcher_a15.sh behaviour.

FRAMEWORK_PATCHES: list[tuple[str, str, str]] = [
    # SigningDetails / PackageParser$SigningDetails
    ("checkCapability(",           "const_return", "1"),
    ("checkCapabilityRecover(",    "const_return", "1"),
    ("hasAncestorOrSelf(",         "const_return", "1"),
    # ApkSignatureVerifier
    ("getMinimumSignatureSchemeVersionForTargetSdk(", "const_return", "0"),
    # StrictJarVerifier
    ("verifyMessageDigest(",       "const_return", "1"),
]

SERVICES_PATCHES: list[tuple[str, str, str]] = [
    ("checkDowngrade(",                "return_void", ""),
    ("shouldCheckUpgradeKeySetLocked(", "const_return", "0"),
    ("verifySignatures(",              "const_return", "0"),
    ("compareSignatures(",             "const_return", "0"),
    ("matchSignaturesCompat(",         "const_return", "1"),
]

MIUI_SERVICES_PATCHES: list[tuple[str, str, str]] = [
    ("verifyIsolationViolation(",  "return_void", ""),
    ("canBeUpdate(",               "return_void", ""),
]


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class PatchResult:
    method:  str
    file:    str
    applied: bool
    note:    str = ""


@dataclass
class JarResult:
    jar_name:    str
    jar_path:    str
    found:       bool
    backup_path: str = ""
    decompile_dir: str = ""
    patched_jar: str = ""
    sig_patches: list[PatchResult] = field(default_factory=list)
    invoke_custom_files_found: int = 0
    invoke_custom_files_handled: int = 0
    invoke_custom_files_skipped: int = 0
    invoke_custom_files_failed:  int = 0
    rebuild_ok: bool = False
    replaced:   bool = False
    error:      str = ""


@dataclass
class RunResult:
    style:       str
    style_tier:  str
    android_ver: str
    codename:    str
    jar_results: list[JarResult]   = field(default_factory=list)
    tools_found: dict[str, str]    = field(default_factory=dict)
    tools_missing: list[str]       = field(default_factory=list)
    error:       str               = ""


# ── Helpers ───────────────────────────────────────────────────────────────────

def _dread(fname: str) -> str:
    p = DDEVICE_DIR / fname
    return p.read_text(encoding="utf-8", errors="replace").strip() if p.is_file() else ""


def _ts() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())


def _run(cmd: list[str], cwd: Optional[Path] = None,
         capture: bool = True) -> tuple[int, str, str]:
    """Run a command, return (rc, stdout, stderr)."""
    result = subprocess.run(
        cmd,
        capture_output=capture,
        text=True,
        cwd=str(cwd) if cwd else None,
    )
    return result.returncode, result.stdout or "", result.stderr or ""


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── Tool management ───────────────────────────────────────────────────────────

def find_java() -> Optional[str]:
    """Return path to java binary or None."""
    for candidate in ["java", "/usr/bin/java", "/usr/local/bin/java"]:
        if shutil.which(candidate):
            return candidate
    return None


def find_apktool() -> Optional[Path]:
    """Return path to apktool.jar or None."""
    candidates = [
        TOOLS_DIR / "apktool.jar",
        TOOLS_DIR / "apktool_2.9.3.jar",
        WORK_DIR / "tools" / "apktool.jar",
        WORK_DIR / "apktool.jar",
    ]
    for p in candidates:
        if p.is_file():
            return p
    return None


def download_apktool(tools_dir: Path) -> Path:
    """Download apktool.jar v2.9.3 to tools_dir if not present."""
    tools_dir.mkdir(parents=True, exist_ok=True)
    dest = tools_dir / "apktool.jar"
    if dest.is_file():
        return dest

    print(f"[FRAMEWORK-PATCHER] Downloading apktool.jar from GitHub...")
    try:
        urllib.request.urlretrieve(APKTOOL_JAR_URL, dest)
        actual = _sha256(dest)
        if actual != APKTOOL_SHA256:
            dest.unlink(missing_ok=True)
            raise RuntimeError(
                f"apktool.jar SHA256 mismatch: expected {APKTOOL_SHA256}, got {actual}"
            )
        print(f"[FRAMEWORK-PATCHER] Downloaded apktool.jar -> {dest}")
        return dest
    except Exception as exc:
        dest.unlink(missing_ok=True)
        raise RuntimeError(f"Failed to download apktool.jar: {exc}") from exc


def check_tools() -> tuple[dict[str, str], list[str]]:
    """Return (tools_found, tools_missing)."""
    found:   dict[str, str] = {}
    missing: list[str]      = []

    java = find_java()
    if java:
        found["java"] = java
    else:
        missing.append("java")

    apktool = find_apktool()
    if apktool is None:
        try:
            apktool = download_apktool(TOOLS_DIR)
        except Exception:
            apktool = None
    if apktool:
        found["apktool.jar"] = str(apktool)
    else:
        missing.append("apktool.jar")

    return found, missing


# ── JAR discovery ─────────────────────────────────────────────────────────────

def find_jars() -> dict[str, Optional[Path]]:
    """Search BUILD_IMAGES/ for the target JARs. Returns {jar_name: path or None}."""
    result: dict[str, Optional[Path]] = {}
    for jar_name, candidates in JAR_CANDIDATES.items():
        found = None
        for rel in candidates:
            p = BUILD_IMAGES / rel
            if p.is_file():
                found = p
                break
        result[jar_name] = found
    return result


# ── Backup ────────────────────────────────────────────────────────────────────

def create_backup(jar_path: Path) -> Path:
    """Create jar_path + BACKUP_SUFFIX. Does NOT overwrite if already exists."""
    bak = Path(str(jar_path) + BACKUP_SUFFIX)
    if not bak.is_file():
        shutil.copy2(jar_path, bak)
        print(f"[FRAMEWORK-PATCHER] Backup: {bak.name}")
    else:
        print(f"[FRAMEWORK-PATCHER] Backup already exists, keeping: {bak.name}")
    return bak


# ── apktool decompile / rebuild ───────────────────────────────────────────────

def decompile_jar(
    jar_path: Path,
    work_dir: Path,
    apktool_jar: Path,
    java_bin: str,
) -> Path:
    """Decompile jar_path into <work_dir>/<jar_stem>_decompile/. Returns decompile dir."""
    stem = jar_path.stem
    out  = work_dir / f"{stem}_decompile"
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    cmd = [java_bin, "-jar", str(apktool_jar), "d", "-q", "-f",
           str(jar_path), "-o", str(out)]
    rc, stdout, stderr = _run(cmd)
    if rc != 0:
        raise RuntimeError(
            f"apktool decompile failed (rc={rc})\n"
            f"JAR: {jar_path}\n"
            f"stdout: {stdout[-2000:]}\n"
            f"stderr: {stderr[-2000:]}"
        )

    # Create compatibility symlinks: classes → smali (mirrors reference patcher)
    if (out / "classes").is_dir() and not (out / "smali").exists():
        os.symlink("classes", out / "smali")
    for n in range(2, 10):
        src = out / f"classes{n}"
        dst = out / f"smali_classes{n}"
        if src.is_dir() and not dst.exists():
            os.symlink(f"classes{n}", dst)

    print(f"[FRAMEWORK-PATCHER] Decompiled {jar_path.name} -> {out.name}/")
    return out


def rebuild_jar(
    jar_path: Path,
    decompile_dir: Path,
    work_dir: Path,
    apktool_jar: Path,
    java_bin: str,
) -> Path:
    """Recompile decompile_dir into <work_dir>/<stem>_patched.jar. Returns patched jar path."""
    stem = jar_path.stem
    patched = work_dir / f"{stem}_patched.jar"

    cmd = [java_bin, "-jar", str(apktool_jar), "b", "-q", "-f",
           str(decompile_dir), "-o", str(patched)]
    rc, stdout, stderr = _run(cmd)
    if rc != 0:
        raise RuntimeError(
            f"apktool rebuild failed (rc={rc})\n"
            f"DIR: {decompile_dir}\n"
            f"stdout: {stdout[-2000:]}\n"
            f"stderr: {stderr[-2000:]}"
        )

    print(f"[FRAMEWORK-PATCHER] Rebuilt {jar_path.name} -> {patched.name}")
    return patched


# ── Smali patching ────────────────────────────────────────────────────────────

def _find_smali_dirs(decompile_dir: Path) -> list[Path]:
    """Return all smali / smali_classes* directories in decompile_dir."""
    dirs = []
    for d in sorted(decompile_dir.iterdir()):
        if d.is_dir() and (d.name == "smali" or re.match(r"smali_classes\d+", d.name)):
            dirs.append(d)
    # Also check classes / classes2 etc. (real names, before symlink)
    for d in sorted(decompile_dir.iterdir()):
        if d.is_dir() and (d.name == "classes" or re.match(r"classes\d+", d.name)):
            if d not in dirs:
                dirs.append(d)
    return dirs


def _all_smali_files(decompile_dir: Path) -> list[Path]:
    """Return all *.smali files under decompile_dir (follows symlinks)."""
    files = []
    for root, dirs, filenames in os.walk(str(decompile_dir), followlinks=True):
        # Skip non-smali dirs to avoid duplicates via symlinks
        if Path(root).name in ("smali_classes2", "smali_classes3", "smali_classes4",
                                "smali_classes5", "smali_classes6", "smali_classes7",
                                "smali_classes8", "smali_classes9"):
            pass
        for fn in filenames:
            if fn.endswith(".smali"):
                files.append(Path(root) / fn)
    return files


def _grep_method_in_dir(decompile_dir: Path, method_sig: str) -> list[Path]:
    """Return smali files that contain a .method line matching method_sig."""
    pattern = re.compile(r"^\s*\.method\s+.*" + re.escape(method_sig))
    matches = []
    for sf in _all_smali_files(decompile_dir):
        try:
            for line in sf.read_text(encoding="utf-8", errors="replace").splitlines():
                if pattern.search(line):
                    matches.append(sf)
                    break
        except Exception:
            pass
    return matches


def _find_method_bounds(lines: list[str], method_sig: str) -> Optional[tuple[int, int]]:
    """Return (start_idx, end_idx) of first method matching method_sig, or None."""
    pattern = re.compile(r"^\s*\.method\s+.*" + re.escape(method_sig))
    start = None
    for i, line in enumerate(lines):
        if pattern.search(line):
            start = i
            break
    if start is None:
        return None
    for i in range(start + 1, len(lines)):
        if ".end method" in lines[i]:
            return (start, i)
    return None


def _find_all_method_bounds(lines: list[str], method_sig: str) -> list[tuple[int, int]]:
    """Return all (start_idx, end_idx) pairs for method_sig in lines."""
    pattern = re.compile(r"^\s*\.method\s+.*" + re.escape(method_sig))
    bounds = []
    i = 0
    while i < len(lines):
        if pattern.search(lines[i]):
            start = i
            for j in range(i + 1, len(lines)):
                if ".end method" in lines[j]:
                    bounds.append((start, j))
                    i = j + 1
                    break
            else:
                i += 1
        else:
            i += 1
    return bounds


def _replace_method_body(
    lines: list[str],
    start: int,
    end: int,
    patch_type: str,
    value: str,
) -> list[str]:
    """Replace lines[start:end+1] with a simple method body."""
    head = lines[start]
    if patch_type == "return_void":
        body = ["    .registers 8", "    return-void"]
    elif patch_type == "const_return":
        body = ["    .registers 8", f"    const/4 v0, 0x{value}", "    return v0"]
    else:
        body = ["    .registers 8", "    return-void"]
    return lines[:start] + [head] + body + [".end method"] + lines[end + 1:]


def patch_method(
    decompile_dir: Path,
    method_sig: str,
    patch_type: str,
    value: str = "",
) -> PatchResult:
    """Find and patch the first occurrence of method_sig across all smali files.

    Matches reference patcher_a15.sh add_static_return_patch / patch_return_void_method
    behaviour: search all smali files, take the first match, replace entire body.
    """
    candidates = _grep_method_in_dir(decompile_dir, method_sig)
    if not candidates:
        return PatchResult(method_sig, "", applied=False, note="method not found in decompile dir")

    sf = candidates[0]
    try:
        lines = sf.read_text(encoding="utf-8", errors="replace").splitlines()
        bounds = _find_method_bounds(lines, method_sig)
        if bounds is None:
            return PatchResult(method_sig, str(sf), applied=False,
                               note="method boundary not found")
        start, end = bounds
        new_lines = _replace_method_body(lines, start, end, patch_type, value)
        sf.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        print(f"[FRAMEWORK-PATCHER]   Patched {method_sig} -> {patch_type}"
              f"({value or 'void'})  in {sf.name}")
        return PatchResult(method_sig, str(sf), applied=True)
    except Exception as exc:
        return PatchResult(method_sig, str(sf), applied=False, note=str(exc))


def patch_method_all_occurrences(
    decompile_dir: Path,
    method_sig: str,
    patch_type: str,
    value: str = "",
) -> list[PatchResult]:
    """Patch ALL occurrences of method_sig (all files, all overloads).

    Processes bounds bottom-to-top within each file to maintain line number stability.
    Matches reference patch_return_void_methods_all behaviour.
    """
    candidates = _grep_method_in_dir(decompile_dir, method_sig)
    if not candidates:
        return [PatchResult(method_sig, "", applied=False, note="method not found")]

    results: list[PatchResult] = []
    for sf in candidates:
        try:
            lines = sf.read_text(encoding="utf-8", errors="replace").splitlines()
            all_bounds = _find_all_method_bounds(lines, method_sig)
            if not all_bounds:
                results.append(PatchResult(method_sig, str(sf), applied=False,
                                           note="boundary not found"))
                continue
            # Process bottom-to-top so earlier line numbers stay stable
            for start, end in reversed(all_bounds):
                lines = _replace_method_body(lines, start, end, patch_type, value)
            sf.write_text("\n".join(lines) + "\n", encoding="utf-8")
            print(f"[FRAMEWORK-PATCHER]   Patched {len(all_bounds)}x {method_sig}"
                  f" -> {patch_type}({value or 'void'})  in {sf.name}")
            results.append(PatchResult(method_sig, str(sf), applied=True,
                                       note=f"{len(all_bounds)} occurrences"))
        except Exception as exc:
            results.append(PatchResult(method_sig, str(sf), applied=False, note=str(exc)))
    return results


# ── invoke-custom handling ────────────────────────────────────────────────────
# Ports modify_invoke_custom_methods() from patching.sh / patcher_a15.sh.
# Must run BEFORE signature bypass patches on Android 15.

def _has_invoke_custom(path: Path) -> bool:
    try:
        return "invoke-custom" in path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False


def _patch_invoke_custom_in_file(smali_path: Path) -> tuple[bool, str]:
    """Remove invoke-custom from equals/hashCode/toString methods in one smali file.

    Returns (modified, note).
    """
    try:
        content  = smali_path.read_text(encoding="utf-8", errors="replace")
        original = content
        lines    = content.splitlines()

        target_methods = [
            ("equals(",   "const_return", "0",  ".registers 2"),
            ("hashCode(", "const_return", "0",  ".registers 2"),
            ("toString(", "return_object_null", "0", ".registers 1"),
        ]

        changed = False
        for method_sig, patch_kind, val, reg_decl in target_methods:
            all_bounds = _find_all_method_bounds(lines, method_sig)
            if not all_bounds:
                continue

            # Process bottom-to-top
            for start, end in reversed(all_bounds):
                method_body = lines[start + 1 : end]
                if not any("invoke-custom" in ln for ln in method_body):
                    continue

                head = lines[start]
                if patch_kind == "const_return":
                    new_body = [reg_decl,
                                f"    const/4 v0, 0x{val}",
                                "",
                                "    return v0"]
                else:  # toString → return-object with null constant
                    new_body = [reg_decl,
                                f"    const/4 v0, 0x0",
                                "",
                                "    return-object v0"]
                lines = lines[:start] + [head] + new_body + [".end method"] + lines[end + 1:]
                changed = True

        if changed:
            smali_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return changed, "ok"
    except Exception as exc:
        return False, str(exc)


def handle_invoke_custom(decompile_dir: Path) -> dict:
    """Scan all smali files and remove invoke-custom from equals/hashCode/toString.

    Returns result dict with counts.
    """
    all_files    = _all_smali_files(decompile_dir)
    ic_files     = [f for f in all_files if _has_invoke_custom(f)]
    handled      = 0
    skipped      = 0
    failed       = 0
    handled_list: list[str] = []
    skipped_list: list[str] = []
    failed_list:  list[str] = []

    if not ic_files:
        print(f"[FRAMEWORK-PATCHER]   invoke-custom: not found in {decompile_dir.name}, "
              f"no changes needed")
        return {
            "files_scanned":  len(all_files),
            "files_with_ic":  0,
            "handled":        0,
            "skipped":        0,
            "failed":         0,
            "handled_list":   [],
            "skipped_list":   [],
            "failed_list":    [],
        }

    print(f"[FRAMEWORK-PATCHER]   invoke-custom: found in {len(ic_files)} file(s)"
          f" in {decompile_dir.name}")
    for sf in ic_files:
        ok, note = _patch_invoke_custom_in_file(sf)
        if note != "ok":
            failed += 1
            failed_list.append(sf.name)
            print(f"[FRAMEWORK-PATCHER]     FAIL {sf.name}: {note}", file=sys.stderr)
        elif ok:
            handled += 1
            handled_list.append(sf.name)
        else:
            skipped += 1
            skipped_list.append(sf.name)

    print(f"[FRAMEWORK-PATCHER]   invoke-custom: handled={handled} "
          f"skipped={skipped} failed={failed}")
    return {
        "files_scanned":  len(all_files),
        "files_with_ic":  len(ic_files),
        "handled":        handled,
        "skipped":        skipped,
        "failed":         failed,
        "handled_list":   handled_list,
        "skipped_list":   skipped_list,
        "failed_list":    failed_list,
    }


# ── Feature application ───────────────────────────────────────────────────────

def apply_signature_bypass(
    decompile_dir: Path,
    patch_list: list[tuple[str, str, str]],
    jar_label: str,
    android_ver: int,
) -> list[PatchResult]:
    """Apply all signature bypass patches for one JAR."""
    results: list[PatchResult] = []
    print(f"[FRAMEWORK-PATCHER] Applying Signature Verification Bypass: {jar_label}")

    for method_sig, patch_type, value in patch_list:
        if patch_type == "return_void_all":
            res_list = patch_method_all_occurrences(
                decompile_dir, method_sig, "return_void", value
            )
            results.extend(res_list)
        else:
            res = patch_method(decompile_dir, method_sig, patch_type, value)
            results.append(res)

    applied = sum(1 for r in results if r.applied)
    print(f"[FRAMEWORK-PATCHER] {jar_label}: {applied}/{len(results)} patches applied")
    return results


# ── JAR processing pipeline ───────────────────────────────────────────────────

def process_jar(
    jar_name: str,
    jar_path: Path,
    patch_list: list[tuple[str, str, str]],
    android_ver: int,
    apktool_jar: Path,
    java_bin: str,
) -> JarResult:
    """Full pipeline: backup → decompile → invoke-custom → sig-bypass → rebuild → replace."""
    result = JarResult(jar_name=jar_name, jar_path=str(jar_path), found=True)
    work_dir = jar_path.parent  # patch alongside original JAR

    # 1. Backup
    try:
        bak = create_backup(jar_path)
        result.backup_path = str(bak)
    except Exception as exc:
        result.error = f"Backup failed: {exc}"
        print(f"[FRAMEWORK-PATCHER] ERROR: {result.error}", file=sys.stderr)
        return result

    # 2. Decompile
    try:
        decompile_dir = decompile_jar(jar_path, work_dir, apktool_jar, java_bin)
        result.decompile_dir = str(decompile_dir)
    except Exception as exc:
        result.error = f"Decompile failed: {exc}"
        print(f"[FRAMEWORK-PATCHER] ERROR: {result.error}", file=sys.stderr)
        return result

    # 3. invoke-custom (must run BEFORE signature patches on A15+)
    try:
        ic_result = handle_invoke_custom(Path(result.decompile_dir))
        result.invoke_custom_files_found   = ic_result["files_with_ic"]
        result.invoke_custom_files_handled = ic_result["handled"]
        result.invoke_custom_files_skipped = ic_result["skipped"]
        result.invoke_custom_files_failed  = ic_result["failed"]
    except Exception as exc:
        print(f"[FRAMEWORK-PATCHER] WARN: invoke-custom step failed for {jar_name}: {exc}",
              file=sys.stderr)

    # 4. Signature verification bypass
    try:
        sig_results = apply_signature_bypass(
            Path(result.decompile_dir), patch_list, jar_name, android_ver
        )
        result.sig_patches = sig_results
    except Exception as exc:
        result.error = f"Signature bypass failed: {exc}"
        print(f"[FRAMEWORK-PATCHER] ERROR: {result.error}", file=sys.stderr)
        return result

    # 5. Rebuild
    try:
        patched_jar = rebuild_jar(
            jar_path, Path(result.decompile_dir), work_dir, apktool_jar, java_bin
        )
        result.patched_jar = str(patched_jar)
        result.rebuild_ok  = True
    except Exception as exc:
        result.error = f"Rebuild failed: {exc}"
        print(f"[FRAMEWORK-PATCHER] ERROR: {result.error}", file=sys.stderr)
        return result

    # 6. Replace original
    try:
        shutil.copy2(patched_jar, jar_path)
        Path(patched_jar).unlink(missing_ok=True)  # clean up
        result.replaced = True
        sz = jar_path.stat().st_size
        print(f"[FRAMEWORK-PATCHER] Replaced {jar_path.name} ({sz:,} bytes)")
    except Exception as exc:
        result.error = f"Replace failed: {exc}"
        print(f"[FRAMEWORK-PATCHER] ERROR: {result.error}", file=sys.stderr)

    # 7. Cleanup decompile dir to save space
    try:
        shutil.rmtree(result.decompile_dir, ignore_errors=True)
    except Exception:
        pass

    return result


# ── Reports ───────────────────────────────────────────────────────────────────

def _sep(ch: str = "=", n: int = 50) -> str:
    return ch * n


def write_framework_report(run: RunResult) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    jars_found   = [jr for jr in run.jar_results if jr.found]
    jars_missing = [name for name, path in find_jars().items() if path is None]
    jars_patched = [jr for jr in jars_found if jr.replaced]
    jars_failed  = [jr for jr in jars_found if jr.error]

    validation = "PASS" if jars_patched and not any(
        jr.error for jr in jars_patched
    ) else "PARTIAL" if jars_patched else "FAIL"

    lines = [
        "DeadZone Framework Patcher Report",
        _sep(),
        f"Generated:        {_ts()}",
        "",
        f"Style:            {run.style}",
        f"Tier:             {run.style_tier}",
        f"Android:          {run.android_ver}",
        f"Codename:         {run.codename}",
        "",
        f"Features Enabled:",
        "  [x] Signature Verification Bypass",
        "  [x] invoke-custom handling",
        "",
        f"JARs Found ({len(jars_found)}):",
    ]
    for jr in jars_found:
        lines.append(f"  {jr.jar_name:<20s} {jr.jar_path}")
    if not jars_found:
        lines.append("  (none)")

    lines += ["", f"JARs Missing ({len(jars_missing)}):"]
    for name in jars_missing:
        lines.append(f"  ! {name}")
    if not jars_missing:
        lines.append("  (none)")

    lines += ["", "Tools Found:"]
    for name, path in run.tools_found.items():
        lines.append(f"  {name:<20s} {path}")

    lines += ["", "Tools Missing:"]
    for name in run.tools_missing:
        lines.append(f"  ! {name}")
    if not run.tools_missing:
        lines.append("  (none)")

    lines += ["", f"Patched JARs ({len(jars_patched)}):"]
    for jr in jars_patched:
        applied = sum(1 for r in jr.sig_patches if r.applied)
        total   = len(jr.sig_patches)
        lines.append(f"  {jr.jar_name:<20s} PATCHED  ({applied}/{total} patches, "
                     f"ic_handled={jr.invoke_custom_files_handled})")
    if not jars_patched:
        lines.append("  (none)")

    lines += ["", f"Failed JARs ({len(jars_failed)}):"]
    for jr in jars_failed:
        lines.append(f"  {jr.jar_name:<20s} FAILED: {jr.error}")
    if not jars_failed:
        lines.append("  (none)")

    lines += ["", f"Validation: {validation}"]
    if run.error:
        lines += ["", f"Fatal error: {run.error}"]

    out = REPORTS_DIR / "framework_patcher_report.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[FRAMEWORK-PATCHER] Report -> {out}")


def write_sig_bypass_report(run: RunResult) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "Signature Verification Bypass Report",
        _sep(),
        f"Generated: {_ts()}",
        "",
    ]
    for jr in run.jar_results:
        if not jr.found:
            lines += [f"  {jr.jar_name}: NOT FOUND", ""]
            continue
        applied = sum(1 for r in jr.sig_patches if r.applied)
        total   = len(jr.sig_patches)
        status  = "PATCHED" if jr.replaced and applied > 0 else "FAILED" if jr.error else "PARTIAL"
        lines += [
            f"JAR: {jr.jar_name}",
            f"  Path:         {jr.jar_path}",
            f"  Backup:       {jr.backup_path or '(none)'}",
            f"  Decompile:    {jr.decompile_dir or '(not done)'}",
            f"  Patches:      {applied}/{total} applied",
            f"  Rebuild:      {'OK' if jr.rebuild_ok else 'FAILED'}",
            f"  Replaced:     {'YES' if jr.replaced else 'NO'}",
            f"  Status:       {status}",
        ]
        if jr.error:
            lines.append(f"  Error:        {jr.error}")
        lines += ["", "  Patch details:"]
        for r in jr.sig_patches:
            mark = "OK" if r.applied else "MISS"
            note = f" ({r.note})" if r.note else ""
            lines.append(f"    [{mark}] {r.method}{note}")
        lines.append("")

    out = REPORTS_DIR / "signature_verification_bypass_report.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[FRAMEWORK-PATCHER] Sig-bypass report -> {out}")


def write_invoke_custom_report(run: RunResult) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    lines = [
        "invoke-custom Handling Report",
        _sep(),
        f"Generated: {_ts()}",
        "",
    ]
    for jr in run.jar_results:
        if not jr.found:
            lines += [f"  {jr.jar_name}: NOT FOUND", ""]
            continue
        if jr.invoke_custom_files_found == 0:
            ic_status = "not found, no changes needed"
        elif jr.invoke_custom_files_failed > 0:
            ic_status = "PARTIAL (some files failed)"
        else:
            ic_status = f"OK ({jr.invoke_custom_files_handled} handled)"
        lines += [
            f"JAR: {jr.jar_name}",
            f"  Files with invoke-custom: {jr.invoke_custom_files_found}",
            f"  Files handled:            {jr.invoke_custom_files_handled}",
            f"  Files skipped:            {jr.invoke_custom_files_skipped}",
            f"  Files failed:             {jr.invoke_custom_files_failed}",
            f"  Status:                   {ic_status}",
            "",
        ]

    out = REPORTS_DIR / "invoke_custom_report.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[FRAMEWORK-PATCHER] invoke-custom report -> {out}")


def write_error_report(
    stage: str,
    tool: str,
    jar: str,
    stdout: str,
    stderr: str,
    exc: str,
) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    stderr_lines = stderr.splitlines()
    last80 = "\n".join(stderr_lines[-80:]) if stderr_lines else "(empty)"
    lines = [
        "Framework Patcher Error Report",
        _sep(),
        f"Generated:        {_ts()}",
        "",
        f"Failed stage:     {stage}",
        f"Failed tool:      {tool or '(none)'}",
        f"Failed JAR:       {jar or '(none)'}",
        f"Exception:        {exc}",
        "",
        f"=== Last 80 lines stderr ===",
        last80,
        "",
        f"=== stdout (last 40 lines) ===",
        "\n".join(stdout.splitlines()[-40:]) if stdout else "(empty)",
        "",
        "=== Suggested next action ===",
        "1. Check that java is installed: java -version",
        "2. Check that apktool.jar is present in bin/tools/",
        "3. Verify the JAR file is a valid ZIP: unzip -t <jar>",
        "4. Check decompile_dir for smali files",
        "5. Check framework_patcher_report.txt for full summary",
    ]
    out = REPORTS_DIR / "framework_patcher_error.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[FRAMEWORK-PATCHER] Error report -> {out}", file=sys.stderr)


# ── Main ──────────────────────────────────────────────────────────────────────

def _get_android_ver() -> int:
    raw = _dread("androidver.txt")
    digits = re.sub(r"\D", "", raw)
    try:
        return int(digits)
    except ValueError:
        return 0


def _get_patch_list(jar_name: str) -> list[tuple[str, str, str]]:
    """Return the patch list for a given JAR name."""
    if jar_name == "framework":
        return FRAMEWORK_PATCHES
    if jar_name == "services":
        return SERVICES_PATCHES
    if jar_name == "miui-services":
        return MIUI_SERVICES_PATCHES
    return []


def main() -> None:
    print("[FRAMEWORK-PATCHER] ===== DeadZone Framework Patcher =====")
    print(f"[FRAMEWORK-PATCHER] Time: {_ts()}")

    # Resolve style/device info
    style      = os.environ.get("DZ_STYLE_ID", "stable")
    style_tier = os.environ.get("DZ_STYLE_TIER", "Free")
    android_ver_int = _get_android_ver()
    android_str = _dread("androidver.txt") or "unknown"
    codename   = _dread("device_f.txt") or _dread("device_code.txt") or "unknown"

    print(f"[FRAMEWORK-PATCHER] Style:   {style} ({style_tier})")
    print(f"[FRAMEWORK-PATCHER] Android: {android_str}")
    print(f"[FRAMEWORK-PATCHER] Device:  {codename}")

    if android_ver_int not in (15, 16, 35, 36):
        if android_ver_int >= 30:
            print(f"[FRAMEWORK-PATCHER] WARN: Android {android_str} is not explicitly "
                  f"tested (A15/A16 supported). Proceeding with A15 patch set.")
        else:
            print(f"[FRAMEWORK-PATCHER] WARN: Android {android_str} -- "
                  f"Framework patcher may not apply correctly.")

    run = RunResult(
        style=style,
        style_tier=style_tier,
        android_ver=android_str,
        codename=codename,
    )

    # Check tools
    tools_found, tools_missing = check_tools()
    run.tools_found   = tools_found
    run.tools_missing = tools_missing

    if "java" in tools_missing:
        run.error = "Missing required framework patch tool: java"
        print(f"[FRAMEWORK-PATCHER] ERROR: {run.error}", file=sys.stderr)
        write_framework_report(run)
        write_sig_bypass_report(run)
        write_invoke_custom_report(run)
        write_error_report("tool-check", "java", "", "", "", run.error)
        sys.exit(1)

    if "apktool.jar" in tools_missing:
        run.error = "Missing required framework patch tool: apktool.jar"
        print(f"[FRAMEWORK-PATCHER] ERROR: {run.error}", file=sys.stderr)
        write_framework_report(run)
        write_sig_bypass_report(run)
        write_invoke_custom_report(run)
        write_error_report("tool-check", "apktool.jar", "", "", "", run.error)
        sys.exit(1)

    java_bin    = tools_found["java"]
    apktool_jar = Path(tools_found["apktool.jar"])

    # Discover JARs
    jar_map = find_jars()
    print(f"[FRAMEWORK-PATCHER] JAR discovery under {BUILD_IMAGES}:")
    for name, path in jar_map.items():
        status = str(path.relative_to(BUILD_IMAGES)) if path else "NOT FOUND"
        print(f"[FRAMEWORK-PATCHER]   {name:<20s} {status}")

    # Process each found JAR
    all_results: list[JarResult] = []
    sig_total_applied  = 0
    sig_total_expected = 0

    for jar_name, jar_path in jar_map.items():
        if jar_path is None:
            jr = JarResult(jar_name=jar_name, jar_path="", found=False)
            all_results.append(jr)
            print(f"[FRAMEWORK-PATCHER] SKIP {jar_name}: not found")
            continue

        patch_list = _get_patch_list(jar_name)
        sig_total_expected += len(patch_list)

        print(f"\n[FRAMEWORK-PATCHER] Processing {jar_name} ...")
        jr = process_jar(
            jar_name    = jar_name,
            jar_path    = jar_path,
            patch_list  = patch_list,
            android_ver = android_ver_int,
            apktool_jar = apktool_jar,
            java_bin    = java_bin,
        )
        all_results.append(jr)
        sig_total_applied += sum(1 for r in jr.sig_patches if r.applied)

        if jr.error:
            run.error = f"{jar_name}: {jr.error}"

    run.jar_results = all_results

    # Write reports
    print("\n[FRAMEWORK-PATCHER] Writing reports...")
    write_framework_report(run)
    write_sig_bypass_report(run)
    write_invoke_custom_report(run)

    # Validation
    jars_patched = [jr for jr in all_results if jr.replaced]
    any_framework_found = any(jr.found for jr in all_results)

    print(f"\n[FRAMEWORK-PATCHER] ===== Summary =====")
    print(f"[FRAMEWORK-PATCHER] Signature patches: {sig_total_applied}/{sig_total_expected} applied")
    print(f"[FRAMEWORK-PATCHER] JARs replaced:     {len(jars_patched)}")

    if not any_framework_found:
        # No JARs found — warn but don't fail (might be a first-run or unusual ROM)
        print("[FRAMEWORK-PATCHER] WARN: No target JARs found in ROM — "
              "patching skipped. Is the ROM fully extracted?", file=sys.stderr)
        sys.exit(0)

    if sig_total_applied == 0 and any_framework_found:
        write_error_report(
            stage="signature-bypass",
            tool="apktool",
            jar="framework/services",
            stdout="",
            stderr="",
            exc="Signature Verification Bypass: zero patches applied despite JARs being found. "
                "ROM may use different method signatures (Android version mismatch?).",
        )
        print(
            "[FRAMEWORK-PATCHER] ERROR: Signature Verification Bypass failed — "
            "no patches were applied. See framework_patcher_error.txt",
            file=sys.stderr,
        )
        sys.exit(1)

    if run.error:
        print(f"[FRAMEWORK-PATCHER] WARN: Completed with errors: {run.error}", file=sys.stderr)
    else:
        print("[FRAMEWORK-PATCHER] Signature Verification Bypass: PASS")
        print("[FRAMEWORK-PATCHER] invoke-custom handling: PASS")

    print("[FRAMEWORK-PATCHER] ===== Done =====")


if __name__ == "__main__":
    main()
