"""Build the three calibration plates, slice them, and save previews (needs Bambu Studio).

  UBMCP_DIR=tests/out uv run python tests/calib_smoke.py
"""
import json
import os
import re

os.environ.setdefault("UBMCP_DIR", os.path.join(os.path.dirname(__file__), "out"))
from unofficial_bambu_mcp import server as s  # noqa: E402
from unofficial_bambu_mcp import slicer

OUT = os.environ["UBMCP_DIR"]
os.makedirs(OUT, exist_ok=True)
s.new_project("calibration", "P1S", filaments=[{"preset": "eSUN PLA+", "color": "#FFFFFF"}])
t = s.make_temperature_tower(1)
f = s.make_flow_test(1)
p = s.make_pa_tower(1)
print(json.dumps({"temp": t["temperatures_bottom_to_top"], "flow": f["squares"][:3], "pa_height": p["height_mm"]}))
assert (t["plate"], f["plate"], p["plate"]) == (1, 2, 3)     # the empty default plate is used by the first one
for k in (1, 2, 3):
    with open(os.path.join(OUT, f"calib_plate{k}.png"), "wb") as fh:
        fh.write(s.preview_plate(k, "iso", zoom=True).data)
r = s.slice_project()
for st in r["plates"]:
    print({k: st[k] for k in ("plate", "minutes", "grams", "layers", "warnings")})
for k in (1, 3):
    g = slicer.gcode(r["sliced_file"], k)
    z, hits = None, []
    for ln in g.splitlines():
        m = re.match(r"; Z_HEIGHT: ([\d.]+)", ln)
        if m:
            z = float(m.group(1))
        if ln.startswith(("M104 S", "M900 K")) and "tower" in ln:
            hits.append((z, ln.split(";")[0].strip()))
    print(f"plate {k}: {len(hits)} actions, first {hits[:3]}, last {hits[-1:]}")
with open(os.path.join(OUT, "calib_flow_layer_top.png"), "wb") as fh:
    fh.write(s.preview_layer(2, z=2.0).data)
