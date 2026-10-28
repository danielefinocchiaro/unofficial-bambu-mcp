"""Unit tests. The ones that need Bambu Studio profiles are skipped when it is not installed."""

import math
import os

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


def test_occlusion_darkens_engraving_floor():
    # a face at depth 5 with a 1 mm deep pit in the middle: the pit is darker, the open face and background are not
    D = np.full((60, 60), -np.inf)
    D[10:50, 10:50] = 5.0
    D[27:33, 27:33] = 4.0
    shade = preview._occlusion(D.reshape(-1), 60, 60, px_per_mm=4).reshape(60, 60)
    assert shade[30, 30] < 0.8 and shade[15, 15] == 1.0 and shade[0, 0] == 1.0


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
    pr.overrides["curr_bed_type"] = "High Temp Plate"
    v, t = geometry.box(20, 20, 5)
    pr.plates[0].objects.append(Obj("Box", [Part("Box", v, t, 2)], at=(100, 100)))
    path = threemf.write(pr, str(tmp_path / "t.3mf"))
    back = threemf.read(path)
    (pi, o), = back.objects()
    assert o.name == "Box" and o.parts[0].filament == 2
    assert np.allclose(o.at, (100, 100), atol=0.01)
    assert back.filaments[1][1] == "#FFFFFF"
    assert back.config()["curr_bed_type"] == "High Temp Plate"           # the build plate survives a reload


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
    assert "remain_percent" not in s["ams_trays"][1]                   # -1 = unknown (spool without RFID)
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


def test_sliced_stats_reports_pauses(tmp_path):
    import zipfile

    from unofficial_bambu_mcp import threemf
    p = tmp_path / "s.3mf"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Metadata/slice_info.config", '<config><plate><metadata key="index" value="1"/>'
                   '<metadata key="prediction" value="600"/><metadata key="weight" value="4.5"/>'
                   '<metadata key="pause_count" value="1"/></plate></config>')
    st = threemf.sliced_stats(str(p))[0]
    assert st["minutes"] == 10.0 and st["grams"] == 4.5 and st["pauses"] == 1


@needs_bambu
def test_round_negative_part(tmp_path, monkeypatch):
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    from unofficial_bambu_mcp import server as s
    s.new_project("hole", "P1S")
    s.add_shape("box", width=40, depth=40, height=10, name="B")
    s.add_modifier("B", kind="negative", region=[-4, -4, 4, 4], shape="cylinder")
    part = s.P().find("B")[1].parts[-1]
    size = part.verts.max(0) - part.verts.min(0)
    assert part.subtype == "negative_part" and size[0] == pytest.approx(8, abs=0.01)
    assert size[2] >= 10                                  # through the whole object
    from mcp.server.mcpserver.exceptions import ToolError
    with pytest.raises(ToolError, match="box or cylinder"):
        s.add_modifier("B", kind="negative", shape="sphere")


@pytest.fixture
def studio_user(tmp_path, monkeypatch):
    """An empty Bambu Studio user preset folder in tmp_path: the real presets are never touched."""
    import json

    from unofficial_bambu_mcp import presets, user_presets
    data = tmp_path / "studio"
    for kind in ("filament", "process", "machine"):
        (data / "user" / "123" / kind).mkdir(parents=True)
    (data / "BambuStudio.conf").write_text(json.dumps({"app": {"preset_folder": "123"}}))
    monkeypatch.setenv("BAMBU_STUDIO_DATA", str(data))
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path / "out"))
    monkeypatch.setattr(user_presets, "BACKUPS", str(tmp_path / "backups"))
    presets.refresh()
    yield tmp_path
    monkeypatch.undo()
    presets.refresh()


@needs_bambu
def test_user_filament_presets(studio_user):
    import json

    from unofficial_bambu_mcp import presets, user_presets
    m = "Bambu Lab P1S 0.4 nozzle"
    # a new filament, like Create Filament: no parent, its own id, listed for AMS slots
    r = user_presets.write_filament("Test PLA X", "Generic PLA", {"nozzle_temperature": "215"}, machine=m)
    path, name, fid = r["file"], r["name"], r["filament_id"]
    d = json.load(open(path))
    assert name == f"Test PLA X @{m}" and d["inherits"] == "" and d["compatible_printers"] == [m]
    assert fid.startswith("P") and len(fid) == 8 and d["filament_id"] == fid
    assert d["nozzle_temperature"] == ["215"] and d["filament_type"] == ["PLA"]
    assert presets.filament_for("Test PLA X", m) == name
    with pytest.raises(presets.PresetError):
        user_presets.write_filament("Test PLA X", "Generic PLA", {}, machine=m)
    # after a calibration: same file, same id, old one backed up
    r2 = user_presets.write_filament("Test PLA X", name, {"filament_flow_ratio": "0.95"}, machine=m, replace=True)
    d2 = json.load(open(r2["file"]))
    assert r2["file"] == path and r2["filament_id"] == fid and d2["filament_flow_ratio"] == ["0.95"]
    assert d2["nozzle_temperature"] == ["215"] and r2["backup"].startswith(str(studio_user / "backups"))
    assert len(list((studio_user / "backups").glob("*.json"))) == 1
    # a tweak of a Bambu filament stays a child of it, so RFID spools still match
    r3 = user_presets.write_filament("My Bambu PLA", "Bambu PLA Basic @BBL P1S 0.4 nozzle", {"nozzle_temperature": "225"})
    d3 = json.load(open(r3["file"]))
    assert "filament_id" not in r3 and d3["inherits"] == "Bambu PLA Basic @BBL P1S 0.4 nozzle" and "filament_id" not in d3
    # one value per extruder variant, as the parent has it, and a .info for Bambu Studio's cloud sync
    variants = presets.flat("filament", "Bambu PLA Basic @BBL P1S 0.4 nozzle")["filament_extruder_variant"]
    assert d3["nozzle_temperature"] == ["225"] * len(variants) and d3["filament_extruder_variant"] == variants
    info = user_presets.read_info(r3["file"])
    assert info["setting_id"] == "" and info["user_id"] == "123"
    assert info["base_id"] == presets.raw("filament", "Bambu PLA Basic @BBL P1S 0.4 nozzle")["setting_id"]


@needs_bambu
def test_pressure_advance_is_a_filament_setting_and_is_saved(studio_user):
    """Bambu's profiles never write pressure_advance: it used to be dropped (kind None) and 'saved' as nothing."""
    import json

    from mcp.server.mcpserver.exceptions import ToolError

    from unofficial_bambu_mcp import server as s
    s.new_project("k", "P1S", filaments=[{"preset": "Bambu PLA Basic", "color": "#FFFFFF"},
                                         {"preset": "Bambu PLA Matte", "color": "#000000"}])
    r = s.set_setting("pressure_advance", "0.025", slot=1)
    assert r["kind"] == "filament" and r["value"][0] == "0.025" and len(r["value"]) == 2 and r["value"][1] != "0.025"
    assert "M900" in r["pressure_advance_note"]                # Bambu printers take K from the AMS slot
    assert s.set_setting("enable_pressure_advance", "1", slot=1)["kind"] == "filament"
    cfg = s.P().config()
    assert cfg["pressure_advance"][0] == "0.025" and len(cfg["pressure_advance"]) == 2
    res = s.save_filament_preset(1, "PLA K test")
    assert res["values"] == {"pressure_advance": "0.025", "enable_pressure_advance": "1"}
    d = json.load(open(res["file"]))
    assert d["pressure_advance"] == ["0.025"] and d["enable_pressure_advance"] == ["1"]
    # a project with the new preset gets its K; with nothing changed, replace fails and the file stays as it is
    s.new_project("k2", "P1S", filaments=[{"preset": "PLA K test", "color": "#FFFFFF"}])
    assert s.P().config()["pressure_advance"] == ["0.025"]
    before = open(res["file"]).read()
    with pytest.raises(ToolError, match="no changes"):
        s.save_filament_preset(1, "PLA K test", replace=True)
    assert open(res["file"]).read() == before
    # changed directly in the preset, then saved again from a project
    s.edit_preset("filament", "PLA K test", {"pressure_advance": "0.03"})
    assert json.load(open(res["file"]))["pressure_advance"] == ["0.03"]
    s.new_project("k3", "P1S", filaments=[{"preset": "PLA K test", "color": "#FFFFFF"}])
    s.set_setting("pressure_advance", "0.028", slot=1)
    s.save_filament_preset(1, "PLA K test", replace=True)
    d = json.load(open(res["file"]))
    assert d["pressure_advance"] == ["0.028"] and d["enable_pressure_advance"] == ["1"]


