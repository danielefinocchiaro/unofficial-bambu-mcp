"""Unit tests. The ones that need Bambu Studio profiles are skipped when it is not installed."""

import numpy as np
import pytest

from unofficial_bambu_mcp import geometry, preview, studio
from unofficial_bambu_mcp.project import flush_volume, next_free_path

HAS_BAMBU = bool(studio.profile_roots())
needs_bambu = pytest.mark.skipif(not HAS_BAMBU, reason="Bambu Studio profiles not installed")


def test_stl_roundtrip(tmp_path):
    v, t = geometry.box(10, 20, 30)
    p = geometry.save_stl(str(tmp_path / "box.stl"), v, t)
    v2, t2 = geometry.load_stl(p)
    assert len(t2) == len(t)
    assert np.allclose(np.ptp(v2, axis=0), [10, 20, 30], atol=1e-4)


def test_check_closed_solid():
    v, t = geometry.cylinder(20, 10)
    info = geometry.check(v, t)
    assert info["manifold"] and info["pieces"] == 1
    assert abs(info["volume_mm3"] - np.pi * 100 * 10) / (np.pi * 1000) < 0.01


def test_crop_height():
    v, t = geometry.box(10, 10, 10)
    v2, t2 = geometry.crop_height(v, t, 2.0)
    assert np.isclose(v2[:, 2].max(), 2.0)


def test_text_solid():
    try:
        geometry.default_font()
    except FileNotFoundError:
        pytest.skip("no system font")
    v, t = geometry.text_solid("AB", height=10, depth=2, base=1.5)
    info = geometry.check(v, t)
    assert info["manifold"] and info["size_mm"][2] == pytest.approx(3.5, abs=0.02)


@pytest.mark.parametrize("code,slot", [("4", 1), ("8", 2), ("0C", 3), ("1C", 4), ("2C", 5), ("5", None), ("", None)])
def test_paint_slot(code, slot):
    assert preview._paint_slot(code) == slot


def test_flush_volume():
    assert flush_volume("#000000", "#000000") == 0
    assert flush_volume("#000000", "#FFFFFF") > flush_volume("#FFFFFF", "#000000")


def test_next_free_path(tmp_path):
    p = tmp_path / "a.3mf"
    assert next_free_path(str(p)) == str(p)
    p.write_text("x")
    assert next_free_path(str(p)).endswith("a-2.3mf")


@needs_bambu
def test_project_roundtrip(tmp_path):
    from unofficial_bambu_mcp import threemf
    from unofficial_bambu_mcp.project import Obj, Part, Project
    pr = Project("t", "P1S", filaments=[("Bambu PLA Basic", "#000000"), ("Bambu PLA Basic", "#FFFFFF")])
    v, t = geometry.box(20, 20, 5)
    pr.plates[0].objects.append(Obj("Box", [Part("Box", v, t, 2)], at=(100, 100)))
    path = threemf.write(pr, str(tmp_path / "t.3mf"))
    back = threemf.read(path)
    (pi, o), = back.objects()
    assert o.name == "Box" and o.parts[0].filament == 2
    assert np.allclose(o.at, (100, 100), atol=0.01)
    assert back.filaments[1][1] == "#FFFFFF"


@needs_bambu
def test_filament_matched_to_printer():
    from unofficial_bambu_mcp import presets
    m = presets.machine_name("A1M")
    assert presets.filament_for("Bambu PLA Basic @BBL X1C", m).endswith("@BBL A1M")


def test_printer_summary():
    from unofficial_bambu_mcp import printer
    rep = {"gcode_state": "RUNNING", "mc_percent": 42, "mc_remaining_time": 87, "layer_num": 9, "total_layer_num": 20,
           "nozzle_temper": 219.8, "nozzle_target_temper": 220, "bed_temper": 64.9, "bed_target_temper": 65,
           "ams": {"tray_now": "1", "ams": [{"id": "0", "humidity": "4", "tray": [
               {"id": "0", "tray_type": "PLA", "tray_sub_brands": "PLA Matte", "tray_color": "000000FF", "remain": 70},
               {"id": "1", "tray_type": "PLA", "tray_color": "FFFFFFFF", "remain": -1, "tray_info_idx": "GFL03"},
               {"id": "2"}]}]}}
    s = printer.summarize(rep)
    assert s["state"] == "printing" and s["progress_percent"] == 42 and s["layer"] == [9, 20]
    assert s["ams_trays"][1]["color"] == "#FFFFFF" and s["ams_trays"][2]["empty"]
    assert s["active_slot"] == 2


@needs_bambu
def test_preset_for_tray():
    from unofficial_bambu_mcp import presets, printer
    m = presets.machine_name("P1S")
    assert printer.preset_for_tray("GFL03", "PLA", m).startswith("eSUN PLA+")
    assert printer.preset_for_tray(None, "PETG", m) == "Generic PETG"
