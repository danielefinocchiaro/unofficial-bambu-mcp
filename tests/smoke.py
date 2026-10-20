"""End-to-end smoke test on a real machine with Bambu Studio installed.

  UBMCP_DIR=tests/out uv run python tests/smoke.py [path/to/some_project.3mf]

Writes images and projects to tests/out/ so they can be looked at.
"""
import json
import os
import sys
import time

os.environ.setdefault("UBMCP_DIR", os.path.join(os.path.dirname(__file__), "out"))
from unofficial_bambu_mcp import server as s  # noqa: E402

OUT = os.environ["UBMCP_DIR"]
os.makedirs(OUT, exist_ok=True)


def show(title, data):
    print(f"\n== {title}")
    print(json.dumps(data, indent=1, default=str)[:1500])


def img(name, image):
    p = os.path.join(OUT, name)
    with open(p, "wb") as f:
        f.write(image.data)
    print("  image:", p)


t0 = time.time()
show("new_project", s.new_project("smoke", "P1S", filaments=[{"preset": "Bambu PLA Basic", "color": "#1A1A1A"},
                                                             {"preset": "eSUN PLA+", "color": "#FFFFFF"}]))
show("search eSUN", s.search_presets("filament", "eSUN PLA+", "P1S", 5))
show("box", s.add_shape("box", width=20, depth=20, height=20, name="Cube"))
show("text", s.add_shape("text", text="DANI", text_height=12, height=1.2, base=2, filament=2, name="Name tag"))
show("cylinder", s.add_shape("cylinder", diameter=30, height=8, filament=2))
show("move", s.move_object("Cube", x=60, y=60, rotate_z=30))
show("duplicate", s.duplicate_object("Cylinder", copies=2))
show("set_object_filament", s.set_object_filament("Cube", 2))
show("set_setting", s.set_setting("textured_plate_temp_initial_layer", "65", slot=2))
show("get_setting", s.get_setting("textured_plate_temp_initial_layer"))
show("object setting", s.set_object_setting("Cube", "sparse_infill_density", "40%"))
show("check", s.check_object("Name tag"))
img("plate1_iso.png", s.preview_plate(1, "iso"))
img("plate1_top.png", s.preview_plate(1, "top"))
show("save", s.save_project())
show("slice", s.slice_project())
img("plate1_layer1.png", s.preview_layer(1, 1))
img("plate1_layer_z3.png", s.preview_layer(1, z=3.0))

show("A1 mini", s.set_printer("A1M"))
img("a1m_plate1.png", s.preview_plate(1, "top"))
show("save A1M", s.save_project(os.path.join(OUT, "smoke_A1mini.3mf")))
show("slice A1M", s.slice_project())

show("first layer test", s.make_first_layer_test(1, 0.6))
img("test_plate.png", s.preview_plate(len(s.P().plates), "iso"))

if len(sys.argv) > 1:
    show("open_project", s.open_project(sys.argv[1]))
    img("opened_plate1.png", s.preview_plate(1, "iso"))
    show("save opened", s.save_project())
    show("slice opened", s.slice_project())
    img("opened_layer1.png", s.preview_layer(1, 1))
print(f"\nOK in {time.time() - t0:.0f} s")