@needs_bambu
def test_process_and_printer_presets_edit_rename_delete(studio_user):
    import json

    from mcp.server.mcpserver.exceptions import ToolError

    from unofficial_bambu_mcp import presets, user_presets
    from unofficial_bambu_mcp import server as s
    s.new_project("p", "P1S")
    parent = s.P().process
    s.set_setting("wall_loops", "4")
    s.set_setting("brim_type", "no_brim")
    s.set_setting("inner_wall_speed", "250")
    s.set_setting("nozzle_temperature", "215")                 # a filament setting: not in the process preset
    res = s.save_process_preset("My strong")
    d = json.load(open(res["file"]))
    assert d["inherits"] == parent and d["print_settings_id"] == "My strong" and "nozzle_temperature" not in d
    assert d["wall_loops"] == "4" and d["brim_type"] == "no_brim"
    variants = presets.flat("process", parent)["print_extruder_variant"]
    assert d["inner_wall_speed"] == ["250"] * len(variants) and d["print_extruder_variant"] == variants
    with pytest.raises(ToolError, match="already exists"):
        s.save_process_preset("My strong")
    s.set_setting("machine_start_gcode", ";hello")
    p2 = s.save_printer_preset("My P1S")["file"]
    d2 = json.load(open(p2))
    assert d2["inherits"] == "Bambu Lab P1S 0.4 nozzle" and d2["machine_start_gcode"] == ";hello"
    assert d2["printer_settings_id"] == "My P1S" and "wall_loops" not in d2
    # edited directly: checked, shaped, backed up; None goes back to the parent's value
    e = s.edit_preset("process", "My strong", {"sparse_infill_density": "25%", "wall_loops": None,
                                               "outer_wall_speed": ["150"] * len(variants)})
    d = json.load(open(res["file"]))
    assert d["sparse_infill_density"] == "25%" and "wall_loops" not in d and d["outer_wall_speed"] == ["150"] * len(variants)
    assert e["values"]["wall_loops"] == presets.flat("process", parent)["wall_loops"] and e["backup"]
    with pytest.raises(ToolError, match="is a number"):
        s.edit_preset("process", "My strong", {"wall_loops": "many"})
    with pytest.raises(ToolError, match="filament setting"):
        s.edit_preset("process", "My strong", {"nozzle_temperature": "200"})
    with pytest.raises(ToolError, match="takes 1 value or"):
        s.edit_preset("process", "My strong", {"outer_wall_speed": ["1"] * (len(variants) + 1)})
    with pytest.raises(ToolError, match="system preset"):
        s.edit_preset("process", parent, {"wall_loops": "3"})
    listed = {(p["kind"], p["name"]): p for p in s.list_user_presets()}
    assert listed[("process", "My strong")]["changes"]["sparse_infill_density"] == "25%"
    assert listed[("printer", "My P1S")]["in_cloud"] is False
    # only on this computer: renamed and deleted (with a backup)
    s.rename_preset("process", "My strong", "My strong 2")
    assert presets.exists("process", "My strong 2") and not presets.exists("process", "My strong")
    s.delete_preset("printer", "My P1S")
    assert not presets.exists("machine", "My P1S") and not list((studio_user / "studio").glob("user/123/machine/My P1S.*"))
    # in the cloud: Bambu Studio would download it again, so it is refused; an edit is marked to be uploaded
    path = presets.path_of("process", "My strong 2")
    info = user_presets.read_info(path)
    info["setting_id"] = "PPUS0123456789"
    user_presets._write_info(path, info)
    for call in (lambda: s.delete_preset("process", "My strong 2"),
                 lambda: s.rename_preset("process", "My strong 2", "Other")):
        with pytest.raises(ToolError, match="Bambu cloud"):
            call()
    assert presets.exists("process", "My strong 2")
    s.edit_preset("process", "My strong 2", {"wall_loops": "3"})
    assert user_presets.read_info(path)["sync_info"] == "update"


@needs_bambu
def test_presets_deleted_in_bambu_studio_while_running(studio_user):
    """Bambu Studio deletes a user preset while the server runs: lists, edits and projects see it gone."""
    import os

    from mcp.server.mcpserver.exceptions import ToolError

    from unofficial_bambu_mcp import server as s
    s.new_project("d", "P1S", filaments=[{"preset": "Bambu PLA Basic", "color": "#FFFFFF"}])
    s.set_setting("nozzle_temperature", "212", slot=1)
    path = s.save_filament_preset(1, "Gone PLA")["file"]
    s.new_project("d2", "P1S", filaments=[{"preset": "Gone PLA", "color": "#FFFFFF"}])
    assert "Gone PLA" in {p["name"] for p in s.list_user_presets()}
    os.remove(path)                                            # what Bambu Studio's Delete does
    os.remove(path[:-5] + ".info")
    assert "Gone PLA" not in {p.get("name") for p in s.list_user_presets()}
    for call in (lambda: s.edit_preset("filament", "Gone PLA", {"nozzle_temperature": "210"}),
                 lambda: s.rename_preset("filament", "Gone PLA", "Back PLA"),
                 lambda: s.delete_preset("filament", "Gone PLA")):
        with pytest.raises(ToolError, match="no user filament preset named 'Gone PLA'"):
            call()
    with pytest.raises(ToolError, match="slot 1 no longer exists"):
        s.get_project()
    s.set_filament(1, "Bambu PLA Basic")
    assert s.get_project()["filaments"][0]["preset"].startswith("Bambu PLA Basic")


def test_orient_stands_a_lying_cylinder_and_keeps_a_good_one():
    import math

    from unofficial_bambu_mcp import orient
    v, t = geometry.cylinder(20, 60)
    current, opts = orient.options(geometry.rotate(v, 90, "x"), t)          # lying on its side
    assert current["support_mm2"] > 500 and opts[0]["support_mm2"] < 1
    assert abs(opts[0]["on_bed_mm2"] - math.pi * 100) < 5 and abs(opts[0]["height_mm"] - 60) < 0.1
    current, opts = orient.options(v, t)                                     # standing: already the best
    assert np.allclose(opts[0]["rotation"], np.eye(3))
    assert len({(round(o["support_mm2"]), round(o["on_bed_mm2"])) for o in opts}) == len(opts)   # no twins


@needs_bambu
def test_fill_plate_with_copies(tmp_path, monkeypatch):
    from shapely import affinity

    from unofficial_bambu_mcp import arrange
    from unofficial_bambu_mcp import server as s
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    s.new_project("fill", "P1S")
    s.add_shape("cylinder", diameter=30, height=5, name="coin")
    s.add_shape("box", width=60, depth=60, height=10, name="block", x=60, y=200)
    block_at = s.P().find("block")[1].at
    r = s.fill_plate("coin")
    pr = s.P()
    assert r["copies_added"] >= 30 and pr.find("block")[1].at == block_at          # the other object stays
    placed = [(o.name, affinity.translate(arrange.footprint(o, pr.config()), *o.at)) for o in pr.plates[0].objects]
    assert arrange.check(placed, pr.info["bed"], 6.0, None) == []                     # nothing closer than the gap
    s.new_project("fill2", "P1S")
    s.add_shape("box", width=20, depth=10, height=5, name="tag", x=50, y=50)
    assert s.fill_plate("tag", copies=5, keep_original=True)["copies_added"] == 5
    assert s.P().find("tag")[1].at == (50.0, 50.0)


@needs_bambu
def test_split_merge_and_boolean(tmp_path, monkeypatch):
    import math

    from mcp.server.mcpserver.exceptions import ToolError

    from unofficial_bambu_mcp import server as s
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    s.new_project("ops", "P1S")
    s.add_shape("box", width=40, depth=40, height=20, name="block", x=80, y=80)
    s.add_shape("box", width=10, depth=10, height=10, name="small", x=160, y=160)
    with pytest.raises(ToolError, match="single piece"):
        s.split_object("block")
    m = s.merge_objects(["block", "small"], name="pair")
    assert m["parts"] == ["block", "small"] and len(s.P().plates[0].objects) == 1
    r = s.split_object("pair")                                   # back where they were, named after their parts
    pr = s.P()
    assert [x["name"] for x in r["result"]] == ["block", "small"]
    assert pr.find("block")[1].at == (80.0, 80.0) and pr.find("small")[1].at == (160.0, 160.0)
    # one part made of two separate boxes: into parts, each keeps the part's filament
    from unofficial_bambu_mcp.project import Obj, Part
    v, t = geometry.box(10, 10, 10)
    twin = Obj("twin", [Part("twin", np.vstack([v, v + [30, 0, 0]]), np.vstack([t, t + len(v)]), filament=1)],
               at=(100.0, 200.0))
    pr.plates[0].objects.append(twin)
    r = s.split_object("twin", into="parts")
    assert r["parts"] == ["twin 1", "twin 2"] and len(pr.find("twin")[1].parts) == 2
    # a hole through the block: exact volume, painting kept on the untouched faces, the tool removed
    s.new_project("bool", "P1S")
    s.add_shape("box", width=40, depth=40, height=20, name="block", x=100, y=100)
    blk = s.P().find("block")[1].parts[0]
    blk.tri_attrs = {"paint_color": ["8"] * len(blk.tris)}
    s.add_shape("cylinder", diameter=10, height=30, name="drill", x=100, y=100)
    r = s.boolean_objects("block", "drill", "difference")
    after = r["volume_mm3"]["block"]["after"]
    assert abs(after - (32000 - math.pi * 25 * 20)) < 40 and r["tool_object"] == "removed"
    part = s.P().find("block")[1].parts[0]
    colors = part.tri_attrs["paint_color"]
    assert colors.count("8") >= 10 and "" in colors                 # old faces painted, the hole's faces not
    s.add_shape("box", width=10, depth=10, height=10, name="far", x=200, y=200)
    assert "do not touch" in s.boolean_objects("block", "far", "union", keep_tool=True)["warning"]
    s.add_shape("box", width=40, depth=10, height=10, name="bar", x=100, y=100)
    r = s.boolean_objects("block", "bar", "intersection")
    assert 0 < r["volume_mm3"]["block"]["after"] < 4000


@needs_bambu
def test_vfa_test_and_cost(tmp_path, monkeypatch):
    from unofficial_bambu_mcp import server as s
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    s.new_project("vfa", "P1S", filaments=[{"preset": "Bambu PLA Basic", "color": "#FFFFFF"}])
    r = s.make_vfa_test(1, start=60, end=120, step=20)
    objs = s.P().plates[0].objects
    assert r["speeds_mm_s"] == [60, 80, 100, 120] and [o.settings["outer_wall_speed"] for o in objs] == ["60", "80", "100", "120"]
    assert s.check_print_risks()[0]["risks"] == "none found" and "note" not in r
    s.set_setting("filament_max_volumetric_speed", "5", slot=1)          # 5 / (0.42 × 0.2) ≈ 60 mm/s
    assert "about 60 mm/s" in s.make_vfa_test(1, start=60, end=120, step=20)["note"]
    s.new_project("cost", "P1S", filaments=[{"preset": "Bambu PLA Basic", "color": "#FFFFFF"}])
    s.add_shape("box", width=20, depth=20, height=10, name="cube")
    s.set_setting("filament_cost", "30", slot=1)
    p = s.slice_project(1)["plates"][0]
    assert abs(p["cost"] - p["grams_per_filament"][1] * 30 / 1000) < 0.011 and p["cost_per_filament"] == {1: p["cost"]}


