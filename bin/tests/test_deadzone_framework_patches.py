"""Smoke tests for deadzone_framework_patches.py

Run from repo root:
  pytest tests/test_deadzone_framework_patches.py -v
"""
from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import pytest

# Load the module under test directly (bin/tests/../scripts = bin/scripts/)
_MODULE_PATH = Path(__file__).resolve().parent.parent / "scripts" / "deadzone_framework_patches.py"
_spec = importlib.util.spec_from_file_location("deadzone_framework_patches", _MODULE_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

apply_stable_framework_patches = _mod.apply_stable_framework_patches
apply_invoke_custom_handling = _mod.apply_invoke_custom_handling
apply_fix_bootloop_a15 = _mod.apply_fix_bootloop_a15
apply_signature_verification_bypass = _mod.apply_signature_verification_bypass
_patch_smali_invoke_custom = _mod._patch_smali_invoke_custom


# ── helpers ────────────────────────────────────────────────────────────────────

def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# ══════════════════════════════════════════════════════════════════════════════
# 1. invoke-custom patch on temporary smali files
# ══════════════════════════════════════════════════════════════════════════════

_EQUALS_SMALI = """\
.class public Lfoo/Bar;
.super Ljava/lang/Object;

.method public equals(Ljava/lang/Object;)Z
    .registers 3
    invoke-custom {p0, p1}, handle@0
    move-result v0
    return v0
.end method

.method public hashCode()I
    .registers 2
    invoke-custom {p0}, handle@1
    move-result v0
    return v0
.end method

.method public toString()Ljava/lang/String;
    .registers 2
    invoke-custom {p0}, handle@2
    move-result-object v0
    return-object v0
.end method

.method public doWork()V
    .registers 1
    invoke-custom {p0}, handle@3
    return-void
.end method
"""

def test_invoke_custom_equals_hashcode_tostring(tmp_path):
    """equals/hashCode/toString methods with invoke-custom get safe stubs."""
    smali = _write(tmp_path / "Bar.smali", _EQUALS_SMALI)
    result = _patch_smali_invoke_custom(smali)

    assert result["error"] is None
    assert result["modified"] is True
    assert result["methods_patched"] == 3  # equals, hashCode, toString

    patched = smali.read_text(encoding="utf-8")

    # equals -> return v0 (false)
    assert "equals" in patched
    assert "const/4 v0, 0x0\n    return v0" in patched

    # hashCode -> return v0 (0)
    assert "hashCode" in patched

    # toString -> return-object v0 (null)
    assert "return-object v0" in patched

    # doWork must NOT be stubbed (not equals/hashCode/toString)
    assert "invoke-custom {p0}, handle@3" in patched


def test_invoke_custom_idempotent(tmp_path):
    """Running the patch twice on the same file produces identical output."""
    smali = _write(tmp_path / "Bar.smali", _EQUALS_SMALI)
    _patch_smali_invoke_custom(smali)
    content_after_first = smali.read_text(encoding="utf-8")

    result2 = _patch_smali_invoke_custom(smali)
    content_after_second = smali.read_text(encoding="utf-8")

    assert content_after_first == content_after_second
    assert result2["modified"] is False  # no-op on second pass


def test_invoke_custom_no_invoke_custom(tmp_path):
    """File without invoke-custom is left completely unchanged."""
    plain = ".class public Lfoo/Plain;\n.method public run()V\n    return-void\n.end method\n"
    smali = _write(tmp_path / "Plain.smali", plain)
    result = _patch_smali_invoke_custom(smali)

    assert result["modified"] is False
    assert smali.read_text(encoding="utf-8") == plain


# ══════════════════════════════════════════════════════════════════════════════
# 2. Missing folders produce SKIPPED entries, no crash
# ══════════════════════════════════════════════════════════════════════════════

def test_missing_dirs_produce_skipped_report(tmp_path, monkeypatch):
    """When work_dir has no unpacked dirs, all patches log SKIPPED, not crash."""
    # Redirect report output so we don't write to the real output/reports
    monkeypatch.setattr(_mod, "REPORT_DIR", tmp_path / "reports")

    report = apply_stable_framework_patches(tmp_path)

    # Must not raise; must produce a report dict
    assert isinstance(report, dict)
    assert "patches" in report

    all_statuses = set()
    for patch_data in report["patches"].values():
        for entry in patch_data["results"]:
            all_statuses.add(entry["status"])

    # Everything should be skipped — nothing changed, nothing failed
    assert "failed" not in all_statuses
    assert "changed" not in all_statuses
    assert "skipped" in all_statuses


def test_missing_dirs_sig_bypass(tmp_path):
    """apply_signature_verification_bypass on empty work_dir logs SKIPPED only."""
    entries: list = []
    apply_signature_verification_bypass(tmp_path, entries)
    assert entries, "should have at least one entry"
    for e in entries:
        assert e["status"] == "skipped", f"Expected skipped, got {e['status']}: {e}"
        assert e["found"] is False


def test_missing_dirs_bootloop(tmp_path):
    """apply_fix_bootloop_a15 on empty work_dir logs SKIPPED for every known file."""
    entries: list = []
    apply_fix_bootloop_a15(tmp_path, entries)
    assert entries
    for e in entries:
        assert e["status"] == "skipped"


def test_missing_dirs_invoke_custom(tmp_path):
    """apply_invoke_custom_handling on empty work_dir logs SKIPPED."""
    entries: list = []
    apply_invoke_custom_handling(tmp_path, entries)
    assert entries
    for e in entries:
        assert e["status"] == "skipped"


# ══════════════════════════════════════════════════════════════════════════════
# 3. Report JSON is valid and has expected schema
# ══════════════════════════════════════════════════════════════════════════════

def test_report_json_valid(tmp_path, monkeypatch):
    """JSON report is parseable and contains required top-level keys."""
    monkeypatch.setattr(_mod, "REPORT_DIR", tmp_path / "reports")
    apply_stable_framework_patches(tmp_path)

    json_path = tmp_path / "reports" / "deadzone_patch_report.json"
    assert json_path.exists(), "JSON report file was not created"

    data = json.loads(json_path.read_text(encoding="utf-8"))
    assert "generated" in data
    assert "work_dir" in data
    assert "patches" in data
    assert "totals" in data

    # Patch keys present
    assert "signature_verification_bypass" in data["patches"]
    assert "invoke_custom_handling" in data["patches"]
    assert "fix_bootloop_a15" in data["patches"]

    # Each patch section has required fields
    for patch_data in data["patches"].values():
        assert "enabled" in patch_data
        assert "total_scanned" in patch_data
        assert "total_modified" in patch_data
        assert "total_skipped" in patch_data
        assert "total_failed" in patch_data
        assert "results" in patch_data
        assert isinstance(patch_data["results"], list)

    # Each result entry has required fields
    for patch_data in data["patches"].values():
        for entry in patch_data["results"]:
            assert "patch_name" in entry
            assert "target_file" in entry
            assert "found" in entry
            assert "status" in entry
            assert entry["status"] in ("changed", "skipped", "failed")


def test_report_txt_written(tmp_path, monkeypatch):
    """TXT report is written alongside the JSON report."""
    monkeypatch.setattr(_mod, "REPORT_DIR", tmp_path / "reports")
    apply_stable_framework_patches(tmp_path)

    txt_path = tmp_path / "reports" / "deadzone_patch_report.txt"
    assert txt_path.exists()
    content = txt_path.read_text(encoding="utf-8")
    assert "DeadZone MEZO Framework Patch Report" in content
    assert "SIGNATURE_VERIFICATION_BYPASS" in content
    assert "INVOKE_CUSTOM_HANDLING" in content
    assert "FIX_BOOTLOOP_A15" in content


# ══════════════════════════════════════════════════════════════════════════════
# 4. Stable insmod.sh calls the patch module
# ══════════════════════════════════════════════════════════════════════════════

def test_stable_insmod_calls_patch_module():
    """Stable insmod.sh must invoke framework patches — directly, via Lite, or via Plus.

    Stable is now a compat alias that delegates to Plus/insmod.sh, which inherits Lite,
    which calls style_mod_runner.py → deadzone_framework_patches.py. Any path is OK.
    """
    insmod = (
        Path(__file__).resolve().parent.parent
        / "modfile" / "Styles" / "Stable" / "insmod.sh"
    )
    assert insmod.exists(), f"insmod.sh not found at {insmod}"
    content = insmod.read_text(encoding="utf-8")

    # Accept direct invocation, Lite inheritance, or Plus delegation (compat wrapper)
    calls_patches_directly = "deadzone_framework_patches.py" in content
    calls_lite             = "Lite" in content or "style_mod_runner" in content
    calls_plus             = "Plus" in content
    assert calls_patches_directly or calls_lite or calls_plus, (
        "Stable insmod.sh must either call deadzone_framework_patches.py directly, "
        "inherit from Lite, or delegate to Plus (compat wrapper)"
    )


# ══════════════════════════════════════════════════════════════════════════════
# 5. Integration: patching an actual smali file structure
# ══════════════════════════════════════════════════════════════════════════════

def test_bootloop_patch_targets_specific_files(tmp_path, monkeypatch):
    """apply_fix_bootloop_a15 patches a real smali file in the known-file map."""
    monkeypatch.setattr(_mod, "REPORT_DIR", tmp_path / "reports")

    # Create one of the known bootloop-causing files
    target_rel = (
        "services_unpacked/smali_classes/"
        "com/android/server/BinaryTransparencyService$Digest.smali"
    )
    smali_content = """\
.class public Lcom/android/server/BinaryTransparencyService$Digest;
.super Ljava/lang/Object;

.method public hashCode()I
    .registers 2
    invoke-custom {p0}, handle@5
    move-result v0
    return v0
.end method
"""
    smali_path = tmp_path / target_rel
    _write(smali_path, smali_content)

    entries: list = []
    apply_fix_bootloop_a15(tmp_path, entries)

    changed = [e for e in entries if e["status"] == "changed"]
    assert len(changed) == 1
    assert "BinaryTransparencyService$Digest.smali" in changed[0]["target_file"]

    patched = smali_path.read_text(encoding="utf-8")
    assert "invoke-custom" not in patched
    assert "const/4 v0, 0x0" in patched
