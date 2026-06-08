"""Tests for rom_metadata.py — region/OS parser."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"

_spec = importlib.util.spec_from_file_location("rom_metadata", SCRIPTS_DIR / "rom_metadata.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


class TestParseRomVersion:
    def test_cnxm_os3(self):
        r = _mod.parse_rom_version("OS3.0.305.0.WFSCNXM")
        assert r["os"] == "OS3"
        assert r["region_code"] == "CN"
        assert r["region_display"] == "China / CN"

    def test_idxm_os3(self):
        r = _mod.parse_rom_version("OS3.0.301.0.WNRIDXM")
        assert r["os"] == "OS3"
        assert r["region_code"] == "ID"
        assert r["region_display"] == "Indonesia / IDGlobal"

    def test_cnxm_os3_wno(self):
        r = _mod.parse_rom_version("OS3.0.303.0.WNOCNXM")
        assert r["os"] == "OS3"
        assert r["region_code"] == "CN"
        assert r["region_display"] == "China / CN"

    def test_mixm_global(self):
        r = _mod.parse_rom_version("OS3.0.304.0.WNRMIXM")
        assert r["os"] == "OS3"
        assert r["region_code"] == "MI"
        assert r["region_display"] == "Global"

    def test_os2(self):
        r = _mod.parse_rom_version("OS2.0.1.0.ABCNXM")
        assert r["os"] == "OS2"
        assert r["region_code"] == "CN"

    def test_empty_string(self):
        r = _mod.parse_rom_version("")
        assert r["os"] == ""
        assert r["region_code"] == ""
        assert r["region_display"] == ""


class TestGetRegionFromDeviceType:
    def test_china(self):
        assert _mod.get_region_from_device_type("China") == "China / CN"

    def test_idglobal(self):
        assert _mod.get_region_from_device_type("IDGlobal") == "Indonesia / IDGlobal"

    def test_global(self):
        assert _mod.get_region_from_device_type("Global") == "Global"

    def test_eeaglobal(self):
        assert _mod.get_region_from_device_type("EEAGlobal") == "Europe / EEA"


class TestGetRegionDisplay:
    def test_rejects_os3(self):
        r = _mod.get_region_display("OS3")
        assert r != "OS3", "get_region_display must not return 'OS3' as a region"
        assert r == "Global"

    def test_rejects_os2(self):
        r = _mod.get_region_display("OS2")
        assert r == "Global"

    def test_china(self):
        assert _mod.get_region_display("China") == "China / CN"
