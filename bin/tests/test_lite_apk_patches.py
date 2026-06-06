"""Tests for lite_apk_patches.py and miui-services patches in deadzone_framework_patches.py

Tests 1–3:   Provision.apk strings
Tests 4–12:  MiuiSystemUI VoLTE CN patch
Tests 13–19: miui-services CN/Global patches (in deadzone_framework_patches)
Tests 20–25: PowerKeeper patches
Tests 26–32: Integration (mods.json, inheritance chain, runner)
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

# ── Repo layout ───────────────────────────────────────────────────────────────
REPO_ROOT   = Path(__file__).resolve().parent.parent.parent
BIN_DIR     = REPO_ROOT / "bin"
SCRIPTS_DIR = BIN_DIR / "scripts"
STYLES_DIR  = BIN_DIR / "styles"
MODFILE_DIR = BIN_DIR / "modfile" / "Styles"

LITE_MODS_JSON = STYLES_DIR / "Lite" / "mods.json"
STABLE_INSMOD  = MODFILE_DIR / "Stable" / "insmod.sh"
LEGEND_INSMOD  = MODFILE_DIR / "Legend" / "insmod.sh"
NINJA_INSMOD   = MODFILE_DIR / "Ninja"  / "insmod.sh"


# ── Module loaders ────────────────────────────────────────────────────────────

def _load(name: str, filename: str):
    path = SCRIPTS_DIR / filename
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_apk = _load("lite_apk_patches", "lite_apk_patches.py")
_fw  = _load("deadzone_framework_patches", "deadzone_framework_patches.py")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _smali_dir(base: Path, subdir: str = "smali_classes") -> Path:
    d = base / subdir
    d.mkdir(parents=True, exist_ok=True)
    return d


def _make_smali(smali_dir: Path, filename: str, content: str) -> Path:
    smali_dir.mkdir(parents=True, exist_ok=True)
    p = smali_dir / filename
    p.write_text(content, encoding="utf-8")
    return p


# ══════════════════════════════════════════════════════════════════════════════
# Tests 1–3: Provision.apk strings
# ══════════════════════════════════════════════════════════════════════════════

_STRINGS_WITH_TARGETS = """\
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">Provision</string>
    <string name="miui14_global_start_up_slogan">Old global slogan</string>
    <string name="miui14_start_up_slogan">Old slogan</string>
    <string name="provision_complete_text">Old complete text</string>
</resources>
"""

_STRINGS_WITHOUT_TARGETS = """\
<?xml version="1.0" encoding="utf-8"?>
<resources>
    <string name="app_name">Provision</string>
    <string name="other_string">Some other string</string>
</resources>
"""


class TestProvisionStrings:
    """Tests 1–3"""

    def test_existing_strings_are_updated(self, tmp_path):
        """Test 1: Provision strings are updated when they already exist."""
        provision_dir = tmp_path / "provision_unpacked"
        xml = _write(
            provision_dir / "res" / "values" / "strings.xml",
            _STRINGS_WITH_TARGETS,
        )
        report = []
        _apk._patch_provision_strings_in_dir(provision_dir, report)

        content = xml.read_text(encoding="utf-8")
        assert "Lets rock with MEZO Development Project" in content
        assert "Ready to Rock with DeadZoneROM!" in content
        assert "Old global slogan" not in content
        assert "Old complete text" not in content
        assert any(e["status"] == "changed" for e in report)

    def test_missing_apk_returns_skipped(self, tmp_path):
        """Test 2: Missing Provision.apk returns skipped/skipped_not_found (no APK, no unpacked dir)."""
        report = []
        _apk.apply_provision_strings(tmp_path, report)
        assert len(report) >= 1
        _skipped_variants = {"skipped", "skipped_not_found"}
        assert all(e["status"] in _skipped_variants for e in report)

    def test_missing_string_names_added_to_values_strings_xml(self, tmp_path):
        """Test 3: String names missing everywhere are added to res/values/strings.xml."""
        provision_dir = tmp_path / "provision_unpacked"
        xml = _write(
            provision_dir / "res" / "values" / "strings.xml",
            _STRINGS_WITHOUT_TARGETS,
        )
        report = []
        _apk._patch_provision_strings_in_dir(provision_dir, report)

        content = xml.read_text(encoding="utf-8")
        assert "miui14_global_start_up_slogan" in content
        assert "miui14_start_up_slogan" in content
        assert "provision_complete_text" in content
        assert "Lets rock with MEZO Development Project" in content
        assert "Ready to Rock with DeadZoneROM!" in content

    def test_idempotent_provision_patch(self, tmp_path):
        """Running twice produces the same result and no duplicate strings."""
        provision_dir = tmp_path / "provision_unpacked"
        xml = _write(
            provision_dir / "res" / "values" / "strings.xml",
            _STRINGS_WITH_TARGETS,
        )
        report1 = []
        _apk._patch_provision_strings_in_dir(provision_dir, report1)
        report2 = []
        _apk._patch_provision_strings_in_dir(provision_dir, report2)

        content = xml.read_text(encoding="utf-8")
        assert content.count("Lets rock with MEZO Development Project") == 2  # 2 distinct strings
        assert content.count("Ready to Rock with DeadZoneROM!") == 1

    def test_multi_locale_strings_all_updated(self, tmp_path):
        """Strings in multiple values-xx dirs are all updated."""
        provision_dir = tmp_path / "provision_unpacked"
        for locale_dir in ("values", "values-en", "values-zh"):
            _write(
                provision_dir / "res" / locale_dir / "strings.xml",
                _STRINGS_WITH_TARGETS,
            )
        report = []
        _apk._patch_provision_strings_in_dir(provision_dir, report)

        for locale_dir in ("values", "values-en", "values-zh"):
            xml_path = provision_dir / "res" / locale_dir / "strings.xml"
            content = xml_path.read_text(encoding="utf-8")
            assert "Lets rock with MEZO Development Project" in content


# ══════════════════════════════════════════════════════════════════════════════
# Tests 4–12: MiuiSystemUI VoLTE CN patch
# ══════════════════════════════════════════════════════════════════════════════

_INTL_BUILD = "Lmiui/os/Build;->IS_INTERNATIONAL_BUILD:Z"

_SMALI_WITH_V_REGISTER = """\
.class public Lcom/android/systemui/MiuiOperatorCustomizedPolicy;
.super Ljava/lang/Object;
.method public doCheck()Z
    .registers 4
    sget-boolean v3, Lmiui/os/Build;->IS_INTERNATIONAL_BUILD:Z
    if-eqz v3, :cond_0
    return v3
    :cond_0
    const/4 v3, 0x0
    return v3
