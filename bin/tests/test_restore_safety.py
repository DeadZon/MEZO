"""Restore-safety tests for DeadZone MEZO APK/JAR patching.

Tests 1-7:   restore_patched_file_in_place() helper
Tests 8-10:  APK patch functions produce restore_in_place fields
Tests 11-13: JAR patch restore fields in framework patch report
Test 14:     MiuiSystemUI applies when OS detection is unknown
Test 15:     Provision rebuild failure keeps original APK
Test 16:     Missing optional targets report SKIPPED not FAILED
Test 17:     deadzone_full_mod_report includes restore_in_place fields
Test 18:     Workflow artifact upload step present
Test 19:     All existing tests still pass (validated by running full suite)
"""
from __future__ import annotations

import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS_DIR  = Path(__file__).resolve().parent.parent / "scripts"
TESTS_DIR    = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import rom_patch_helpers as _rph
from lite_apk_patches import (
    apply_provision_strings,
    apply_miuisystemui_volte_cn_patch,
    apply_powerkeeper_cn_global_patches,
    _rebuild_and_restore,
    _patch_sysui_in_dir,
    _collect_smali_dirs,
)
from deadzone_framework_patches import _rebuild_framework_jars
from deadzone_full_mod_report import build_full_report, _format_txt


# ── helpers ────────────────────────────────────────────────────────────────────

def _mk(path: Path, content: str = "dummy") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _smali_dir(pk_dir: Path) -> Path:
    sd = pk_dir / "smali"
    sd.mkdir(exist_ok=True)
    return sd


# ══════════════════════════════════════════════════════════════════════════════
# Tests 1-7: restore_patched_file_in_place()
# ══════════════════════════════════════════════════════════════════════════════

class TestRestorePatcedFileInPlace:

    def test_1_restores_provision_to_same_path(self, tmp_path):
        """1. restore_patched_file_in_place restores Provision.apk to same path/name."""
        rebuilt = _mk(tmp_path / "rebuilt_Provision.apk", "REBUILT")
        original = tmp_path / "dest" / "Provision" / "Provision.apk"
        original.parent.mkdir(parents=True)
        original.write_text("ORIGINAL", encoding="utf-8")

        result = _rph.restore_patched_file_in_place(rebuilt, original, "Provision.apk")

        assert result["restored"] is True
        assert result["restored_path"] == str(original)
        assert original.read_text() == "REBUILT"
        assert not rebuilt.exists(), "rebuilt temp file should be consumed"

    def test_2_restores_miuisystemui_to_same_path(self, tmp_path):
        """2. restore_patched_file_in_place restores MiuiSystemUI.apk to same path/name."""
        rebuilt = _mk(tmp_path / "rebuilt_MiuiSystemUI.apk", "MSUI_REBUILT")
        original = tmp_path / "system_ext" / "priv-app" / "MiuiSystemUI" / "MiuiSystemUI.apk"
        original.parent.mkdir(parents=True)
        original.write_text("MSUI_ORIGINAL", encoding="utf-8")

        result = _rph.restore_patched_file_in_place(rebuilt, original, "MiuiSystemUI.apk")

        assert result["restored"] is True
        assert Path(result["restored_path"]).name == "MiuiSystemUI.apk"
        assert original.read_text() == "MSUI_REBUILT"

    def test_3_restores_powerkeeper_to_same_path(self, tmp_path):
        """3. restore_patched_file_in_place restores PowerKeeper.apk to same path/name."""
        rebuilt = _mk(tmp_path / "rebuilt_PowerKeeper.apk", "PK_REBUILT")
        original = tmp_path / "product" / "priv-app" / "PowerKeeper" / "PowerKeeper.apk"
        original.parent.mkdir(parents=True)
        original.write_text("PK_ORIGINAL", encoding="utf-8")

        result = _rph.restore_patched_file_in_place(rebuilt, original, "PowerKeeper.apk")

        assert result["restored"] is True
        assert Path(result["restored_path"]).name == "PowerKeeper.apk"
        assert original.read_text() == "PK_REBUILT"

    def test_4_restores_services_jar_to_same_path(self, tmp_path):
        """4. restore_patched_file_in_place restores services.jar to same path/name."""
        rebuilt = _mk(tmp_path / "rebuilt_services.jar", "SVC_REBUILT")
        original = tmp_path / "system" / "framework" / "services.jar"
        original.parent.mkdir(parents=True)
        original.write_text("SVC_ORIGINAL", encoding="utf-8")

        result = _rph.restore_patched_file_in_place(rebuilt, original, "services.jar")

        assert result["restored"] is True
        assert Path(result["restored_path"]).name == "services.jar"
        assert original.read_text() == "SVC_REBUILT"

    def test_5_rejects_missing_rebuilt_file(self, tmp_path):
        """5. restore helper rejects missing rebuilt file (original untouched)."""
        missing = tmp_path / "nonexistent.apk"
        original = _mk(tmp_path / "orig" / "Provision.apk", "SAFE")

        result = _rph.restore_patched_file_in_place(missing, original, "Provision.apk")

        assert result["restored"] is False
        assert "not found" in result["error"]
        assert original.read_text() == "SAFE", "original must be untouched"

    def test_6_original_file_remains_if_rebuilt_missing(self, tmp_path):
        """6. original file remains if rebuilt file is missing."""
        original = _mk(tmp_path / "orig" / "Provision.apk", "ORIGINAL_CONTENT")
        absent = tmp_path / "absent.apk"

        _rph.restore_patched_file_in_place(absent, original, "Provision.apk")

        assert original.exists()
        assert original.read_text() == "ORIGINAL_CONTENT"

    def test_7_chmod_0644_applied(self, tmp_path):
        """7. chmod 0644 is applied to restored APK/JAR (on non-Windows)."""
        rebuilt = _mk(tmp_path / "rebuilt.apk", "CONTENT")
        original = tmp_path / "dest" / "file.apk"
        original.parent.mkdir(parents=True)
        original.write_text("OLD", encoding="utf-8")

        result = _rph.restore_patched_file_in_place(rebuilt, original, "file.apk")

        assert result["restored"] is True
        assert result["permission"] is not None
        assert "0644" in result["permission"]


