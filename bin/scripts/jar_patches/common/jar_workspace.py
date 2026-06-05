#!/usr/bin/env python3
"""JAR decode/rebuild workspace management for the DeadZone JAR patch engine."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional


BACKUP_SUFFIX = ".bak_deadzone_jarmods"

# Preferred apktool locations (searched in order)
_APKTOOL_CANDIDATES = [
    "bin/tools/apktool.jar",
    "bin/apktool/apktool.jar",
    "tools/apktool.jar",
    "apktool.jar",
]


def find_java() -> Optional[str]:
    for name in ["java", "/usr/bin/java", "/usr/local/bin/java"]:
        if shutil.which(name):
            return name
    return None


def find_apktool(work_dir: Path) -> Optional[Path]:
    for rel in _APKTOOL_CANDIDATES:
        p = work_dir / rel
        if p.is_file():
            return p
    return None


def find_jar(build_images: Path, candidates: list[str]) -> Optional[Path]:
    """Return the first existing JAR path from candidates list.

    candidates: list of paths relative to build_images, e.g.
      ["system/framework/framework.jar", "product/framework/framework.jar"]
    """
    for rel in candidates:
        p = build_images / rel
        if p.is_file():
            return p
    return None


def backup_jar(jar_path: Path) -> Path:
    """Create jar_path + BACKUP_SUFFIX if backup doesn't already exist.

    Returns backup path.
    """
    backup = Path(str(jar_path) + BACKUP_SUFFIX)
    if not backup.exists():
        shutil.copy2(jar_path, backup)
    return backup


def decompile_jar(
    jar_path: Path,
    apktool: Path,
    java: str,
    out_dir: Path,
) -> tuple[bool, str]:
    """Run apktool d on jar_path → out_dir.

    Returns (success, stderr_or_error).
    """
    if out_dir.exists():
        shutil.rmtree(out_dir)
    cmd = [
        java, "-jar", str(apktool),
        "d", str(jar_path),
        "-o", str(out_dir),
        "--no-res",
        "-f",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or "apktool returned non-zero")
        return True, ""
    except Exception as exc:
        return False, str(exc)


def rebuild_jar(
    source_dir: Path,
    apktool: Path,
    java: str,
    out_jar: Path,
) -> tuple[bool, str]:
    """Run apktool b on source_dir → out_jar.

    Returns (success, stderr_or_error).
    """
    cmd = [
        java, "-jar", str(apktool),
        "b", str(source_dir),
        "-o", str(out_jar),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=300
        )
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or "apktool b returned non-zero")
        if not out_jar.is_file():
            return False, f"apktool b succeeded but {out_jar} not created"
        return True, ""
    except Exception as exc:
        return False, str(exc)


def replace_jar(rebuilt_jar: Path, original_jar: Path) -> None:
    """Overwrite original_jar with rebuilt_jar."""
    shutil.copy2(rebuilt_jar, original_jar)