def test_sd_card_listing_frames_and_camera():
    import struct
    import time

    from unofficial_bambu_mcp import camera, sdcard
    now = time.mktime((2026, 10, 27, 12, 0, 0, 0, 0, -1))
    rows = ["drw-rw-rw-   1 root  root         0 Mar 01 2026 thumbnail",
            "-rw-rw-rw-   1 root  root     68664 Oct 26 20:40 video_2026-10-26_20-38-21.avi",
            "-rw-rw-rw-   1 root  root   3161586 Sep 23 2025 video_2025-09-23_18-41-25.avi",
            "-rw-rw-rw-   1 root  root       100 Dec 30 10:00 old one.avi"]                      # last year
    files = sdcard.parse_list(rows, now)
    assert [f["name"] for f in files] == ["video_2026-10-26_20-38-21.avi", "old one.avi",
                                          "video_2025-09-23_18-41-25.avi"]
    assert files[0]["size"] == 68664 and files[0]["date"] == "2026-10-26 20:40" and files[1]["date"].startswith("2025-12-30")
    a, b = sdcard.confirm_code("timelapse", ["x.avi", "y.avi"]), sdcard.confirm_code("timelapse", ["y.avi", "x.avi"])
    assert a == b and a.startswith("delete 2 files ") and a != sdcard.confirm_code("timelapse", ["x.avi"])
    jpg = b"\xff\xd8\xff\xe0" + b"a" * 2000 + b"\xff\xd9"
    avi = b"RIFF....AVI " + jpg.replace(b"a", b"b") + b"idx" + jpg + b"tail"
    assert sdcard.last_frame(avi) == jpg

    class Sock:
        def __init__(self, data):
            self.data = data

        def recv(self, n):
            out, self.data = self.data[:n], self.data[n:]
            return out
    assert camera.read_frame(Sock(struct.pack("<IIII", len(jpg), 0, 0, 0) + jpg)) == jpg
    assert len(camera.login_packet("12345678")) == 80


def test_delete_printer_files_asks_first(tmp_path, monkeypatch):
    import contextlib

    from mcp.server.mcpserver.exceptions import ToolError

    from unofficial_bambu_mcp import printer, sdcard
    from unofficial_bambu_mcp import server as s
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    card = {"/timelapse": ["-rw-rw-rw-   1 root  root   5000000 Oct 01 2025 video_old.avi",
                           "-rw-rw-rw-   1 root  root   1000000 Oct 26 20:40 video_new.avi"],
            "/timelapse/thumbnail": ["-rw-rw-rw-   1 root  root   20000 Oct 01 2025 video_old.jpg",
                                     "-rw-rw-rw-   1 root  root   20000 Mar 01 2025 video_gone.jpg"]}
    deleted = []

    class FakeFTP:
        def retrlines(self, cmd, cb):
            for row in card[cmd.split(" ", 1)[1]]:
                cb(row)

        def delete(self, path):
            deleted.append(path)
            folder, name = path.rsplit("/", 1)
            card[folder] = [r for r in card[folder] if not r.endswith(" " + name)]

    monkeypatch.setattr(sdcard, "session", contextlib.contextmanager(lambda serial=None: (yield FakeFTP())))
    state = {"gcode_state": "FINISH"}
    monkeypatch.setattr(printer, "status", lambda serial=None, max_age=20.0: (state, "SERIAL"))
    assert s.printer_files("thumbnails")["thumbnails"]["files"] == 1          # only the one without its video
    first = s.delete_printer_files("timelapse", older_than_days=100)
    assert [f["name"] for f in first["would_delete"]] == ["video_old.avi"] and first["frees_mb"] == 5.0
    assert deleted == []                                                     # nothing goes without the code
    with pytest.raises(ToolError, match="does not match"):
        s.delete_printer_files("timelapse", older_than_days=100, confirm="delete 1 files 0000")
    state["gcode_state"] = "RUNNING"
    with pytest.raises(ToolError, match="printing"):
        s.delete_printer_files("timelapse", older_than_days=100, confirm=first["confirm"])
    state["gcode_state"] = "FINISH"
    done = s.delete_printer_files("timelapse", older_than_days=100, confirm=first["confirm"])
    assert done["deleted"] == 1 and done["left"] == 1
    assert deleted == ["/timelapse/video_old.avi", "/timelapse/thumbnail/video_old.jpg"]
    with pytest.raises(ToolError, match="not on the SD card"):
        s.delete_printer_files("timelapse", names=["../etc"])


@needs_bambu
def test_prime_tower_place_kept_from_file(tmp_path, monkeypatch):
    """Bambu Studio never lists wipe_tower_x/y among the changed settings, but slices with them."""
    import json
    import zipfile

    from unofficial_bambu_mcp import server as s
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    s.new_project("tower", "P1S", filaments=[{"preset": "Bambu PLA Basic", "color": "#FFFFFF"},
                                             {"preset": "Bambu PLA Basic", "color": "#000000"}])
    s.add_shape("box", width=30, depth=30, height=5, name="a", filament=1, x=60, y=60)
    s.add_shape("box", width=30, depth=30, height=5, name="b", filament=2, x=180, y=60)
    saved = s.save_project()["saved"]
    moved = str(tmp_path / "moved.3mf")                    # the tower moved by hand in Bambu Studio
    with zipfile.ZipFile(saved) as zin, zipfile.ZipFile(moved, "w") as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "Metadata/project_settings.config":
                cfg = json.loads(data)
                cfg["wipe_tower_x"], cfg["wipe_tower_y"] = ["120.5"], ["130"]
                data = json.dumps(cfg).encode()
            zout.writestr(item, data)
    s.open_project(moved)
    assert s.get_setting("wipe_tower_x")["value"] == ["120.5"] and s.get_setting("wipe_tower_y")["value"] == ["130"]
    assert s.get_project()["plates"][0]["prime_tower_xy"] == [120.5, 130.0]
    with zipfile.ZipFile(s.save_project()["saved"]) as z:
        cfg = json.loads(z.read("Metadata/project_settings.config"))
    assert cfg["wipe_tower_x"] == ["120.5"] and cfg["wipe_tower_y"] == ["130"]
    s.arrange()                                            # arranging frees a corner for it again
    assert s.get_setting("wipe_tower_x")["value"] != ["120.5"] and "prime_tower_xy" not in s.get_project()["plates"][0]


def test_split_at_keeps_a_closed_solid_and_painting():
    from unofficial_bambu_mcp import painting
    v, t = geometry.cylinder(20, 30, segments=24)
    attrs = {"paint_color": ["8"] * len(t)}
    v2, t2, a2 = painting.split_at(v, t, 12.0, attrs)
    m0, m1 = geometry.to_manifold(v, t), geometry.to_manifold(v2, t2)
    assert m1.status() == geometry.m3.Error.NoError and abs(m1.volume() - m0.volume()) < 1e-3
    assert len(t2) > len(t) and a2["paint_color"] == ["8"] * len(t2)                # whole leaves stay as they are
    assert np.isclose(v2[:, 2], 12.0).sum() == 48              # on each side: the vertical edge and the diagonal


def test_slicer_closes_a_stuck_bambu_studio(monkeypatch):
    import time

    from unofficial_bambu_mcp import slicer
    if slicer._cpu_seconds(os.getpid()) is None:
        pytest.skip("CPU time cannot be read here")
    import sys
    monkeypatch.setattr(slicer, "STALL_S", 4)
    t = time.time()
    with pytest.raises(slicer.SliceError, match="no CPU use"):
        slicer.run([sys.executable, "-c", "import time; time.sleep(60)"], timeout=60)
    assert time.time() - t < 25
    assert slicer.run([sys.executable, "-c", "print('ok')"], timeout=30) == (0, "ok\n")


@needs_bambu
def test_height_ranges_plate_settings_and_painting(tmp_path, monkeypatch):
    import zipfile

    from mcp.server.mcpserver.exceptions import ToolError

    from unofficial_bambu_mcp import server as s
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    s.new_project("p3", "P1S", filaments=[{"preset": "Bambu PLA Basic", "color": "#FFFFFF"},
                                          {"preset": "Bambu PLA Basic", "color": "#FF0000"}])
    s.add_shape("box", width=20, depth=20, height=20, name="cube")
    s.set_height_range("cube", 0, 5, {"sparse_infill_density": "100%"})
    s.set_height_range("cube", 10, 25, {"layer_height": "0.12", "filament": 2})       # clipped to the top
    r = s.set_height_range("cube", 0, 5, {"wall_loops": "4", "sparse_infill_density": None})   # same band: updated
    assert r["height_ranges"] == [{"from": 0.0, "to": 5.0, "settings": {"wall_loops": "4"}},
                                  {"from": 10.0, "to": 20.0, "settings": {"layer_height": "0.12", "filament": "2"}}]
    with pytest.raises(ToolError, match="overlaps"):
        s.set_height_range("cube", 4, 12, {"wall_loops": "3"})
    with pytest.raises(ToolError, match="filament setting"):
        s.set_height_range("cube", 5, 8, {"nozzle_temperature": "230"})
    s.set_plate_settings(1, bed_type="High Temp Plate", print_sequence="by object", first_layer_filaments=[2, 1],
                         spiral_vase="off", prime_tower=[100, 150])
    with pytest.raises(ToolError, match="bed_type"):
        s.set_plate_settings(1, bed_type="Glass")
    print(s.paint_object("cube", "color", filament=2, z_from=2, z_to=4))
    s.paint_object("cube", "fuzzy_skin", facing="sides")
    saved = s.save_project()["saved"]
    with zipfile.ZipFile(saved) as z:
        xml = z.read("Metadata/layer_config_ranges.xml").decode()
        ms = z.read("Metadata/model_settings.config").decode()
    assert xml.count("<range") == 2 and 'opt_key="extruder">0<' in xml and 'opt_key="layer_height">0.2<' in xml
    assert 'key="first_layer_print_sequence" value="2 1"' in ms and 'key="spiral_mode" value="false"' in ms
    s.open_project(saved)
    o = s.P().find("cube")[1]
    assert [r["from"] for r in o.height_ranges] == [0.0, 10.0] and o.height_ranges[1]["settings"]["extruder"] == "2"
    pl = s.get_project()["plates"][0]
    assert pl["settings"]["bed_type"] == "High Temp Plate" and pl["prime_tower_xy"] == [100.0, 150.0]
    part = o.parts[0]
    assert any(part.tri_attrs["paint_color"]) and any(part.tri_attrs["paint_fuzzy_skin"])
    zc = part.verts[part.tris][:, :, 2].mean(axis=1) - part.verts[:, 2].min()
    red = np.array([x != "" for x in part.tri_attrs["paint_color"]])
    assert red.any() and (zc[red] > 2 - 1e-6).all() and (zc[red] < 4 + 1e-6).all()   # sharp band edges
    assert s.remove_height_range("cube")["removed"] == 2
    o.layer_profile = [0, 0.2, 10, 0.1, 20, 0.2]
    s.transform_object("cube", rotate_z=30)
    assert o.layer_profile                                                    # same height: kept
    s.transform_object("cube", scale=2)
    assert o.layer_profile == []                                              # made for the old height