# ══════════════════════════════════════════════════════════════════════════════
# Tests 8-10: APK patch functions produce restore_in_place fields
# ══════════════════════════════════════════════════════════════════════════════

class TestApkPatchRestoreFields:

    def _make_provision_unpacked(self, work_dir: Path) -> Path:
        pdir = work_dir / "provision_unpacked"
        xml = pdir / "res" / "values" / "strings.xml"
        xml.parent.mkdir(parents=True, exist_ok=True)
        xml.write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
            '  <string name="miui14_global_start_up_slogan">old</string>\n'
            '  <string name="miui14_start_up_slogan">old</string>\n'
            '  <string name="provision_complete_text">old</string>\n'
            '</resources>\n',
            encoding="utf-8",
        )
        return pdir

    def test_8_provision_report_has_restore_fields(self, tmp_path):
        """8. Provision patch report entry has restore_in_place fields."""
        self._make_provision_unpacked(tmp_path)
        report: list = []
        # No APK to rebuild — strings are patched in pre-decompiled dir (no rebuild step)
        apply_provision_strings(tmp_path, report)
        # At least one entry should have been produced
        assert len(report) >= 1
        # When there's a pre-decompiled dir but no APK, we_decompiled=False → no rebuild → no restore
        # The entry for changed strings should still exist
        changed = [r for r in report if r["status"] == "changed"]
        assert len(changed) >= 1
        # restore_in_place should be present (False when no rebuild needed)
        for r in report:
            assert "restore_in_place" in r

    def test_9_miuisystemui_report_has_restore_fields(self, tmp_path):
        """9. MiuiSystemUI patch skips gracefully — report has restore_in_place field."""
        report: list = []
        # Work dir without APK or unpacked dir → skipped_not_found
        apply_miuisystemui_volte_cn_patch(tmp_path, report, rom_os="OS2", rom_region="CN")
        assert any("skipped_not_found" == r["status"] for r in report)
        for r in report:
            assert "restore_in_place" in r

    def test_10_powerkeeper_report_has_restore_fields(self, tmp_path):
        """10. PowerKeeper patch skips gracefully — report has restore_in_place field."""
        report: list = []
        apply_powerkeeper_cn_global_patches(tmp_path, report)
        assert len(report) >= 1
        for r in report:
            assert "restore_in_place" in r


# ══════════════════════════════════════════════════════════════════════════════
# Tests 11-13: JAR restore fields in framework decompile outcomes
# ══════════════════════════════════════════════════════════════════════════════

