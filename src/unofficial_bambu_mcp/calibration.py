"""Calibration prints built as normal objects plus layer actions, so they work with any filament preset.

- Temperature tower: blocks with a bridge and the temperature engraved, one temperature per block (M104).
- Flow rate test: squares printed with a per-object flow ratio, the percentage engraved on top.
- Pressure advance tower: a thin square tube, the K value changes every millimeter (M900, as Bambu's own tower).
"""
import math

import numpy as np

from . import geometry
from .project import LayerGcode, Obj, Part

try:
    import manifold3d as m3
except ImportError:  # pragma: no cover
    m3 = None


def _box(x0, y0, z0, x1, y1, z1):
    return m3.Manifold.cube((x1 - x0, y1 - y0, z1 - z0)).translate((x0, y0, z0))


def _engrave_front(solid, text, cx, cz, y_face, cap=4.5, depth=0.6):
    """Engrave text on a face looking toward -Y (readable from the front)."""
    shape = geometry.text_outline(text, cap)
    v, t = geometry.extrude(shape, depth + 1.0)
    m = geometry.to_manifold(v, t).rotate((90.0, 0.0, 0.0))     # text in the XZ plane, slab toward -Y
    m = m.translate((cx, y_face + depth, cz))
    return solid - m


def _engrave_top(solid, text, cx, cy, z_top, cap=5.0, depth=0.6):
    shape = geometry.text_outline(text, cap)
    v, t = geometry.extrude(shape, depth + 1.0)
    m = geometry.to_manifold(v, t).translate((cx, cy, z_top - depth))
    return solid - m


def _mesh(m):
    return geometry.from_manifold(m)


def snap(z, layer_h, first_h):
    """Nearest print_z of a real layer at or above z (layer actions run before printing that layer)."""
    if z <= first_h:
        return round(first_h, 4)
    k = math.ceil((z - first_h) / layer_h - 1e-6)
    return round(first_h + k * layer_h, 4)


# ---------------------------------------------------------------- temperature tower
def temperature_tower(temps, layer_h=0.2, first_h=0.2, filament=1, block_h=8.0):
    """(Obj, [LayerGcode]) for the given temperatures, bottom to top."""
    w, d = 50.0, 10.0
    base_h = 1.0
    parts = [_box(-30, -8, 0, 30, 8, base_h)]
    for i, temp in enumerate(temps):
        z0 = base_h + i * block_h
        blk = _box(-w / 2, -d / 2, z0, w / 2, d / 2, z0 + block_h)
        blk = blk - _box(-7, -d / 2 - 1, z0 - 0.01, 15, d / 2 + 1, z0 + block_h - 2.4)   # bridge 22 mm, 2.4 thick
        blk = _engrave_front(blk, f"{temp:g}", -16.0, z0 + block_h / 2 - 2.2, -d / 2)
        parts.append(blk)
    solid = m3.Manifold.batch_boolean(parts, m3.OpType.Add)
    v, t = _mesh(solid)
    ob = Obj("Temperature tower", [Part("Temperature tower", v, t, filament)],
             settings={"brim_type": "no_brim"})
    actions = []
    for i, temp in enumerate(temps):
        z = snap(base_h + i * block_h + layer_h, layer_h, first_h)
        actions.append(LayerGcode(z, "custom", gcode=f"M104 S{int(temp)} ; temperature tower block {i + 1}"))
    return ob, actions


# ---------------------------------------------------------------- flow rate
def flow_blocks(modifiers, filament=1, size=22.0, height=2.0):
    """One square per flow modifier (percent): [(Obj, ratio)]. Laid out later by the caller."""
    out = []
    for mod in modifiers:
        blk = _box(-size / 2, -size / 2, 0, size / 2, size / 2, height)
        label = f"{mod:+g}" if mod else "0"
        blk = _engrave_top(blk, label, 0.0, size / 2 - 5.0, height, cap=4.0, depth=0.4)
        v, t = _mesh(blk)
        ratio = round(1.0 + mod / 100.0, 4)
        ob = Obj(f"Flow {label}%", [Part(f"Flow {label}%", v, t, filament)],
                 settings={"print_flow_ratio": f"{ratio:g}", "ironing_type": "no ironing",
                           "top_surface_pattern": "monotonic"})
        out.append((ob, ratio))
    return out