.end method
"""

_SMALI_WITH_P_REGISTER = """\
.class public Lcom/android/systemui/statusbar/policy/MiuiCarrierTextController;
.super Ljava/lang/Object;
.method public checkCarrier(Ljava/lang/String;)Z
    .registers 3
    sget-boolean p1, Lmiui/os/Build;->IS_INTERNATIONAL_BUILD:Z
    if-eqz p1, :cond_0
    return p1
    :cond_0
    const/4 p1, 0x0
    return p1
.end method
"""

_SMALI_NO_INTL_FLAG = """\
.class public Lcom/android/systemui/MiuiOperatorCustomizedPolicy;
.super Ljava/lang/Object;
.method public doCheck()Z
    .registers 2
    const/4 v0, 0x1
    return v0
.end method
"""


class TestMiuiSystemUIVolte:
    """Tests 4–12"""

    def _make_sysui_dir(self, tmp_path: Path, cls_name: str, smali_content: str) -> Path:
        sysui_dir = tmp_path / "miuisystemui_unpacked"
        sd = _smali_dir(sysui_dir)
        _make_smali(sd, f"{cls_name}.smali", smali_content)
        return sysui_dir

    def test_patch_adds_const4_v_register(self, tmp_path):
        """Test 4: Patch adds const/4 with same v-register."""
        sysui_dir = self._make_sysui_dir(
            tmp_path, "MiuiOperatorCustomizedPolicy", _SMALI_WITH_V_REGISTER
        )
        report = []
        _apk._patch_sysui_in_dir(sysui_dir, report)

        smali_path = sysui_dir / "smali_classes" / "MiuiOperatorCustomizedPolicy.smali"
        content = smali_path.read_text(encoding="utf-8")
        assert "const/4 v3, 0x1" in content
        assert any(e["status"] == "changed" for e in report)

    def test_patch_adds_const4_p_register(self, tmp_path):
        """Test 5: Patch adds const/4 with same p-register."""
        sysui_dir = self._make_sysui_dir(
            tmp_path, "MiuiCarrierTextController", _SMALI_WITH_P_REGISTER
        )
        report = []
        _apk._patch_sysui_in_dir(sysui_dir, report)

        smali_path = sysui_dir / "smali_classes" / "MiuiCarrierTextController.smali"
        content = smali_path.read_text(encoding="utf-8")
        assert "const/4 p1, 0x1" in content

    def test_does_not_hardcode_v0_when_register_differs(self, tmp_path):
        """Test 6: When register is v3, the patch injects const/4 v3 — not v0."""
        sysui_dir = self._make_sysui_dir(
            tmp_path, "MiuiOperatorCustomizedPolicy", _SMALI_WITH_V_REGISTER
        )
        report = []
        _apk._patch_sysui_in_dir(sysui_dir, report)

        smali_path = sysui_dir / "smali_classes" / "MiuiOperatorCustomizedPolicy.smali"
        content = smali_path.read_text(encoding="utf-8")
        lines_added = [l for l in content.splitlines()
                       if l.strip().startswith("const/4") and "0x1" in l]
        # Must use v3, not v0
        assert any("v3" in l for l in lines_added), "Should use v3 register"
        # Should NOT inject a v0, 0x1 line (v0 not in the sget-boolean)
        assert not any("v0, 0x1" in l for l in lines_added), "Must not hardcode v0"

    def test_missing_class_returns_skipped(self, tmp_path):
        """Test 7: Missing target class returns SKIPPED."""
        sysui_dir = tmp_path / "miuisystemui_unpacked"
        _smali_dir(sysui_dir)  # empty smali dir, no class files
        report = []
        _apk._patch_sysui_in_dir(sysui_dir, report)

        skipped = [e for e in report if e["status"] == "skipped"]
        assert len(skipped) >= 1

    def test_missing_intl_line_returns_skipped(self, tmp_path):
        """Test 8: Class exists but IS_INTERNATIONAL_BUILD not in it → SKIPPED."""
        sysui_dir = self._make_sysui_dir(
            tmp_path, "MiuiOperatorCustomizedPolicy", _SMALI_NO_INTL_FLAG
        )
        report = []
        _apk._patch_sysui_in_dir(sysui_dir, report)

        entry = next(
            (e for e in report if "MiuiOperatorCustomizedPolicy" in e.get("target_class", "")),
            None,
        )
        assert entry is not None
        assert entry["status"] == "skipped"

    def test_os1_returns_skipped(self, tmp_path):
        """Test 9: OS1 ROM → SKIPPED, patch not applied."""
        report = []
        _apk.apply_miuisystemui_volte_cn_patch(
            tmp_path, report, rom_os="OS1", rom_region="CN"
        )
        assert any(e["status"] == "skipped" for e in report)

    def test_non_cn_returns_skipped(self, tmp_path):
        """Test 10: Global ROM → SKIPPED."""
        report = []
        _apk.apply_miuisystemui_volte_cn_patch(
            tmp_path, report, rom_os="OS2", rom_region="Global"
        )
        assert any(e["status"] == "skipped" for e in report)

    def test_os2_cn_applies(self, tmp_path):
        """Test 11: OS2 CN ROM applies the patch."""
        sysui_dir = tmp_path / "miuisystemui_unpacked"
        sd = _smali_dir(sysui_dir)
        _make_smali(sd, "MiuiOperatorCustomizedPolicy.smali", _SMALI_WITH_V_REGISTER)

        report = []
        _apk.apply_miuisystemui_volte_cn_patch(
            tmp_path, report, rom_os="OS2", rom_region="CN"
        )
        assert any(e["status"] == "changed" for e in report)

    def test_os3_cn_applies(self, tmp_path):
        """Test 12: OS3 CN ROM applies the patch."""
        sysui_dir = tmp_path / "miuisystemui_unpacked"
        sd = _smali_dir(sysui_dir)
        _make_smali(sd, "MiuiOperatorCustomizedPolicy.smali", _SMALI_WITH_V_REGISTER)

        report = []
        _apk.apply_miuisystemui_volte_cn_patch(
            tmp_path, report, rom_os="OS3", rom_region="CN"
        )
        assert any(e["status"] == "changed" for e in report)

    def test_patch_idempotent(self, tmp_path):
        """Running twice does not insert duplicate const/4 lines."""
        sysui_dir = tmp_path / "miuisystemui_unpacked"
        sd = _smali_dir(sysui_dir)
        smali_path = _make_smali(sd, "MiuiOperatorCustomizedPolicy.smali", _SMALI_WITH_V_REGISTER)

        _apk._patch_sysui_in_dir(sysui_dir, [])
        _apk._patch_sysui_in_dir(sysui_dir, [])

        content = smali_path.read_text(encoding="utf-8")
        # Should only appear once
        assert content.count("const/4 v3, 0x1") == 1


# ══════════════════════════════════════════════════════════════════════════════
# Tests 13–19: miui-services CN/Global patches (in deadzone_framework_patches)
# ══════════════════════════════════════════════════════════════════════════════

_INTL_FLAG  = "Lmiui/os/Build;->IS_INTERNATIONAL_BUILD:Z"
_GLOBAL_FLAG = "Lmiui/os/Build;->IS_GLOBAL_BUILD:Z"
_MIUI_FLAG  = "Lmiui/os/Build;->IS_MIUI:Z"
_POLICY_SPUT = "sput-boolean v0, Lcom/miui/server/greeze/PolicyManager;->CN_MODEL:Z"


def _make_miui_svc_dir(tmp_path: Path) -> Path:
    return tmp_path / "miui_services_unpacked"


def _make_class(base: Path, cls_name: str, content: str, subdir: str = "smali_classes") -> Path:
    d = base / subdir
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{cls_name}.smali"
    p.write_text(content, encoding="utf-8")
    return p


class TestMiuiServicesCnGlobalPatches:
    """Tests 13–19"""

    def _smali_with_intl_flag(self, class_name: str) -> str:
        return (
            f".class public Lcom/android/server/am/{class_name};\n"
            f".super Ljava/lang/Object;\n"
            f".method public check()Z\n"
            f"    .registers 2\n"
            f"    sget-boolean v2, {_INTL_FLAG}\n"
            f"    return v2\n"
            f".end method\n"
        )

    def _smali_with_global_flag(self, class_name: str) -> str:
        return (
            f".class public Lcom/android/server/policy/{class_name};\n"
            f".super Ljava/lang/Object;\n"
            f".method public check()Z\n"
            f"    .registers 2\n"
            f"    sget-boolean v1, {_GLOBAL_FLAG}\n"
            f"    return v1\n"
            f".end method\n"
        )

    def _smali_unrelated(self, class_name: str) -> str:
        return (
            f".class public Lunrelated/{class_name};\n"
            f".super Ljava/lang/Object;\n"
            f".method public doThing()V\n"
            f"    return-void\n"
            f".end method\n"
        )

    def test_intl_replaced_in_target_classes(self, tmp_path):
        """Test 13: IS_INTERNATIONAL_BUILD replaced with IS_MIUI in all 5 target classes."""
        mi = _make_miui_svc_dir(tmp_path)
        target_classes = [
            "ActivityManagerServiceImpl",
            "BroadcastQueueModernStubImpl",
            "ProcessManagerService",
            "ProcessPolicy",
            "ProcessSceneCleaner",
        ]
        paths = {}
        for cls in target_classes:
            paths[cls] = _make_class(mi, cls, self._smali_with_intl_flag(cls))

        report = []
        _fw.apply_miui_services_cn_global_patches(tmp_path, report)

        for cls, path in paths.items():
            content = path.read_text(encoding="utf-8")
            assert _INTL_FLAG not in content, f"{cls} still has IS_INTERNATIONAL_BUILD"
            assert _MIUI_FLAG in content, f"{cls} does not have IS_MIUI"

    def test_global_replaced_in_shortcut_observer_only(self, tmp_path):
        """Test 14: IS_GLOBAL_BUILD replaced in ShortcutSettingsObserver only."""
        mi = _make_miui_svc_dir(tmp_path)
        obs_cls = "MiuiShortcutTriggerHelper$ShortcutSettingsObserver"
        obs_path = _make_class(mi, obs_cls, self._smali_with_global_flag(obs_cls))
        # Also create a class that should NOT have IS_GLOBAL_BUILD replaced
        other_path = _make_class(mi, "ActivityManagerServiceImpl",
                                 self._smali_with_global_flag("ActivityManagerServiceImpl"))

        report = []
        _fw.apply_miui_services_cn_global_patches(tmp_path, report)

        # Observer: IS_GLOBAL_BUILD → IS_MIUI
        obs_content = obs_path.read_text(encoding="utf-8")
        assert _GLOBAL_FLAG not in obs_content
        assert _MIUI_FLAG in obs_content

        # Other class: IS_GLOBAL_BUILD should be untouched (Patch B is only for observer)
        other_content = other_path.read_text(encoding="utf-8")
        assert _GLOBAL_FLAG in other_content, "Other class must not have IS_GLOBAL_BUILD replaced"

    def test_const4_added_below_is_miui_in_three_classes(self, tmp_path):
        """Test 15: const/4 same register added below IS_MIUI in BroadcastQueue/ProcessMgr/SceneCleaner."""
        mi = _make_miui_svc_dir(tmp_path)
        # Start with IS_MIUI directly (simulates post-Patch-A or originally IS_MIUI)
        smali_with_miui = (
            ".class public Lcom/android/server/am/BroadcastQueueModernStubImpl;\n"
            ".super Ljava/lang/Object;\n"
            ".method public check()Z\n"
            "    .registers 2\n"
            f"    sget-boolean v5, {_MIUI_FLAG}\n"
            "    return v5\n"
            ".end method\n"
        )
        path = _make_class(mi, "BroadcastQueueModernStubImpl", smali_with_miui)

        report = []
        _fw.apply_miui_services_cn_global_patches(tmp_path, report)

        content = path.read_text(encoding="utf-8")
        assert "const/4 v5, 0x1" in content

    def test_policy_manager_cn_model_gets_const4_above_sput(self, tmp_path):
        """Test 16: PolicyManager CN_MODEL gets const/4 v0, 0x0 above sput."""
        mi = _make_miui_svc_dir(tmp_path)
        smali = (
            ".class public Lcom/miui/server/greeze/PolicyManager;\n"
            ".super Ljava/lang/Object;\n"
            ".method public init()V\n"
            "    .registers 2\n"
            "    const/4 v0, 0x1\n"
            f"    {_POLICY_SPUT}\n"
            "    return-void\n"
            ".end method\n"
        )
        path = _make_class(mi, "PolicyManager", smali)

        report = []
        _fw.apply_miui_services_cn_global_patches(tmp_path, report)

        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        sput_idx = next(i for i, l in enumerate(lines) if _POLICY_SPUT in l)
        # Line immediately before sput must be const/4 v0, 0x0
        prev_code = next(
            l.strip() for l in reversed(lines[:sput_idx]) if l.strip()
        )
        assert prev_code == "const/4 v0, 0x0", f"Expected const/4 v0, 0x0, got: {prev_code!r}"

    def test_unrelated_classes_untouched(self, tmp_path):
        """Test 17: Classes not in target list are not modified."""
        mi = _make_miui_svc_dir(tmp_path)
        unrelated_content = self._smali_unrelated("UnrelatedClass")
        unrelated_content += f"    sget-boolean v0, {_INTL_FLAG}\n"
        path = _make_class(mi, "UnrelatedClass", unrelated_content)
        original = path.read_text(encoding="utf-8")

        report = []
        _fw.apply_miui_services_cn_global_patches(tmp_path, report)

        assert path.read_text(encoding="utf-8") == original, "Unrelated class must not be touched"

    def test_missing_classes_return_skipped(self, tmp_path):
        """Test 18: Classes not present in smali dirs return SKIPPED entries."""
        mi = _make_miui_svc_dir(tmp_path)
        # Create empty smali dir (no class files)
        (mi / "smali_classes").mkdir(parents=True)

        report = []
        _fw.apply_miui_services_cn_global_patches(tmp_path, report)

        skipped = [e for e in report if e["status"] == "skipped"]
        assert len(skipped) >= 1
        # At least the 5 Patch A classes should be reported skipped
        skipped_classes = {e.get("target_class", "") for e in skipped}
        assert "ActivityManagerServiceImpl" in skipped_classes

    def test_patches_are_idempotent(self, tmp_path):
        """Test 19: Running patches twice produces identical file content."""
        mi = _make_miui_svc_dir(tmp_path)
        cls = "ActivityManagerServiceImpl"
        path = _make_class(mi, cls, self._smali_with_intl_flag(cls))

        _fw.apply_miui_services_cn_global_patches(tmp_path, [])
        content_after_first = path.read_text(encoding="utf-8")

        _fw.apply_miui_services_cn_global_patches(tmp_path, [])
        content_after_second = path.read_text(encoding="utf-8")

        assert content_after_first == content_after_second, "Patch must be idempotent"

    def test_missing_miui_services_dir_skipped(self, tmp_path):
        """miui_services_unpacked absent → single SKIPPED entry, no exception."""
        report = []
        _fw.apply_miui_services_cn_global_patches(tmp_path, report)
        assert len(report) == 1
        assert report[0]["status"] == "skipped"
        assert report[0]["found"] is False


# ══════════════════════════════════════════════════════════════════════════════
# Tests 20–25: PowerKeeper patches
# ══════════════════════════════════════════════════════════════════════════════

class TestPowerKeeperPatches:
    """Tests 20–25"""

    def _smali_with_intl_flag(self, cls: str, reg: str = "v2") -> str:
        return (
            f".class public Lcom/miui/powerkeeper/{cls};\n"
            f".super Ljava/lang/Object;\n"
            f".method public check()Z\n"
            f"    .registers 3\n"
            f"    sget-boolean {reg}, {_INTL_FLAG}\n"
            f"    return {reg}\n"
            f".end method\n"
        )

    def _milletconfig_smali(self) -> str:
        return (
            ".class public Lcom/miui/powerkeeper/millet/MilletConfig;\n"
            ".super Ljava/lang/Object;\n"
            ".method public isEnabled()Z\n"
            "    .registers 2\n"
            f"    sget-boolean v4, {_MIUI_FLAG}\n"
            "    return v4\n"
            ".end method\n"
        )

    def _gms_smali(self, cls: str, reg: str = "v0") -> str:
        return (
            f".class public Lcom/miui/powerkeeper/{cls};\n"
            f".super Ljava/lang/Object;\n"
            f".method public isGmsControlEnabled()Z\n"
            f"    .registers 1\n"
            f"    const/4 {reg}, 0x1\n"
            f"    return {reg}\n"
            f".end method\n"
        )

    def _make_pk_dir(self, tmp_path: Path) -> Path:
        return tmp_path / "powerkeeper_unpacked"

    def test_intl_replaced_in_listed_classes_only(self, tmp_path):
        """Test 20: IS_INTERNATIONAL_BUILD replaced with IS_MIUI in listed classes."""
        pk_dir = self._make_pk_dir(tmp_path)
        sd = _smali_dir(pk_dir)

        listed_cls = "GmsObserver"
        unlisted_cls = "SomeRandomClass"

        listed_path = _make_smali(sd, f"{listed_cls}.smali",
                                   self._smali_with_intl_flag(listed_cls))
        unlisted_path = _make_smali(sd, f"{unlisted_cls}.smali",
                                     self._smali_with_intl_flag(unlisted_cls))
        unlisted_orig = unlisted_path.read_text(encoding="utf-8")

        report = []
        _apk._patch_powerkeeper_in_dir(pk_dir, report)

        # Listed class: flag replaced
        content = listed_path.read_text(encoding="utf-8")
        assert _INTL_FLAG not in content
        assert _MIUI_FLAG in content

        # Unlisted class: untouched
        assert unlisted_path.read_text(encoding="utf-8") == unlisted_orig

    def test_milletconfig_gets_const4_below_is_miui(self, tmp_path):
        """Test 21: MilletConfig gets const/4 same register below IS_MIUI sget."""
        pk_dir = self._make_pk_dir(tmp_path)
        sd = _smali_dir(pk_dir)
        path = _make_smali(sd, "MilletConfig.smali", self._milletconfig_smali())

        report = []
        _apk._patch_powerkeeper_in_dir(pk_dir, report)

        content = path.read_text(encoding="utf-8")
        # v4 is the register in _milletconfig_smali
        assert "const/4 v4, 0x1" in content

    def test_is_gms_control_enabled_returns_false(self, tmp_path):
        """Test 22: isGmsControlEnabled()Z returns false using same return register."""
        pk_dir = self._make_pk_dir(tmp_path)
        sd = _smali_dir(pk_dir)
        path = _make_smali(sd, "GmsObserver.smali", self._gms_smali("GmsObserver", "v0"))

        report = []
        _apk._patch_powerkeeper_in_dir(pk_dir, report)

        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        # Find 'return v0' and verify preceding non-empty line is 'const/4 v0, 0x0'
        for i, line in enumerate(lines):
            if line.strip() == "return v0":
                prev = next(
                    l.strip() for l in reversed(lines[:i]) if l.strip()
                )
                assert prev == "const/4 v0, 0x0", (
                    f"Expected const/4 v0, 0x0 before return v0, got: {prev!r}"
                )
                break
        else:
            pytest.fail("return v0 not found in patched MilletConfig smali")

    def test_is_gms_control_uses_same_return_register(self, tmp_path):
        """isGmsControlEnabled patch uses same register as return, not hardcoded v0."""
        pk_dir = self._make_pk_dir(tmp_path)
        sd = _smali_dir(pk_dir)
        # Use v3 as the return register
        smali = (
            ".class public Lcom/miui/powerkeeper/GmsObserver;\n"
            ".super Ljava/lang/Object;\n"
            ".method public isGmsControlEnabled()Z\n"
            "    .registers 4\n"
            "    const/4 v3, 0x1\n"
            "    return v3\n"
            ".end method\n"
        )
        path = _make_smali(sd, "GmsObserver.smali", smali)

        report = []
        _apk._patch_powerkeeper_in_dir(pk_dir, report)

        content = path.read_text(encoding="utf-8")
        assert "const/4 v3, 0x0" in content
        # Must NOT inject v0
        assert "const/4 v0, 0x0" not in content

    def test_unrelated_classes_untouched(self, tmp_path):
        """Test 23: Classes not in _PK_PATCH_A_CLASSES are not modified for IS_INTERNATIONAL_BUILD."""
        pk_dir = self._make_pk_dir(tmp_path)
        sd = _smali_dir(pk_dir)
        orig_content = self._smali_with_intl_flag("UnlistedPowerClass")
        path = _make_smali(sd, "UnlistedPowerClass.smali", orig_content)

        report = []
        _apk._patch_powerkeeper_in_dir(pk_dir, report)

        assert path.read_text(encoding="utf-8") == orig_content

    def test_missing_powerkeeper_class_returns_skipped(self, tmp_path):
        """Test 24: Missing class files return SKIPPED entries."""
        pk_dir = self._make_pk_dir(tmp_path)
        _smali_dir(pk_dir)  # empty smali dir

        report = []
        _apk._patch_powerkeeper_in_dir(pk_dir, report)

        skipped = [e for e in report if e["status"] == "skipped"]
        assert len(skipped) >= 1

    def test_missing_gms_method_returns_skipped(self, tmp_path):
        """Test 24b: Class without isGmsControlEnabled method → methods_patched == 0."""
        pk_dir = self._make_pk_dir(tmp_path)
        sd = _smali_dir(pk_dir)
        smali = (
            ".class public Lcom/miui/powerkeeper/GmsObserver;\n"
            ".super Ljava/lang/Object;\n"
            ".method public someOtherMethod()V\n"
            "    return-void\n"
            ".end method\n"
        )
        _make_smali(sd, "GmsObserver.smali", smali)

        report = []
        _apk._patch_powerkeeper_in_dir(pk_dir, report)

        gms_entry = next(
            (e for e in report if "GmsObserver" in e.get("target_class", "")),
            None,
        )
        assert gms_entry is not None
        assert gms_entry.get("methods_patched", 0) == 0

    def test_missing_powerkeeper_apk_skipped(self, tmp_path):
        """Test 24c: No APK and no unpacked dir → SKIPPED/SKIPPED_NOT_FOUND at top level."""
        report = []
        _apk.apply_powerkeeper_cn_global_patches(tmp_path, report)
        _skipped = {"skipped", "skipped_not_found"}
        assert any(e["status"] in _skipped for e in report)

    def test_powerkeeper_patches_idempotent(self, tmp_path):
        """Test 25: Running PowerKeeper patches twice produces identical results."""
        pk_dir = self._make_pk_dir(tmp_path)
        sd = _smali_dir(pk_dir)
        path = _make_smali(sd, "GmsObserver.smali",
                            self._smali_with_intl_flag("GmsObserver", "v2"))

        _apk._patch_powerkeeper_in_dir(pk_dir, [])
        after_first = path.read_text(encoding="utf-8")

        _apk._patch_powerkeeper_in_dir(pk_dir, [])
        after_second = path.read_text(encoding="utf-8")

        assert after_first == after_second, "PowerKeeper patches must be idempotent"


# ══════════════════════════════════════════════════════════════════════════════
# Tests 26–32: Integration
# ══════════════════════════════════════════════════════════════════════════════

class TestIntegration:
    """Tests 26–32"""

    @pytest.fixture(autouse=True)
    def _manifest(self):
        assert LITE_MODS_JSON.is_file()
        self.manifest = json.loads(LITE_MODS_JSON.read_text(encoding="utf-8"))
        self.mods = self.manifest["mods"]
        self.manifest_text = json.dumps(self.manifest)

    def _mod_by_id(self, mod_id: str):
        return next((m for m in self.mods if m.get("id") == mod_id), None)

    def test_lite_mods_contains_deadzone_framework_patches_group(self):
        """Test 26: Lite mods.json contains deadzone_framework_patches group."""
        groups = {m.get("group") for m in self.mods if m.get("group")}
        assert "deadzone_framework_patches" in groups

    def test_lite_mods_contains_miui_services_patch(self):
        """Test 26b: miui_services_cn_global_patches entry exists in framework group."""
        mod = self._mod_by_id("miui_services_cn_global_patches")
        assert mod is not None, "miui_services_cn_global_patches must be in mods.json"
        assert mod["group"] == "deadzone_framework_patches"
        assert mod["python_entry"] == "bin/scripts/deadzone_framework_patches.py"

    def test_lite_mods_contains_lite_apk_patches(self):
        """Test 27: Lite mods.json contains lite_apk_patches entry."""
        mod = self._mod_by_id("lite_apk_patches")
        assert mod is not None, "lite_apk_patches must be in mods.json"
        assert mod["python_entry"] == "bin/scripts/lite_apk_patches.py"
        assert mod["enabled"] is True

    def test_lite_apk_patches_entry_is_optional(self):
        """lite_apk_patches must be required=false (optional, missing APKs skip)."""
        mod = self._mod_by_id("lite_apk_patches")
        assert mod is not None
        assert mod.get("required") is False

    def test_framework_patches_still_required(self):
        """Test 26c: Core framework patches remain required=true."""
        for mod_id in ("signature_verification_bypass", "invoke_custom_handling", "fix_bootloop_a15"):
            mod = self._mod_by_id(mod_id)
            assert mod is not None, f"{mod_id} must exist"
            assert mod["required"] is True

    def test_poco_spoof_still_present(self):
        """Test 31: POCO launcher spoof entry is still in mods.json."""
        mod = self._mod_by_id("poco_launcher_to_miuihome_spoofing")
        assert mod is not None, "POCO spoof entry must remain in mods.json"
        assert mod["enabled"] is True

    def test_style_mod_runner_runs_both_groups(self, tmp_path):
        """Test 28: style_mod_runner executes both deadzone_framework_patches and lite_apk_patches."""
        runner_py = SCRIPTS_DIR / "style_mod_runner.py"
        spec = importlib.util.spec_from_file_location("style_mod_runner", runner_py)
        runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runner)

        scripts_dir = tmp_path / "bin" / "scripts"
        scripts_dir.mkdir(parents=True)
        manifest_dir = tmp_path / "bin" / "styles" / "Lite"
        manifest_dir.mkdir(parents=True)

        # Script that succeeds (group leader)
        ok_script = scripts_dir / "ok_fw.py"
        ok_script.write_text(
            "import argparse, sys\n"
            "p = argparse.ArgumentParser()\n"
            "p.add_argument('--style', default='lite')\n"
            "p.add_argument('--work-dir', default='.')\n"
            "p.parse_args()\n"
            "print('[OK_FW]')\n",
            encoding="utf-8",
        )
        ok_apk = scripts_dir / "ok_apk.py"
        ok_apk.write_text(
            "import argparse, sys\n"
            "p = argparse.ArgumentParser()\n"
            "p.add_argument('--style', default='lite')\n"
            "p.add_argument('--work-dir', default='.')\n"
            "p.parse_args()\n"
            "print('[OK_APK]')\n",
            encoding="utf-8",
        )

        manifest = {
            "style": "lite",
            "name": "Test Lite",
            "mods": [
                {
                    "id": "fw_leader",
                    "name": "FW Leader",
                    "enabled": True, "required": True,
                    "source_stage": "fw", "group": "deadzone_framework_patches",
                    "python_entry": "bin/scripts/ok_fw.py",
                    "description": "fw group leader",
                },
                {
                    "id": "fw_follower",
                    "name": "FW Follower",
                    "enabled": True, "required": True,
                    "source_stage": "fw", "group": "deadzone_framework_patches",
                    "python_entry": "bin/scripts/ok_fw.py",
                    "description": "fw group follower",
                },
                {
                    "id": "apk_mod",
                    "name": "APK Mod",
                    "enabled": True, "required": False,
                    "source_stage": "apk", "group": "lite_apk_patches",
                    "python_entry": "bin/scripts/ok_apk.py",
                    "description": "apk patches",
                },
            ],
        }
        (manifest_dir / "mods.json").write_text(json.dumps(manifest), encoding="utf-8")

        results = runner.run_style("lite", tmp_path)

        ids = [r["id"] for r in results]
        statuses = {r["id"]: r["status"] for r in results}

        assert "fw_leader" in ids
        assert "apk_mod" in ids
        assert statuses["fw_leader"] == "success"
        assert statuses["apk_mod"] == "success"
        # fw_follower must be skipped (group deduplication)
        assert statuses.get("fw_follower") == "skipped"

    def test_stable_delegates_to_plus(self):
        """Test 29: Stable insmod.sh is a compat wrapper delegating to Plus."""
        if not STABLE_INSMOD.is_file():
            pytest.skip("Stable insmod.sh not present")
        content = STABLE_INSMOD.read_text(encoding="utf-8")
        assert "Plus" in content, "Stable must delegate to Plus (compat wrapper)"

    def test_legend_inherits_plus(self):
        """Test 30: Legend insmod.sh references Plus (not Stable)."""
        if not LEGEND_INSMOD.is_file():
            pytest.skip("Legend insmod.sh not present")
        content = LEGEND_INSMOD.read_text(encoding="utf-8")
        assert "Plus" in content, "Legend must inherit Plus"
        assert "Stable" not in content, "Legend must not reference old Stable"

    def test_ninja_inherits_plus(self):
        """Test 30b: Ninja insmod.sh references Plus (not Stable)."""
        if not NINJA_INSMOD.is_file():
            pytest.skip("Ninja insmod.sh not present")
        content = NINJA_INSMOD.read_text(encoding="utf-8")
        assert "Plus" in content, "Ninja must inherit Plus"
        assert "Stable" not in content, "Ninja must not reference old Stable"

    def test_all_mods_have_executor(self):
        """Test 32: All mods in updated mods.json have a python_entry or script_path."""
        for mod in self.mods:
            assert mod.get("python_entry") or mod.get("script_path"), (
                f"Mod {mod.get('id')!r} has no executor"
            )

    def test_deadzone_framework_patches_script_compiles(self):
        """deadzone_framework_patches.py is importable without syntax error."""
        import py_compile
        py_compile.compile(str(SCRIPTS_DIR / "deadzone_framework_patches.py"), doraise=True)

    def test_lite_apk_patches_script_compiles(self):
        """lite_apk_patches.py is importable without syntax error."""
        import py_compile
        py_compile.compile(str(SCRIPTS_DIR / "lite_apk_patches.py"), doraise=True)

    def test_apply_stable_framework_patches_includes_msvc(self, tmp_path):
        """apply_stable_framework_patches runs miui_services patch and includes it in report."""
        report = _fw.apply_stable_framework_patches(tmp_path)
        assert "miui_services_cn_global_patches" in report["patches"]
        # Missing dir → skipped, not failed
        patch_data = report["patches"]["miui_services_cn_global_patches"]
        assert patch_data["total_failed"] == 0