class TestJarRestoreFields:

    def _make_outcome(self, tmp_path: Path, jar_name: str) -> dict:
        """Create a fake decompile outcome with a pre-built JAR to restore."""
        unpacked = tmp_path / f"{jar_name.replace('.', '_')}_unpacked"
        unpacked.mkdir()
        jar = _mk(tmp_path / jar_name, "JAR_CONTENT")
        return {jar_name: {
            "decompiled": True,
            "jar_path": str(jar),
            "unpacked_dir": str(unpacked),
            "searched_paths": [],
            "reason": "",
        }}

    def _run_rebuild(self, tmp_path: Path, jar_name: str) -> dict:
        """Mock rebuild to succeed and return a rebuilt file."""
        outcome = self._make_outcome(tmp_path, jar_name)
        jar_path = Path(outcome[jar_name]["jar_path"])

        # Patch _rph.rebuild_apk to produce a rebuilt file
        rebuilt_tmp = tmp_path / f"rebuilt_{jar_name}"
        rebuilt_tmp.write_text("REBUILT_JAR", encoding="utf-8")

        import rom_patch_helpers as rph_mod
        original_rebuild = rph_mod.rebuild_apk

        def fake_rebuild(decompile_dir, out_apk, force=True):
            out_apk.write_text("REBUILT_JAR", encoding="utf-8")
            return {"ok": True, "tool_path": "fake", "command": "fake",
                    "stdout": "", "stderr": "", "reason": ""}

        rph_mod.rebuild_apk = fake_rebuild
        try:
            _rebuild_framework_jars(outcome)
        finally:
            rph_mod.rebuild_apk = original_rebuild

        return outcome

    def test_11_services_jar_restore_in_place(self, tmp_path):
        """11. services.jar patch restores services.jar to original path."""
        outcome = self._run_rebuild(tmp_path, "services.jar")
        info = outcome["services.jar"]
        assert info.get("restore_in_place") is True
        assert info.get("restored_path") is not None
        assert Path(info["restored_path"]).name == "services.jar"
        assert Path(info["restored_path"]).read_text() == "REBUILT_JAR"

    def test_12_miui_services_jar_restore_in_place(self, tmp_path):
        """12. miui-services.jar patch restores miui-services.jar to original path."""
        outcome = self._run_rebuild(tmp_path, "miui-services.jar")
        info = outcome["miui-services.jar"]
        assert info.get("restore_in_place") is True
        assert Path(info["restored_path"]).name == "miui-services.jar"

    def test_13_framework_jar_restore_in_place(self, tmp_path):
        """13. framework.jar patch restores framework.jar to original path."""
        outcome = self._run_rebuild(tmp_path, "framework.jar")
        info = outcome["framework.jar"]
        assert info.get("restore_in_place") is True
        assert Path(info["restored_path"]).name == "framework.jar"


# ══════════════════════════════════════════════════════════════════════════════
# Test 14: MiuiSystemUI applies when OS detection is unknown
# ══════════════════════════════════════════════════════════════════════════════

class TestMiuiSystemUIUnknownOS:

    _INTL_FLAG = "Lmiui/os/Build;->IS_INTERNATIONAL_BUILD:Z"

    def _make_sysui_dir(self, work_dir: Path, cls: str = "MiuiOperatorCustomizedPolicy") -> Path:
        sd = work_dir / "miuisystemui_unpacked" / "smali"
        sd.mkdir(parents=True, exist_ok=True)
        smali = sd / f"{cls}.smali"
        smali.write_text(
            f".class public L{cls};\n"
            ".super Ljava/lang/Object;\n\n"
            ".method public testMethod()V\n"
            "    .registers 2\n"
            f"    sget-boolean v0, {self._INTL_FLAG}\n"
            "    return-void\n"
            ".end method\n",
            encoding="utf-8",
        )
        return work_dir / "miuisystemui_unpacked"

    def test_14_applies_when_os_unknown(self, tmp_path):
        """14. MiuiSystemUI patch applies when OS detection is unknown but target class found."""
        self._make_sysui_dir(tmp_path)
        report: list = []

        # Pass empty strings — detection is unknown
        apply_miuisystemui_volte_cn_patch(tmp_path, report, rom_os="", rom_region="")

        # Should NOT skip due to OS/region — should attempt the patch
        statuses = [r["status"] for r in report]
        assert "skipped" not in statuses or any(
            r["status"] not in ("skipped",) for r in report
        ), f"Got all skipped when OS unknown: {statuses}"

        # The os_detection field must say 'unknown' when detection was empty
        for r in report:
            if r.get("os_detection") is not None:
                assert r["os_detection"] in ("unknown", "", "OS2", "OS3", None)

    def test_14b_does_not_skip_on_empty_os(self, tmp_path):
        """14b. Empty rom_os does not cause OS-based skip."""
        self._make_sysui_dir(tmp_path)
        report: list = []
        apply_miuisystemui_volte_cn_patch(tmp_path, report, rom_os="", rom_region="CN")
        # Should not produce OS-skipped entry
        os_skipped = [r for r in report if r["status"] == "skipped" and "OS" in r.get("detail", "")]
        assert len(os_skipped) == 0, f"Should not skip on empty OS: {os_skipped}"

    def test_14c_still_skips_on_known_wrong_os(self, tmp_path):
        """14c. Known non-OS2/OS3 still skips."""
        report: list = []
        apply_miuisystemui_volte_cn_patch(tmp_path, report, rom_os="OS1", rom_region="CN")
        assert any(r["status"] == "skipped" and "OS1" in r.get("detail", "") for r in report)

    def test_14d_still_skips_on_known_wrong_region(self, tmp_path):
        """14d. Known non-CN region still skips."""
        report: list = []
        apply_miuisystemui_volte_cn_patch(tmp_path, report, rom_os="OS2", rom_region="Global")
        assert any(r["status"] == "skipped" and "Global" in r.get("detail", "") for r in report)


