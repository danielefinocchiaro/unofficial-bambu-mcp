"""Open real Bambu Studio / MakerWorld projects (read-only), preview, save a copy and slice it.

  UBMCP_DIR=tests/out uv run python tests/open_real.py file1.3mf [file2.3mf ...]
"""
import json
import os
import sys
import time

os.environ.setdefault("UBMCP_DIR", os.path.join(os.path.dirname(__file__), "out"))
from unofficial_bambu_mcp import server as s  # noqa: E402

OUT = os.environ["UBMCP_DIR"]
for path in sys.argv[1:]:
    t0 = time.time()
    tag = os.path.splitext(os.path.basename(path))[0].replace(" ", "_")
    summ = s.open_project(path)
    print(f"\n== {os.path.basename(path)}  ({time.time() - t0:.1f} s)")
    print(" printer:", summ["printer"], "| process:", summ["process"])
    print(" filaments:", [(f["preset"], f["color"]) for f in summ["filaments"]])
    print(" overrides:", list(summ["overrides"])[:12])
    for pl in summ["plates"]:
        print(f" plate {pl['plate']} '{pl['name']}': " + ", ".join(
            f"{o['name']} {o['size_mm']} fil{o['filaments']}{' painted' if o.get('painted_colors') else ''}"
            for o in pl["objects"])[:400])
    print(" warnings:", summ["warnings"])
    for k, name in ((1, "iso"), (1, "top")):
        with open(os.path.join(OUT, f"{tag}_{name}.png"), "wb") as f:
            f.write(s.preview_plate(k, name, zoom=True).data)
    sv = s.save_project()
    try:
        sl = s.slice_project()
        print(" slice:", json.dumps(sl["plates"])[:600])
        with open(os.path.join(OUT, f"{tag}_layer1.png"), "wb") as f:
            f.write(s.preview_layer(1, 1).data)
    except Exception as e:  # noqa: BLE001
        print(" SLICE ERROR:", str(e)[:600])
    print(f" total {time.time() - t0:.1f} s")
