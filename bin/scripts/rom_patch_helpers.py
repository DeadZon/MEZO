#!/usr/bin/env python3
"""ROM patch helpers for DeadZone MEZO.

Path resolution approach adapted from HyperURBuild.py (resolve_partition_root /
resolve_partition_file). Extended with MEZO's build/baserom/images layout.

All public functions return a result dict with at minimum:
  found          : bool
  found_path     : str | None        (absolute path string, or None)
  searched_paths : list[str]         (every candidate checked)
  reason         : str               (non-empty on failure)

Never raises — callers check "found" instead.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# ── Project constants ──────────────────────────────────────────────────────────
SCRIPT_DIR   = Path(__file__).resolve().parent   # bin/scripts
BIN_DIR      = SCRIPT_DIR.parent                 # bin
PROJECT_ROOT = BIN_DIR.parent                    # repo root

# Extra base paths relative to work_dir where partitions may live in MEZO builds
_BUILD_IMAGES_REL = "build/baserom/images"

# All partition names we care about
_KNOWN_PARTITIONS = ("system", "system_ext", "product", "vendor", "odm")

# Status constants
STATUS_CHANGED          = "changed"
STATUS_SKIPPED          = "skipped"
STATUS_FAILED           = "failed"
STATUS_SKIPPED_NF       = "skipped_not_found"
STATUS_SKIPPED_NOT_ROM  = "skipped_not_target_rom"
STATUS_FAILED_OPTIONAL  = "failed_optional"
STATUS_FAILED_FATAL     = "failed_fatal"
STATUS_APPLIED          = "applied"


# ══════════════════════════════════════════════════════════════════════════════
# 1. Partition root resolution  (modelled on HyperURBuild.resolve_partition_root)
# ══════════════════════════════════════════════════════════════════════════════

def _partition_candidates(work_dir: Path, partition_name: str) -> list[Path]:
    """All candidate root directories for *partition_name*, in priority order.

    Order (mirrors HyperURBuild nested-first preference):
      1. <work_dir>/<part>/<part>                 (nested direct)
      2. <work_dir>/<part>                        (direct)
      3. <work_dir>/build/baserom/images/<part>/<part>  (nested under build)
      4. <work_dir>/build/baserom/images/<part>         (direct under build)
    """
    base_build = work_dir / _BUILD_IMAGES_REL
    return [
        work_dir    / partition_name / partition_name,
        work_dir    / partition_name,
        base_build  / partition_name / partition_name,
        base_build  / partition_name,
    ]


def resolve_partition_roots(work_dir: Path, partition_name: str) -> dict:
    """Return all existing root directories for *partition_name*.

    Matches HyperURBuild.resolve_partition_root() logic but also checks the
    MEZO build/baserom/images tree and returns ALL matches with full diagnostics.

    Returns:
      partition       : str
      found           : bool
      found_paths     : list[str]   all existing roots (may be >1)
      first_found     : str | None  first existing root
      searched_paths  : list[str]
    """
    candidates = _partition_candidates(work_dir, partition_name)
    searched: list[str] = []
    found_paths: list[str] = []
    for c in candidates:
        s = str(c)
        if s not in searched:
            searched.append(s)
        if c.is_dir() and s not in found_paths:
            found_paths.append(s)

    return {
        "partition":      partition_name,
        "found":          bool(found_paths),
        "found_paths":    found_paths,
        "first_found":    found_paths[0] if found_paths else None,
        "searched_paths": searched,
    }


def resolve_partition_root(work_dir: Path, partition_name: str) -> Optional[Path]:
    """Return the best single root for *partition_name*, or None.

    Mirrors HyperURBuild.resolve_partition_root() — nested path preferred over direct.
    """
    for c in _partition_candidates(work_dir, partition_name):
        if c.is_dir():
            return c
    return None


def resolve_partition_file(work_dir: Path, partition_name: str, *parts: str) -> Optional[Path]:
    """Return the full path to a file within the best partition root, or None.

    Mirrors HyperURBuild.resolve_partition_file().
    Does NOT verify the file exists — callers should check .exists() / .is_file().
    """
    root = resolve_partition_root(work_dir, partition_name)
    if root is None:
        return None
    return root.joinpath(*parts)


# ══════════════════════════════════════════════════════════════════════════════
# 2. General file finder across ROM tree
# ══════════════════════════════════════════════════════════════════════════════

def find_partition_file(
    work_dir: Path,
    partition_name: str,
    relative_candidates: list[str],
) -> dict:
    """Search for a file at each of *relative_candidates* within every root of *partition_name*.

    Returns standard {found, found_path, searched_paths, reason} dict.
    """
    roots_info = resolve_partition_roots(work_dir, partition_name)
    searched: list[str] = list(roots_info["searched_paths"])

    for root_str in roots_info["found_paths"]:
        root = Path(root_str)
        for rel in relative_candidates:
            p = root / rel
            s = str(p)
            if s not in searched:
                searched.append(s)
            if p.is_file():
                return {"found": True, "found_path": str(p), "searched_paths": searched, "reason": ""}

    return {
        "found":         False,
        "found_path":    None,
        "searched_paths": searched,
        "reason":        f"File not found in any {partition_name!r} root",
    }


def find_file_in_rom(work_dir: Path, relative_candidates: list[str]) -> dict:
    """Search for a file using raw relative paths under work_dir and build images.

    Tries each candidate under work_dir AND under build/baserom/images.
    Returns {found, found_path, searched_paths, reason}.
    """
    bases = [work_dir, work_dir / _BUILD_IMAGES_REL]
    searched: list[str] = []

    for base in bases:
        for rel in relative_candidates:
            p = base / rel
            s = str(p)
            if s not in searched:
                searched.append(s)
            if p.is_file():
                return {"found": True, "found_path": str(p), "searched_paths": searched, "reason": ""}

    return {
        "found":         False,
        "found_path":    None,
        "searched_paths": searched,
        "reason":        f"Not found in {len(searched)} searched paths",
    }


# ══════════════════════════════════════════════════════════════════════════════
# 3. APK finders
# ══════════════════════════════════════════════════════════════════════════════

_PROVISION_CANDIDATES = [
    "system_ext/priv-app/Provision/Provision.apk",
    "system_ext/system_ext/priv-app/Provision/Provision.apk",
    "product/priv-app/Provision/Provision.apk",
    "product/product/priv-app/Provision/Provision.apk",
]

_MIUI_SYSUI_CANDIDATES = [
    "system_ext/priv-app/MiuiSystemUI/MiuiSystemUI.apk",
    "system_ext/system_ext/priv-app/MiuiSystemUI/MiuiSystemUI.apk",
    "system_ext/app/MiuiSystemUI/MiuiSystemUI.apk",
    "system_ext/system_ext/app/MiuiSystemUI/MiuiSystemUI.apk",
]

_POWERKEEPER_CANDIDATES = [
    "system_ext/priv-app/PowerKeeper/PowerKeeper.apk",
    "system_ext/system_ext/priv-app/PowerKeeper/PowerKeeper.apk",
    "system_ext/app/PowerKeeper/PowerKeeper.apk",
    "system_ext/system_ext/app/PowerKeeper/PowerKeeper.apk",
    "product/priv-app/PowerKeeper/PowerKeeper.apk",
    "product/product/priv-app/PowerKeeper/PowerKeeper.apk",
    "product/app/PowerKeeper/PowerKeeper.apk",
    "product/product/app/PowerKeeper/PowerKeeper.apk",
    "system/priv-app/PowerKeeper/PowerKeeper.apk",
    "system/system/priv-app/PowerKeeper/PowerKeeper.apk",
    "system/app/PowerKeeper/PowerKeeper.apk",
    "system/system/app/PowerKeeper/PowerKeeper.apk",
]


def find_apk(work_dir: Path, apk_name: str, candidate_paths: Optional[list[str]] = None) -> dict:
    """Find an APK by name using a list of relative candidate paths.

    If *candidate_paths* is None, a rglob fallback across ROM partitions is attempted.
    Returns {found, found_path, searched_paths, reason}.
    """
    if candidate_paths:
        result = find_file_in_rom(work_dir, candidate_paths)
        if result["found"]:
            return result
        # Fall through to rglob if explicit list exhausted
        searched = result["searched_paths"]
    else:
        searched = []

    # rglob fallback across known partition roots
    for partition in _KNOWN_PARTITIONS:
        root = resolve_partition_root(work_dir, partition)
        if root is None:
            continue
        for p in root.rglob(apk_name):
            if p.is_file():
                return {"found": True, "found_path": str(p), "searched_paths": searched, "reason": ""}

    return {
        "found":         False,
        "found_path":    None,
        "searched_paths": searched,
        "reason":        f"{apk_name} not found in ROM tree",
    }


def find_provision_apk(work_dir: Path) -> dict:
    return find_file_in_rom(work_dir, _PROVISION_CANDIDATES)


def find_miui_systemui_apk(work_dir: Path) -> dict:
    return find_file_in_rom(work_dir, _MIUI_SYSUI_CANDIDATES)


def find_powerkeeper_apk(work_dir: Path) -> dict:
    return find_file_in_rom(work_dir, _POWERKEEPER_CANDIDATES)


# ══════════════════════════════════════════════════════════════════════════════
# 4. build.prop / framework targets
# ══════════════════════════════════════════════════════════════════════════════

_BUILDPROP_CANDIDATES = [
    "system/build.prop",
    "system/system/build.prop",
    "product/build.prop",
    "product/product/build.prop",
    "system_ext/build.prop",
    "system_ext/system_ext/build.prop",
    "odm/build.prop",
    "odm/odm/build.prop",
]

_FRAMEWORK_JAR_CANDIDATES = [
    "system/framework/framework.jar",
    "system/system/framework/framework.jar",
]

_SERVICES_JAR_CANDIDATES = [
    "system/framework/services.jar",
    "system/system/framework/services.jar",
]

_MIUI_SERVICES_JAR_CANDIDATES = [
    "system/framework/miui-services.jar",
    "system/system/framework/miui-services.jar",
]


def find_build_prop_files(work_dir: Path) -> list[dict]:
    """Return a list of result dicts for every build.prop found."""
    results: list[dict] = []
    bases = [work_dir, work_dir / _BUILD_IMAGES_REL]
    seen: set[str] = set()
    for base in bases:
        for rel in _BUILDPROP_CANDIDATES:
            p = base / rel
            s = str(p)
            if s in seen:
                continue
            seen.add(s)
            if p.is_file():
                results.append({"found": True, "found_path": s, "rel": rel})
    return results


def find_framework_targets(work_dir: Path) -> dict:
    """Find framework.jar, services.jar, and miui-services.jar.

    Returns {found_any, framework, services, miui_services} where each
    value is a standard finder result dict.
    """
    fw  = find_file_in_rom(work_dir, _FRAMEWORK_JAR_CANDIDATES)
    svc = find_file_in_rom(work_dir, _SERVICES_JAR_CANDIDATES)
    msvc = find_file_in_rom(work_dir, _MIUI_SERVICES_JAR_CANDIDATES)
    return {
        "found_any":    fw["found"] or svc["found"] or msvc["found"],
        "framework":    fw,
        "services":     svc,
        "miui_services": msvc,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 5. Smali file finder
# ══════════════════════════════════════════════════════════════════════════════

def find_smali_file(root_dir: Path, class_path: str) -> Optional[Path]:
    """Find a .smali file for *class_path* inside *root_dir* (an unpacked dir).

    *class_path* may be 'com/android/provision/Utils' (without .smali).
    Searches smali/, smali_classes*, classes* subdirectories.
    """
    target = class_path.replace("\\", "/")
    if not target.endswith(".smali"):
        target += ".smali"

    # Search smali_classes* / smali / classes* dirs
    for subdir in sorted(root_dir.iterdir()):
        if not subdir.is_dir():
            continue
        n = subdir.name
        if n in ("smali", "classes") or n.startswith("smali_classes") or n.startswith("classes"):
            candidate = subdir / target
            if candidate.is_file():
                return candidate
    # Fall back: rglob
    for p in root_dir.rglob(Path(target).name):
        if p.is_file():
            return p
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 6. APK / JAR decompile + rebuild + restore
# ══════════════════════════════════════════════════════════════════════════════

def _find_apktool() -> Optional[Path]:
    candidates = [
        BIN_DIR / "apktool" / "apktool.jar",
        BIN_DIR / "tools" / "apktool.jar",
        PROJECT_ROOT / "apktool.jar",
    ]
    for p in candidates:
        if p.is_file():
            return p
    # glob fallback
    apktool_dir = BIN_DIR / "apktool"
    if apktool_dir.is_dir():
        for jar in apktool_dir.glob("apktool*.jar"):
            return jar
    return None


def decompile_apk(apk_path: Path, out_dir: Path, force: bool = True) -> dict:
    """Decompile an APK/JAR using apktool.

    Returns {ok, tool_path, command, stdout, stderr, reason}.
    """
    apktool = _find_apktool()
    if apktool is None:
        return {
            "ok": False, "tool_path": None,
            "command": None, "stdout": "", "stderr": "",
            "reason": "apktool.jar not found — install it to bin/apktool/",
        }

    cmd = ["java", "-jar", str(apktool), "d"]
    if force:
        cmd.append("-f")
    cmd += [str(apk_path), "-o", str(out_dir)]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        ok = r.returncode == 0 and out_dir.is_dir()
        return {
            "ok":        ok,
            "tool_path": str(apktool),
            "command":   " ".join(cmd),
            "stdout":    r.stdout[-2000:] if r.stdout else "",
            "stderr":    r.stderr[-2000:] if r.stderr else "",
            "reason":    "" if ok else f"apktool exited rc={r.returncode}",
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False, "tool_path": str(apktool), "command": " ".join(cmd),
            "stdout": "", "stderr": "", "reason": "apktool decompile timed out (300s)",
        }
    except FileNotFoundError:
        return {
            "ok": False, "tool_path": str(apktool), "command": " ".join(cmd),
            "stdout": "", "stderr": "", "reason": "java not found — JDK required",
        }
    except Exception as exc:
        return {
            "ok": False, "tool_path": str(apktool), "command": " ".join(cmd),
            "stdout": "", "stderr": "", "reason": str(exc),
        }


def rebuild_apk(decompiled_dir: Path, out_apk: Path, force: bool = True) -> dict:
    """Rebuild an APK/JAR from decompiled directory using apktool.

    Returns {ok, tool_path, command, stdout, stderr, reason}.
    """
    apktool = _find_apktool()
    if apktool is None:
        return {
            "ok": False, "tool_path": None, "command": None,
            "stdout": "", "stderr": "", "reason": "apktool.jar not found",
        }

    cmd = ["java", "-jar", str(apktool), "b"]
    if force:
        cmd.append("-f")
    cmd += [str(decompiled_dir), "-o", str(out_apk)]

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        ok = r.returncode == 0 and out_apk.is_file()
        return {
            "ok":        ok,
            "tool_path": str(apktool),
            "command":   " ".join(cmd),
            "stdout":    r.stdout[-2000:] if r.stdout else "",
            "stderr":    r.stderr[-2000:] if r.stderr else "",
            "reason":    "" if ok else f"apktool rebuild rc={r.returncode}",
        }
    except subprocess.TimeoutExpired:
        return {
            "ok": False, "tool_path": str(apktool), "command": " ".join(cmd),
            "stdout": "", "stderr": "", "reason": "apktool rebuild timed out (300s)",
        }
    except FileNotFoundError:
        return {
            "ok": False, "tool_path": str(apktool), "command": " ".join(cmd),
            "stdout": "", "stderr": "", "reason": "java not found — JDK required",
        }
    except Exception as exc:
        return {
            "ok": False, "tool_path": str(apktool), "command": " ".join(cmd),
            "stdout": "", "stderr": "", "reason": str(exc),
        }


def restore_file(src: Path, dst: Path) -> dict:
    """Move *src* over *dst*, replacing it.

    Returns {ok, src, dst, reason}.
    """
    try:
        import shutil as _shutil
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.exists():
            dst.unlink()
        _shutil.move(str(src), str(dst))
        return {"ok": True, "src": str(src), "dst": str(dst), "reason": ""}
    except Exception as exc:
        return {"ok": False, "src": str(src), "dst": str(dst), "reason": str(exc)}


# ══════════════════════════════════════════════════════════════════════════════
# 7. Generic text-file patcher
# ══════════════════════════════════════════════════════════════════════════════

def patch_text_file(path: Path, patch_func) -> dict:
    """Apply *patch_func(content: str) -> str* to a text file in-place.

    Returns {ok, changed, path, reason}.
    patch_func should return the same string unchanged if no patch needed.
    """
    try:
        original = path.read_text(encoding="utf-8", errors="replace")
        patched  = patch_func(original)
        if patched == original:
            return {"ok": True, "changed": False, "path": str(path), "reason": "already patched or not applicable"}
        path.write_text(patched, encoding="utf-8")
        return {"ok": True, "changed": True, "path": str(path), "reason": ""}
    except Exception as exc:
        return {"ok": False, "changed": False, "path": str(path), "reason": str(exc)}