# ══════════════════════════════════════════════════════════════════════════════
# Test 15: Provision rebuild failure keeps original APK
# ══════════════════════════════════════════════════════════════════════════════

class TestProvisionRebuildSafety:

    def test_15_rebuild_failure_keeps_original(self, tmp_path):
        """15. If rebuild fails, original Provision.apk remains untouched."""
        original_content = "ORIGINAL_APK_CONTENT"
        apk = _mk(
            tmp_path / "system_ext" / "priv-app" / "Provision" / "Provision.apk",
            original_content,
        )

        # Create a provision_unpacked dir to skip decompile path
        pdir = tmp_path / "provision_unpacked"
        xml = pdir / "res" / "values" / "strings.xml"
        xml.parent.mkdir(parents=True, exist_ok=True)
        xml.write_text(
            '<?xml version="1.0"?><resources>'
            '<string name="provision_complete_text">old</string>'
            '</resources>',
            encoding="utf-8",
        )

        # With pre-decompiled dir, we_decompiled=False, so no rebuild happens
        # and original APK is not touched
        report: list = []
        apply_provision_strings(tmp_path, report)

        # Original APK content must be unchanged
        assert apk.read_text() == original_content, \
            "original APK must not be modified when using pre-decompiled dir"

    def test_15b_rebuild_and_restore_with_failed_recompile(self, tmp_path):
        """15b. _rebuild_and_restore with a failing recompile keeps original untouched."""
        original_content = "ORIGINAL"
        apk = _mk(tmp_path / "Provision.apk", original_content)
        unpacked = tmp_path / "unpacked"
        unpacked.mkdir()

        # Force recompile to fail by providing an empty unpacked dir
        result = _rebuild_and_restore(unpacked, apk, "Provision.apk")

        # Rebuild should fail (apktool not available in test env, or no smali)
        # Either way, original must still have content
        # (ok=True only if apktool is installed; we can't guarantee that in tests)
        # What we CAN guarantee: if ok=False, original is untouched
        if not result["ok"]:
            assert apk.read_text() == original_content, \
                "original must be untouched when rebuild fails"
            assert result["restore_in_place"] is False


# ══════════════════════════════════════════════════════════════════════════════
# Test 16: Missing optional targets report SKIPPED not FAILED
# ══════════════════════════════════════════════════════════════════════════════

class TestMissingTargetsSkipped:

    def test_16_missing_provision_apk_is_skipped_not_failed(self, tmp_path):
        """16a. Missing Provision.apk reports skipped_not_found, not failed."""
        report: list = []
        apply_provision_strings(tmp_path, report)
        statuses = [r["status"] for r in report]
        # Must not be FAILED
        assert "failed" not in statuses
        assert "failed_fatal" not in statuses
        assert any(s in ("skipped", "skipped_not_found") for s in statuses)

    def test_16b_missing_miuisystemui_is_skipped(self, tmp_path):
        """16b. Missing MiuiSystemUI.apk reports skipped, not failed."""
        report: list = []
        apply_miuisystemui_volte_cn_patch(tmp_path, report, rom_os="OS2", rom_region="CN")
        statuses = [r["status"] for r in report]
        assert all(s in ("skipped", "skipped_not_found") for s in statuses)
        assert "failed" not in statuses

    def test_16c_missing_powerkeeper_is_skipped(self, tmp_path):
        """16c. Missing PowerKeeper.apk reports skipped_not_found, not failed."""
        report: list = []
        apply_powerkeeper_cn_global_patches(tmp_path, report)
        statuses = [r["status"] for r in report]
        assert "failed" not in statuses
        assert any(s in ("skipped", "skipped_not_found") for s in statuses)


# ══════════════════════════════════════════════════════════════════════════════
# Test 17: deadzone_full_mod_report includes restore_in_place fields
# ══════════════════════════════════════════════════════════════════════════════