@needs_bambu
def test_small_object_tools(tmp_path, monkeypatch):
    import zipfile

    from mcp.server.mcpserver.exceptions import ToolError

    from unofficial_bambu_mcp import server as s
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    s.new_project("small", "P1S")
    s.add_shape("box", width=20, depth=20, height=10, name="a", x=50, y=60)
    s.add_shape("box", width=30, depth=10, height=10, name="b", x=120, y=90)
    s.add_shape("cylinder", diameter=15, height=10, name="c", x=200, y=40)
    s.align_objects(["a", "b", "c"], align="front")
    s.align_objects(["a", "b", "c"], distribute="x")
    pr = s.P()
    assert [pr.find(n)[1].footprint()[1] for n in "abc"] == [32.5, 32.5, 32.5]          # same front edge
    xs = sorted(pr.find(n)[1].footprint() for n in "abc")
    assert abs((xs[1][0] - xs[0][2]) - (xs[2][0] - xs[1][2])) < 1e-6                   # equal gaps
    # not printable: kept in the file, left out of the print
    s.set_object_printable("b", False)
    with zipfile.ZipFile(s.save_project()["saved"]) as z:
        assert z.read("3D/3dmodel.model").decode().count('printable="0"') == 1
    s.open_project(s.S.saved)
    assert next(o for pl in s.get_project()["plates"] for o in pl["objects"] if o["name"] == "b")["printable"] is False
    s.set_object_setting("a", "wall_loops", "4")
    s.set_object_setting("a", "sparse_infill_density", "40%")
    assert s.copy_object_settings("a", ["c"], keys=["wall_loops"])["settings"] == {"wall_loops": "4"}
    assert s.P().find("c")[1].settings == {"wall_loops": "4"}
    with pytest.raises(ToolError, match="no settings of its own"):
        s.copy_object_settings("b", ["c"])
    # STL out, one per object (centered) or all as placed
    files = s.export_stl()["files"]
    assert len(files) == 3 and all(os.path.exists(f["file"]) for f in files)
    v, t = geometry.load_stl(files[0]["file"])
    assert abs(v[:, 2].min()) < 1e-6 and np.allclose((v.min(0)[:2] + v.max(0)[:2]) / 2, 0, atol=1e-4)
    one = s.export_stl(plate=1, one_file=True)["files"][0]["file"]
    assert len(geometry.load_stl(one)[1]) == sum(len(geometry.load_stl(f["file"])[1]) for f in files)
    # inches, and a new shape for a part
    geometry.save_stl(str(tmp_path / "inch.stl"), *geometry.box(1, 2, 0.5))
    hint = s.import_model(str(tmp_path / "inch.stl"))[0]["hint"]
    assert "convert_units" in hint
    assert s.convert_units("inch", "inch")["size_mm"] == [25.4, 50.8, 12.7]
    assert s.convert_units("inch", "inch", restore=True)["size_mm"] == [1.0, 2.0, 0.5]
    at = s.P().find("a")[1].at
    geometry.save_stl(str(tmp_path / "new.stl"), *geometry.cylinder(25, 12))
    r = s.replace_with_stl("a", str(tmp_path / "new.stl"))
    assert r["new_size_mm"] == [25.0, 25.0, 12.0] and s.P().find("a")[1].at == at
    # part types
    s.merge_objects(["b", "c"], name="bc")
    assert s.set_part_type("bc", "c", "negative")["now"] == "negative_part"
    with pytest.raises(ToolError, match="only printed part"):
        s.set_part_type("bc", "b", "modifier")
    assert s.set_part_type("bc", "c", "part")["now"] == "normal_part"


@needs_bambu
def test_measure_object_and_between(tmp_path, monkeypatch):
    from unofficial_bambu_mcp import server as s
    from unofficial_bambu_mcp.project import Obj, Part
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    s.new_project("measure", "P1S")
    m = geometry.to_manifold(*geometry.box(40, 20, 10))
    m = m + geometry.to_manifold(*geometry.box(0.3, 15, 8)).translate((-10, 0, 10))     # a fin too thin to print
    m = m + geometry.to_manifold(*geometry.box(0.8, 15, 8)).translate((0, 0, 10))       # a fin that prints
    m = m - geometry.to_manifold(*geometry.cylinder(6, 30)).translate((12, 0, -5))      # a 6 mm hole
    m = m + geometry.to_manifold(*geometry.box(5, 20, 4)).translate((22.8, 0, 0))       # a block 0.3 mm away
    v, t = geometry.from_manifold(m)
    s.P().plates[0].objects.append(Obj("piece", [Part("piece", v, t)], at=(100.0, 100.0)))
    r = s.measure_object("piece", z=5)
    assert r["pieces"] == 2 and abs(r["smallest_gaps"][0]["gap_mm"] - 0.3) < 0.01
    spots = r["thin_walls"]["where"]
    assert len(spots) == 1 and abs(spots[0]["about_mm"] - 0.3) < 0.05 and spots[0]["z_from"] > 10
    big = r["section"]["islands"][0]
    assert big["length_mm"] == 40.0 and big["width_mm"] == 20.0 and big["holes"][0]["round_diameter_mm"] == 6.0
    fin = s.measure_object("piece", z=14)["section"]["islands"]
    assert sorted(round(i["width_mm"], 2) for i in fin) == [0.3, 0.8]                      # how thick each fin is
    s.add_shape("box", width=10, depth=10, height=10, name="cube", x=140, y=100)
    b = s.measure_between("piece", "cube")
    assert abs(b["gap_mm"] - b["box_gap_xyz"][0]) < 0.01 and b["gap_mm"] > 5 and "overlap_mm3" not in b
    s.add_shape("box", width=10, depth=10, height=10, name="inside", x=100, y=100)
    assert s.measure_between("piece", "inside")["overlap_mm3"] > 900


def test_svg_shapes(tmp_path):
    import math

    from unofficial_bambu_mcp import svg
    f = tmp_path / "t.svg"
    f.write_text('''<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="50mm" viewBox="0 0 200 100">
      <g transform="translate(10 10) scale(2)">
        <rect x="0" y="0" width="10" height="20"/>
        <circle cx="40" cy="10" r="10"/>
        <path d="M 60 0 h 20 v 20 h -20 Z M 65 5 h 10 v 10 h -10 Z" fill-rule="evenodd"/>
        <path d="M 0 30 A 5 5 0 0 0 10 30 Z" fill="none" stroke="#000" stroke-width="1"/>
      </g>
      <rect x="0" y="0" width="5" height="5" style="display:none"/>
    </svg>''')
    shape, (w, h) = svg.load(str(f))
    # user unit = 0.5 mm and the group scales by 2: 1 mm per unit. Rect 10 x 20, circle r 10, a 20 mm square with
    # a 10 mm hole, and the stroke (1 mm wide) of a half circle of radius 5
    stroke, rect, square, circle = sorted(getattr(shape, "geoms", [shape]), key=lambda g: g.area)
    assert abs(rect.area - 200) < 0.5 and abs(circle.area - math.pi * 100) < 2
    assert abs(square.area - 300) < 0.5 and len(square.interiors) == 1
    assert abs(stroke.area - (math.pi * 5 + 10)) < 2                     # half circle + its diameter, 1 mm wide
    assert abs(w - 80.5) < 0.1 and abs(np.mean(shape.bounds[::2])) < 1e-6


def test_relief_wraps_around_curves():
    """Text on the side of a cup keeps its width along the surface and stands out straight from it, also off
    center; a step under it does not swallow part of it; on a slope it keeps its size along the slope."""
    from unofficial_bambu_mcp import relief
    v, t = geometry.cylinder(30, 40)
    tea = geometry.text_outline("TEA", 7, None)
    width = tea.bounds[2] - tea.bounds[0]
    for cu in (0.0, 4.0, 8.0):                                  # 8: projected flat, it would not fit on the cup
        tv, tt, info = relief.build(v, t, tea, "front", (cu, 20.0), 0.8)
        ang = np.arctan2(tv[:, 0], -tv[:, 1])
        r = np.hypot(tv[:, 0], tv[:, 1])
        assert abs(np.ptp(ang) * 15 - width) < 0.2 and info["surface_relief_mm"] > 1
        assert abs(np.degrees((ang.min() + ang.max()) / 2) - np.degrees(np.arcsin(cu / 15))) < 1
        side = ang > np.radians(30)
        assert abs(r[side].max() - 15.8) < 0.05 and r.min() > 14.65 and r.max() < 15.85    # 0.8 out, square to it
        assert geometry.check(tv, tt)["manifold"]
    m3 = geometry.m3
    step = m3.Manifold.cube((40, 20, 10)) + m3.Manifold.cube((20, 20, 2)).translate((20, 0, 10))
    hello = geometry.text_outline("HELLO", 6, None)
    tv, tt, _ = relief.build(*geometry.from_manifold(step), hello, "top", (20.0, 10.0), 1.0)
    assert abs(np.ptp(tv[:, 0]) - (hello.bounds[2] - hello.bounds[0])) < 0.1
    roof = m3.Manifold.extrude(m3.CrossSection([[(0, 0), (40, 0), (0, 40 * math.tan(math.radians(30)))]]), 20)
    slope = m3.Manifold.cube((40, 20, 10)) + roof.rotate((90, 0, 0)).translate((0, 20, 10))
    tv, tt, _ = relief.build(*geometry.from_manifold(slope), hello, "top", (20.0, 10.0), 1.0)
    along = np.ptp(tv[:, 0]) / math.cos(math.radians(30))
    assert abs(along - (hello.bounds[2] - hello.bounds[0])) < 1.0      # projected flat it was 15% longer