# ---------------------------------------------------------------- pressure advance
def pa_tower(values, layer_h=0.2, first_h=0.2, filament=1, step_h=1.0, size=40.0, wall=0.84):
    """(Obj, [LayerGcode]): thin square tube, K = values[i] from height i*step_h."""
    height = step_h * len(values)
    outer = _box(-size / 2, -size / 2, 0, size / 2, size / 2, height)
    inner = _box(-size / 2 + wall, -size / 2 + wall, -1, size / 2 - wall, size / 2 - wall, height + 1)
    base = _box(-size / 2, -size / 2, 0, size / 2, size / 2, 0.6)
    solid = (outer - inner) + base
    v, t = _mesh(solid)
    ob = Obj("Pressure advance tower", [Part("Pressure advance tower", v, t, filament)],
             settings={"wall_loops": "2", "sparse_infill_density": "0%", "top_shell_layers": "0",
                       "outer_wall_speed": "200", "inner_wall_speed": "200", "brim_type": "no_brim"})
    actions = []
    for i, k in enumerate(values):
        z = snap(max(first_h, i * step_h + layer_h if i else first_h), layer_h, first_h)
        actions.append(LayerGcode(z, "custom", gcode=f"M900 K{k:.4f} ; pressure advance tower step {i + 1}"))
    return ob, actions


def frange(a, b, step):
    n = int(math.floor((b - a) / step + 1e-9)) + 1
    return [round(a + i * step, 6) for i in range(max(1, n))]


def grid(objs, cols, gap=6.0):
    """Centers for objects in rows of `cols`, centered on (0, 0)."""
    sizes = [o.size() for o in objs]
    w = max(s[0] for s in sizes) + gap
    d = max(s[1] for s in sizes) + gap
    rows = int(np.ceil(len(objs) / cols))
    out = []
    for i in range(len(objs)):
        r, c = divmod(i, cols)
        out.append(((c - (min(cols, len(objs)) - 1) / 2) * w, ((rows - 1) / 2 - r) * d))
    return out


# ---------------------------------------------------------------- max volumetric speed
def flow_speed_cylinders(qs, line_w=0.42, layer_h=0.2, filament=1, d=30.0, h=15.0):
    """One single-wall cylinder per volumetric speed Q (mm³/s), wall speed = Q / (line width × layer height),
    plus a small tag with Q engraved (printed with normal settings). [(cylinder, tag, speed_mm_s)]"""
    out = []
    for q in qs:
        speed = q / (line_w * layer_h)
        v, t = geometry.cylinder(d, h)
        cyl = Obj(f"Q{q:g} cylinder", [Part(f"Q{q:g} cylinder", v, t, filament)],
                  settings={"wall_loops": "1", "sparse_infill_density": "0%", "top_shell_layers": "0",
                            "bottom_shell_layers": "3", "outer_wall_speed": f"{speed:.0f}",
                            "inner_wall_speed": f"{speed:.0f}", "brim_type": "no_brim"})
        tag = _engrave_top(_box(-8, -4, 0, 8, 4, 1.2), f"{q:g}", 0.0, 0.0, 1.2, cap=4.5, depth=0.4)
        tv, tt = _mesh(tag)
        out.append((cyl, Obj(f"Q{q:g} tag", [Part(f"Q{q:g} tag", tv, tt, filament)]), speed))
    return out


# ---------------------------------------------------------------- retraction / stringing
def stringing_test(filament=1):
    """Two thin pillars on a strip: travel between them shows stringing."""
    base = _box(-30, -5, 0, 30, 5, 0.8)
    p1 = m3.Manifold.cylinder(25.0, 2.5, circular_segments=48).translate((-22, 0, 0.6))
    p2 = m3.Manifold.cylinder(25.0, 2.5, circular_segments=48).translate((22, 0, 0.6))
    v, t = _mesh(m3.Manifold.batch_boolean([base, p1, p2], m3.OpType.Add))
    return Obj("Stringing test", [Part("Stringing test", v, t, filament)], settings={"brim_type": "no_brim"})