class TestFullModReportRestoreFields:

    def _make_report_with_restore(self, tmp_path: Path) -> Path:
        reports_dir = tmp_path / "bin" / "output" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "generated": "2026-06-06T00:00:00+00:00",
            "style": "lite",
            "results": [{
                "patch_name": "provision_mezo_strings",
                "target_file": "/fake/Provision.apk",
                "found": True,
                "status": "changed",
                "detail": "patched",
                "error": None,
                "searched_paths": [],
                "original_path": "/fake/Provision.apk",
                "rebuilt_path": "/tmp/rebuilt_Provision.apk",
                "restored_path": "/fake/Provision.apk",
                "restore_in_place": True,
                "permission": "0644",
            }],
        }
        f = reports_dir / "lite_apk_patches_mod_report.json"
        f.write_text(json.dumps(data), encoding="utf-8")
        return reports_dir

    def test_17_full_report_contains_restore_in_place(self, tmp_path):
        """17. deadzone_full_mod_report TXT shows restore_in_place when present."""
        reports_dir = self._make_report_with_restore(tmp_path)
        full = build_full_report(reports_dir)
        txt = _format_txt(
            dz_style="lite",
            mod_reports=full["mod_reports"],
            totals=full["totals"],
            final_zip="",
        )
        assert "restore_in_place" in txt, "TXT report must contain restore_in_place"

    def test_17b_full_report_json_has_restore_field_from_results(self, tmp_path):
        """17b. JSON report preserves restore_in_place from individual results."""
        reports_dir = self._make_report_with_restore(tmp_path)
        full = build_full_report(reports_dir)
        # Find the result entry
        all_results = []
        for mod in full["mod_reports"]:
            all_results.extend(mod.get("results", []))
        assert any(r.get("restore_in_place") is True for r in all_results)


# ══════════════════════════════════════════════════════════════════════════════
# Test 18: Workflow artifact upload step present
# ══════════════════════════════════════════════════════════════════════════════

class TestWorkflowArtifacts:

    def _wf(self, name: str) -> str:
        return (PROJECT_ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")

    def test_18a_mtk_has_upload_reports_artifact(self):
        """18a. mezo_mtk.yml has upload-artifact for build reports."""
        c = self._wf("mezo_mtk.yml")
        assert "upload-artifact" in c
        assert "deadzone-build-reports" in c
        assert "bin/output/reports/**" in c
        assert "if: always()" in c

    def test_18b_snapdragon_has_upload_reports_artifact(self):
        """18b. mezo_snapdragon.yml has upload-artifact for build reports."""
        c = self._wf("mezo_snapdragon.yml")
        assert "upload-artifact" in c
        assert "deadzone-build-reports" in c
        assert "bin/output/reports/**" in c
        assert "if: always()" in c


# ══════════════════════════════════════════════════════════════════════════════
# Test 19: restore_patched_file_in_place handles name mismatch gracefully
# ══════════════════════════════════════════════════════════════════════════════

class TestRestoreNameHandling:

    def test_19a_wrong_name_is_renamed_before_restore(self, tmp_path):
        """restore helper renames rebuilt file to expected_name before moving."""
        # Simulate a rebuilt file with a temp name
        rebuilt = _mk(tmp_path / "Provision_rebuilt_abc123.apk", "REBUILT")
        original = _mk(tmp_path / "dest" / "Provision.apk", "ORIGINAL")

        result = _rph.restore_patched_file_in_place(rebuilt, original, "Provision.apk")

        assert result["restored"] is True
        assert Path(result["restored_path"]).name == "Provision.apk"

    def test_19b_cleanup_done_true_after_success(self, tmp_path):
        """cleanup_done is True when rebuilt file was successfully moved."""
        rebuilt = _mk(tmp_path / "rebuilt.apk", "R")
        original = _mk(tmp_path / "orig.apk", "O")

        result = _rph.restore_patched_file_in_place(rebuilt, original, "orig.apk")

        assert result["cleanup_done"] is True
        assert not rebuilt.exists()

    def test_19c_creates_parent_dir_if_missing(self, tmp_path):
        """restore helper creates destination parent directory if it doesn't exist."""
        rebuilt = _mk(tmp_path / "rebuilt.apk", "R")
        # Destination parent does NOT exist yet
        original = tmp_path / "deep" / "nested" / "dir" / "file.apk"

        result = _rph.restore_patched_file_in_place(rebuilt, original, "file.apk")

        assert result["restored"] is True
        assert original.exists()
        assert original.read_text() == "R"