@needs_bambu
def test_relief_on_flat_and_curved_faces(tmp_path, monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError

    from unofficial_bambu_mcp import server as s
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    s.new_project("relief", "P1S", filaments=[{"preset": "Bambu PLA Basic", "color": "#FFFFFF"},
                                             {"preset": "Bambu PLA Basic", "color": "#D02020"}])
    s.add_shape("box", width=60, depth=30, height=10, name="tag", x=70, y=70)
    r = s.add_relief("tag", text="HI", size=10, depth=1.0, filament=2)
    o = s.P().find("tag")[1]
    text = o.parts[-1]
    assert r["type"] == "raised" and text.filament == 2 and r["surface_relief_mm"] == 0
    assert geometry.check(text.verts, text.tris)["manifold"]
    assert abs(text.verts[:, 2].max() - (o.parts[0].verts[:, 2].max() + 1.0)) < 1e-3      # 1 mm above the top
    s.add_shape("cylinder", diameter=40, height=30, name="cup", x=180, y=70)
    r = s.add_relief("cup", text="TEA", face="front", size=8, depth=0.8, engrave=True)
    cut = s.P().find("cup")[1].parts[-1]
    assert cut.subtype == "negative_part" and r["surface_relief_mm"] > 2                  # it followed the curve
    assert geometry.check(cut.verts, cut.tris)["manifold"]
    with pytest.raises(ToolError, match="does not reach"):
        s.add_relief("tag", text="TOO LONG FOR IT", size=10, depth=1.0)
    f = tmp_path / "logo.svg"
    f.write_text('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10"><circle cx="5" cy="5" r="5"/></svg>')
    r = s.add_shape("svg", svg=str(f), size=30, height=1.5, base=2, filament=2, base_filament=1)
    assert r["size_mm"][2] == 3.5 and [p.name for p in s.P().find(r["name"])[1].parts] == ["Base", "Logo"]


@needs_bambu
def test_every_printer_family_presets_and_two_nozzles(tmp_path, monkeypatch):
    """P1P filaments live in a subfolder (filament/P1P/); two-nozzle printers keep every variant of each filament."""
    import zipfile

    from unofficial_bambu_mcp import presets, slicer
    from unofficial_bambu_mcp import server as s
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    assert presets.filament_for("Bambu PLA Basic", "Bambu Lab P1P 0.4 nozzle") == "Bambu PLA Basic @BBL P1P"
    s.new_project("h2d", "Bambu Lab H2D 0.4 nozzle", filaments=[{"preset": "Bambu PLA Basic", "color": "#FFFFFF"},
                                                                {"preset": "Bambu PLA Basic", "color": "#202020"}])
    s.add_shape("box", width=20, depth=20, height=6, name="a", filament=1)
    s.add_shape("box", width=20, depth=20, height=6, name="b", filament=2)
    assert s.set_setting("nozzle_temperature", "215", slot=2)["value"] == ["220", "215"]       # one value per slot
    cfg = s.P().config()
    k = len(cfg["filament_self_index"]) // 2
    assert cfg["filament_self_index"] == ["1"] * k + ["2"] * k and k > 1
    assert cfg["nozzle_temperature"] == ["220"] * k + ["215"] * k
    assert len(cfg["nozzle_volume_type"]) == 2 and len(cfg["extruder_nozzle_stats"]) == 2
    assert s.get_setting("nozzle_temperature")["value"] == ["220", "215"]
    r = s.slice_project(1)
    g = slicer.gcode(r["sliced_file"], 1)
    assert "; nozzle_temperature = 220,215" in g and r["plates"][0]["warnings"] == []
    s.open_project(s.save_project()["saved"])
    assert s.P().overrides["nozzle_temperature"] == ["220", "215"]
    with zipfile.ZipFile(r["sliced_file"]) as z:
        assert "Metadata/plate_1.gcode" in z.namelist()


def _cube_xml(oid, size):
    s = size
    vs = [(0, 0, 0), (s, 0, 0), (s, s, 0), (0, s, 0), (0, 0, s), (s, 0, s), (s, s, s), (0, s, s)]
    tris = [(0, 2, 1), (0, 3, 2), (4, 5, 6), (4, 6, 7), (0, 1, 5), (0, 5, 4), (1, 2, 6), (1, 6, 5),
            (2, 3, 7), (2, 7, 6), (3, 0, 4), (3, 4, 7)]
    v = "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in vs)
    t = "".join(f'<triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in tris)
    return f'<object id="{oid}" type="model"><mesh><vertices>{v}</vertices><triangles>{t}</triangles></mesh></object>'


def _old_3mf(path, files):
    import zipfile
    with zipfile.ZipFile(path, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return str(path)


CORE_NS = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PROD_NS = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"


@needs_bambu
def test_reads_bambu_studio_1_7_file_with_undeclared_prefix(tmp_path):
    """Like Bambu Studio 1.7 files: p:UUID on components, but no xmlns:p on <model>; an author's filament change
    on a filament that does not exist here is dropped, the one on a known filament kept."""
    import json

    from unofficial_bambu_mcp import threemf
    model = (f'<?xml version="1.0" encoding="UTF-8"?><model unit="millimeter" xmlns="{CORE_NS}" '
             f'xmlns:slic3rpe="http://schemas.slic3r.org/3mf/2017/06"><resources>{_cube_xml(1, 20)}'
             '<object id="2" type="model"><components><component objectid="1" p:UUID="00000001-aaaa" '
             'transform="1 0 0 0 1 0 0 0 1 0 0 0"/></components></object></resources>'
             '<build><item objectid="2" transform="1 0 0 0 1 0 0 0 1 118 118 0" printable="1"/></build></model>')
    ms = ('<config><object id="2"><metadata key="name" value="Cube A"/><part id="1" subtype="normal_part">'
          '<metadata key="name" value="cube"/></part></object><plate><metadata key="plater_id" value="1"/>'
          '<model_instance><metadata key="object_id" value="2"/><metadata key="instance_id" value="0"/>'
          '</model_instance></plate></config>')
    cfg = {"printer_settings_id": "Bambu Lab X1 Carbon 0.4 nozzle", "print_settings_id": "0.20mm Standard @BBL X1C",
           "filament_settings_id": ["Generic PLA", "Nonexistent PLA @Nowhere"], "filament_colour": ["#FF0000", "#00FF00"],
           "different_settings_to_system": ["brim_type", "nozzle_temperature", "nozzle_temperature", ""],
           "brim_type": "no_brim", "nozzle_temperature": ["205", "250"],
           "printable_area": ["0x0", "256x0", "256x256", "0x256"]}
    p = _old_3mf(tmp_path / "a.3mf", {"3D/3dmodel.model": model, "Metadata/model_settings.config": ms,
                                       "Metadata/project_settings.config": json.dumps(cfg)})
    pr = threemf.read(p)
    (_, o), = pr.objects()
    assert o.name == "Cube A" and (o.size() == np.array([20, 20, 20])).all()
    assert pr.overrides["brim_type"] == "no_brim"
    assert pr.overrides["nozzle_temperature"][0] == "205" and pr.overrides["nozzle_temperature"][1] != "250"
    assert any("nozzle_temperature" in w for w in pr.warnings)


@needs_bambu
def test_reads_bambu_studio_1_6_file_with_objects_in_separate_models(tmp_path):
    """Like Bambu Studio 1.6 files: build items point (p:path) to 3D/Objects/*.model, whose components have no path
    and the same ids in different files; the start G-code changed for an unknown printer is not carried over."""
    import json

    from unofficial_bambu_mcp import threemf
    head = f'<?xml version="1.0" encoding="UTF-8"?><model unit="millimeter" xmlns="{CORE_NS}" xmlns:p="{PROD_NS}" requiredextensions="p">'
    main = (head + '<resources/><build>'
            '<item objectid="7" p:path="/3D/Objects/Assembly_35.model" transform="1 0 0 0 1 0 0 0 1 90 118 0" printable="1"/>'
            '<item objectid="2" p:path="/3D/Objects/cube_1.model" transform="1 0 0 0 1 0 0 0 1 160 123 0" printable="1"/>'
            '</build></model>')
    asm = (head + f'<resources>{_cube_xml(3, 20)}<object id="7" type="model"><components>'
           '<component objectid="3" transform="1 0 0 0 1 0 0 0 1 0 0 0"/></components></object></resources><build/></model>')
    cube = (head + f'<resources>{_cube_xml(3, 10)}<object id="2" type="model"><components>'
            '<component objectid="3" transform="1 0 0 0 1 0 0 0 1 0 0 0"/></components></object></resources><build/></model>')
    ms = ('<config><object id="7"><metadata key="name" value="Assembly"/><metadata key="brim_type" value="outer_only"/>'
          '<part id="3" subtype="normal_part"><metadata key="name" value="big"/></part></object>'
          '<object id="2"><metadata key="name" value="Cube B"/><part id="3" subtype="normal_part">'
          '<metadata key="name" value="small"/><metadata key="extruder" value="2"/></part></object>'
          '<plate><metadata key="plater_id" value="1"/>'
          '<model_instance><metadata key="object_id" value="7"/><metadata key="instance_id" value="0"/></model_instance>'
          '<model_instance><metadata key="object_id" value="2"/><metadata key="instance_id" value="0"/></model_instance>'
          '</plate></config>')
    cfg = {"printer_settings_id": "Bambu Lab X1 0.4 nozzle - no prime line", "print_settings_id": "0.20mm Standard @BBL X1C",
           "filament_settings_id": ["Generic PLA", "Generic TPU"], "filament_colour": ["#FFFFFF", "#000000"],
           "different_settings_to_system": ["sparse_infill_density", "", "", "machine_start_gcode"],
           "sparse_infill_density": "5%", "machine_start_gcode": "M973 S3 P1 ; lidar of the X1",
           "printable_area": ["0x0", "256x0", "256x256", "0x256"]}
    p = _old_3mf(tmp_path / "b.3mf", {"3D/3dmodel.model": main, "3D/Objects/Assembly_35.model": asm,
                                       "3D/Objects/cube_1.model": cube, "Metadata/model_settings.config": ms,
                                       "Metadata/project_settings.config": json.dumps(cfg)})
    pr = threemf.read(p)
    objs = {o.name: o for _, o in pr.objects()}
    assert set(objs) == {"Assembly", "Cube B"}
    assert objs["Assembly"].size()[0] == pytest.approx(20) and objs["Cube B"].size()[0] == pytest.approx(10)
    assert objs["Assembly"].settings == {"brim_type": "outer_only"} and objs["Cube B"].parts[0].filament == 2
    assert "machine_start_gcode" not in pr.overrides and pr.overrides["sparse_infill_density"] == "5%"
    assert pr.machine == "Bambu Lab P1S 0.4 nozzle"
    assert any("machine_start_gcode" in w for w in pr.warnings)


@needs_bambu
def test_reprint_objects_and_labels(tmp_path, monkeypatch):
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    from mcp.server.mcpserver.exceptions import ToolError

    from unofficial_bambu_mcp import server as s
    from unofficial_bambu_mcp import threemf
    s.new_project("orig", "P1S", filaments=[{"preset": "Bambu PLA Basic", "color": "#000000"},
                                            {"preset": "Bambu PLA Basic", "color": "#FFFFFF"}])
    s.set_setting("sparse_infill_density", "25%")
    s.add_shape("cylinder", diameter=8, height=11, name="pin a")
    s.add_shape("cylinder", diameter=8, height=11, name="pin b", filament=2)
    s.add_shape("box", name="body")
    assert s.preview_plate(1, view="top", labels=True).data[:4] == b"\x89PNG"
    with pytest.raises(ToolError, match="matches 2 objects"):
        s.reprint_objects(["pin"], slice=False)
    r = s.reprint_objects(["pin b"], slice=False)
    t = threemf.read(r["file"])
    (_, o), = t.objects()
    assert o.name == "pin b" and o.settings["brim_type"] == "outer_only" and o.parts[0].filament == 2
    assert len(t.filaments) == 2 and t.overrides["sparse_infill_density"] == "25%"
    assert [x.name for _, x in s.P().objects()] == ["pin a", "pin b", "body"]      # the open project is untouched


def test_printer_advice_and_skipped_objects(tmp_path):
    import zipfile

    from unofficial_bambu_mcp import printer, threemf
    s = printer.summarize({"gcode_state": "RUNNING", "mc_remaining_time": 1085, "spd_lvl": 3, "s_obj": [648, 670],
                           "ams": {"tray_now": "0", "tray_exist_bits": "3", "ams": [{"id": "0", "tray": [
                               {"id": "0"}, {"id": "1", "tray_type": "PLA", "tray_color": "161616FF",
                                             "tray_info_idx": "P80ed8f6"}]}]}})
    assert s["skipped_objects"] == [648, 670] and s["active_slot"] == 1
    w = printer.advice(s, [(1, "eSUN PLA Basic Nero @Bambu Lab P1S 0.4 nozzle", "P80ed8f6")])
    assert any("slot 1" in x and "no auto-refill" in x and "slot 2" in x for x in w)
    assert any("sport" in x for x in w)
    s["active_slot"] = 2
    assert not [x for x in printer.advice(s, [(1, "eSUN PLA Basic Nero", "P80ed8f6")]) if "feeding" in x]
    assert printer.advice({"state": "idle"}) == []
    p = tmp_path / "job.gcode.3mf"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("Metadata/slice_info.config", '<config><plate><object identify_id="648" name="pin_short x2 b" '
                   'skipped="false" /></plate></config>')
    assert threemf.object_names(str(p)) == {648: "pin_short x2 b"}


def test_printer_reports_merged_by_sequence_and_old_ones_flagged():
    """P1 printers answer pushall with a full report, then send only what changed every 2-4 s."""
    import time

    from unofficial_bambu_mcp import printer

    def full(seq, nozzle, state="RUNNING"):
        rep = {f"k{i}": i for i in range(20)}
        rep.update({"command": "push_status", "sequence_id": str(seq), "gcode_state": state, "nozzle_temper": nozzle,
                    "nozzle_target_temper": 0, "bed_temper": 61.8, "bed_target_temper": 0, "layer_num": 0,
                    "total_layer_num": 12, "subtask_name": "old job"})
        return rep

    def part(seq, nozzle):
        return {"command": "push_status", "msg": 1, "sequence_id": str(seq), "nozzle_temper": nozzle}

    # changes newer than the full report win; older ones (sent before it) do not
    m = printer.merge([part(40, 150.0), full(41, 106.1), part(42, 108.5), part(43, 111.0)])
    assert m["nozzle_temper"] == 111.0 and m["_updates"] == 2 and m["_full_seq"] == 41
    # an old full report (lower number than changes already received): the changes still win
    m = printer.merge([part(60, 176.4), full(41, 106.1)])
    assert m["nozzle_temper"] == 176.4 and m["gcode_state"] == "RUNNING"
    assert printer.merge([part(5, 30.0), part(6, 31.0)])["nozzle_temper"] == 31.0
    # no change after the full report while the nozzle should be cooling, or the very same report again: old
    old = printer.merge([full(41, 106.1)])
    old["_received"] = time.time() - 60
    assert any("may be old" in w for w in printer.staleness(old))
    again = dict(old, _received=time.time())
    assert any("same report" in w for w in printer.staleness(again, old))
    assert printer.staleness(printer.merge([full(41, 106.1), part(42, 105.0)])) == []
    assert printer.staleness(printer.merge([full(41, 24.0)])) == []          # cold and idle: nothing changes
    s = printer.summarize(old)
    assert s["age_s"] >= 59 and len(s["read_at"]) == 8
    assert any("heaters are off" in w for w in printer.advice(s))


@needs_bambu
def test_check_print_risks(tmp_path, monkeypatch):
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    from unofficial_bambu_mcp import server as s
    s.new_project("risks", "P1S")
    s.set_setting("brim_type", "no_brim")
    s.add_shape("box", width=6, depth=6, height=60, name="pole")
    s.add_shape("box", width=40, depth=40, height=10, name="slab")
    s.add_shape("cylinder", diameter=12, height=8, name="peg")
    (r,) = s.check_print_risks(1)
    flagged = {x["object"]: x["risk"] for x in r["risks"] if "object" in x}
    assert set(flagged) == {"pole", "peg"} and "60 mm high on a 6 mm side" in flagged["pole"]
    assert "113 mm²" in flagged["peg"]
    s.set_object_setting("peg", "brim_type", "outer_only")
    (r,) = s.check_print_risks(1)
    assert {x["object"] for x in r["risks"] if "object" in x} == {"pole"}
    s.set_object_setting("pole", "brim_type", "outer_only")
    (r,) = s.check_print_risks(1)
    (pole,) = r["risks"]
    assert pole["risk"].endswith("brim outer_only") and "give it an outer brim" not in pole["advice"]


def test_release_metadata_agree():
    # pyproject, server.json (MCP Registry) and the README marker the registry checks on PyPI must agree
    import json
    import re
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    version = re.search(r'^version = "([^"]+)"', (root / "pyproject.toml").read_text(), re.M).group(1)
    server = json.loads((root / "server.json").read_text())
    assert server["version"] == server["packages"][0]["version"] == version
    assert f"<!-- mcp-name: {server['name']} -->" in (root / "README.md").read_text()


# ---------------------------------------------------------------- brim ears
def _hand():
    """A 20 × 10 mm palm with three 1.6 mm fingers 8 mm long, and a separate piece 0.8 mm past the palm."""
    from shapely.geometry import box as rect
    from shapely.ops import unary_union
    palm = unary_union([rect(0, 0, 20, 10)] + [rect(x, 10, x + 1.6, 18) for x in (2, 9, 16)])
    return [palm, rect(20.8, 0, 30, 10)]


def test_brim_ears_on_finger_tips_only():
    from unofficial_bambu_mcp import brim
    islands = _hand()
    ears, skipped = brim.auto_ears(islands, 4)
    assert len(ears) == 3 and not skipped
    for x, y, r in ears:
        assert y > 16 and r >= 2                        # at the tips, not on the palm
        assert brim.check(islands, 0, x, y, r, 0.6) is None
        assert islands[1].distance(brim.Point(x, y)) > r  # never reaching the other piece
    assert round(brim.gaps(islands), 2) == 0.8


def test_brim_ear_checks():
    from shapely.geometry import Polygon
    from shapely.geometry import box as rect

    from unofficial_bambu_mcp import brim
    islands = _hand()
    assert brim.check(islands, 0, 20.4, 5, 3, 0.6) == "it would reach another piece"
    assert brim.check(islands, 0, 9.8, 18, 6, 0.6) == "it would join two thin parts of the same piece"
    assert brim.check(islands, 0, 50, 50, 3, 0.6) == "it does not touch the object"
    ring = Polygon(rect(0, 0, 20, 20).exterior, [rect(8, 8, 12, 12).exterior.coords])
    assert brim.check([ring], 0, 10, 10, 1.5, 0.3) == "it would fill a gap or hole"


def test_brim_ear_points_file_round_trip():
    from unofficial_bambu_mcp import brim
    txt = brim.write_points([(1, [(1.5, -2.0, -3.001, 4.0)]), (2, []), (3, [(0, 0, 0, 2), (1, 1, 0, 3)])])
    assert txt.startswith("brim_points_format_version=1\nobject_id=1|1.500000 -2.000000 -3.001000 4.000000 -1\n")
    pts = brim.read_points(txt)
    assert set(pts) == {1, 3} and pts[3][1] == (1.0, 1.0, 0.0, 3.0, -1.0)
    assert brim.read_points("object_id=2|1 2 3 4") == {2: [(1.0, 2.0, 3.0, 4.0, -1.0)]}   # format 0


def test_brim_ears_follow_the_object():
    from unofficial_bambu_mcp import geometry
    from unofficial_bambu_mcp.project import Obj, Part
    v, t = geometry.box(20, 10, 5)
    o = Obj("tag", [Part("tag", v + [50, 60, 0], t, 1)], at=(50, 60))
    o.brim_ears = [(60.0, 60.0, 3.0)]                 # on the right end
    assert o.transform(lambda q: geometry.rotate(q, 90)) is False
    assert np.allclose(o.brim_ears[0][:2], (50, 70), atol=1e-6)
    assert o.transform(lambda q: geometry.rotate(q, 90, "x")) is True and o.brim_ears == []


@needs_bambu
def test_brim_ears_in_3mf_and_sliced(tmp_path, monkeypatch):
    import re
    import zipfile
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    from unofficial_bambu_mcp import server as s
    from unofficial_bambu_mcp import threemf
    s.new_project("ears", "P1S")
    s.add_shape("box", width=30, depth=2, height=2, name="bar", x=100, y=100)
    res = s.add_brim_ears("bar", points=[[115, 100]])
    assert res["brim_type"] == "brim_ears" and res["ears"][0]["x"] == 115.0
    path = s.save_project()["saved"]
    back = threemf.read(path).plates[0].objects[0]
    lo, hi = back.bbox()
    ex, ey, er = back.brim_ears[0]
    assert abs(ex - (lo[0] + hi[0]) / 2 + back.at[0] - 115) < 0.01 and er == res["ears"][0]["radius"]
    sliced = s.slice_project()["sliced_file"]
    g = zipfile.ZipFile(sliced).read("Metadata/plate_1.gcode").decode()
    first = g.split("; CHANGE_LAYER")[1] if "; CHANGE_LAYER" in g else g
    brim_part = first.split("; FEATURE: Brim")[1].split("; FEATURE:")[0]
    xs = [float(x) for x in re.findall(r"G1 X([-\d.]+) Y[-\d.]+ E", brim_part)]
    assert xs and min(xs) > 110                      # only around the right end, not along the whole bar
    s.remove_brim_ears("bar")
    assert "brim_type" not in s.P().find("bar")[1].settings


# ---------------------------------------------------------------- purge volumes
@needs_bambu
def test_purge_volumes_set_kept_and_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    from mcp.server.mcpserver.exceptions import ToolError

    from unofficial_bambu_mcp import server as s
    from unofficial_bambu_mcp import threemf
    s.new_project("purge", "P1S", filaments=[{"color": "#000000"}, {"color": "#FFFFFF"}, {"color": "#FF0000"}])
    auto = s.get_purge_volumes()["volumes_mm3"]
    t = s.set_purge_volumes(volumes=[{"from": 1, "to": 2, "volume": 800}], multiplier=1.5)
    assert t["volumes_mm3"][0][1] == 800 and t["set_by_hand"] == [[1, 2]] and t["multiplier"] == 1.5
    cfg = s.P().config()
    assert cfg["flush_volumes_matrix"][1] == "800" and cfg["flush_multiplier"] == ["1.5"]
    with pytest.raises(ToolError, match="two different"):
        s.set_purge_volumes(volumes=[{"from": 2, "to": 2, "volume": 100}])
    with pytest.raises(ToolError, match="3 × 3"):
        s.set_purge_volumes(matrix=[[0, 1]])
    back = threemf.read(s.save_project()["saved"])
    assert back.purge_volumes()[0][0][1] == 800 and back.flush_multiplier == 1.5
    s.set_filament(2, color="#00FF00")                 # a new color: the value set for the old one no longer applies
    assert s.get_purge_volumes()["set_by_hand"] == []
    t = s.set_purge_volumes(reset=True)
    assert t["multiplier"] == 1 and t["volumes_mm3"][0][2] == auto[0][2]


# ---------------------------------------------------------------- cutting with connectors
def _cut_box(**kw):
    import manifold3d as m3

    from unofficial_bambu_mcp import cutting
    box = m3.Manifold.cube((60, 40, 30), True).translate((0, 0, 15))
    return cutting, box, cutting.cut([(box, "box", True)], (0, 0, 15), kw.pop("normal", (0, 0, 1)), **kw)


def test_cut_upper_piece_lies_on_its_cut():
    import manifold3d as m3

    from unofficial_bambu_mcp import cutting
    cone = m3.Manifold.cylinder(40, 20, 2, 96)
    res = cutting.cut([(cone, "cone", True)], (0, 0, 20), (0, 0, 1))
    top = res["B"][0][0]
    assert top.bounding_box()[2] == pytest.approx(0, abs=1e-6)
    assert top.slice(0.01).area() > 300                 # the 22 mm cut face, not the 4 mm tip


def test_cut_plug_peg_fits_hole_with_clearance():
    cutting, box, res = _cut_box(connector="plug", clearance=0.2)
    assert res["male"] == "A" and len(res["connectors"]) == 1 and res["connectors"][0]["at"] == [0.0, 0.0, 15.0]
    (a, _), (b, _) = res["A"][0], res["B"][0]
    assert a.status() == b.status() and a.bounding_box()[5] == pytest.approx(15 + res["depth"])   # the peg is up
    b0 = cutting.from_frame(b, *cutting.frame((0, 0, 15), (0, 0, 1))[:2])      # B back where it was
    assert (a ^ b0).volume() < 1e-6                                           # no overlap once assembled
    peg = a.slice(18).area()
    hole = 60 * 40 - b0.slice(18).area()
    assert hole - peg == pytest.approx(math.pi * (5.2 ** 2 - 5 ** 2), rel=0.05)                # 0.2 mm all around


def test_cut_dowel_holes_both_sides_and_pin():
    cutting, box, res = _cut_box(connector="dowel", place="cut_down", count=2, shape="square")
    assert len(res["connectors"]) == 2 and res["pins"] is not None and len(res["pins"].decompose()) == 2
    for side in ("A", "B"):
        m = res[side][0][0]
        assert m.volume() < 60 * 40 * 15 - 1 and m.bounding_box()[2] == pytest.approx(0, abs=1e-6)


def test_cut_connectors_refused_or_shortened_where_needed():
    import manifold3d as m3

    from unofficial_bambu_mcp import cutting
    with pytest.raises(ValueError, match="sideways"):
        _cut_box(connector="plug", normal=(1, 0, 0))
    cone = m3.Manifold.cylinder(40, 20, 2, 96)
    res = cutting.cut([(cone, "cone", True)], (0, 0, 20), (0, 0, 1), connector="plug", size=8, depth=15)
    assert res["connectors"][0]["depth"] < 15                                 # the narrowing top is too thin
    _, _, res = _cut_box(connector="plug", positions=[(29, 0, 15)])
    assert res["connectors"] == [] and "edge" in res["skipped"][0]["why"]


def test_cut_connector_positions():
    import manifold3d as m3

    from unofficial_bambu_mcp import cutting
    legs = cutting._union([m3.Manifold.cube((10, 10, 40), True).translate((x, y, 20)) for x in (-30, 30) for y in (-20, 20)])
    res = cutting.cut([(legs, "legs", True)], (0, 0, 20), (0, 0, 1), connector="plug")
    assert sorted(tuple(c["at"][:2]) for c in res["connectors"]) == [(-30, -20), (-30, 20), (30, -20), (30, 20)]
    bar = m3.Manifold.cube((120, 20, 10), True).translate((0, 0, 5))
    res = cutting.cut([(bar, "bar", True)], (0, 0, 5), (0, 0, 1), connector="plug", count=3)
    xs = sorted(c["at"][0] for c in res["connectors"])
    assert xs[1] == pytest.approx(0, abs=0.01) and xs[2] == pytest.approx(-xs[0], abs=0.01)


@needs_bambu
def test_cut_object_with_plug_slices(tmp_path, monkeypatch):
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    from unofficial_bambu_mcp import server as s
    s.new_project("cut", "P1S")
    s.add_shape("box", width=40, depth=30, height=30, name="block", x=100, y=100)
    s.add_modifier("block", {"sparse_infill_density": "100%"}, z_from=20)
    res = s.cut_object("block", 15, connector="plug", shape="hexagon", style="frustum")
    assert res["connectors"]["peg_on"] == "block bottom" and len(res["connectors"]["placed"]) == 1
    names = {p["name"] for p in res["pieces"]}
    assert names == {"block bottom", "block top"}
    top = s.P().find("block top")[1]
    assert any(p.subtype == "modifier_part" for p in top.parts)              # the modifier went with its piece
    plates = s.slice_project()["plates"]
    assert plates[0]["warnings"] == []


def test_cut_dovetail_slides_along_the_cut():
    cutting, box, res = _cut_box(connector="dovetail", clearance=0.2)
    (k,) = res["connectors"]
    assert k["along"] == [1.0, 0.0, 0.0] and res["male"] == "A"                # along the 60 mm side
    a = res["A"][0][0]
    b0 = cutting.from_frame(res["B"][0][0], *cutting.frame((0, 0, 15), (0, 0, 1))[:2])
    assert (a ^ b0).volume() < 1e-6 and a.bounding_box()[0] == pytest.approx(-30)   # flush with the ends
    low, high = a.slice(15.5).area() / 60, a.slice(15 + k["depth"] - 0.5).area() / 60
    assert high > low + 1                                                     # wider at the top: it locks
    slot = (60 * 40 - b0.slice(15.5).area()) / 60
    assert slot - low == pytest.approx(0.4, abs=0.05)                         # 0.2 mm on each side


# ---------------------------------------------------------------- painting through booleans
def test_paint_strings():
    from unofficial_bambu_mcp import paint
    assert [paint.leaf(k) for k in (0, 1, 2, 3, 4, 17, 18)] == ["", "4", "8", "0C", "1C", "EC", "0FC"]
    for k in (1, 2, 3, 4, 17, 18, 40):
        assert paint.areas(paint.leaf(k)) == {k: 1.0}
    # one triangle split in four (code 3), children painted 1, 1, 2, 1: three quarters filament 1
    assert paint.areas("48443") == {1: 0.75, 2: 0.25} and paint.dominant("48443") == "4"


def test_cut_keeps_painting():
    from unofficial_bambu_mcp import cutting, geometry, paint
    v, t = geometry.box(40, 40, 20)
    n = np.cross(v[t][:, 1] - v[t][:, 0], v[t][:, 2] - v[t][:, 0])
    colors = ["8" if nz > 0.5 else ("48443" if abs(nz) < 0.5 else "") for nz in n[:, 2] / np.linalg.norm(n, axis=1)]
    m, oid = paint.tracked(v, t)
    res = cutting.cut([(m, "box", True)], (0, 0, 10), (0, 0, 1), connector="plug")
    tv, tt, attrs = paint.carry(res["B"][0][0], oid, v, t, {"paint_color": colors})
    col = attrs["paint_color"]
    tn = np.cross(tv[tt][:, 1] - tv[tt][:, 0], tv[tt][:, 2] - tv[tt][:, 0])
    tn = tn / np.linalg.norm(tn, axis=1)[:, None]
    face_up = tn[:, 2] > 0.5          # the top piece keeps its orientation: its painted top still faces up
    lowest = tv[tt][:, :, 2].max(1) < 0.01
    assert all(c == "8" for c, up, low in zip(col, face_up, lowest, strict=True) if up and not low)
    assert all(c == "" for c, low in zip(col, lowest, strict=True) if low)      # the cut face and the hole: base
    sides = [c for c, nz in zip(col, tn[:, 2], strict=True) if abs(nz) < 0.5 and c]
    assert sides and set(sides) <= {"48443", "4"}                             # split sides take the main color


# ---------------------------------------------------------------- arrange by real outlines
def _placed(s, plate):
    from shapely import affinity

    from unofficial_bambu_mcp import arrange
    pr = s.P()
    cfg = pr.config()
    return [(o, affinity.translate(arrange.footprint(o, cfg), o.at[0], o.at[1])) for o in pr.plates[plate - 1].objects]


@needs_bambu
def test_arrange_spreads_evenly_or_says_what_is_left(tmp_path, monkeypatch):
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    from unofficial_bambu_mcp import server as s
    s.new_project("arr", "P1S")
    for k in range(6):
        s.add_shape("box", width=60, depth=60, height=5, name=f"b{k}")
    res = s.arrange(plates=2)
    assert res["applied"] and [p["objects"] for p in res["plates"]] == [3, 3]
    for k in range(6, 20):
        s.add_shape("box", width=60, depth=60, height=5, name=f"b{k}", plate=1, x=128, y=128)
    before = [tuple(o.at) for _, o in s.P().objects()]
    res = s.arrange(plates=2)                         # 9 boxes of 60 mm per plate: 20 need 3 plates
    assert not res["applied"] and res["plates_needed"] == 3 and len(res["does_not_fit"]) == 2
    assert [tuple(o.at) for _, o in s.P().objects()] == before                 # nothing moved
    res = s.arrange(plates=-1)
    assert res["applied"] and sum(p["objects"] for p in res["plates"]) == 20
    for p in res["plates"]:
        shapes = [sh for _, sh in _placed(s, p["plate"])]
        assert all(a.distance(b) >= 6 - 0.05 for i, a in enumerate(shapes) for b in shapes[i + 1:])


@needs_bambu
def test_arrange_materials_tower_and_calibration_corner(tmp_path, monkeypatch):
    from shapely.geometry import Polygon, box
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    from unofficial_bambu_mcp import server as s
    s.new_project("arr", "P1S", filaments=[{"color": "#000000"}, {"color": "#FFFFFF"}])
    for k in range(4):
        s.add_shape("box", width=50, depth=50, height=5, name=f"f{k}", filament=1 + k % 2)
    res = s.arrange(plates=2, multi_material=False)
    assert res["applied"]
    for p in (1, 2):
        assert len({f for o, _ in _placed(s, p) for f in o.filaments()}) == 1     # one material per plate
    res = s.arrange(plates=1)
    tower = box(256 - 4 - 60, 256 - 4 - 60, 256 - 4, 256 - 4)
    corner = Polygon(s.P().info["exclude"])
    assert res["applied"] and all(not sh.intersects(tower) and not sh.intersects(corner) for _, sh in _placed(s, 1))


@needs_bambu
def test_arrange_leaves_other_objects_and_aligns_to_y(tmp_path, monkeypatch):
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    from unofficial_bambu_mcp import server as s
    s.new_project("arr", "P1S")
    s.add_shape("box", width=40, depth=40, height=5, name="fixed", x=128, y=128)
    s.add_shape("box", width=100, depth=20, height=5, name="bar", x=20, y=200)
    res = s.arrange(objects=["bar"], align_to_y=True)
    assert res["applied"] and s.P().find("fixed")[1].at == (128, 128)
    bar = s.P().find("bar")[1]
    w, d, _ = bar.size()
    assert d > w and abs(res["rotated_deg"]["bar"]) == 90
    shapes = dict((o.name, sh) for o, sh in _placed(s, 1))
    assert shapes["bar"].distance(shapes["fixed"]) >= 6 - 0.05


@needs_bambu
def test_footprint_counts_brim_and_ears(tmp_path, monkeypatch):
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    from unofficial_bambu_mcp import arrange
    from unofficial_bambu_mcp import server as s
    s.new_project("arr", "P1S")
    s.add_shape("box", width=20, depth=20, height=5, name="b")
    o = s.P().find("b")[1]
    assert arrange.footprint(o, s.P().config()).bounds == pytest.approx((-10, -10, 10, 10), abs=0.05)
    s.set_object_setting("b", "brim_type", "outer_only")
    s.set_object_setting("b", "brim_width", "5")
    assert arrange.footprint(o, s.P().config()).bounds[0] == pytest.approx(-15.1, abs=0.05)
    s.set_object_setting("b", "brim_type", "")
    s.add_brim_ears("b", points=[[o.at[0] + 10, o.at[1]]], radius=4)
    assert arrange.footprint(o, s.P().config()).bounds[2] == pytest.approx(14, abs=0.05)


def test_ams_mapping():
    from unofficial_bambu_mcp import lan, printer
    trays = [{"slot": 1, "type": "PETG", "color": "#00AE42"}, {"slot": 2, "unknown": True},
             {"slot": 5, "type": "PLA", "color": "#FF6A13"}, {"slot": 7, "type": "PLA", "color": "#5E43B7"}]
    fils = [("PLA", "#FF7020"), ("PLA", "#6040B0"), ("PETG", "#000000")]
    assert lan.ams_mapping(fils, [1, 2], trays) == [4, 6, -1]          # closest color, unused slot = -1
    assert lan.ams_mapping(fils, [1, 2], trays, {2: 5}) == [4, 4, -1]   # chosen slot wins
    with pytest.raises(printer.PrinterError):
        lan.ams_mapping(fils, [1], trays, {1: 2})                       # spool not set in the AMS
    with pytest.raises(printer.PrinterError):
        lan.ams_mapping([("TPU", "#000000")], [1], trays)              # no such filament loaded


def test_print_command():
    from unofficial_bambu_mcp import lan
    c = lan.print_command("cube-plate1.gcode.3mf", 1, [4, 6])["print"]
    assert c["command"] == "project_file" and c["param"] == "Metadata/plate_1.gcode"
    assert c["url"] == "file:///sdcard/cube-plate1.gcode.3mf" and c["subtask_name"] == "cube-plate1"
    assert c["use_ams"] and c["ams_mapping"] == [4, 6]
    assert not lan.print_command("x.gcode.3mf", 2)["print"]["use_ams"]


def test_print_refusal():
    from unofficial_bambu_mcp import lan
    old = {"hms": [{"attr": 0x05000500, "code": 0x00010007, "timestamp": 1}]}
    assert lan.refusal(old, lan.hms_seen(old)) is None                       # already there before
    again = {"hms": [{"attr": 0x05000500, "code": 0x00010007, "timestamp": 2}]}
    assert "Developer Mode" in lan.refusal(again, lan.hms_seen(old))          # raised again: refused
    assert "verify" in lan.refusal({"command": "project_file", "result": "failed", "reason": "verify failed"})
    assert lan.refusal({"command": "project_file", "result": "success"}) is None
    # what a P1S in cloud mode answers: the command echoed back with an error code and no result
    assert "84033543" in lan.refusal({"command": "project_file", "err_code": 84033543})


def test_skip_objects_request_and_refusal():
    from unofficial_bambu_mcp import lan
    c = lan.skip_command([670, 648])["print"]
    assert c["command"] == "skip_objects" and c["obj_list"] == [670, 648] and c["sequence_id"].isdigit()
    # a P1S in cloud mode answers like for project_file: the command echoed back with an error code
    assert "84033543" in lan.refusal({"command": "skip_objects", "err_code": 84033543}, command="skip_objects")
    assert lan.refusal({"command": "skip_objects", "result": "success"}, command="skip_objects") is None


# ---------------------------------------------------------------- AMS load / unload (LAN, Developer Mode)
def _ams_report(state="IDLE", now="1"):
    tray = [{"id": str(k), "tray_type": "PLA", "nozzle_temp_min": "190", "nozzle_temp_max": "230"} for k in range(3)]
    tray.append({"id": "3"})                            # empty
    tray2 = [{"id": "1", "tray_type": "PETG", "nozzle_temp_min": "230", "nozzle_temp_max": "260"}]
    return {"gcode_state": state, "ams": {"tray_now": now, "tray_exist_bits": "27",
                                          "ams": [{"id": "0", "tray": tray}, {"id": "1", "tray": tray2}]}}


def test_ams_change_commands_as_bambu_studio_sends_them():
    from unofficial_bambu_mcp import lan
    load = lan.ams_change_command(_ams_report(), 6)["print"]
    assert {k: load[k] for k in ("command", "ams_id", "target", "slot_id", "curr_temp", "tar_temp")} == {
        "command": "ams_change_filament", "ams_id": 1, "target": 5, "slot_id": 1, "curr_temp": 210, "tar_temp": 245}
    unload = lan.ams_change_command(_ams_report(now="5"), None)["print"]
    assert (unload["target"], unload["slot_id"], unload["ams_id"]) == (255, 255, 1)


def test_ams_change_refused_when_it_makes_no_sense():
    from unofficial_bambu_mcp import lan
    assert "not printing" in lan.check_ams_change(_ams_report(state="RUNNING"), 3)
    assert lan.check_ams_change(_ams_report(), 4) == "AMS slot 4 is empty"
    assert lan.check_ams_change(_ams_report(), 2) == "AMS slot 2 is already loaded"
    assert lan.check_ams_change(_ams_report(now="255"), None) == "no filament is loaded in the nozzle"
    assert lan.check_ams_change(_ams_report(), 3) is None


def test_ams_load_asks_before_sending(monkeypatch):
    from unofficial_bambu_mcp import lan, printer
    from unofficial_bambu_mcp import server as s
    monkeypatch.setattr(printer, "status", lambda max_age=20.0: (_ams_report(), "SERIAL0001"))
    sent = []
    monkeypatch.setattr(lan, "ams_change", lambda slot=None: sent.append(slot) or {"done": "load"})
    first = s.ams_load(3)
    assert first["confirm"] == "load 3" and not sent
    assert s.ams_load(3, confirm="load 2")["confirm"] == "load 3" and not sent    # a wrong code sends nothing
    assert s.ams_load(3, confirm="load 3")["done"] == "load" and sent == [3]
    assert "cannot" in s.ams_load(2) and "confirm" not in s.ams_load(2)          # already loaded


@needs_bambu
def test_lan_print_asks_before_starting(tmp_path, monkeypatch):
    """send_to_printer(via='lan') first only says what it would do; nothing is exported or sent without the code."""
    from unofficial_bambu_mcp import lan, printer, slicer
    from unofficial_bambu_mcp import server as s
    monkeypatch.setenv("UBMCP_DIR", str(tmp_path))
    rep = _ams_report()
    monkeypatch.setattr(printer, "status", lambda serial=None, max_age=20.0: (rep, "SERIAL0001"))
    calls = []
    monkeypatch.setattr(slicer, "export_plate", lambda *a, **k: calls.append("export") or {})
    monkeypatch.setattr(lan, "start_print", lambda *a, **k: calls.append("print") or {"started": True})
    s.new_project("lan", "P1S", filaments=[{"preset": "Bambu PLA Basic", "color": "#FFFFFF"}])
    s.add_shape("box", width=20, depth=20, height=5, name="cube")
    first = s.send_to_printer(1, via="lan")
    assert first["confirm"] == "print plate 1" and first["ams_slots"] == {1: 1} and calls == []
    s.send_to_printer(1, via="lan", confirm="print plate 1")
    assert calls == ["export", "print"]
    rep["gcode_state"] = "RUNNING"
    from mcp.server.mcpserver.exceptions import ToolError
    with pytest.raises(ToolError, match="printing"):
        s.send_to_printer(1, via="lan")

