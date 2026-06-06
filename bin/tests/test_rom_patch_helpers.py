"""Tests for rom_patch_helpers, kaorios --work-dir, POCO spoof nested paths,
RefreshRate 1hz.sh fix, lite_apk_patches FAILED_OPTIONAL, full mod report
searched_paths, and workflow upload-artifact steps.
"""
from __future__ import annotations

import json
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

# ── sys.path setup ─────────────────────────────────────────────────────────────
SCRIPTS_DIR  = Path(__file__).resolve().parent.parent / "scripts"
TESTS_DIR    = Path(__file__).resolve().parent
PROJECT_ROOT = TESTS_DIR.parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

import rom_patch_helpers as _rph
from poco_launcher_spoof import _candidate_partition_dirs
from deadzone_full_mod_report import (
    _summarize_results,
    _iter_all_results,
    _classify_status,
    build_full_report,
)
from lite_apk_patches import (
    apply_provision_strings,
    apply_powerkeeper_cn_global_patches,
)


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _mk_file(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ══════════════════════════════════════════════════════════════════════════════
# 1–3: resolve_partition_root — system, system_ext, vendor/odm
# ══════════════════════════════════════════════════════════════════════════════

class TestResolvePartitionRoot:
    def test_resolves_build_baserom_images_system(self, tmp_path):
        system_dir = tmp_path / "build" / "baserom" / "images" / "system"
        system_dir.mkdir(parents=True)
        result = _rph.resolve_partition_root(tmp_path, "system")
        assert result == system_dir

    def test_resolves_build_baserom_images_system_ext(self, tmp_path):
        sysext_dir = tmp_path / "build" / "baserom" / "images" / "system_ext"
        sysext_dir.mkdir(parents=True)
        result = _rph.resolve_partition_root(tmp_path, "system_ext")
        assert result == sysext_dir

    def test_resolves_build_baserom_images_vendor_and_odm(self, tmp_path):
        vendor_dir = tmp_path / "build" / "baserom" / "images" / "vendor"
        odm_dir    = tmp_path / "build" / "baserom" / "images" / "odm"
        vendor_dir.mkdir(parents=True)
        odm_dir.mkdir(parents=True)
        assert _rph.resolve_partition_root(tmp_path, "vendor") == vendor_dir
        assert _rph.resolve_partition_root(tmp_path, "odm")    == odm_dir

    def test_prefers_nested_over_direct(self, tmp_path):
        # nested: build/baserom/images/system/system should win over build/baserom/images/system
        # Creating nested implicitly creates direct (parent dir) too
        nested = tmp_path / "build" / "baserom" / "images" / "system" / "system"
        nested.mkdir(parents=True)
        result = _rph.resolve_partition_root(tmp_path, "system")
        # Candidates order: work/system/system, work/system, build/.../system/system, build/.../system
        # Nested (build/images/system/system) should be found before direct (build/images/system)
        assert result is not None
        assert result == nested


# ══════════════════════════════════════════════════════════════════════════════
# 4–7: APK finders
# ══════════════════════════════════════════════════════════════════════════════

class TestApkFinders:
    def test_provision_finder_direct(self, tmp_path):
        apk = tmp_path / "system_ext" / "priv-app" / "Provision" / "Provision.apk"
        _mk_file(apk)
        result = _rph.find_provision_apk(tmp_path)
        assert result["found"]
        assert result["found_path"] == str(apk)

    def test_provision_finder_under_build_baserom_images(self, tmp_path):
        apk = (tmp_path / "build" / "baserom" / "images"
               / "system_ext" / "priv-app" / "Provision" / "Provision.apk")
        _mk_file(apk)
        result = _rph.find_provision_apk(tmp_path)
        assert result["found"]
        assert result["found_path"] == str(apk)

    def test_miuisystemui_finder_under_build_baserom_images(self, tmp_path):
        apk = (tmp_path / "build" / "baserom" / "images"
               / "system_ext" / "priv-app" / "MiuiSystemUI" / "MiuiSystemUI.apk")
        _mk_file(apk)
        result = _rph.find_miui_systemui_apk(tmp_path)
        assert result["found"]
        assert result["found_path"] == str(apk)

    def test_powerkeeper_finder_under_build_baserom_images(self, tmp_path):
        apk = (tmp_path / "build" / "baserom" / "images"
               / "product" / "priv-app" / "PowerKeeper" / "PowerKeeper.apk")
        _mk_file(apk)
        result = _rph.find_powerkeeper_apk(tmp_path)
        assert result["found"]
        assert result["found_path"] == str(apk)

    def test_apk_not_found_returns_searched_paths(self, tmp_path):
        result = _rph.find_provision_apk(tmp_path)
        assert not result["found"]
        assert isinstance(result["searched_paths"], list)
        assert len(result["searched_paths"]) > 0


# ══════════════════════════════════════════════════════════════════════════════
# 8–9: Framework JAR finder
# ══════════════════════════════════════════════════════════════════════════════

class TestFrameworkTargetFinder:
    def test_finds_services_jar_direct(self, tmp_path):
        jar = tmp_path / "build" / "baserom" / "images" / "system" / "framework" / "services.jar"
        _mk_file(jar, "PK")
        result = _rph.find_framework_targets(tmp_path)
        assert result["services"]["found"]
        assert result["services"]["found_path"] == str(jar)

    def test_finds_services_jar_nested(self, tmp_path):
        jar = (tmp_path / "build" / "baserom" / "images"
               / "system" / "system" / "framework" / "services.jar")
        _mk_file(jar, "PK")
        result = _rph.find_framework_targets(tmp_path)
        assert result["services"]["found"]
        assert result["services"]["found_path"] == str(jar)


# ══════════════════════════════════════════════════════════════════════════════
# 10: Kaorios accepts --work-dir and finds build.prop in nested system/system
# ══════════════════════════════════════════════════════════════════════════════

class TestKaoriosBuildPropPaths:
    def test_finds_buildprop_in_system_system(self, tmp_path):
        bp = (tmp_path / "build" / "baserom" / "images"
              / "system" / "system" / "build.prop")
        _mk_file(bp, "ro.build.version.sdk=35\n")

        result = _rph.find_build_prop_files(tmp_path)
        found_paths = [r["found_path"] for r in result]
        assert any(str(bp) in p for p in found_paths), (
            f"Expected to find {bp} in {found_paths}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 11: POCO spoof finds vendor prop under build/baserom/images/vendor
# ══════════════════════════════════════════════════════════════════════════════

class TestPocoSpoofNestedPaths:
    def test_candidate_dirs_include_build_images_vendor(self, tmp_path):
        cands = _candidate_partition_dirs(tmp_path)
        labels = [label for label, _ in cands]
        paths  = [str(p) for _, p in cands]

        assert "vendor" in labels, "direct vendor missing"
        assert "vendor/vendor" in labels, "nested vendor/vendor missing"
        assert "odm" in labels, "direct odm missing"
        assert "odm/odm" in labels, "nested odm/odm missing"
        assert "odm/etc" in labels, "odm/etc missing"

    def test_build_images_vendor_included(self, tmp_path):
        cands = _candidate_partition_dirs(tmp_path)
        paths = [str(p) for _, p in cands]
        images_vendor = str(tmp_path / "build" / "baserom" / "images" / "vendor")
        assert any(images_vendor in p for p in paths), (
            f"build/baserom/images/vendor not in candidates: {paths[:6]}"
        )

    def test_no_duplicate_resolved_paths(self, tmp_path):
        cands = _candidate_partition_dirs(tmp_path)
        resolved = [p.resolve() for _, p in cands]
        assert len(resolved) == len(set(resolved)), "Duplicate resolved paths found"


# ══════════════════════════════════════════════════════════════════════════════
# 12: RefreshRate script handles multiple XML files safely
# ══════════════════════════════════════════════════════════════════════════════

class TestRefreshRateScript:
    def _script_path(self):
        return PROJECT_ROOT / "bin" / "package" / "RefreshRate" / "1hz.sh"

    def test_script_exists(self):
        assert self._script_path().exists()

    def test_no_unquoted_glob_with_f_flag(self):
        content = self._script_path().read_text(encoding="utf-8")
        assert "if [ -f $work_dir" not in content, (
            "Unquoted glob with -f still present on line 12"
        )
        assert "if [ -f" not in content, (
            "[ -f ... ] with glob not removed from script"
        )

    def test_uses_find_or_for_loop(self):
        content = self._script_path().read_text(encoding="utf-8")
        uses_find   = "find " in content
        uses_for    = "for " in content
        uses_mapfile = "mapfile" in content
        assert uses_find or uses_for or uses_mapfile, (
            "Script must use find, for-loop, or mapfile to handle multiple XML files"
        )

    def test_has_skipped_message_when_no_xml(self):
        content = self._script_path().read_text(encoding="utf-8")
        assert "SKIPPED" in content.upper(), (
            "Script should print SKIPPED when no XML files found"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 13: lite_apk_patches reports FAILED_OPTIONAL (not hiding optional failure)
# ══════════════════════════════════════════════════════════════════════════════

class TestLiteApkPatchesFailedOptional:
    def test_provision_not_found_reports_skipped_not_found(self, tmp_path):
        report: list = []
        apply_provision_strings(tmp_path, report)
        assert len(report) >= 1
        statuses = [r["status"] for r in report]
        assert "skipped_not_found" in statuses, (
            f"Expected skipped_not_found when APK is absent, got: {statuses}"
        )

    def test_provision_not_found_includes_searched_paths(self, tmp_path):
        report: list = []
        apply_provision_strings(tmp_path, report)
        entry = next((r for r in report if r["status"] == "skipped_not_found"), None)
        assert entry is not None
        assert isinstance(entry.get("searched_paths"), list)

    def test_powerkeeper_not_found_reports_skipped_not_found(self, tmp_path):
        report: list = []
        apply_powerkeeper_cn_global_patches(tmp_path, report)
        assert any(r["status"] == "skipped_not_found" for r in report), (
            f"Expected skipped_not_found, got: {[r['status'] for r in report]}"
        )


# ══════════════════════════════════════════════════════════════════════════════
# 14: deadzone_full_mod_report contains searched_paths for missing patches
# ══════════════════════════════════════════════════════════════════════════════

class TestFullModReportSearchedPaths:
    def _make_apk_report(self, tmp_path: Path) -> Path:
        report_data = {
            "generated": "2026-06-06T00:00:00+00:00",
            "work_dir": str(tmp_path),
            "patches": {
                "provision_mezo_strings": {
                    "enabled": True,
                    "total_scanned": 1,
                    "total_modified": 0,
                    "total_skipped": 0,
                    "total_skipped_not_found": 1,
                    "total_failed": 0,
                    "total_failed_optional": 0,
                    "results": [{
                        "patch_name": "provision_mezo_strings",
                        "target_file": "/not/found/Provision.apk",
                        "found": False,
                        "status": "skipped_not_found",
                        "detail": "Provision.apk not found",
                        "error": None,
                        "searched_paths": [
                            "/fake/system_ext/priv-app/Provision/Provision.apk",
                            "/fake/build/baserom/images/system_ext/priv-app/Provision/Provision.apk",
                        ],
                    }],
                },
            },
        }
        reports_dir = tmp_path / "bin" / "output" / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        f = reports_dir / "lite_apk_patches_mod_report.json"
        f.write_text(json.dumps(report_data), encoding="utf-8")
        return reports_dir

    def test_iter_all_results_from_patches_format(self, tmp_path):
        reports_dir = self._make_apk_report(tmp_path)
        report_data = json.loads(
            (reports_dir / "lite_apk_patches_mod_report.json").read_text(encoding="utf-8")
        )
        results = _iter_all_results(report_data)
        assert len(results) == 1
        assert results[0]["status"] == "skipped_not_found"

    def test_summarize_counts_skipped_not_found(self, tmp_path):
        reports_dir = self._make_apk_report(tmp_path)
        full = build_full_report(reports_dir)
        assert full["totals"]["skipped_not_found"] >= 1

    def test_classify_status_skipped_not_found(self):
        assert _classify_status("skipped_not_found") == "skipped"

    def test_classify_status_failed_optional(self):
        assert _classify_status("failed_optional") == "failed"

    def test_classify_status_applied_via_group(self):
        assert _classify_status("changed", "applied via group run") == "applied_via_group"


# ══════════════════════════════════════════════════════════════════════════════
# 15: Workflow YAML contains upload-artifact step
# ══════════════════════════════════════════════════════════════════════════════

class TestWorkflowUploadArtifact:
    def _wf_content(self, name: str) -> str:
        p = PROJECT_ROOT / ".github" / "workflows" / name
        return p.read_text(encoding="utf-8")

    def test_mtk_workflow_has_upload_artifact(self):
        content = self._wf_content("mezo_mtk.yml")
        assert "upload-artifact" in content, "mezo_mtk.yml missing upload-artifact step"
        assert "deadzone-build-reports" in content

    def test_snapdragon_workflow_has_upload_artifact(self):
        content = self._wf_content("mezo_snapdragon.yml")
        assert "upload-artifact" in content, "mezo_snapdragon.yml missing upload-artifact step"
        assert "deadzone-build-reports" in content

    def test_mtk_workflow_upload_always_runs(self):
        content = self._wf_content("mezo_mtk.yml")
        # The upload step should run even on failure
        assert "if: always()" in content

    def test_snapdragon_workflow_upload_always_runs(self):
        content = self._wf_content("mezo_snapdragon.yml")
        assert "if: always()" in content

    def test_reports_path_in_artifact(self):
        for name in ("mezo_mtk.yml", "mezo_snapdragon.yml"):
            content = self._wf_content(name)
            assert "bin/output/reports/**" in content, (
                f"{name}: bin/output/reports/** not in artifact paths"
            )
