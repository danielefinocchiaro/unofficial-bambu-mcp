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


def test_snap_to_layer():
    from unofficial_bambu_mcp.calibration import snap
    assert snap(0.05, 0.2, 0.2) == 0.2
    assert snap(2.0, 0.2, 0.2) == 2.0
    assert snap(2.05, 0.2, 0.2) == 2.2


def test_calibration_solids_are_closed():
    from unofficial_bambu_mcp import calibration
    try:
        geometry.default_font()
    except FileNotFoundError:
        pytest.skip("no system font")
    tower, actions = calibration.temperature_tower([230, 225, 220])
    info = geometry.check(tower.parts[0].verts, tower.parts[0].tris)
    assert info["manifold"] and info["pieces"] == 1
    assert [a.gcode.split()[1] for a in actions] == ["S230", "S225", "S220"]
    pa, steps = calibration.pa_tower([0.0, 0.01, 0.02])
    assert geometry.check(pa.parts[0].verts, pa.parts[0].tris)["manifold"] and len(steps) == 3
    blocks = calibration.flow_blocks([-5, 0, 5])
    assert [o.settings["print_flow_ratio"] for o, _ in blocks] == ["0.95", "1", "1.05"]


@needs_bambu
def test_layer_actions_roundtrip(tmp_path):
    from unofficial_bambu_mcp import threemf
    from unofficial_bambu_mcp.project import LayerGcode, Obj, Part, Project
    pr = Project("t", "P1S", filaments=[("Bambu PLA Basic", "#000000"), ("Bambu PLA Basic", "#FFFFFF")])
    v, t = geometry.box(20, 20, 10)
    pr.plates[0].objects.append(Obj("Box", [Part("Box", v, t, 1)], at=(100, 100)))
    pr.plates[0].layer_gcodes = [LayerGcode(2.0, "pause", message="magnets"), LayerGcode(4.0, "tool_change", filament=2),
                                 LayerGcode(6.0, "custom", gcode="M104 S210")]
    back = threemf.read(threemf.write(pr, str(tmp_path / "t.3mf")))
    got = [g.as_dict() for g in back.plates[0].layer_gcodes]
    assert got == [{"z": 2.0, "kind": "pause", "message": "magnets"}, {"z": 4.0, "kind": "tool_change", "filament": 2},
                   {"z": 6.0, "kind": "custom", "gcode": "M104 S210"}]


def test_mirror_keeps_solid_closed():
    v, t = geometry.box(10, 20, 5)
    v2, t2 = geometry.mirror(v + [3, 0, 0], t, "x")
    info = geometry.check(v2, t2)
    assert info["manifold"] and info["volume_mm3"] == pytest.approx(1000, rel=1e-6)


def test_lay_flat_picks_biggest_face():
    v, t = geometry.box(30, 10, 20)
    R, area = geometry.lay_flat_matrix(geometry.rotate(v, 37, "x"))
    assert area == pytest.approx(600, rel=1e-3)
    h = np.ptp(geometry.rotate(v, 37, "x") @ R.T, axis=0)[2]
    assert h == pytest.approx(10, abs=1e-6)


def test_split_z():
    v, t = geometry.cylinder(20, 30)
    below, above = geometry.split_z(v, t, 12)
    assert np.ptp(below[0], axis=0)[2] == pytest.approx(12, abs=1e-6)
    assert np.ptp(above[0], axis=0)[2] == pytest.approx(18, abs=1e-6)


@needs_bambu
def test_modifier_roundtrip(tmp_path):
    from unofficial_bambu_mcp import threemf
    from unofficial_bambu_mcp.project import Obj, Part, Project
    pr = Project("t", "P1S")
    v, t = geometry.box(20, 20, 10)
    mv, mt = geometry.box(22, 22, 3)
    ob = Obj("Box", [Part("Box", v, t), Part("Top", mv + [0, 0, 7], mt, subtype="modifier_part",
                                             meta={"sparse_infill_density": "100%"})], at=(100, 100))
    pr.plates[0].objects.append(ob)
    (_, back), = threemf.read(threemf.write(pr, str(tmp_path / "m.3mf"))).objects()
    mod = [p for p in back.parts if p.subtype == "modifier_part"][0]
    assert mod.meta["sparse_infill_density"] == "100%"
    assert back.size()[2] == pytest.approx(10, abs=1e-3)       # modifiers do not change the object's size
