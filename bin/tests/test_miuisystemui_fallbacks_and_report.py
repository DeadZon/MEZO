"""Tests for PART 1-4 of the MiuiSystemUI APKEditor fallback and report fixes.

Tests 1-6:   MiuiSystemUI rebuild strategies (APKEditor fallback, Strategy C)
Tests 7-9:   Full report timing — final_zip_summary, pixeldrain_url
Tests 10-13: Restore totals — strings/class entries not counted as restore failures
Test 14:     Regression guard — all tests still pass
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

SCRIPTS_DIR  = Path(__file__).resolve().parent.parent / "scripts"
TESTS_DIR    = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from lite_apk_patches import (
    apply_miuisystemui_volte_cn_patch,
    _rebuild_miuisystemui_smali_only,
    _rebuild_miuisystemui_with_apkeditor,
    _find_apkeditor_jar,
)
from deadzone_full_mod_report import (
    build_full_report,
    write_full_report,
    _summarize_results,
    _is_restore_applicable,
    _iter_all_results,
)


# ── helpers ────────────────────────────────────────────────────────────────────

def _mk(path: Path, content: bytes | str = b"x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def _make_zip(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(str(path), "w") as zf:
        zf.writestr("classes.dex", b"\x64\x65\x78\x0a\x00" * 10, compress_type=zipfile.ZIP_STORED)
        zf.writestr("AndroidManifest.xml", b"<manifest/>")
    return path


def _make_sysui_apk(tmp_path: Path) -> Path:
    return _make_zip(
        tmp_path / "build" / "baserom" / "images" /
        "system_ext" / "priv-app" / "MiuiSystemUI" / "MiuiSystemUI.apk"
    )


def _fake_fail(**extra) -> dict:
    base = {
        "ok": False, "rebuilt_path": None, "restored_path": None,
        "restore_in_place": False, "permission": None,
        "stdout": "", "stderr": "", "error": "mock fail",
        "smali_compile_tool": None,
        "changed_smali_folders": [], "dex_files_rebuilt": [], "dex_entries_replaced": [],
        "smali_compile_commands": [], "smali_compile_stdout": "", "smali_compile_stderr": "",
    }
    base.update(extra)
    return base


def _fake_ok(apk_path: Path, **extra) -> dict:
    base = {
        "ok": True, "rebuilt_path": str(apk_path), "restored_path": str(apk_path),
        "restore_in_place": True, "permission": "0644",
        "stdout": "", "stderr": "", "error": None,
        "smali_compile_tool": "smali.jar",
        "changed_smali_folders": [], "dex_files_rebuilt": ["classes.dex"],
        "dex_entries_replaced": ["classes.dex"],
        "smali_compile_commands": [], "smali_compile_stdout": "", "smali_compile_stderr": "",
    }
    base.update(extra)
    return base


def _make_unpacked_dir(tmp_path: Path) -> Path:
    d = tmp_path / "msui_unpacked"
    (d / "smali_classes").mkdir(parents=True)
    return d


# ══════════════════════════════════════════════════════════════════════════════
# Tests 1-6: MiuiSystemUI rebuild strategies
# ══════════════════════════════════════════════════════════════════════════════

class TestMiuiSystemUIApkEditorFallback:

    def test_1_apkeditor_fallback_attempted_when_apktool_fails(self, tmp_path):
        """Test 1: APKEditor fallback is attempted when apktool rebuild fails."""
        apk = _make_sysui_apk(tmp_path)
        unpacked = _make_unpacked_dir(tmp_path)
        report: list = []

        called = []

        def fake_get_or_decompile(*a, **kw):
            return unpacked, True, apk, [str(apk)]

        def fake_apktool_fail(*a, **kw):
            return _fake_fail(error="aapt2 failed")

        def fake_smali_fail(*a, **kw):
            return _fake_fail(error="IndexOutOfBoundsException: toIndex = 128")

        def fake_ae_ok(*a, **kw):
            called.append("apkeditor")
            return _fake_ok(apk,
                apkeditor_decode_command="java -jar apke.jar d ...",
                apkeditor_build_command="java -jar apke.jar b ...",
                apkeditor_decode_rc=0, apkeditor_build_rc=0,
            )

        with patch("lite_apk_patches._get_or_decompile", side_effect=fake_get_or_decompile), \
             patch("lite_apk_patches._rebuild_and_restore", side_effect=fake_apktool_fail), \
             patch("lite_apk_patches._rebuild_miuisystemui_smali_only", side_effect=fake_smali_fail), \
             patch("lite_apk_patches._rebuild_miuisystemui_with_apkeditor", side_effect=fake_ae_ok):
            apply_miuisystemui_volte_cn_patch(tmp_path, report, rom_os="OS3", rom_region="CN")

        assert "apkeditor" in called, "APKEditor fallback was not attempted"

    def test_2_apkeditor_fallback_attempted_when_smali_standalone_fails(self, tmp_path):
        """Test 2: APKEditor fallback is attempted when smali standalone compile fails."""
        apk = _make_sysui_apk(tmp_path)
        unpacked = _make_unpacked_dir(tmp_path)
        report: list = []
        ae_attempted = []

        def fake_get_or_decompile(*a, **kw):
            return unpacked, True, apk, [str(apk)]

        def fake_smali_fail(*a, **kw):
            return _fake_fail(
                error="smali compile failed for changed folder classes.dex: rc=1\n"
                      "java.lang.IndexOutOfBoundsException: toIndex = 128",
            )

        def fake_ae(*a, **kw):
            ae_attempted.append(True)
            return _fake_ok(apk)

        with patch("lite_apk_patches._get_or_decompile", side_effect=fake_get_or_decompile), \
             patch("lite_apk_patches._rebuild_and_restore", return_value=_fake_fail()), \
             patch("lite_apk_patches._rebuild_miuisystemui_smali_only", side_effect=fake_smali_fail), \
             patch("lite_apk_patches._rebuild_miuisystemui_with_apkeditor", side_effect=fake_ae):
            apply_miuisystemui_volte_cn_patch(tmp_path, report, rom_os="OS3", rom_region="CN")

        assert ae_attempted, "APKEditor fallback was not attempted after smali-zip failure"

    def test_3_apkeditor_success_restores_in_place(self, tmp_path):
        """Test 3: APKEditor fallback success → MiuiSystemUI.apk restores in place."""
        apk = _make_sysui_apk(tmp_path)
        unpacked = _make_unpacked_dir(tmp_path)
        report: list = []

        def fake_get_or_decompile(*a, **kw):
            return unpacked, True, apk, [str(apk)]

        def fake_ae_ok(*a, **kw):
            return _fake_ok(apk)

        with patch("lite_apk_patches._get_or_decompile", side_effect=fake_get_or_decompile), \
             patch("lite_apk_patches._rebuild_and_restore", return_value=_fake_fail()), \
             patch("lite_apk_patches._rebuild_miuisystemui_smali_only", return_value=_fake_fail()), \
             patch("lite_apk_patches._rebuild_miuisystemui_with_apkeditor", side_effect=fake_ae_ok):
            apply_miuisystemui_volte_cn_patch(tmp_path, report, rom_os="OS3", rom_region="CN")

        apk_entries = [r for r in report if r.get("target_class") == "MiuiSystemUI"]
        assert any(r.get("restore_in_place") is True for r in apk_entries), \
            f"Expected restore_in_place=True from APKEditor success. Entries: {apk_entries}"
        assert any(r.get("status") == "changed" for r in apk_entries)

    def test_4_all_strategies_fail_original_apk_untouched(self, tmp_path):
        """Test 4: When all strategies fail, original APK is not modified."""
        apk = _make_sysui_apk(tmp_path)
        original_mtime = apk.stat().st_mtime
        original_size  = apk.stat().st_size
        unpacked = _make_unpacked_dir(tmp_path)
        report: list = []

        def fake_get_or_decompile(*a, **kw):
            return unpacked, True, apk, [str(apk)]

        with patch("lite_apk_patches._get_or_decompile", side_effect=fake_get_or_decompile), \
             patch("lite_apk_patches._rebuild_and_restore", return_value=_fake_fail()), \
             patch("lite_apk_patches._rebuild_miuisystemui_smali_only", return_value=_fake_fail()), \
             patch("lite_apk_patches._rebuild_miuisystemui_with_apkeditor", return_value=_fake_fail(
                 error="APKEditor build failed",
                 apkeditor_decode_rc=0, apkeditor_build_rc=1,
                 apkeditor_decode_command="...", apkeditor_build_command="...",
             )):
            apply_miuisystemui_volte_cn_patch(tmp_path, report, rom_os="OS3", rom_region="CN")

        assert apk.stat().st_mtime == original_mtime, "Original APK mtime changed"
        assert apk.stat().st_size == original_size, "Original APK size changed"

    def test_5_report_lists_all_rebuild_strategies(self, tmp_path):
        """Test 5: Report entry includes rebuild_strategies for every strategy attempted."""
        apk = _make_sysui_apk(tmp_path)
        unpacked = _make_unpacked_dir(tmp_path)
        report: list = []

        def fake_get_or_decompile(*a, **kw):
            return unpacked, True, apk, [str(apk)]

        with patch("lite_apk_patches._get_or_decompile", side_effect=fake_get_or_decompile), \
             patch("lite_apk_patches._rebuild_and_restore", return_value=_fake_fail()), \
             patch("lite_apk_patches._rebuild_miuisystemui_smali_only", return_value=_fake_fail()), \
             patch("lite_apk_patches._rebuild_miuisystemui_with_apkeditor", return_value=_fake_fail(
                 apkeditor_decode_rc=0, apkeditor_build_rc=1,
                 apkeditor_decode_command="java -jar apke.jar d ...",
                 apkeditor_build_command="java -jar apke.jar b ...",
             )):
            apply_miuisystemui_volte_cn_patch(tmp_path, report, rom_os="OS3", rom_region="CN")

        apk_entries = [r for r in report if r.get("target_class") == "MiuiSystemUI"]
        assert apk_entries, "No MiuiSystemUI APK-level entry found"
        entry = apk_entries[0]
        strategies = entry.get("rebuild_strategies", [])
        strategy_names = {s["name"] for s in strategies}
        assert "apktool" in strategy_names, f"apktool not in strategies: {strategy_names}"
        assert "smali_zip" in strategy_names, f"smali_zip not in strategies: {strategy_names}"
        assert "apkeditor" in strategy_names, f"apkeditor not in strategies: {strategy_names}"
        for s in strategies:
            assert "name" in s
            assert "attempted" in s
            assert "success" in s

    def test_6_failed_optional_only_when_all_strategies_fail(self, tmp_path):
        """Test 6: FAILED_OPTIONAL status only if all three strategies fail."""
        apk = _make_sysui_apk(tmp_path)
        unpacked = _make_unpacked_dir(tmp_path)

        # Scenario A: all fail → FAILED_OPTIONAL
        report_all_fail: list = []

        def fake_get_or_decompile(*a, **kw):
            return unpacked, True, apk, [str(apk)]

        with patch("lite_apk_patches._get_or_decompile", side_effect=fake_get_or_decompile), \
             patch("lite_apk_patches._rebuild_and_restore", return_value=_fake_fail()), \
             patch("lite_apk_patches._rebuild_miuisystemui_smali_only", return_value=_fake_fail()), \
             patch("lite_apk_patches._rebuild_miuisystemui_with_apkeditor", return_value=_fake_fail(
                 apkeditor_decode_rc=None, apkeditor_build_rc=None,
                 apkeditor_decode_command=None, apkeditor_build_command=None,
             )):
            apply_miuisystemui_volte_cn_patch(tmp_path, report_all_fail, rom_os="OS3", rom_region="CN")

        apk_entries = [r for r in report_all_fail if r.get("target_class") == "MiuiSystemUI"]
        assert any(r["status"] == "failed_optional" for r in apk_entries), \
            "Expected failed_optional when all strategies fail"

        # Scenario B: APKEditor succeeds → CHANGED, not failed
        unpacked2 = tmp_path / "msui_unpacked_b"
        (unpacked2 / "smali_classes").mkdir(parents=True)
        report_ae_ok: list = []

        def fake_get_or_decompile2(*a, **kw):
            return unpacked2, True, apk, [str(apk)]

        with patch("lite_apk_patches._get_or_decompile", side_effect=fake_get_or_decompile2), \
             patch("lite_apk_patches._rebuild_and_restore", return_value=_fake_fail()), \
             patch("lite_apk_patches._rebuild_miuisystemui_smali_only", return_value=_fake_fail()), \
             patch("lite_apk_patches._rebuild_miuisystemui_with_apkeditor",
                   return_value=_fake_ok(apk)):
            apply_miuisystemui_volte_cn_patch(tmp_path, report_ae_ok, rom_os="OS3", rom_region="CN")

        apk_entries_ok = [r for r in report_ae_ok if r.get("target_class") == "MiuiSystemUI"]
        assert any(r["status"] == "changed" for r in apk_entries_ok), \
            "Expected changed when APKEditor succeeds"
        assert not any(r["status"] == "failed_optional" for r in apk_entries_ok), \
            "Must not be failed_optional when APKEditor succeeds"


# ══════════════════════════════════════════════════════════════════════════════
# Tests 7-9: Full report timing — final_zip and pixeldrain_url
# ══════════════════════════════════════════════════════════════════════════════

class TestFullReportTiming:

    def _rdir(self, tmp_path: Path) -> Path:
        d = tmp_path / "bin" / "output" / "reports"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def test_7_final_zip_shown_when_summary_exists(self, tmp_path):
        """Test 7: full report shows final_zip_name when final_zip_summary.json exists."""
        rdir = self._rdir(tmp_path)
        (rdir / "final_zip_summary.json").write_text(
            json.dumps({"final_zip_name": "DeadZone_Plus_zircon_OS3.0.303.0.zip", "status": "success"}),
            encoding="utf-8",
        )

        full = build_full_report(rdir)
        assert full["final_zip"] == "DeadZone_Plus_zircon_OS3.0.303.0.zip", \
            f"Expected final_zip name, got: {full['final_zip']!r}"

        write_full_report(rdir, dz_style="Plus")
        txt = (rdir / "deadzone_full_mod_report.txt").read_text(encoding="utf-8")
        assert "DeadZone_Plus_zircon_OS3.0.303.0.zip" in txt, \
            "Final ZIP name not found in TXT report"
        assert "(not built yet)" not in txt, \
            "Report incorrectly says '(not built yet)' when summary exists"

    def test_8_pixeldrain_url_shown_when_report_exists(self, tmp_path):
        """Test 8: full report shows PixelDrain URL when pixeldrain_upload_report.json exists."""
        rdir = self._rdir(tmp_path)
        (rdir / "pixeldrain_upload_report.json").write_text(
            json.dumps({"url": "https://pixeldrain.com/u/ABCD1234", "status": "uploaded"}),
            encoding="utf-8",
        )

        full = build_full_report(rdir)
        assert full.get("pixeldrain_url") == "https://pixeldrain.com/u/ABCD1234", \
            f"Expected pixeldrain_url in report, got: {full.get('pixeldrain_url')!r}"

        write_full_report(rdir, dz_style="Plus")
        txt = (rdir / "deadzone_full_mod_report.txt").read_text(encoding="utf-8")
        assert "https://pixeldrain.com/u/ABCD1234" in txt, \
            "PixelDrain URL not found in TXT report"

    def test_9_workflow_yaml_full_report_after_package_before_upload(self):
        """Test 9: both workflow YAMLs call full_mod_report after package_rom and before upload-artifact."""
        for yml_name in ("mezo_mtk.yml", "mezo_snapdragon.yml"):
            yml = PROJECT_ROOT / ".github" / "workflows" / yml_name
            if not yml.is_file():
                pytest.skip(f"{yml_name} not found")
            content = yml.read_text(encoding="utf-8")

            pkg_idx  = content.find("package_rom.py")
            rep_idx  = content.find("deadzone_full_mod_report.py")
            art_idx  = content.find("deadzone-build-reports-")

            assert pkg_idx != -1,  f"{yml_name}: package_rom.py not found"
            assert rep_idx != -1,  f"{yml_name}: deadzone_full_mod_report.py not found"
            assert art_idx != -1,  f"{yml_name}: upload-artifact for build-reports not found"

            assert rep_idx > pkg_idx, \
                f"{yml_name}: full_mod_report must appear after package_rom.py"
            assert rep_idx < art_idx, \
                f"{yml_name}: full_mod_report must appear before upload-artifact"

    def test_final_zip_empty_when_summary_missing(self, tmp_path):
        """Edge case: final_zip is empty string when final_zip_summary.json does not exist."""
        rdir = self._rdir(tmp_path)
        full = build_full_report(rdir)
        assert full["final_zip"] == "", \
            "final_zip should be empty when summary file is missing"

        write_full_report(rdir)
        txt = (rdir / "deadzone_full_mod_report.txt").read_text(encoding="utf-8")
        assert "(not built yet)" in txt


# ══════════════════════════════════════════════════════════════════════════════
# Tests 10-13: Restore totals
# ══════════════════════════════════════════════════════════════════════════════

class TestRestoreTotals:

    def _rdir(self, tmp_path: Path) -> Path:
        d = tmp_path / "bin" / "output" / "reports"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _write_report(self, rdir: Path, name: str, data: dict) -> None:
        (rdir / name).write_text(json.dumps(data), encoding="utf-8")

    def test_10_strings_xml_entries_not_restore_failures(self, tmp_path):
        """Test 10: Individual strings.xml patch entries do NOT count as restore failures."""
        rdir = self._rdir(tmp_path)
        # Simulate lite_apk_patches_report with individual string entries (no original_path)
        self._write_report(rdir, "lite_apk_patches_report.json", {
            "patches": {
                "provision_mezo_strings": {
                    "results": [
                        # Individual string file entry — no original_path (sub-entry)
                        {
                            "patch_name": "provision_mezo_strings",
                            "target_file": "/tmp/provision_unpacked/res/values/strings.xml",
                            "found": True,
                            "status": "changed",
                            "detail": "Updated: ['miui14_start_up_slogan']",
                            "restore_in_place": False,  # string entries are never "restored in place"
                            "original_path": None,
                            "restored_path": None,
                        },
                        # APK-level restore entry
                        {
                            "patch_name": "provision_mezo_strings",
                            "target_file": "/rom/system_ext/priv-app/Provision/Provision.apk",
                            "found": True,
                            "status": "changed",
                            "detail": "Provision.apk patched and restored in place",
                            "restore_in_place": True,
                            "original_path": "/rom/system_ext/priv-app/Provision/Provision.apk",
                            "restored_path": "/rom/system_ext/priv-app/Provision/Provision.apk",
                        },
                    ]
                }
            }
        })

        full = build_full_report(rdir)
        t = full["totals"]
        assert t["restore_success"] >= 1, "Provision.apk restore should count as success"
        assert t["restore_failed"] == 0, \
            f"strings.xml entry must not count as restore failure, got restore_failed={t['restore_failed']}"

    def test_11_smali_class_entries_not_restore_failures(self, tmp_path):
        """Test 11: Individual smali class entries do NOT count as restore failures."""
        rdir = self._rdir(tmp_path)
        # Simulate MiuiSystemUI individual class entries (no original_path) + APK entry
        results = []
        # 4 individual class entries — changed, no original_path
        for cls in ("MiuiOperatorCustomizedPolicy", "MiuiCarrierTextController",
                    "MiuiCellularIconVM$special$$inlined$combine$1$3",
                    "MiuiMobileIconBinder$bind$1$1$10"):
            results.append({
                "patch_name": "miuisystemui_volte_cn",
                "target_class": cls,
                "target_file": f"/tmp/sysui_unpacked/smali_classes/{cls}.smali",
                "found": True,
                "status": "changed",
                "restore_in_place": False,
                "original_path": None,
                "restored_path": None,
            })
        # 1 APK-level entry — changed + restored
        results.append({
            "patch_name": "miuisystemui_volte_cn",
            "target_class": "MiuiSystemUI",
            "target_file": "/rom/system_ext/priv-app/MiuiSystemUI/MiuiSystemUI.apk",
            "found": True,
            "status": "changed",
            "restore_in_place": True,
            "original_path": "/rom/system_ext/priv-app/MiuiSystemUI/MiuiSystemUI.apk",
            "restored_path": "/rom/system_ext/priv-app/MiuiSystemUI/MiuiSystemUI.apk",
        })

        self._write_report(rdir, "lite_apk_patches_report.json", {
            "patches": {"miuisystemui_volte_cn": {"results": results}}
        })

        full = build_full_report(rdir)
        t = full["totals"]
        assert t["restore_failed"] == 0, \
            f"Class entries must not inflate restore_failed; got {t['restore_failed']}"
        assert t["restore_success"] == 1, \
            f"Only MiuiSystemUI APK should count; got restore_success={t['restore_success']}"
        assert t.get("restore_not_applicable", 0) >= 4, \
            "4 class entries should be restore_not_applicable"

    def test_12_apk_jar_entries_count_restore_correctly(self, tmp_path):
        """Test 12: APK/JAR entries with original_path count restore success/failure."""
        rdir = self._rdir(tmp_path)
        self._write_report(rdir, "lite_apk_patches_report.json", {
            "patches": {
                "provision_mezo_strings": {
                    "results": [
                        {
                            "patch_name": "provision_mezo_strings",
                            "status": "changed",
                            "restore_in_place": True,
                            "original_path": "/rom/Provision.apk",
                            "restored_path": "/rom/Provision.apk",
                        }
                    ]
                },
                "powerkeeper_cn_global": {
                    "results": [
                        {
                            "patch_name": "powerkeeper_cn_global",
                            "status": "changed",
                            "restore_in_place": True,
                            "original_path": "/rom/PowerKeeper.apk",
                            "restored_path": "/rom/PowerKeeper.apk",
                        }
                    ]
                },
                "miuisystemui_volte_cn": {
                    "results": [
                        {
                            "patch_name": "miuisystemui_volte_cn",
                            "target_class": "MiuiSystemUI",
                            "status": "failed_optional",
                            "restore_in_place": False,
                            "original_path": "/rom/MiuiSystemUI.apk",
                        }
                    ]
                },
            }
        })

        full = build_full_report(rdir)
        t = full["totals"]
        assert t["restore_success"] == 2, \
            f"Provision + PowerKeeper should be 2 restore_success, got {t['restore_success']}"
        assert t["restore_failed"] == 1, \
            f"MiuiSystemUI failed_optional with original_path should be 1 restore_failed, got {t['restore_failed']}"

    def test_13_restore_totals_non_misleading(self, tmp_path):
        """Test 13: With mixed entries, restore totals reflect only real restores."""
        rdir = self._rdir(tmp_path)
        # Mix: 3 class entries (no original_path) + 2 APK entries (with original_path)
        results = []
        for i in range(3):
            results.append({
                "status": "changed", "restore_in_place": False,
                "original_path": None, "restored_path": None,
            })
        results.append({
            "status": "changed", "restore_in_place": True,
            "original_path": "/rom/framework.jar", "restored_path": "/rom/framework.jar",
        })
        results.append({
            "status": "changed", "restore_in_place": True,
            "original_path": "/rom/services.jar", "restored_path": "/rom/services.jar",
        })

        self._write_report(rdir, "deadzone_patch_report.json", {
            "patches": {"fw_patch": {"results": results}}
        })

        full = build_full_report(rdir)
        t = full["totals"]
        # Only 2 JAR entries are restore_applicable
        assert t["restore_success"] == 2, \
            f"Only JAR entries should count; got restore_success={t['restore_success']}"
        assert t["restore_failed"] == 0
        assert t.get("restore_not_applicable", 0) == 3

    def test_is_restore_applicable_helper(self):
        """_is_restore_applicable returns True only for entries with original_path or restored_path."""
        assert _is_restore_applicable({"original_path": "/rom/Provision.apk"}) is True
        assert _is_restore_applicable({"restored_path": "/rom/Provision.apk"}) is True
        assert _is_restore_applicable({"original_path": None, "restored_path": None}) is False
        assert _is_restore_applicable({}) is False
        assert _is_restore_applicable({"status": "changed", "restore_in_place": False}) is False


# ══════════════════════════════════════════════════════════════════════════════
# Test 14: Regression — _rebuild_miuisystemui_with_apkeditor is importable
# ══════════════════════════════════════════════════════════════════════════════

class TestRegressionGuard:

    def test_14_apkeditor_function_importable(self):
        """Test 14: _rebuild_miuisystemui_with_apkeditor is importable and callable."""
        assert callable(_rebuild_miuisystemui_with_apkeditor)

    def test_apkeditor_not_found_returns_graceful_failure(self, tmp_path):
        """_rebuild_miuisystemui_with_apkeditor returns ok=False if APKEditor not found."""
        apk = _make_sysui_apk(tmp_path)
        with patch("lite_apk_patches._find_apkeditor_jar", return_value=None):
            result = _rebuild_miuisystemui_with_apkeditor(apk, "MiuiSystemUI.apk")
        assert result["ok"] is False
        assert result["restore_in_place"] is False
        assert "APKEditor" in result["error"]

    def test_apkeditor_decode_failure_returns_diagnostics(self, tmp_path):
        """APKEditor decode failure returns rc and error."""
        apk = _make_sysui_apk(tmp_path)
        fake_jar = tmp_path / "apke.jar"
        fake_jar.write_bytes(b"PK")

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            m.returncode = 1
            m.stdout = ""
            m.stderr = "APKEditor decode error"
            return m

        with patch("lite_apk_patches._find_apkeditor_jar", return_value=fake_jar), \
             patch("lite_apk_patches.subprocess.run", side_effect=fake_run):
            result = _rebuild_miuisystemui_with_apkeditor(apk, "MiuiSystemUI.apk")

        assert result["ok"] is False
        assert result.get("apkeditor_decode_rc") == 1
        assert result.get("apkeditor_decode_command") is not None

    def test_apkeditor_build_failure_returns_diagnostics(self, tmp_path):
        """APKEditor build failure (after decode ok) returns build rc and error."""
        apk = _make_sysui_apk(tmp_path)
        fake_jar = tmp_path / "apke.jar"
        fake_jar.write_bytes(b"PK")
        call_count = [0]

        def fake_run(cmd, **kwargs):
            m = MagicMock()
            call_count[0] += 1
            if call_count[0] == 1:  # decode
                m.returncode = 0
                m.stdout = m.stderr = ""
            else:  # build
                m.returncode = 1
                m.stdout = ""
                m.stderr = "APKEditor build failed"
            return m

        with patch("lite_apk_patches._find_apkeditor_jar", return_value=fake_jar), \
             patch("lite_apk_patches.subprocess.run", side_effect=fake_run):
            result = _rebuild_miuisystemui_with_apkeditor(apk, "MiuiSystemUI.apk")

        assert result["ok"] is False
        assert result.get("apkeditor_build_rc") == 1
        assert result.get("apkeditor_build_command") is not None

    def test_lite_apk_patches_compiles(self):
        """lite_apk_patches.py has no syntax errors."""
        import py_compile
        py_compile.compile(str(SCRIPTS_DIR / "lite_apk_patches.py"), doraise=True)

    def test_deadzone_full_mod_report_compiles(self):
        """deadzone_full_mod_report.py has no syntax errors."""
        import py_compile
        py_compile.compile(str(SCRIPTS_DIR / "deadzone_full_mod_report.py"), doraise=True)
