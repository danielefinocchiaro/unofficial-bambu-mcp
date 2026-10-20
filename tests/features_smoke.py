"""End-to-end checks for modifiers, cut/mirror/lay flat, Bambu Studio sync and the standalone tests.

  UBMCP_DIR=tests/out uv run python tests/features_smoke.py
"""
import os
import re
import time

os.environ.setdefault("UBMCP_DIR", os.path.join(os.path.dirname(__file__), "out"))
from unofficial_bambu_mcp import server as s  # noqa: E402
from unofficial_bambu_mcp import slicer, threemf  # noqa: E402

os.makedirs(os.environ["UBMCP_DIR"], exist_ok=True)


def grams():
    return s.slice_project()["plates"][0]["grams"]


s.new_project("features", "P1S", filaments=[{"preset": "eSUN PLA+", "color": "#FFFFFF"}])
s.add_shape("box", width=40, depth=40, height=20, name="Block")
g0 = grams()
s.add_modifier("Block", {"sparse_infill_density": "100%"}, z_from=15)
g1 = grams()
print(f"modifier top 5 mm 100%: {g0} g -> {g1} g")
s.add_modifier("Block", kind="negative", z_from=0, z_to=20, region=[-8, -8, 8, 8])
g2 = grams()
print(f"negative 16x16 hole: {g1} g -> {g2} g")
print("parts:", [p["name"] for p in s.get_project()["plates"][0]["objects"][0]["part_list"]])

s.add_shape("box", width=30, depth=10, height=20, name="Tilted")
s.transform_object("Tilted", rotate_x=37)
print("tilted size", s.get_project()["plates"][0]["objects"][1]["size_mm"], "->", s.lay_flat("Tilted"))
s.add_shape("cylinder", diameter=20, height=30, name="Column")
print("cut:", [(p["name"], p["size_mm"]) for p in s.cut_object("Column", 12)["pieces"]])
s.add_shape("text", text="LEO", text_height=10, height=2, name="Leo")
print("mirror:", s.mirror_object("Leo", "x"))
r = s.slice_project()
print("slice all ok:", r["plates"][0]["minutes"], "min,", r["plates"][0]["warnings"])

# sync with Bambu Studio: simulate a save from the app (move an object, write the same file later)
saved = s.save_project()["saved"]
time.sleep(1.1)
app = threemf.read(saved)
(_, ob), = [(pi, o) for pi, o in app.objects() if o.name == "Leo"]
ob.at = (30.0, 30.0)
threemf.write(app, saved)
print("auto reload:", s.get_project().get("note"), "| Leo at",
      [o["center_xy"] for o in s.get_project()["plates"][0]["objects"] if o["name"] == "Leo"])
s.move_object("Block", dx=5)                              # unsaved change here
time.sleep(1.1)
threemf.write(app, saved)                                 # ...and another save in the app
print("conflict:", "conflict" in s.get_project())
print("forced sync:", s.sync_with_bambu_studio(force=True)["reloaded_from"].endswith(os.path.basename(saved)))

mf = s.make_max_flow_test(1)
print("max flow:", mf["file"].split("/")[-1], mf["minutes"], "min,", mf["cylinders"][:3], "...")
g = slicer.gcode(mf["sliced_file"], 1)
feats, cur, speeds = {}, "", {}
obj = None
for ln in g.splitlines():
    if ln.startswith("; FEATURE:"):
        cur = ln.split(":", 1)[1].strip()
    m = re.match(r"M624 (\S+)", ln)
    if ln.startswith("; start printing object"):
        obj = ln.split("id:")[-1].strip() if "id:" in ln else ln
    mf_ = re.search(r"G1 .*F(\d+)", ln)
    if mf_ and cur == "Outer wall" and " E" in ln and obj:
        speeds.setdefault(obj, set()).add(int(mf_.group(1)) // 60)
print("outer wall speeds per object (mm/s):", sorted(max(v) for v in speeds.values())[:12])
rt = s.make_retraction_test(1, [0.4, 1.0])
for t in rt["tests"]:
    gg = slicer.gcode(t["sliced_file"], 1)
    retr = re.findall(r"^G1 E-([\d.]+)", gg, re.M)
    print("retraction", t["retraction_mm"], "->", sorted(set(retr))[:4], f"{t['minutes']} min")
