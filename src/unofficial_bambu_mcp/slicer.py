"""Slicing with the Bambu Studio command line, and reading the resulting G-code."""
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import zipfile

from . import studio, threemf


class SliceError(RuntimeError):
    pass


def slice_3mf(path, out_path, plate=0, timeout=1800):
    """Slice `path` (plate=0: all plates) and save the sliced project to out_path. Returns per-plate stats."""
    exe = studio.executable()
    if not exe:
        raise SliceError("Bambu Studio not found (set BAMBU_STUDIO_EXE)")
    work = tempfile.mkdtemp(prefix="ubmcp_")
    try:
        r = subprocess.run([exe, "--outputdir", work, "--slice", str(plate), "--export-3mf", "sliced.3mf",
                            os.path.abspath(path)], capture_output=True, text=True, timeout=timeout)
        res = {}
        rj = os.path.join(work, "result.json")
        if os.path.exists(rj):
            with open(rj, encoding="utf-8") as f:
                res = json.load(f)
        sliced = os.path.join(work, "sliced.3mf")
        if r.returncode != 0 or res.get("return_code", 0) != 0 or not os.path.exists(sliced):
            tail = "\n".join((r.stdout + r.stderr).splitlines()[-15:])
            raise SliceError(f"slicing failed: {res.get('error_string', '') or 'see log'}\n{tail}")
        shutil.move(sliced, out_path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    stats = threemf.sliced_stats(out_path)
    for st in stats:
        g = gcode(out_path, st["plate"])
        if g:
            st["filament_changes"] = len(re.findall(r"^M620 S\d+A", g, re.M))
            st["layers"] = len(re.findall(r"^; CHANGE_LAYER", g, re.M))
            st["filament_changes"] = max(0, st["filament_changes"] - 1)   # the first load is not a change
    return stats


def gcode(sliced_path, plate=1):
    with zipfile.ZipFile(sliced_path) as z:
        name = f"Metadata/plate_{plate}.gcode"
        if name not in z.namelist():
            return None
        return z.read(name).decode("utf-8", "ignore")


def layer_paths(gtext, layer=None, z=None):
    """Extrusion segments of one layer: ([(x0, y0, x1, y1, tool, feature)], layer_index, z, layer_count).
    Pick the layer by 1-based index or by height (nearest)."""
    lines = gtext.splitlines()
    layers = []                         # (line_index, z)
    for i, ln in enumerate(lines):
        if ln.startswith("; CHANGE_LAYER"):
            zz = None
            for j in range(i + 1, min(i + 4, len(lines))):
                m = re.match(r"; Z_HEIGHT: ([\d.]+)", lines[j])
                if m:
                    zz = float(m.group(1))
                    break
            layers.append((i, zz))
    if not layers:
        return [], 0, 0.0, 0
    if layer is None and z is not None:
        k = min(range(len(layers)), key=lambda t: abs((layers[t][1] or 0) - z))
    else:
        k = max(0, min(len(layers) - 1, int(layer or 1) - 1))
    start = layers[k][0]
    end = layers[k + 1][0] if k + 1 < len(layers) else len(lines)
    # state at layer start: last position and tool before it
    x = y = 0.0
    tool = 0
    for ln in lines[:start]:
        if ln.startswith(("G0", "G1", "G2", "G3")):
            mx = re.search(r"X(-?[\d.]+)", ln)
            my = re.search(r"Y(-?[\d.]+)", ln)
            if mx:
                x = float(mx.group(1))
            if my:
                y = float(my.group(1))
        elif ln.startswith("M620 S"):
            m = re.match(r"M620 S(\d+)A", ln)
            if m:
                tool = int(m.group(1))
    segs, feature = [], ""
    for ln in lines[start:end]:
        if ln.startswith("; FEATURE:"):
            feature = ln.split(":", 1)[1].strip()
            continue
        if ln.startswith("M620 S"):
            m = re.match(r"M620 S(\d+)A", ln)
            if m:
                tool = int(m.group(1))
            continue
        if not ln.startswith(("G1", "G2", "G3", "G0")):
            continue
        code = ln.split(";", 1)[0]
        mx, my = re.search(r"X(-?[\d.]+)", code), re.search(r"Y(-?[\d.]+)", code)
        me = re.search(r"E(-?[\d.]+)", code)
        nx = float(mx.group(1)) if mx else x
        ny = float(my.group(1)) if my else y
        extr = me is not None and float(me.group(1)) > 0 and code.startswith(("G1", "G2", "G3"))
        if code.startswith(("G2", "G3")) and extr:
            mi, mj = re.search(r"I(-?[\d.]+)", code), re.search(r"J(-?[\d.]+)", code)
            if mi and mj:
                cx, cy = x + float(mi.group(1)), y + float(mj.group(1))
                a0, a1 = math.atan2(y - cy, x - cx), math.atan2(ny - cy, nx - cx)
                r = math.hypot(x - cx, y - cy)
                cw = code.startswith("G2")
                if cw and a1 >= a0:
                    a1 -= 2 * math.pi
                if not cw and a1 <= a0:
                    a1 += 2 * math.pi
                n = max(2, int(abs(a1 - a0) * r / 0.5))
                px, py = x, y
                for t in range(1, n + 1):
                    a = a0 + (a1 - a0) * t / n
                    qx, qy = cx + r * math.cos(a), cy + r * math.sin(a)
                    segs.append((px, py, qx, qy, tool, feature))
                    px, py = qx, qy
                x, y = nx, ny
                continue
        if extr and (nx != x or ny != y):
            segs.append((x, y, nx, ny, tool, feature))
        x, y = nx, ny
    return segs, k + 1, layers[k][1] or 0.0, len(layers)

def export_plate(path, plate, out_path, timeout=1800):
    """Print file for one plate (.gcode.3mf: G-code, md5, thumbnails, slice info), the format Bambu Studio,
    Bambu Connect and the printer accept. Returns the plate stats."""
    exe = studio.executable()
    if not exe:
        raise SliceError("Bambu Studio not found (set BAMBU_STUDIO_EXE)")
    work = tempfile.mkdtemp(prefix="ubmcp_")
    try:
        r = subprocess.run([exe, "--outputdir", work, "--slice", str(plate), "--min-save", "--export-3mf",
                            "plate.gcode.3mf", os.path.abspath(path)], capture_output=True, text=True, timeout=timeout)
        out = os.path.join(work, "plate.gcode.3mf")
        if r.returncode != 0 or not os.path.exists(out):
            tail = "\n".join((r.stdout + r.stderr).splitlines()[-15:])
            raise SliceError(f"export failed for plate {plate}\n{tail}")
        shutil.move(out, out_path)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    stats = threemf.sliced_stats(out_path)
    return stats[0] if stats else {}
