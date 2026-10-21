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
    (bn, bv, bt), (tn, tv, tt) = geometry.text_parts("AB", height=10, depth=2, base=1.5)
    assert (bn, tn) == ("Base", "Text")
    assert geometry.check(bv, bt)["manifold"] and geometry.check(tv, tt)["manifold"]
    assert bv[:, 2].max() == pytest.approx(1.5) and tv[:, 2].min() == pytest.approx(1.5)
    assert tv[:, 2].max() == pytest.approx(3.5)


def test_rasterize_nearest_wins():
    # a big far triangle drawn after a small near one must not cover it (painter's sorting by center failed here)
    small = [[40, 40], [60, 40], [50, 60]]
    big = [[0, 0], [100, 0], [0, 100]]
    for order in ([small, big], [big, small]):
        px = np.array(order, float)
        z = np.array([[5.0] * 3 if t is small else [1.0] * 3 for t in order])
        rgb = np.array([[255, 0, 0] if t is small else [0, 0, 255] for t in order], np.uint8)
        covered, colors = preview._rasterize(px, z, rgb, 100, 100)
        assert covered[45 * 100 + 50] and tuple(colors[45 * 100 + 50]) == (255, 0, 0)
        assert tuple(colors[10 * 100 + 10]) == (0, 0, 255) and not covered[99 * 100 + 99]


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
    g = tmp_path / "a-plate1.gcode.3mf"
    g.write_text("x")
    assert next_free_path(str(g)).endswith("a-plate1-2.gcode.3mf")


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


def test_printer_summary_idle_and_unknown_spool():
    from unofficial_bambu_mcp import printer
    # shape of a real P1S report: last print cancelled, a third-party spool in tray 2 never set in the AMS
    rep = {"gcode_state": "FAILED", "subtask_name": "50% Scale", "mc_percent": 0, "mc_remaining_time": 39,
           "print_error": 0, "ams": {"tray_now": "1", "tray_exist_bits": "7", "ams": [
               {"id": "0", "humidity": "1", "humidity_raw": "60", "temp": "25.7", "tray": [
                   {"id": "0", "tray_type": "PETG", "tray_color": "00AE42FF", "remain": 84, "tray_info_idx": "GFG02"},
                   {"id": "1"}, {"id": "2"}, {"id": "3"}]}]}}
    s = printer.summarize(rep)
    assert s["state"] == "idle" and "progress_percent" not in s
    assert s["last_job"] == {"name": "50% Scale", "result": "failed or cancelled"}
    assert s["ams_trays"][1]["unknown"] and s["ams_trays"][2]["unknown"] and s["ams_trays"][3]["empty"]
    assert s["ams_units"] == {1: {"humidity_percent": 60, "temp_c": 25.7}}
    assert "[2, 3]" in s["hint"] and s["active_slot"] == 2


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


def test_preferred_bed_type(tmp_path, monkeypatch):
    import json

    from unofficial_bambu_mcp import studio
    monkeypatch.setenv("BAMBU_STUDIO_DATA", str(tmp_path))
    assert studio.preferred_bed_type("Bambu Lab P1S 0.4 nozzle") is None
    conf = {"app": {"curr_bed_type": "4"}, "user_bed_type_list": {"Bambu Lab P1S 0.4 nozzle": "High Temp Plate"}}
    (tmp_path / "BambuStudio.conf").write_text("# header\n" + json.dumps(conf))
    assert studio.preferred_bed_type("Bambu Lab P1S 0.4 nozzle") == "High Temp Plate"
    assert studio.preferred_bed_type("Bambu Lab A1 mini 0.4 nozzle") == "Textured PEI Plate"


def test_set_printer_model_id(tmp_path):
    import zipfile

    from unofficial_bambu_mcp import slicer
    p = tmp_path / "a.gcode.3mf"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Metadata/slice_info.config", '<metadata key="printer_model_id" value=""/>')
        z.writestr("Metadata/plate_1.gcode", "G28")
    slicer._set_printer_model_id(str(p), "C12")
    with zipfile.ZipFile(p) as z:
        assert b'value="C12"' in z.read("Metadata/slice_info.config") and z.read("Metadata/plate_1.gcode") == b"G28"


@needs_bambu
def test_object_ids_are_stable(tmp_path, monkeypatch):
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    from unofficial_bambu_mcp import server as s
    s.new_project("ids", "P1S")
    a = s.add_shape("box", name="A")["id"]
    b = s.add_shape("box", name="B")["id"]
    s.add_plate()
    s.move_object("A", plate=2)                     # A is now listed after B: its id must not change
    assert s.P().find(a)[1].name == "A" and s.P().find(b)[1].name == "B"
    c = s.duplicate_object("B")[0]["id"]
    assert c not in (a, b) and s.P().find(b)[1].name == "B"
    s.delete_object("B 2")
    assert s.add_shape("box", name="D")["id"] not in (a, b, c)     # ids are never reused


@needs_bambu
def test_plate_temperature_for_another_plate_warns(tmp_path, monkeypatch):
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    from unofficial_bambu_mcp import server as s
    s.new_project("bed", "P1S")
    s.set_setting("curr_bed_type", "High Temp Plate")
    assert "hot_plate_temp" in s.set_setting("textured_plate_temp_initial_layer", "65")["warning"]
    assert "warning" not in s.set_setting("hot_plate_temp_initial_layer", "65")
    s.set_setting("curr_bed_type", "Textured PEI Plate")
    assert "warning" not in s.set_setting("textured_plate_temp", "60")


@needs_bambu
def test_calibrations_reuse_empty_plate_and_slice_all_skips_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    from unofficial_bambu_mcp import server as s
    s.new_project("cal", "P1S")
    assert s.make_pa_tower(start=0, end=0.008, step=0.004)["plate"] == 1      # plate 1 was empty: reused
    s.add_plate()                                                            # plate 2: empty
    s.add_shape("box", plate=1, x=40, y=40, width=10, depth=10, height=2)
    s.add_plate()
    s.add_shape("cylinder", plate=3, diameter=10, height=2)
    res = s.slice_project()
    assert res["skipped_empty_plates"] == [2] and [p["plate"] for p in res["plates"]] == [1, 3]
    from unofficial_bambu_mcp import slicer
    assert s.S.sliced_plates == {1: 1, 3: 2}                                 # the sliced file has no empty plate
    assert slicer.gcode(res["sliced_file"], 1) and slicer.gcode(res["sliced_file"], 2)
    assert s.preview_layer(3, layer=1).data                                  # project numbers keep working
