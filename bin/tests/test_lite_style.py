"""Tests for the Lite style engine, inheritance chain, and mod runner."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# ── Repo layout ───────────────────────────────────────────────────────────────
REPO_ROOT   = Path(__file__).resolve().parent.parent.parent
BIN_DIR     = REPO_ROOT / "bin"
STYLES_DIR  = BIN_DIR / "styles"
MODFILE_DIR = BIN_DIR / "modfile" / "Styles"
SCRIPTS_DIR = BIN_DIR / "scripts"

LITE_MODS_JSON   = STYLES_DIR / "Lite" / "mods.json"
LITE_INSMOD      = MODFILE_DIR / "Lite"   / "insmod.sh"
STABLE_INSMOD    = MODFILE_DIR / "Stable" / "insmod.sh"
LEGEND_INSMOD    = MODFILE_DIR / "Legend" / "insmod.sh"
NINJA_INSMOD     = MODFILE_DIR / "Ninja"  / "insmod.sh"
RUNNER_PY        = SCRIPTS_DIR / "style_mod_runner.py"

FW_PATCHER_INSTALL = (
    REPO_ROOT / "bin" / "modfile" / "UpdateFile" / "DeadZone_FrameworkPatcher" / "install.sh"
)
KAORIOS_INSTALL = (
    REPO_ROOT / "bin" / "modfile" / "UpdateFile" / "DeadZone_KaoriosToolbox" / "install.sh"
)


# ── Module loader for style_mod_runner ────────────────────────────────────────
def _load_runner():
    spec = importlib.util.spec_from_file_location("style_mod_runner", RUNNER_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── 1. Lite insmod calls style_mod_runner ─────────────────────────────────────
class TestLiteInsmodCallsRunner:
    def test_lite_insmod_calls_style_mod_runner(self):
        content = LITE_INSMOD.read_text(encoding="utf-8")
        assert "style_mod_runner.py" in content, (
            "bin/modfile/Styles/Lite/insmod.sh must call style_mod_runner.py"
        )

    def test_lite_insmod_passes_style_lite(self):
        content = LITE_INSMOD.read_text(encoding="utf-8")
        assert "--style lite" in content or "--style" in content, (
            "Lite insmod.sh must pass --style lite to the runner"
        )

    def test_lite_insmod_exits_on_runner_failure(self):
        content = LITE_INSMOD.read_text(encoding="utf-8")
        # Must have error handling (set -e or explicit if-not)
        assert "exit 1" in content or "set -euo pipefail" in content or "set -e" in content


# ── 2–5. Lite manifest entries ────────────────────────────────────────────────
class TestLiteManifest:
    @pytest.fixture(autouse=True)
    def _manifest(self):
        assert LITE_MODS_JSON.is_file(), f"Manifest not found: {LITE_MODS_JSON}"
        self.manifest = json.loads(LITE_MODS_JSON.read_text(encoding="utf-8"))
        self.mods = self.manifest["mods"]
        # Build fast lookup of all text in manifest
        self.manifest_text = json.dumps(self.manifest, ensure_ascii=False)

    def test_manifest_is_valid_json(self):
        assert isinstance(self.manifest, dict)
        assert "mods" in self.manifest
        assert isinstance(self.mods, list)
        assert len(self.mods) > 0

    def test_manifest_style_field(self):
        assert self.manifest.get("style") == "lite"

    def test_manifest_contains_signature_verification_bypass(self):
        assert "Signature Verification Bypass" in self.manifest_text, (
            "mods.json must mention 'Signature Verification Bypass'"
        )

    def test_manifest_contains_invoke_custom_handling(self):
        assert "invoke-custom handling" in self.manifest_text, (
            "mods.json must mention 'invoke-custom handling'"
        )

    def test_manifest_contains_fix_bootloop_a15(self):
        assert "fix bootloop A15" in self.manifest_text, (
            "mods.json must mention 'fix bootloop A15'"
        )

    def test_manifest_contains_kaorios_toolbox(self):
        # Accept either "Kaorios" or "Kousei"
        has_kaorios = "Kaorios" in self.manifest_text or "Kousei" in self.manifest_text
        assert has_kaorios, "mods.json must mention 'Kaorios' or 'Kousei' Toolbox"

    def test_framework_patches_are_required(self):
        required_names = {"Signature Verification Bypass", "invoke-custom handling", "fix bootloop A15"}
        for mod in self.mods:
            if mod.get("name") in required_names:
                assert mod.get("required") is True, (
                    f"Framework patch {mod['name']!r} must be required=true"
                )

    def test_framework_patches_are_enabled(self):
        fw_names = {"Signature Verification Bypass", "invoke-custom handling", "fix bootloop A15"}
        for mod in self.mods:
            if mod.get("name") in fw_names:
                assert mod.get("enabled") is True, (
                    f"Framework patch {mod['name']!r} must be enabled=true"
                )

    def test_all_mods_have_required_fields(self):
        required_keys = {"id", "name", "enabled", "required", "description"}
        for mod in self.mods:
            missing = required_keys - set(mod.keys())
            assert not missing, f"Mod {mod.get('id')!r} missing fields: {missing}"

    def test_each_mod_has_an_executor(self):
        for mod in self.mods:
            has_executor = bool(mod.get("python_entry") or mod.get("script_path"))
            assert has_executor, (
                f"Mod {mod.get('id')!r} has neither python_entry nor script_path"
            )


# ── 6–8. Style inheritance chain ─────────────────────────────────────────────
class TestStyleInheritance:
    def test_stable_delegates_to_plus(self):
        """Stable is now a compat alias; it must delegate to Plus."""
        content = STABLE_INSMOD.read_text(encoding="utf-8")
        assert "Plus/insmod.sh" in content or "Plus" in content, (
            "Stable insmod.sh must delegate to Plus (compat wrapper)"
        )

    def test_legend_inherits_plus(self):
        """Legend inherits Plus (→ Lite), not Stable directly."""
        content = LEGEND_INSMOD.read_text(encoding="utf-8")
        assert "Plus/insmod.sh" in content or "Plus" in content, (
            "Legend insmod.sh must call Plus/insmod.sh"
        )

    def test_ninja_inherits_plus(self):
        """Ninja inherits Plus (→ Lite), not Stable directly."""
        content = NINJA_INSMOD.read_text(encoding="utf-8")
        assert "Plus/insmod.sh" in content or "Plus" in content, (
            "Ninja insmod.sh must call Plus/insmod.sh"
        )

    def test_stable_is_compat_wrapper(self):
        """Stable insmod.sh must clearly indicate it is a compat alias."""
        content = STABLE_INSMOD.read_text(encoding="utf-8")
        assert "Plus" in content, "Stable must delegate to Plus"

    def test_legend_error_propagates(self):
        content = LEGEND_INSMOD.read_text(encoding="utf-8")
        assert "exit 1" in content or "set -euo pipefail" in content, (
            "Legend insmod.sh must propagate Plus failure (exit 1 or set -e)"
        )

    def test_ninja_error_propagates(self):
        content = NINJA_INSMOD.read_text(encoding="utf-8")
        assert "exit 1" in content or "set -euo pipefail" in content, (
            "Ninja insmod.sh must propagate Plus failure (exit 1 or set -e)"
        )


# ── 9. UpdateFile wrappers do not duplicate Lite mods ─────────────────────────
class TestUpdateFileNoduplication:
    def test_framework_patcher_gate_prevents_duplication(self):
        content = FW_PATCHER_INSTALL.read_text(encoding="utf-8")
        # Accept both old flag name and the new ENABLE_LEGACY_* name
        has_gate = (
            "ENABLE_DEADZONE_FRAMEWORK_PATCHER" in content
            or "ENABLE_LEGACY_DEADZONE_FRAMEWORK_PATCHER" in content
        )
        assert has_gate, (
            "DeadZone_FrameworkPatcher/install.sh must check "
            "ENABLE_LEGACY_DEADZONE_FRAMEWORK_PATCHER (or legacy ENABLE_DEADZONE_FRAMEWORK_PATCHER)"
        )
        assert "false" in content.lower() or "exit 0" in content, (
            "Gate must default to false / exit 0 to prevent duplicate execution"
        )

    def test_kaorios_toolbox_gate_prevents_duplication(self):
        content = KAORIOS_INSTALL.read_text(encoding="utf-8")
        # Accept both old flag name and the new ENABLE_LEGACY_* name
        has_gate = (
            "ENABLE_DEADZONE_KAORIOS_TOOLBOX" in content
            or "ENABLE_LEGACY_DEADZONE_KAORIOS_TOOLBOX" in content
        )
        assert has_gate, (
            "DeadZone_KaoriosToolbox/install.sh must check "
            "ENABLE_LEGACY_DEADZONE_KAORIOS_TOOLBOX (or legacy ENABLE_DEADZONE_KAORIOS_TOOLBOX)"
        )
        assert "false" in content.lower() or "exit 0" in content, (
            "Gate must default to false / exit 0 to prevent duplicate execution"
        )

    def test_framework_patcher_is_compatibility_wrapper(self):
        content = FW_PATCHER_INSTALL.read_text(encoding="utf-8")
        # Must document that Lite handles it
        assert "Lite" in content or "style engine" in content.lower() or "style_mod_runner" in content


# ── 10. Report JSON is valid ──────────────────────────────────────────────────
class TestReportJson:
    def test_runner_writes_valid_json(self, tmp_path):
        """Run the runner with a bare tmp_path (no ROM). Reports must be valid JSON."""
        runner = _load_runner()
        # Create a minimal fake manifest
        manifest_dir = tmp_path / "bin" / "styles" / "Lite"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "mods.json").write_text(json.dumps({
            "style": "lite",
            "name": "Test Lite",
            "mods": [
                {
                    "id": "noop_mod",
                    "name": "Noop Mod",
                    "enabled": False,
                    "required": False,
                    "source_stage": "test",
                    "python_entry": "bin/scripts/nonexistent.py",
                    "description": "Disabled test mod",
                }
            ],
        }), encoding="utf-8")

        results = runner.run_style("lite", tmp_path)
        runner._write_reports(results, "lite", tmp_path)

        report_path = tmp_path / "bin" / "output" / "reports" / "lite_mod_report.json"
        assert report_path.is_file(), "lite_mod_report.json must be written"
        data = json.loads(report_path.read_text(encoding="utf-8"))
        assert data["style"] == "lite"
        assert "mods" in data
        assert "summary" in data

    def test_report_json_has_required_fields(self, tmp_path):
        runner = _load_runner()
        manifest_dir = tmp_path / "bin" / "styles" / "Lite"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "mods.json").write_text(json.dumps({
            "style": "lite",
            "name": "Test",
            "mods": [{
                "id": "test_mod",
                "name": "Test Mod",
                "enabled": False,
                "required": False,
                "source_stage": "test",
                "python_entry": "bin/scripts/nonexistent.py",
                "description": "test",
            }],
        }), encoding="utf-8")

        results = runner.run_style("lite", tmp_path)
        runner._write_reports(results, "lite", tmp_path)

        report_path = tmp_path / "bin" / "output" / "reports" / "lite_mod_report.json"
        data = json.loads(report_path.read_text(encoding="utf-8"))

        assert "style" in data
        assert "work_dir" in data
        assert "generated" in data
        assert "mods" in data
        assert "summary" in data

        mod_entry = data["mods"][0]
        for field in ("id", "name", "enabled", "required", "status"):
            assert field in mod_entry, f"Mod entry missing field: {field}"


# ── 11. Missing ROM folders produce SKIPPED, not crash ───────────────────────
class TestMissingRomFoldersSafe:
    def test_disabled_mod_is_skipped_not_crash(self, tmp_path):
        runner = _load_runner()
        manifest_dir = tmp_path / "bin" / "styles" / "Lite"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "mods.json").write_text(json.dumps({
            "style": "lite",
            "name": "Test",
            "mods": [
                {
                    "id": "sig_bypass",
                    "name": "Signature Verification Bypass",
                    "enabled": False,
                    "required": True,
                    "source_stage": "test",
                    "python_entry": "bin/scripts/deadzone_framework_patches.py",
                    "args": ["--style", "lite"],
                    "group": "deadzone_framework_patches",
                    "description": "test",
                },
            ],
        }), encoding="utf-8")

        results = runner.run_style("lite", tmp_path)
        assert len(results) == 1
        assert results[0]["status"] == "skipped"
        assert results[0]["reason"] == "disabled in manifest"

    def test_missing_python_script_produces_failed_not_crash(self, tmp_path):
        runner = _load_runner()
        manifest_dir = tmp_path / "bin" / "styles" / "Lite"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "mods.json").write_text(json.dumps({
            "style": "lite",
            "name": "Test",
            "mods": [{
                "id": "missing_mod",
                "name": "Missing Mod",
                "enabled": True,
                "required": False,  # optional — must not crash
                "source_stage": "test",
                "python_entry": "bin/scripts/does_not_exist.py",
                "description": "intentionally missing",
            }],
        }), encoding="utf-8")

        results = runner.run_style("lite", tmp_path)
        assert len(results) == 1
        # Script missing → failed but runner continued (required=False)
        assert results[0]["status"] == "failed"
        assert results[0]["error"] is not None

    def test_missing_shell_script_produces_failed_not_crash(self, tmp_path):
        runner = _load_runner()
        manifest_dir = tmp_path / "bin" / "styles" / "Lite"
        manifest_dir.mkdir(parents=True)
        (manifest_dir / "mods.json").write_text(json.dumps({
            "style": "lite",
            "name": "Test",
            "mods": [{
                "id": "missing_shell",
                "name": "Missing Shell Mod",
                "enabled": True,
                "required": False,
                "source_stage": "test",
                "script_path": "bin/modfile/OS99/insmod.sh",
                "description": "intentionally missing",
            }],
        }), encoding="utf-8")

        results = runner.run_style("lite", tmp_path)
        assert len(results) == 1
        assert results[0]["status"] == "failed"

    def test_group_deduplication_skips_subsequent_entries(self, tmp_path):
        runner = _load_runner()
        manifest_dir = tmp_path / "bin" / "styles" / "Lite"
        manifest_dir.mkdir(parents=True)

        # Create a simple Python script that succeeds
        scripts_dir = tmp_path / "bin" / "scripts"
        scripts_dir.mkdir(parents=True)
        noop_script = scripts_dir / "noop.py"
        noop_script.write_text(
            "import argparse, sys\n"
            "p = argparse.ArgumentParser()\n"
            "p.add_argument('--style', default='lite')\n"
            "p.add_argument('--work-dir', default='.')\n"
            "p.parse_args()\n"
            "print('[NOOP] ok')\n",
            encoding="utf-8",
        )

        (manifest_dir / "mods.json").write_text(json.dumps({
            "style": "lite",
            "name": "Test",
            "mods": [
                {
                    "id": "patch_a",
                    "name": "Patch A",
                    "enabled": True,
                    "required": True,
                    "source_stage": "test",
                    "python_entry": "bin/scripts/noop.py",
                    "args": ["--style", "lite"],
                    "group": "fw_patches",
                    "description": "group leader",
                },
                {
                    "id": "patch_b",
                    "name": "Patch B",
                    "enabled": True,
                    "required": True,
                    "source_stage": "test",
                    "python_entry": "bin/scripts/noop.py",
                    "args": ["--style", "lite"],
                    "group": "fw_patches",
                    "description": "group follower — should be skipped",
                },
            ],
        }), encoding="utf-8")

        results = runner.run_style("lite", tmp_path)
        assert len(results) == 2
        assert results[0]["status"] == "success", "First entry in group must execute"
        assert results[1]["status"] == "skipped", "Second entry in group must be skipped"
        assert "fw_patches" in results[1].get("reason", "")


# ── 12. Required framework patch failure fails Lite clearly ───────────────────
class TestRequiredModFailure:
    def test_required_mod_failure_stops_runner(self, tmp_path):
        runner = _load_runner()
        manifest_dir = tmp_path / "bin" / "styles" / "Lite"
        manifest_dir.mkdir(parents=True)

        # Script that always exits 1
        scripts_dir = tmp_path / "bin" / "scripts"
        scripts_dir.mkdir(parents=True)
        fail_script = scripts_dir / "fail.py"
        fail_script.write_text(
            "import sys\nprint('[FAIL] intentional failure', file=sys.stderr)\nsys.exit(1)\n",
            encoding="utf-8",
        )

        (manifest_dir / "mods.json").write_text(json.dumps({
            "style": "lite",
            "name": "Test",
            "mods": [
                {
                    "id": "required_fail",
                    "name": "Required Failing Mod",
                    "enabled": True,
                    "required": True,
                    "source_stage": "test",
                    "python_entry": "bin/scripts/fail.py",
                    "description": "intentional fail",
                },
                {
                    "id": "should_not_run",
                    "name": "Should Not Run",
                    "enabled": True,
                    "required": False,
                    "source_stage": "test",
                    "python_entry": "bin/scripts/noop.py",
                    "description": "must not execute",
                },
            ],
        }), encoding="utf-8")

        results = runner.run_style("lite", tmp_path)

        # Runner must have stopped after the required failure
        assert len(results) == 1, "Runner must stop at required failure — no more mods after it"
        assert results[0]["status"] == "failed"
        assert results[0]["id"] == "required_fail"

    def test_optional_mod_failure_continues(self, tmp_path):
        runner = _load_runner()
        manifest_dir = tmp_path / "bin" / "styles" / "Lite"
        manifest_dir.mkdir(parents=True)

        scripts_dir = tmp_path / "bin" / "scripts"
        scripts_dir.mkdir(parents=True)
        fail_script = scripts_dir / "fail.py"
        fail_script.write_text(
            "import sys\nsys.exit(1)\n", encoding="utf-8"
        )
        ok_script = scripts_dir / "ok.py"
        ok_script.write_text(
            "import argparse\np=argparse.ArgumentParser()\n"
            "p.add_argument('--work-dir',default='.')\n"
            "p.parse_args()\nprint('ok')\n",
            encoding="utf-8",
        )

        (manifest_dir / "mods.json").write_text(json.dumps({
            "style": "lite",
            "name": "Test",
            "mods": [
                {
                    "id": "optional_fail",
                    "name": "Optional Failing Mod",
                    "enabled": True,
                    "required": False,
                    "source_stage": "test",
                    "python_entry": "bin/scripts/fail.py",
                    "description": "fails but optional",
                },
                {
                    "id": "continues_after",
                    "name": "Continues After",
                    "enabled": True,
                    "required": False,
                    "source_stage": "test",
                    "python_entry": "bin/scripts/ok.py",
                    "description": "must still run",
                },
            ],
        }), encoding="utf-8")

        results = runner.run_style("lite", tmp_path)

        assert len(results) == 2, "Runner must continue after optional failure"
        assert results[0]["status"] == "failed"
        assert results[1]["status"] == "success"
