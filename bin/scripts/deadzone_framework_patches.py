#!/usr/bin/env python3
"""
DeadZone MEZO Framework Patches
Ports four targeted smali patches from HyperURBuild:
  1. Signature Verification Bypass  (A14/A15 safe; A16 variant dirs included)
  2. invoke-custom Handling         (broad smali scan)
  3. Fix Bootloop A15               (specific known-bad file map)
  4. miui-services CN/Global Build flag patches (IS_INTERNATIONAL/GLOBAL → IS_MIUI)

All patches are Stable/Free by default — no Legend gate.
Reports written to output/reports/deadzone_patch_report.{txt,json}.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# ── Project paths ──────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent          # bin/scripts
PROJECT_ROOT = SCRIPT_DIR.parent.parent               # project root
REPORT_DIR = PROJECT_ROOT / "bin" / "output" / "reports"

# ── rom_patch_helpers (provides path resolution + decompile/rebuild) ──────────
sys.path.insert(0, str(SCRIPT_DIR))
try:
    import rom_patch_helpers as _rph
except ImportError:
    _rph = None  # type: ignore[assignment]

# JAR candidates searched when pre-decompiled dirs are absent
_FRAMEWORK_JAR_CANDS    = ["system/framework/framework.jar",
                            "system/system/framework/framework.jar"]
_SERVICES_JAR_CANDS     = ["system/framework/services.jar",
                            "system/system/framework/services.jar"]
_MIUI_SERVICES_JAR_CANDS = [
    # system_ext — primary MIUI/HyperOS location
    "system_ext/framework/miui-services.jar",
    "system_ext/system_ext/framework/miui-services.jar",
    "system_ext/miui-services.jar",
    "system_ext/fremawork/miui-services.jar",            # typo fallback seen in some ROMs
    "system_ext/system_ext/fremawork/miui-services.jar",
    # system
    "system/framework/miui-services.jar",
    "system/system/framework/miui-services.jar",
    "system/system_ext/framework/miui-services.jar",
    # product
    "product/framework/miui-services.jar",
    "product/product/framework/miui-services.jar",
]

# ── Report entry schema ────────────────────────────────────────────────────────
# {patch_name, target_file, found, status, detail, error}
# status: "changed" | "skipped" | "failed"

def _entry(
    patch_name: str,
    target_file: str,
    *,
    found: bool,
    status: str,
    detail: str = "",
    error: Optional[str] = None,
) -> dict:
    return {
        "patch_name": patch_name,
        "target_file": target_file,
        "found": found,
        "status": status,
        "detail": detail,
        "error": error,
    }


def _prev_code_line(out: list[str]) -> str:
    """Return the last non-blank stripped line already written to out."""
    for line in reversed(out):
        s = line.strip()
        if s:
            return s
    return ""


# ══════════════════════════════════════════════════════════════════════════════
# PATCH 2 helper — invoke-custom smali file patcher (idempotent)
# ══════════════════════════════════════════════════════════════════════════════

def _patch_smali_invoke_custom(smali_file: Path) -> dict:
    """
    Scan one smali file for methods containing invoke-custom.
    For equals/hashCode/toString methods, replace the body with a safe stub.
    Other methods with invoke-custom are left unchanged.
    Idempotent: a stub body contains no invoke-custom, so a second run is a no-op.

    Returns {"modified": bool, "methods_patched": int, "error": str|None}
    """
    try:
        with smali_file.open("r", encoding="utf-8", errors="ignore") as fh:
            lines = fh.readlines()

        new_lines: list[str] = []
        in_method = False
        method_lines: list[str] = []
        has_invoke_custom = False
        method_name: Optional[str] = None
        file_modified = False
        methods_patched = 0

        for line in lines:
            stripped = line.strip()

            if stripped.startswith(".method"):
                in_method = True
                method_lines = [line]
                has_invoke_custom = False
                parts = stripped.split()
                method_name = parts[-1] if len(parts) > 1 else None

            elif in_method and "invoke-custom" in line:
                has_invoke_custom = True
                method_lines.append(line)

            elif in_method and stripped.startswith(".end method"):
                if has_invoke_custom and method_name:
                    base = method_name.split("(")[0]
                    if "equals" in base:
                        new_lines.append(method_lines[0])
                        new_lines += [
                            "    .registers 2\n",
                            "    const/4 v0, 0x0\n",
                            "    return v0\n",
                            ".end method\n",
                        ]
                        file_modified = True
                        methods_patched += 1
                    elif "hashCode" in base:
                        new_lines.append(method_lines[0])
                        new_lines += [
                            "    .registers 1\n",
                            "    const/4 v0, 0x0\n",
                            "    return v0\n",
                            ".end method\n",
                        ]
                        file_modified = True
                        methods_patched += 1
                    elif "toString" in base:
                        new_lines.append(method_lines[0])
                        new_lines += [
                            "    .registers 1\n",
                            "    const/4 v0, 0x0\n",
                            "    return-object v0\n",
                            ".end method\n",
                        ]
                        file_modified = True
                        methods_patched += 1
                    else:
                        # Not equals/hashCode/toString — preserve unchanged
                        new_lines.extend(method_lines)
                        new_lines.append(line)
                else:
                    new_lines.extend(method_lines)
                    new_lines.append(line)

                in_method = False
                method_lines = []
                has_invoke_custom = False
                method_name = None

            elif in_method:
                method_lines.append(line)
            else:
                new_lines.append(line)

        if file_modified:
            with smali_file.open("w", encoding="utf-8") as fh:
                fh.writelines(new_lines)

        return {"modified": file_modified, "methods_patched": methods_patched, "error": None}

    except Exception as exc:
        return {"modified": False, "methods_patched": 0, "error": str(exc)}


# ══════════════════════════════════════════════════════════════════════════════
# PATCH 1 — Signature Verification Bypass (A14/A15, services, miui_services)
# ══════════════════════════════════════════════════════════════════════════════

_PATCH_SIG = "signature_verification_bypass"

# Extra base paths (relative to work_dir) searched when unpacked dirs are absent
_UNPACKED_EXTRA_BASES: tuple[str, ...] = ("build/baserom/images",)


def _find_unpacked(work_dir: Path, name: str) -> Path:
    """Return the first existing directory named *name* under work_dir or extra bases."""
    direct = work_dir / name
    if direct.is_dir():
        return direct
    for base_rel in _UNPACKED_EXTRA_BASES:
        candidate = work_dir / base_rel / name
        if candidate.is_dir():
            return candidate
    return direct  # fallback — callers check .exists()


def _find_unpacked_path(work_dir: Path, dir_rel: str) -> Path:
    """Resolve a sub-path like 'framework_unpacked/smali_classes2' under work_dir,
    also checking _UNPACKED_EXTRA_BASES when the direct path does not exist."""
    direct = work_dir / dir_rel
    if direct.is_dir():
        return direct
    for base_rel in _UNPACKED_EXTRA_BASES:
        candidate = work_dir / base_rel / dir_rel
        if candidate.is_dir():
            return candidate
    return direct  # fallback — callers check .exists()


def _find_one(root: Path, filename: str) -> Optional[Path]:
    for p in root.rglob(filename):
        return p
    return None


def _overwrite(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def _sig_patch_packageparser(smali_root: Path) -> list[dict]:
    results: list[dict] = []
    rel = str(smali_root)

    # PackageParser.smali
    tgt = _find_one(smali_root, "PackageParser.smali")
    if not tgt:
        results.append(_entry(_PATCH_SIG, f"{rel}/PackageParser.smali",
                              found=False, status="skipped",
                              detail="PackageParser.smali not found"))
    else:
        try:
            lines = tgt.read_text(encoding="utf-8").splitlines(True)
            out: list[str] = []
            in_collect = in_common = False
            changed = 0
            for line in lines:
                s = line.strip()
                if s.startswith(".method") and "collectCertificates(" in s and s.endswith("Z)V"):
                    in_collect = True
                elif in_collect and s.startswith(".end method"):
                    in_collect = False
                if in_collect and "if-eqz p2" in s:
                    # Idempotency: skip if already injected
                    if "const/4 p2, 0x1" not in _prev_code_line(out):
                        out.append("    const/4 p2, 0x1\n")
                        changed += 1
                if s.startswith(".method") and "parseBaseApkCommon(" in s:
                    in_common = True
                elif in_common and s.startswith(".end method"):
                    in_common = False
                if in_common and "if-nez v5" in s:
                    if "const/4 v5, 0x1" not in _prev_code_line(out):
                        out.append("    const/4 v5, 0x1\n")
                        changed += 1
                out.append(line)
            if changed:
                _overwrite(tgt, "".join(out))
                results.append(_entry(_PATCH_SIG, str(tgt), found=True,
                                      status="changed",
                                      detail=f"PackageParser.smali: {changed} spot(s) patched"))
            else:
                results.append(_entry(_PATCH_SIG, str(tgt), found=True,
                                      status="skipped",
                                      detail="PackageParser.smali: no changes needed"))
        except Exception as exc:
            results.append(_entry(_PATCH_SIG, str(tgt), found=True,
                                  status="failed", error=str(exc)))

    # PackageParser$PackageParserException.smali
    tgt2 = _find_one(smali_root, "PackageParser$PackageParserException.smali")
    if tgt2:
        try:
            lines = tgt2.read_text(encoding="utf-8").splitlines(True)
            out2: list[str] = []
            changed2 = 0
            target_iput = ("iput p1, p0, Landroid/content/pm/"
                           "PackageParser$PackageParserException;->error:I")
            for line in lines:
                out2.append(line)
                if target_iput in line:
                    if "const/4 p1, 0x0" not in _prev_code_line(out2[:-1]):
                        out2.append("    const/4 p1, 0x0\n")
                        changed2 += 1
            if changed2:
                _overwrite(tgt2, "".join(out2))
                results.append(_entry(_PATCH_SIG, str(tgt2), found=True,
                                      status="changed",
                                      detail="PackageParserException.smali: error zeroed"))
            else:
                results.append(_entry(_PATCH_SIG, str(tgt2), found=True,
                                      status="skipped",
                                      detail="PackageParserException.smali: no changes needed"))
        except Exception as exc:
            results.append(_entry(_PATCH_SIG, str(tgt2), found=True,
                                  status="failed", error=str(exc)))

    # SigningDetails*.smali (PackageParser$SigningDetails.smali or SigningDetails.smali)
    for fn in ("PackageParser$SigningDetails.smali", "SigningDetails.smali"):
        tgt3 = _find_one(smali_root, fn)
        if not tgt3:
            continue
        try:
            txt = tgt3.read_text(encoding="utf-8")
            orig = txt
            txt = re.sub(
                r"(\.method[^\n]*checkCapability[^\n]*\n)(.*?)(\.end method)",
                r"\1    .registers 3\n    const/4 p0, 0x1\n    return p0\n\3",
                txt, flags=re.DOTALL,
            )
            txt = re.sub(
                r"(\.method[^\n]*hasAncestorOrSelf[^\n]*\n)(.*?)(\.end method)",
                r"\1    .registers 2\n    const/4 p0, 0x1\n    return p0\n\3",
                txt, flags=re.DOTALL,
            )
            if txt != orig:
                _overwrite(tgt3, txt)
                results.append(_entry(_PATCH_SIG, str(tgt3), found=True,
                                      status="changed",
                                      detail=f"{fn}: capability/ancestor forced true"))
            else:
                results.append(_entry(_PATCH_SIG, str(tgt3), found=True,
                                      status="skipped",
                                      detail=f"{fn}: no changes needed"))
        except Exception as exc:
            results.append(_entry(_PATCH_SIG, str(tgt3), found=True,
                                  status="failed", error=str(exc)))

    return results


def _sig_patch_v2_verifier(smali_root: Path) -> list[dict]:
    results: list[dict] = []
    fn = "ApkSignatureSchemeV2Verifier.smali"
    tgt = _find_one(smali_root, fn)
    if not tgt:
        results.append(_entry(_PATCH_SIG, f"{smali_root}/{fn}",
                              found=False, status="skipped",
                              detail=f"{fn} not found"))
        return results
    try:
        lines = tgt.read_text(encoding="utf-8").splitlines(True)
        out: list[str] = []
        in_m = False
        idxs: list[int] = []
        sig = ("verifySigner(Ljava/nio/ByteBuffer;Ljava/util/Map;"
               "Ljava/security/cert/CertificateFactory;)")
        for line in lines:
            s = line.strip()
            if s.startswith(".method") and sig in s:
                in_m = True
            elif in_m and s.startswith(".end method"):
                in_m = False
            if in_m and s == "move-result v0":
                idxs.append(len(out))
            out.append(line)
        if idxs:
            out[idxs[-1]] = "    const/4 v0, 0x1\n"
            _overwrite(tgt, "".join(out))
            results.append(_entry(_PATCH_SIG, str(tgt), found=True,
                                  status="changed",
                                  detail=f"{fn}: v0=1 (verifySigner)"))
        else:
            results.append(_entry(_PATCH_SIG, str(tgt), found=True,
                                  status="skipped",
                                  detail=f"{fn}: pattern not found or already patched"))
    except Exception as exc:
        results.append(_entry(_PATCH_SIG, str(tgt), found=True,
                              status="failed", error=str(exc)))
    return results


def _sig_patch_v3_verifier(smali_root: Path) -> list[dict]:
    results: list[dict] = []
    fn = "ApkSignatureSchemeV3Verifier.smali"
    tgt = _find_one(smali_root, fn)
    if not tgt:
        results.append(_entry(_PATCH_SIG, f"{smali_root}/{fn}",
                              found=False, status="skipped",
                              detail=f"{fn} not found"))
        return results
    try:
        lines = tgt.read_text(encoding="utf-8").splitlines(True)
        out: list[str] = []
        in_m = changed = False
        sig = ("verifySigner(Ljava/nio/ByteBuffer;Ljava/util/Map;"
               "Ljava/security/cert/CertificateFactory;)")
        is_equal_call = ("invoke-static {v12, v6}, "
                         "Ljava/security/MessageDigest;->isEqual([B[B)Z")
        for line in lines:
            s = line.strip()
            if s.startswith(".method") and sig in s:
                in_m = True
            elif in_m and s.startswith(".end method"):
                in_m = False
            if in_m and s == "move-result v0":
                k = len(out) - 1
                while k >= 0 and out[k].strip() == "":
                    k -= 1
                if k >= 0 and out[k].strip() == is_equal_call:
                    out.append("    const/4 v0, 0x1\n")
                    changed = True
                    continue
            out.append(line)
        if changed:
            _overwrite(tgt, "".join(out))
            results.append(_entry(_PATCH_SIG, str(tgt), found=True,
                                  status="changed",
                                  detail=f"{fn}: v0=1 after isEqual"))
        else:
            results.append(_entry(_PATCH_SIG, str(tgt), found=True,
                                  status="skipped",
                                  detail=f"{fn}: pattern not found or already patched"))
    except Exception as exc:
        results.append(_entry(_PATCH_SIG, str(tgt), found=True,
                              status="failed", error=str(exc)))
    return results


def _sig_patch_apksignatureverifier(smali_root: Path) -> list[dict]:
    results: list[dict] = []
    fn = "ApkSignatureVerifier.smali"
    tgt = _find_one(smali_root, fn)
    if not tgt:
        results.append(_entry(_PATCH_SIG, f"{smali_root}/{fn}",
                              found=False, status="skipped",
                              detail=f"{fn} not found"))
        return results
    try:
        lines = tgt.read_text(encoding="utf-8").splitlines(True)
        out: list[str] = []
        in_m = changed = False
        v1_flag = ("invoke-static {p0, p1, p3}, "
                   "Landroid/util/apk/ApkSignatureVerifier;->verifyV1Signature(")
        for line in lines:
            s = line.strip()
            if s.startswith(".method") and "getMinimumSignatureSchemeVersionForTargetSdk" in s:
                in_m = True
                out.append(line)
                out += [
                    "    .registers 1\n",
                    "    const/4 v0, 0x0\n",
                    "    return v0\n",
                ]
                changed = True
                continue
            elif in_m and s.startswith(".end method"):
                out.append(line)
                in_m = False
                continue
            elif in_m:
                continue  # drop old body
            if v1_flag in s:
                out.append("    const p3, 0x0\n")
                changed = True
            out.append(line)
        if changed:
            _overwrite(tgt, "".join(out))
            results.append(_entry(_PATCH_SIG, str(tgt), found=True,
                                  status="changed",
                                  detail=f"{fn}: minScheme=0, p3=0"))
        else:
            results.append(_entry(_PATCH_SIG, str(tgt), found=True,
                                  status="skipped",
                                  detail=f"{fn}: no changes needed"))
    except Exception as exc:
        results.append(_entry(_PATCH_SIG, str(tgt), found=True,
                              status="failed", error=str(exc)))
    return results


def _sig_patch_apksigningblockutils(smali_root: Path) -> list[dict]:
    results: list[dict] = []
    fn = "ApkSigningBlockUtils.smali"
    tgt = _find_one(smali_root, fn)
    if not tgt:
        results.append(_entry(_PATCH_SIG, f"{smali_root}/{fn}",
                              found=False, status="skipped",
                              detail=f"{fn} not found"))
        return results
    try:
        lines = tgt.read_text(encoding="utf-8").splitlines(True)
        out: list[str] = []
        in_m = changed = False
        for line in lines:
            s = line.strip()
            if s.startswith(".method") and "verifyIntegrityFor1MbChunkBasedAlgorithm" in s:
                in_m = True
            elif in_m and s.startswith(".end method"):
                in_m = False
            if in_m and s == "move-result v7":
                out.append("    const/4 v7, 0x1\n")
                changed = True
                continue
            out.append(line)
        if changed:
            _overwrite(tgt, "".join(out))
            results.append(_entry(_PATCH_SIG, str(tgt), found=True,
                                  status="changed",
                                  detail=f"{fn}: v7=1 (integrity always ok)"))
        else:
            results.append(_entry(_PATCH_SIG, str(tgt), found=True,
                                  status="skipped",
                                  detail=f"{fn}: pattern not found or already patched"))
    except Exception as exc:
        results.append(_entry(_PATCH_SIG, str(tgt), found=True,
                              status="failed", error=str(exc)))
    return results


def _sig_patch_strictjar(smali_root: Path) -> list[dict]:
    results: list[dict] = []

    # StrictJarVerifier.smali -> verifyMessageDigest always true
    v = _find_one(smali_root, "StrictJarVerifier.smali")
    if v:
        try:
            lines = v.read_text(encoding="utf-8").splitlines(True)
            out: list[str] = []
            in_m = changed = False
            for line in lines:
                s = line.strip()
                if s.startswith(".method") and "verifyMessageDigest" in s:
                    in_m = True
                    out.append(line)
                    out += [
                        "    .registers 2\n",
                        "    const/4 v0, 0x1\n",
                        "    return v0\n",
                    ]
                    changed = True
                    continue
                if in_m and s.startswith(".end method"):
                    out.append(line)
                    in_m = False
                    continue
                if in_m:
                    continue  # drop old body
                out.append(line)
            if changed:
                _overwrite(v, "".join(out))
                results.append(_entry(_PATCH_SIG, str(v), found=True,
                                      status="changed",
                                      detail="StrictJarVerifier: verifyMessageDigest -> true"))
            else:
                results.append(_entry(_PATCH_SIG, str(v), found=True,
                                      status="skipped",
                                      detail="StrictJarVerifier: no changes needed"))
        except Exception as exc:
            results.append(_entry(_PATCH_SIG, str(v), found=True,
                                  status="failed", error=str(exc)))

    # StrictJarFile.smali: drop fail branch in <init>(...ZZ)V
    f = _find_one(smali_root, "StrictJarFile.smali")
    if f:
        try:
            lines = f.read_text(encoding="utf-8").splitlines(True)
            out2: list[str] = []
            in_m2 = False
            dropped = 0
            for line in lines:
                s = line.strip()
                if s.startswith(".method") and "<init>(Ljava/lang/String;Ljava/io/FileDescriptor;ZZ)V" in s:
                    in_m2 = True
                elif in_m2 and s.startswith(".end method"):
                    in_m2 = False
                if in_m2 and (s == "if-eqz v6, :cond_56" or s == ":cond_56"):
                    dropped += 1
                    continue
                out2.append(line)
            if dropped:
                _overwrite(f, "".join(out2))
                results.append(_entry(_PATCH_SIG, str(f), found=True,
                                      status="changed",
                                      detail="StrictJarFile: dropped fail branch"))
            else:
                results.append(_entry(_PATCH_SIG, str(f), found=True,
                                      status="skipped",
                                      detail="StrictJarFile: no changes needed"))
        except Exception as exc:
            results.append(_entry(_PATCH_SIG, str(f), found=True,
                                  status="failed", error=str(exc)))

    return results


def _sig_patch_services(smali_root: Path) -> list[dict]:
    results: list[dict] = []

    # PackageManagerServiceUtils.smali -> checkDowngrade -> return-void
    f1 = _find_one(smali_root, "PackageManagerServiceUtils.smali")
    if f1:
        try:
            lines = f1.read_text(encoding="utf-8").splitlines(True)
            out: list[str] = []
            in_m = changed = False
            for ln in lines:
                s = ln.strip()
                if s.startswith(".method") and "checkDowngrade" in s:
                    in_m = True
                    out.append(ln)
                    out += ["    .locals 0\n", "    return-void\n"]
                    changed = True
                    continue
                if in_m and s.startswith(".end method"):
                    out.append(ln); in_m = False; continue
                if in_m:
                    continue
                out.append(ln)
            if changed:
                _overwrite(f1, "".join(out))
                results.append(_entry(_PATCH_SIG, str(f1), found=True,
                                      status="changed",
                                      detail="PackageManagerServiceUtils.checkDowngrade -> return-void"))
            else:
                results.append(_entry(_PATCH_SIG, str(f1), found=True,
                                      status="skipped",
                                      detail="PackageManagerServiceUtils: no changes needed"))
        except Exception as exc:
            results.append(_entry(_PATCH_SIG, str(f1), found=True,
                                  status="failed", error=str(exc)))

    # KeySetManagerService.smali -> shouldCheckUpgradeKeySetLocked -> false
    f2 = _find_one(smali_root, "KeySetManagerService.smali")
    if f2:
        try:
            lines = f2.read_text(encoding="utf-8").splitlines(True)
            out2: list[str] = []
            in_m = changed = False
            for ln in lines:
                s = ln.strip()
                if s.startswith(".method") and "shouldCheckUpgradeKeySetLocked" in s:
                    in_m = True
                    out2.append(ln)
                    out2 += ["    .locals 1\n", "    const/4 v0, 0x0\n", "    return v0\n"]
                    changed = True
                    continue
                if in_m and s.startswith(".end method"):
                    out2.append(ln); in_m = False; continue
                if in_m:
                    continue
                out2.append(ln)
            if changed:
                _overwrite(f2, "".join(out2))
                results.append(_entry(_PATCH_SIG, str(f2), found=True,
                                      status="changed",
                                      detail="KeySetManagerService.shouldCheckUpgradeKeySetLocked -> false"))
            else:
                results.append(_entry(_PATCH_SIG, str(f2), found=True,
                                      status="skipped",
                                      detail="KeySetManagerService: no changes needed"))
        except Exception as exc:
            results.append(_entry(_PATCH_SIG, str(f2), found=True,
                                  status="failed", error=str(exc)))

    # InstallPackageHelper.smali: force v12=1 before isLeavingSharedUser()
    f3 = _find_one(smali_root, "InstallPackageHelper.smali")
    if f3:
        try:
            lines = f3.read_text(encoding="utf-8").splitlines(True)
            out3: list[str] = []
            changed3 = 0
            leaving = "invoke-interface {v7}, Lcom/android/server/pm/pkg/AndroidPackage;->isLeavingSharedUser()Z"
            i = 0
            while i < len(lines):
                ln = lines[i]
                s = ln.strip()
                if "if-eqz v12" in s:
                    j = i + 1
                    while j < len(lines) and lines[j].strip() == "":
                        j += 1
                    if j < len(lines) and lines[j].strip() == leaving:
                        # Idempotency: only inject if not already injected
                        if "const/4 v12, 0x1" not in _prev_code_line(out3):
                            out3.append("    const/4 v12, 0x1\n")
                            changed3 += 1
                out3.append(ln)
                i += 1
            if changed3:
                _overwrite(f3, "".join(out3))
                results.append(_entry(_PATCH_SIG, str(f3), found=True,
                                      status="changed",
                                      detail=f"InstallPackageHelper: v12=1 injected ({changed3}x)"))
            else:
                results.append(_entry(_PATCH_SIG, str(f3), found=True,
                                      status="skipped",
                                      detail="InstallPackageHelper: no changes needed"))
        except Exception as exc:
            results.append(_entry(_PATCH_SIG, str(f3), found=True,
                                  status="failed", error=str(exc)))

    # ReconcilePackageUtils.smali: flip first const/4 v0, 0x0 -> 0x1
    f4 = _find_one(smali_root, "ReconcilePackageUtils.smali")
    if f4:
        try:
            txt = f4.read_text(encoding="utf-8")
            new_txt = txt.replace("const/4 v0, 0x0", "const/4 v0, 0x1", 1)
            if new_txt != txt:
                _overwrite(f4, new_txt)
                results.append(_entry(_PATCH_SIG, str(f4), found=True,
                                      status="changed",
                                      detail="ReconcilePackageUtils: v0 -> 1 (first occurrence)"))
            else:
                results.append(_entry(_PATCH_SIG, str(f4), found=True,
                                      status="skipped",
                                      detail="ReconcilePackageUtils: no changes needed"))
        except Exception as exc:
            results.append(_entry(_PATCH_SIG, str(f4), found=True,
                                  status="failed", error=str(exc)))

    return results


def _sig_patch_miui_pms_impl(smali_root: Path) -> list[dict]:
    results: list[dict] = []
    fn = "PackageManagerServiceImpl.smali"
    f = _find_one(smali_root, fn)
    if not f:
        results.append(_entry(_PATCH_SIG, f"{smali_root}/{fn}",
                              found=False, status="skipped",
                              detail=f"{fn} not found in miui_services"))
        return results
    try:
        lines = f.read_text(encoding="utf-8").splitlines(True)
        out: list[str] = []
        in_m = changed = False
        for ln in lines:
            s = ln.strip()
            if s.startswith(".method") and "verifyIsolationViolation" in s:
                in_m = True
                out.append(ln)
                out += ["    .registers 3\n", "    return-void\n"]
                changed = True
                continue
            if s.startswith(".method") and "canBeUpdate(" in s:
                in_m = True
                out.append(ln)
                out += ["    .registers 2\n", "    return-void\n"]
                changed = True
                continue
            if in_m and s.startswith(".end method"):
                out.append(ln); in_m = False; continue
            if in_m:
                continue
            out.append(ln)
        if changed:
            _overwrite(f, "".join(out))
            results.append(_entry(_PATCH_SIG, str(f), found=True,
                                  status="changed",
                                  detail=f"{fn}: verifyIsolationViolation + canBeUpdate -> return-void"))
        else:
            results.append(_entry(_PATCH_SIG, str(f), found=True,
                                  status="skipped",
                                  detail=f"{fn}: no changes needed"))
    except Exception as exc:
        results.append(_entry(_PATCH_SIG, str(f), found=True,
                              status="failed", error=str(exc)))
    return results


def apply_signature_verification_bypass(work_dir: Path, report: list) -> None:
    """
    Patch 1: Disable signature verification in framework, services, and miui_services.
    Targets framework_unpacked/smali_classes{,4,5}, services_unpacked/smali_classes{,2,3},
    and miui_services_unpacked/smali_classes.
    Safe for A14/A15/A16 ROMs where some files/classes may be absent.
    """
    fw = _find_unpacked(work_dir, "framework_unpacked")
    sv = _find_unpacked(work_dir, "services_unpacked")
    mi = _find_unpacked(work_dir, "miui_services_unpacked")

    def _dir_entry(label: str, reason: str) -> dict:
        return _entry(_PATCH_SIG, label, found=False, status="skipped", detail=reason)

    # framework smali dirs
    fw_dirs = [
        fw / "smali_classes",
        fw / "smali_classes4",
        fw / "smali_classes5",
    ]
    # services smali dirs
    sv_dirs = [
        sv / "smali_classes",
        sv / "smali_classes2",
        sv / "smali_classes3",
    ]
    # miui_services smali dir
    mi_dirs = [mi / "smali_classes"]

    if not fw.exists():
        report.append(_dir_entry(str(fw), "framework_unpacked missing — SKIPPED"))
    else:
        if fw_dirs[0].exists():
            report.extend(_sig_patch_packageparser(fw_dirs[0]))
        else:
            report.append(_dir_entry(str(fw_dirs[0]),
                                     "framework_unpacked/smali_classes missing"))
        if fw_dirs[1].exists():
            report.extend(_sig_patch_v2_verifier(fw_dirs[1]))
            report.extend(_sig_patch_v3_verifier(fw_dirs[1]))
            report.extend(_sig_patch_apksignatureverifier(fw_dirs[1]))
            report.extend(_sig_patch_apksigningblockutils(fw_dirs[1]))
            report.extend(_sig_patch_strictjar(fw_dirs[1]))
        else:
            report.append(_dir_entry(str(fw_dirs[1]),
                                     "framework_unpacked/smali_classes4 missing"))
        # smali_classes5 reserved; not required
        if fw_dirs[2].exists():
            pass  # placeholder — no known patches for classes5 yet

    if not sv.exists():
        report.append(_dir_entry(str(sv), "services_unpacked missing — SKIPPED"))
    else:
        any_sv = False
        for d in sv_dirs:
            if d.exists():
                report.extend(_sig_patch_services(d))
                any_sv = True
        if not any_sv:
            report.append(_dir_entry(str(sv),
                                     "services_unpacked: no smali_classes dirs found"))

    if not mi.exists():
        report.append(_dir_entry(str(mi), "miui_services_unpacked missing — SKIPPED"))
    else:
        if mi_dirs[0].exists():
            report.extend(_sig_patch_miui_pms_impl(mi_dirs[0]))
        else:
            report.append(_dir_entry(str(mi_dirs[0]),
                                     "miui_services_unpacked/smali_classes missing"))


# ══════════════════════════════════════════════════════════════════════════════
# PATCH 2 — invoke-custom Handling (broad scan across all smali dirs)
# ══════════════════════════════════════════════════════════════════════════════

_PATCH_IC = "invoke_custom_handling"

_INVOKE_CUSTOM_SMALI_DIRS = [
    "framework_unpacked",
    "services_unpacked",
    "miui_services_unpacked",
]


def apply_invoke_custom_handling(work_dir: Path, report: list) -> None:
    """
    Patch 2: Broad scan of ALL smali files under framework/services/miui_services.
    Replaces invoke-custom in equals/hashCode/toString method bodies with safe stubs.
    Idempotent: stub bodies contain no invoke-custom, so a second run is a no-op.
    """
    any_dir_found = False

    for base_dir_name in _INVOKE_CUSTOM_SMALI_DIRS:
        base_dir = _find_unpacked(work_dir, base_dir_name)
        if not base_dir.exists():
            report.append(_entry(_PATCH_IC, str(base_dir),
                                 found=False, status="skipped",
                                 detail=f"{base_dir_name} missing — SKIPPED"))
            continue

        # Only scan smali_classes* subdirectories (bounded scope)
        smali_subdirs = [d for d in base_dir.iterdir()
                         if d.is_dir() and d.name.startswith("smali")]
        if not smali_subdirs:
            report.append(_entry(_PATCH_IC, str(base_dir),
                                 found=True, status="skipped",
                                 detail=f"{base_dir_name}: no smali_classes dirs found"))
            continue

        any_dir_found = True
        for smali_dir in sorted(smali_subdirs):
            for smali_file in smali_dir.rglob("*.smali"):
                result = _patch_smali_invoke_custom(smali_file)
                if result["error"]:
                    report.append(_entry(_PATCH_IC, str(smali_file),
                                         found=True, status="failed",
                                         detail="",
                                         error=result["error"]))
                elif result["modified"]:
                    report.append(_entry(_PATCH_IC, str(smali_file),
                                         found=True, status="changed",
                                         detail=f"{result['methods_patched']} method(s) stubbed"))

    if not any_dir_found:
        report.append(_entry(_PATCH_IC, str(work_dir),
                             found=False, status="skipped",
                             detail="All target dirs missing — broad scan skipped"))


# ══════════════════════════════════════════════════════════════════════════════
# PATCH 3 — Fix Bootloop A15 (specific known-bad file map)
# ══════════════════════════════════════════════════════════════════════════════

_PATCH_BL = "fix_bootloop_a15"

# Exact file map from fix_bootloop_a15 in HyperURBuild.py
_BOOTLOOP_FILE_MAP: dict[str, list[str]] = {
    "framework_unpacked/smali_classes2": [
        "android/hardware/input/KeyboardLayoutPreviewDrawable$GlyphDrawable.smali",
        "android/hardware/input/PhysicalKeyLayout$EnterKey.smali",
        "android/hardware/input/PhysicalKeyLayout$LayoutKey.smali",
        "android/media/MediaRouter2$InstanceInvalidatedCallbackRecord.smali",
        "android/media/MediaRouter2$PackageNameUserHandlePair.smali",
    ],
    "services_unpacked/smali_classes": [
        "com/android/server/BinaryTransparencyService$Digest.smali",
    ],
    "services_unpacked/smali_classes2": [
        "com/android/server/inputmethod/AdditionalSubtypeMapRepository$WriteTask.smali",
        "com/android/server/policy/PhoneWindowManager$SwitchKeyboardLayoutMessageObject.smali",
        "com/android/server/policy/SingleKeyGestureDetector$MessageObject.smali",
    ],
    "miui_services_unpacked/smali_classes": [
        "com/android/server/am/BroadcastQueueModernStubImpl$ActionCount.smali",
        "com/android/server/input/InputDfsReportStubImpl$MessageObject.smali",
        "com/android/server/input/InputOneTrackUtil$TrackEventListData.smali",
        "com/android/server/input/InputOneTrackUtil$TrackEventStringData.smali",
        "com/android/server/policy/MiuiScreenOnProximityLock$AcquireMessageObject.smali",
        "com/android/server/policy/MiuiScreenOnProximityLock$ReleaseMessageObject.smali",
    ],
}

# Top-level dirs referenced in the file map
_BOOTLOOP_PARENT_DIRS = {
    "framework_unpacked",
    "services_unpacked",
    "miui_services_unpacked",
}


def apply_fix_bootloop_a15(work_dir: Path, report: list) -> None:
    """
    Patch 3: Target the specific known-bad smali files that cause bootloop on A15.
    Uses the same invoke-custom stub logic as Patch 2 but only touches the exact
    files from the original HyperURBuild fix_bootloop_a15 file map.
    """
    missing_parents: set[str] = set()

    for dir_rel, file_list in _BOOTLOOP_FILE_MAP.items():
        parent_name = dir_rel.split("/")[0]
        dir_path = _find_unpacked_path(work_dir, dir_rel)

        if not dir_path.exists():
            if parent_name not in missing_parents:
                missing_parents.add(parent_name)
            report.append(_entry(_PATCH_BL, str(dir_path),
                                 found=False, status="skipped",
                                 detail=f"{dir_rel} missing — SKIPPED"))
            continue

        for file_rel in file_list:
            full_path = dir_path.joinpath(*file_rel.split("/"))
            if not full_path.exists():
                report.append(_entry(_PATCH_BL, str(full_path),
                                     found=False, status="skipped",
                                     detail=f"{file_rel} not present (A15 file may be absent)"))
                continue

            result = _patch_smali_invoke_custom(full_path)
            if result["error"]:
                report.append(_entry(_PATCH_BL, str(full_path),
                                     found=True, status="failed",
                                     detail="",
                                     error=result["error"]))
            elif result["modified"]:
                report.append(_entry(_PATCH_BL, str(full_path),
                                     found=True, status="changed",
                                     detail=f"{result['methods_patched']} method(s) stubbed"))
            else:
                report.append(_entry(_PATCH_BL, str(full_path),
                                     found=True, status="skipped",
                                     detail="No invoke-custom methods requiring stubs"))


# ══════════════════════════════════════════════════════════════════════════════
# PATCH 4 — miui-services CN/Global Build flag patches
# ══════════════════════════════════════════════════════════════════════════════

_PATCH_MSVC = "miui_services_cn_global_patches"

_INTL_FLAG   = "Lmiui/os/Build;->IS_INTERNATIONAL_BUILD:Z"
_GLOBAL_FLAG = "Lmiui/os/Build;->IS_GLOBAL_BUILD:Z"
_MIUI_FLAG   = "Lmiui/os/Build;->IS_MIUI:Z"
_POLICY_MGR_SPUT = "sput-boolean v0, Lcom/miui/server/greeze/PolicyManager;->CN_MODEL:Z"

# Patch A: replace IS_INTERNATIONAL_BUILD → IS_MIUI in these classes
_MSVC_PATCH_A_CLASSES = frozenset([
    "ActivityManagerServiceImpl",
    "BroadcastQueueModernStubImpl",
    "ProcessManagerService",
    "ProcessPolicy",
    "ProcessSceneCleaner",
])

# Patch B: replace IS_GLOBAL_BUILD → IS_MIUI in this class only
_MSVC_PATCH_B_CLASS = "MiuiShortcutTriggerHelper$ShortcutSettingsObserver"

# Patch C: insert const/4 vX, 0x1 below sget-boolean IS_MIUI in these classes
_MSVC_PATCH_C_CLASSES = frozenset([
    "BroadcastQueueModernStubImpl",
    "ProcessManagerService",
    "ProcessSceneCleaner",
])


def _extract_sget_register(line: str) -> Optional[str]:
    """Return the register name from a sget-boolean line, or None."""
    m = re.match(r'\s*sget-boolean\s+(v\d+|p\d+)\s*,', line)
    return m.group(1) if m else None


def _replace_flag(content: str, old_flag: str, new_flag: str) -> tuple[str, int]:
    """Replace old_flag with new_flag everywhere. Returns (new_content, count)."""
    count = content.count(old_flag)
    return (content.replace(old_flag, new_flag), count) if count else (content, 0)


def _insert_const_below_sget(content: str, flag: str, const_value: str = "0x1") -> tuple[str, int]:
    """
    Below each sget-boolean line that references flag, insert const/4 vX, const_value.
    Idempotent: skips if the next non-empty line is already const/4 same_register, const_value.
    Returns (new_content, insertions_count).
    """
    lines = content.splitlines(True)
    out: list[str] = []
    insertions = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("sget-boolean") and flag in stripped:
            reg = _extract_sget_register(stripped)
            if reg:
                # Peek at next non-empty line for idempotency
                j = i + 1
                while j < len(lines) and not lines[j].strip():
                    j += 1
                next_stripped = lines[j].strip() if j < len(lines) else ""
                if next_stripped != f"const/4 {reg}, {const_value}":
                    out.append(line)
                    indent = len(line) - len(line.lstrip())
                    out.append(" " * indent + f"const/4 {reg}, {const_value}\n")
                    insertions += 1
                    i += 1
                    continue
        out.append(line)
        i += 1
    return "".join(out), insertions


def _insert_const_above_sput(content: str, sput_pattern: str) -> tuple[str, int]:
    """
    Insert const/4 v0, 0x0 immediately above the first line matching sput_pattern.
    Idempotent: skips if the preceding non-empty line is already const/4 v0, 0x0.
    Returns (new_content, insertions_count).
    """
    lines = content.splitlines(True)
    out: list[str] = []
    insertions = 0
    for line in lines:
        if line.strip() == sput_pattern.strip() and insertions == 0:
            prev = ""
            for prev_line in reversed(out):
                s = prev_line.strip()
                if s:
                    prev = s
                    break
            if prev != "const/4 v0, 0x0":
                indent = len(line) - len(line.lstrip())
                out.append(" " * indent + "const/4 v0, 0x0\n")
                insertions += 1
        out.append(line)
    return "".join(out), insertions


def _find_smali_class_in_dirs(smali_dirs: list[Path], class_name: str) -> Optional[Path]:
    """Search smali_dirs recursively for class_name.smali."""
    for sd in smali_dirs:
        for p in sd.rglob(f"{class_name}.smali"):
            return p
    return None


def _msvc_entry(
    class_name: str,
    path: str,
    *,
    found: bool,
    status: str,
    replacements: int = 0,
    const_insertions: int = 0,
    detail: str = "",
    error: Optional[str] = None,
) -> dict:
    return {
        "patch_name": _PATCH_MSVC,
        "target_class": class_name,
        "target_file": path,
        "found": found,
        "status": status,
        "replacements_count": replacements,
        "const_insertions_count": const_insertions,
        "files_modified": [path] if status == "changed" else [],
        "detail": detail,
        "error": error,
    }


def apply_miui_services_cn_global_patches(work_dir: Path, report: list) -> None:
    """
    Patch 4: CN/Global Build flag patches for miui-services.jar smali.

    Patch A — Replace IS_INTERNATIONAL_BUILD → IS_MIUI in 5 target classes.
    Patch B — Replace IS_GLOBAL_BUILD → IS_MIUI in ShortcutSettingsObserver.
    Patch C — Insert const/4 vX, 0x1 below IS_MIUI sget-boolean in 3 classes.
    Patch D — Insert const/4 v0, 0x0 above PolicyManager->CN_MODEL sput-boolean.
    """
    mi = _find_unpacked(work_dir, "miui_services_unpacked")

    if not mi.exists():
        report.append(_msvc_entry(
            "miui_services_unpacked", str(mi),
            found=False, status="skipped",
            detail="miui_services_unpacked missing — SKIPPED",
        ))
        return

    smali_dirs = sorted(
        [d for d in mi.iterdir() if d.is_dir() and d.name.startswith("smali")],
        key=lambda d: d.name,
    )
    if not smali_dirs:
        report.append(_msvc_entry(
            "miui_services_unpacked", str(mi),
            found=True, status="skipped",
            detail="No smali_classes dirs in miui_services_unpacked",
        ))
        return

    # ── Patch A: IS_INTERNATIONAL_BUILD → IS_MIUI ──────────────────────────────
    for cls in sorted(_MSVC_PATCH_A_CLASSES):
        path = _find_smali_class_in_dirs(smali_dirs, cls)
        if not path:
            report.append(_msvc_entry(
                cls, f"{mi}/**/{cls}.smali",
                found=False, status="skipped",
                detail=f"{cls}: class not found — SKIPPED",
            ))
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            new_content, count = _replace_flag(content, _INTL_FLAG, _MIUI_FLAG)
            if count:
                path.write_text(new_content, encoding="utf-8")
                report.append(_msvc_entry(
                    cls, str(path), found=True, status="changed",
                    replacements=count,
                    detail=f"{cls}: {count} IS_INTERNATIONAL_BUILD → IS_MIUI",
                ))
            else:
                report.append(_msvc_entry(
                    cls, str(path), found=True, status="skipped",
                    detail=f"{cls}: IS_INTERNATIONAL_BUILD not found",
                ))
        except Exception as exc:
            report.append(_msvc_entry(cls, str(path), found=True, status="failed", error=str(exc)))

    # ── Patch B: IS_GLOBAL_BUILD → IS_MIUI in ShortcutSettingsObserver ─────────
    obs_path = _find_smali_class_in_dirs(smali_dirs, _MSVC_PATCH_B_CLASS)
    if not obs_path:
        report.append(_msvc_entry(
            _MSVC_PATCH_B_CLASS, f"{mi}/**/{_MSVC_PATCH_B_CLASS}.smali",
            found=False, status="skipped",
            detail=f"{_MSVC_PATCH_B_CLASS}: class not found — SKIPPED",
        ))
    else:
        try:
            content = obs_path.read_text(encoding="utf-8", errors="ignore")
            new_content, count = _replace_flag(content, _GLOBAL_FLAG, _MIUI_FLAG)
            if count:
                obs_path.write_text(new_content, encoding="utf-8")
                report.append(_msvc_entry(
                    _MSVC_PATCH_B_CLASS, str(obs_path), found=True, status="changed",
                    replacements=count,
                    detail=f"{_MSVC_PATCH_B_CLASS}: {count} IS_GLOBAL_BUILD → IS_MIUI",
                ))
            else:
                report.append(_msvc_entry(
                    _MSVC_PATCH_B_CLASS, str(obs_path), found=True, status="skipped",
                    detail=f"{_MSVC_PATCH_B_CLASS}: IS_GLOBAL_BUILD not found",
                ))
        except Exception as exc:
            report.append(_msvc_entry(_MSVC_PATCH_B_CLASS, str(obs_path), found=True,
                                      status="failed", error=str(exc)))

    # ── Patch C: const/4 vX, 0x1 below IS_MIUI sget-boolean in 3 classes ───────
    for cls in sorted(_MSVC_PATCH_C_CLASSES):
        path = _find_smali_class_in_dirs(smali_dirs, cls)
        if not path:
            # Already reported as missing in Patch A loop (classes overlap)
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
            new_content, insertions = _insert_const_below_sget(content, _MIUI_FLAG)
            if insertions:
                path.write_text(new_content, encoding="utf-8")
                report.append(_msvc_entry(
                    cls, str(path), found=True, status="changed",
                    const_insertions=insertions,
                    detail=f"{cls} (Patch C): {insertions} const/4 inserted below IS_MIUI",
                ))
            else:
                report.append(_msvc_entry(
                    cls, str(path), found=True, status="skipped",
                    detail=f"{cls} (Patch C): no IS_MIUI sget-boolean found or already patched",
                ))
        except Exception as exc:
            report.append(_msvc_entry(cls, str(path), found=True, status="failed", error=str(exc)))

    # ── Patch D: const/4 v0, 0x0 above PolicyManager->CN_MODEL sput-boolean ─────
    cn_model_found = False
    for sd in smali_dirs:
        for smali_file in sd.rglob("*.smali"):
            try:
                content = smali_file.read_text(encoding="utf-8", errors="ignore")
                if _POLICY_MGR_SPUT not in content:
                    continue
                cn_model_found = True
                new_content, insertions = _insert_const_above_sput(content, _POLICY_MGR_SPUT)
                if insertions:
                    smali_file.write_text(new_content, encoding="utf-8")
                    report.append(_msvc_entry(
                        "PolicyManager", str(smali_file), found=True, status="changed",
                        const_insertions=insertions,
                        detail="PolicyManager CN_MODEL: const/4 v0, 0x0 inserted above sput",
                    ))
                else:
                    report.append(_msvc_entry(
                        "PolicyManager", str(smali_file), found=True, status="skipped",
                        detail="PolicyManager CN_MODEL: already has const/4 v0, 0x0 above sput",
                    ))
                break
            except Exception as exc:
                report.append(_msvc_entry("PolicyManager", str(smali_file), found=True,
                                          status="failed", error=str(exc)))
                cn_model_found = True
                break
        if cn_model_found:
            break

    if not cn_model_found:
        report.append(_msvc_entry(
            "PolicyManager", str(mi),
            found=False, status="skipped",
            detail="PolicyManager CN_MODEL sput-boolean not found — SKIPPED",
        ))


# ══════════════════════════════════════════════════════════════════════════════
# Stable entry point — runs all 4 patches and writes reports
# ══════════════════════════════════════════════════════════════════════════════

def _decompile_framework_jars(work_dir: Path) -> dict[str, dict]:
    """Decompile framework JARs to *_unpacked/ dirs if those dirs are missing.

    Returns a dict mapping unpacked_dir_name -> {decompiled, jar_path, unpacked_dir, result}.
    Only entries where we decompiled (not pre-existing) are included so the caller
    knows what to rebuild+restore afterward.
    """
    if _rph is None:
        return {}

    jar_map = {
        "framework_unpacked":     _FRAMEWORK_JAR_CANDS,
        "services_unpacked":      _SERVICES_JAR_CANDS,
        "miui_services_unpacked": _MIUI_SERVICES_JAR_CANDS,
    }
    outcomes: dict[str, dict] = {}

    for name, cands in jar_map.items():
        unpacked = _find_unpacked(work_dir, name)
        if unpacked.is_dir():
            continue  # already available — no decompile needed

        jar_result = _rph.find_file_in_rom(work_dir, cands)

        # Recursive fallback for miui-services.jar — scan entire build/baserom/images tree
        if not jar_result["found"] and name == "miui_services_unpacked":
            build_images = work_dir / "build" / "baserom" / "images"
            if build_images.is_dir():
                for found_jar in build_images.rglob("miui-services.jar"):
                    if found_jar.is_file():
                        jar_result = {
                            "found":          True,
                            "found_path":     str(found_jar),
                            "searched_paths": jar_result["searched_paths"] + [
                                f"(rglob under {build_images})"
                            ],
                            "reason": "",
                        }
                        break

        if not jar_result["found"]:
            outcomes[name] = {
                "decompiled": False,
                "jar_path": None,
                "unpacked_dir": str(work_dir / name),
                "searched_paths": jar_result["searched_paths"],
                "reason": jar_result["reason"],
            }
            continue

        jar_path = Path(jar_result["found_path"])
        out_dir  = work_dir / name
        decomp   = _rph.decompile_apk(jar_path, out_dir)

        if decomp["ok"]:
            print(f"[DeadZone] Decompiled {jar_path.name} → {out_dir.name}/")
            outcomes[name] = {
                "decompiled":   True,
                "jar_path":     str(jar_path),
                "unpacked_dir": str(out_dir),
                "searched_paths": jar_result["searched_paths"],
                "reason":       "",
            }
        else:
            print(f"[DeadZone] WARN: decompile failed for {jar_path.name}: {decomp['reason']}")
            outcomes[name] = {
                "decompiled":   False,
                "jar_path":     str(jar_path),
                "unpacked_dir": str(out_dir),
                "searched_paths": jar_result["searched_paths"],
                "reason":       decomp["reason"],
                "decomp_stdout": decomp["stdout"],
                "decomp_stderr": decomp["stderr"],
            }

    return outcomes


def _rebuild_framework_jars(decompile_outcomes: dict[str, dict]) -> None:
    """Rebuild and restore JARs for any entry where *decompiled* is True.

    Builds to a temp file first, then uses restore_patched_file_in_place() so
    the original JAR is never touched unless the rebuild succeeds.
    """
    if _rph is None:
        return

    import tempfile as _tf

    for name, info in decompile_outcomes.items():
        if not info["decompiled"]:
            continue
        unpacked_dir = Path(info["unpacked_dir"])
        jar_path     = Path(info["jar_path"])
        expected     = jar_path.name

        tmp_jar = Path(_tf.mktemp(suffix=f"_{expected}", dir=str(jar_path.parent)))
        rebuild = _rph.rebuild_apk(unpacked_dir, tmp_jar)

        if rebuild["ok"]:
            restore = _rph.restore_patched_file_in_place(tmp_jar, jar_path, expected)
            info["rebuild_ok"]      = True
            info["restore_ok"]      = restore["restored"]
            info["restored_path"]   = restore["restored_path"]
            info["restore_in_place"] = restore["restored"]
            info["permission"]      = restore.get("permission")
            info["restore_error"]   = restore.get("error")
            if restore["restored"]:
                print(f"[DeadZone] Rebuilt+restored {expected} → {restore['restored_path']}")
            else:
                print(f"[DeadZone] WARN: rebuild OK but restore failed for {expected}: {restore['error']}")
        else:
            tmp_jar.unlink(missing_ok=True)
            info["rebuild_ok"]       = False
            info["restore_ok"]       = False
            info["restore_in_place"] = False
            info["restore_error"]    = rebuild["reason"]
            print(f"[DeadZone] WARN: rebuild failed for {expected}: {rebuild['reason']}")

        shutil.rmtree(unpacked_dir, ignore_errors=True)


def apply_stable_framework_patches(work_dir: Path) -> dict:
    """
    Run all four framework patches for the active style.
    Writes output/reports/deadzone_patch_report.{txt,json}.
    Returns the full report dict.

    If pre-decompiled *_unpacked/ dirs are absent, attempts to decompile
    the framework JARs first (using rom_patch_helpers + apktool).
    """
    import os as _os
    work_dir = Path(work_dir).resolve()

    # ── COREPATCH overlap guard ───────────────────────────────────────────────
    # When bin/package/COREPATCH is active (ENABLE_DEADZONE_PACKAGE_PATCHES=true),
    # the old framework/signature patch groups overlap with COREPATCH. Skip them
    # unless the user has explicitly opted-in via ENABLE_LEGACY_* flags.
    _corepatch_dir = work_dir / "bin" / "package" / "COREPATCH"
    _pkg_patches_on = _os.environ.get("ENABLE_DEADZONE_PACKAGE_PATCHES", "true").lower() == "true"
    _corepatch_active = _pkg_patches_on and _corepatch_dir.is_dir()

    _legacy_sig    = _os.environ.get("ENABLE_LEGACY_SIGNATURE_BYPASS", "false").lower() == "true"
    _legacy_fw     = _os.environ.get("ENABLE_LEGACY_FRAMEWORK_PATCHES", "false").lower() == "true"
    _legacy_invoke = _os.environ.get("ENABLE_LEGACY_INVOKE_CUSTOM", "false").lower() == "true"

    _skip_sig    = _corepatch_active and not _legacy_sig
    _skip_fw     = _corepatch_active and not _legacy_fw
    _skip_invoke = _corepatch_active and not _legacy_invoke

    if _skip_sig:
        print("[legacy-overlap] Skipping old signature_verification_bypass because bin/package/COREPATCH is active")
    if _skip_fw:
        print("[legacy-overlap] Skipping old framework_patches because bin/package/COREPATCH is active")
    if _skip_invoke:
        print("[legacy-overlap] Skipping old invoke_custom_handling because bin/package/COREPATCH is active")

    # Decompile JARs when unpacked dirs are missing
    decompile_outcomes = _decompile_framework_jars(work_dir)

    sig_entries:  list[dict] = []
    ic_entries:   list[dict] = []
    bl_entries:   list[dict] = []
    msvc_entries: list[dict] = []

    if not _skip_sig:
        apply_signature_verification_bypass(work_dir, sig_entries)
    else:
        sig_entries = [{"target_file": "skipped", "found": False, "status": "skipped",
                        "detail": "COREPATCH active — ENABLE_LEGACY_SIGNATURE_BYPASS=false",
                        "error": None, "searched_paths": []}]

    if not _skip_invoke:
        apply_invoke_custom_handling(work_dir, ic_entries)
    else:
        ic_entries = [{"target_file": "skipped", "found": False, "status": "skipped",
                       "detail": "COREPATCH active — ENABLE_LEGACY_INVOKE_CUSTOM=false",
                       "error": None, "searched_paths": []}]

    if not _skip_fw:
        apply_fix_bootloop_a15(work_dir, bl_entries)
    else:
        bl_entries = [{"target_file": "skipped", "found": False, "status": "skipped",
                       "detail": "COREPATCH active — ENABLE_LEGACY_FRAMEWORK_PATCHES=false",
                       "error": None, "searched_paths": []}]

    apply_miui_services_cn_global_patches(work_dir, msvc_entries)

    # Rebuild JARs we decompiled
    _rebuild_framework_jars(decompile_outcomes)

    all_entries = sig_entries + ic_entries + bl_entries + msvc_entries

    def _summary(entries: list[dict]) -> dict:
        return {
            "enabled": True,
            "total_scanned":  len(entries),
            "total_modified": sum(1 for e in entries if e["status"] == "changed"),
            "total_skipped":  sum(1 for e in entries if e["status"] in ("skipped", "skipped_not_found")),
            "total_failed":   sum(1 for e in entries if e["status"] in ("failed", "failed_optional")),
            "results": entries,
        }

    report = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "work_dir": str(work_dir),
        "decompile_info": decompile_outcomes,
        "patches": {
            "signature_verification_bypass":     _summary(sig_entries),
            "invoke_custom_handling":             _summary(ic_entries),
            "fix_bootloop_a15":                   _summary(bl_entries),
            "miui_services_cn_global_patches":    _summary(msvc_entries),
        },
        "totals": {
            "total_scanned":  len(all_entries),
            "total_modified": sum(1 for e in all_entries if e["status"] == "changed"),
            "total_skipped":  sum(1 for e in all_entries if e["status"] in ("skipped", "skipped_not_found")),
            "total_failed":   sum(1 for e in all_entries if e["status"] in ("failed", "failed_optional")),
        },
    }

    _write_reports(report)
    return report


def _write_reports(report: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # JSON
    json_path = REPORT_DIR / "deadzone_patch_report.json"
    json_path.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # TXT
    txt_path = REPORT_DIR / "deadzone_patch_report.txt"
    lines = [
        "=" * 72,
        "DeadZone MEZO Framework Patch Report",
        f"Generated : {report['generated']}",
        f"Work dir  : {report['work_dir']}",
        "=" * 72,
        "",
    ]
    # Decompile info
    decompile_info = report.get("decompile_info", {})
    if decompile_info:
        lines += ["[JAR DECOMPILE / REBUILD / RESTORE]"]
        for name, info in decompile_info.items():
            ok_tag     = "OK  " if info.get("decompiled") else "SKIP"
            jar        = info.get("jar_path") or "(not found)"
            reason     = info.get("reason") or ""
            restore_ok = info.get("restore_in_place", False)
            restored   = info.get("restored_path") or ""
            r_err      = info.get("restore_error") or ""
            lines.append(f"  [{ok_tag}] {name}: {jar}")
            if reason:
                lines.append(f"       Reason: {reason}")
            if info.get("decompiled"):
                r_tag = "OK  " if restore_ok else "FAIL"
                lines.append(f"       Restore [{r_tag}]: {restored or '(not restored)'}")
                if r_err:
                    lines.append(f"       Restore error: {r_err}")
            for sp in info.get("searched_paths", []):
                lines.append(f"       Searched: {sp}")
        lines.append("")

    for patch_key, patch_data in report["patches"].items():
        lines += [
            f"[{patch_key.upper()}]",
            f"  Enabled  : {patch_data['enabled']}",
            f"  Scanned  : {patch_data['total_scanned']}",
            f"  Modified : {patch_data['total_modified']}",
            f"  Skipped  : {patch_data['total_skipped']}",
            f"  Failed   : {patch_data['total_failed']}",
            "",
        ]
        for e in patch_data["results"]:
            status_tag = e["status"].upper().ljust(16)
            found_tag = "FOUND" if e["found"] else "MISSING"
            lines.append(f"  [{status_tag}] [{found_tag}] {e['target_file']}")
            if e.get("detail"):
                lines.append(f"           {e['detail']}")
            if e.get("error"):
                lines.append(f"           ERROR: {e['error']}")
            for sp in e.get("searched_paths", []):
                lines.append(f"           Searched: {sp}")
        lines.append("")

    t = report["totals"]
    lines += [
        "=" * 72,
        "TOTALS",
        f"  Scanned  : {t['total_scanned']}",
        f"  Modified : {t['total_modified']}",
        f"  Skipped  : {t['total_skipped']}",
        f"  Failed   : {t['total_failed']}",
        "=" * 72,
    ]
    txt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[DeadZone] Report written: {json_path}")
    print(f"[DeadZone] Report written: {txt_path}")


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="DeadZone MEZO Framework Patches",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--work-dir", required=True,
                        help="Path to the ROM work directory (contains framework_unpacked/ etc.)")
    parser.add_argument("--style", choices=["stable", "lite"], default="stable",
                        help="Patch style to apply (stable/lite = all 3 patches)")
    args = parser.parse_args()

    work_dir = Path(args.work_dir)
    if not work_dir.exists():
        print(f"[DeadZone][ERROR] work-dir does not exist: {work_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"[DeadZone] Applying {args.style} framework patches to: {work_dir}")
    report = apply_stable_framework_patches(work_dir)
    t = report["totals"]
    print(f"[DeadZone] Done — scanned={t['total_scanned']} "
          f"modified={t['total_modified']} "
          f"skipped={t['total_skipped']} "
          f"failed={t['total_failed']}")
    if t["total_failed"] > 0:
        sys.exit(2)


if __name__ == "__main__":
    main()
