"""Measuring: sizes, cross-sections (how long and how thick a bar is at a height), walls too thin for the nozzle,
gaps between the separate pieces of a print-in-place model, and distances between objects or parts.
Everything is in plate millimeters: x, y on the plate, z above the bed."""
import numpy as np
import shapely
from shapely.geometry import Polygon

from . import geometry, meshops

SCAN_STEPS = 60              # cross-sections looked at for thin walls
MAX_PIECES = 60              # pieces compared for the gaps between them
GAP_SEARCH = 1.0             # gaps up to this (mm) are measured: the clearances that matter
DENSE = 200_000              # meshes with more triangles are measured on a copy simplified by SIMPLIFY mm
SIMPLIFY = 0.005


def solid(p, shift=(0, 0, 0)):
    m = geometry.to_manifold(np.asarray(p.verts) + shift, p.tris)
    return m if m.status() == geometry.m3.Error.NoError and not m.is_empty() else None


def light(m):
    """The solid, or for a dense mesh a copy within SIMPLIFY mm of it (gaps and sections are much quicker)."""
    return m.simplify(SIMPLIFY) if m.num_tri() > DENSE else m


def _near(a, b, d):
    return all(a[k] - d <= b[k + 3] and b[k] - d <= a[k + 3] for k in range(3))


def section(manifolds, z):
    """Islands (shapely Polygons with holes) of the solids cut at height z."""
    shapes = []
    for m in manifolds:
        shape = Polygon()
        for ring in m.slice(z).to_polygons():
            if len(ring) >= 3:
                shape = shape.symmetric_difference(Polygon(ring).buffer(0))
        shapes.append(shape)
    union = shapely.union_all(shapes).buffer(0) if shapes else Polygon()
    return [g for g in getattr(union, "geoms", [union]) if isinstance(g, Polygon) and not g.is_empty]


def _rect(poly):
    """(length, width) of the smallest rectangle around a polygon, any rotation."""
    r = poly.minimum_rotated_rectangle
    xs, ys = r.exterior.coords.xy
    sides = sorted(float(np.hypot(xs[i + 1] - xs[i], ys[i + 1] - ys[i])) for i in range(2))
    return sides[1], sides[0]


def _thickest(poly):
    """Diameter of the biggest circle that fits inside (the thickest point)."""
    try:
        line = shapely.maximum_inscribed_circle(poly, 0.01)
        return 2 * float(line.length)
    except Exception:  # noqa: BLE001 - very old shapely: from the rectangle
        return _rect(poly)[1]


def describe(poly, dx, dy):
    """An island of a cross-section: where it is, how long, wide and thick, and its holes."""
    length, width = _rect(poly)
    c = poly.centroid
    out = {"center_xy": [round(c.x + dx, 2), round(c.y + dy, 2)], "length_mm": round(length, 2),
           "width_mm": round(width, 2), "thickest_mm": round(_thickest(poly), 2), "area_mm2": round(poly.area, 2)}
    holes = []
    for ring in poly.interiors:
        h = Polygon(ring)
        hl, hw = _rect(h)
        hc = h.centroid
        holes.append({"center_xy": [round(hc.x + dx, 2), round(hc.y + dy, 2)], "length_mm": round(hl, 2),
                      "width_mm": round(hw, 2), "round_diameter_mm": round(float(2 * np.sqrt(h.area / np.pi)), 2)})
    if holes:
        out["holes"] = holes
    return out


def thin_spots(polys, w):
    """Parts of the islands thinner than w (they do not survive an opening of width w): [(thickness, x, y, area)].
    The thickness of a thin strip is about 2 × area / perimeter; bits shorter than 3 w (sharp corners) are not
    walls and are left out."""
    out = []
    for poly in polys:
        kept = poly.buffer(-w / 2, join_style="mitre").buffer(w / 2, join_style="mitre")
        lost = poly.difference(kept).buffer(-0.01).buffer(0.01)
        for g in getattr(lost, "geoms", [lost]):
            if isinstance(g, Polygon) and g.area > 0.02 and g.length / 2 >= 3 * w:
                t = min(w, 2 * g.area / g.length)
                c = g.representative_point()
                out.append((t, c.x, c.y, g.area))
    return out


def scan_thin(manifolds, z0, z1, w, dx, dy):
    """Walls thinner than w over the height: (thinnest found or None, [spots]) with spots merged per place."""
    zs = np.linspace(z0 + 0.1, z1 - 0.1, max(2, min(SCAN_STEPS, int((z1 - z0) / 0.2))))
    spots = []
    for z in zs:
        for t, x, y, a in thin_spots(section(manifolds, float(z)), w):
            spots.append((t, x + dx, y + dy, float(z) - z0, a))
    merged = []
    for t, x, y, z, _a in sorted(spots, key=lambda s: s[0]):
        near = next((m for m in merged if np.hypot(m["xy"][0] - x, m["xy"][1] - y) < 3), None)
        if near:
            near["z_from"], near["z_to"] = min(near["z_from"], z), max(near["z_to"], z)
            continue
        merged.append({"xy": [round(x, 1), round(y, 1)], "z_from": z, "z_to": z, "about_mm": round(t, 2)})
    for m in merged:
        m["z_from"], m["z_to"] = round(m["z_from"], 1), round(m["z_to"], 1)
    return (merged[0]["about_mm"] if merged else None), merged


def gaps_between(pieces, search=GAP_SEARCH):
    """Gaps under `search` mm between separate solids [(name, manifold)]: [(gap, name a, name b)], smallest
    first. Only pairs whose boxes come that close are measured."""
    boxes = [m.bounding_box() for _, m in pieces]
    out = []
    for i in range(len(pieces)):
        for j in range(i + 1, len(pieces)):
            if not _near(boxes[i], boxes[j], search):
                continue
            g = pieces[i][1].min_gap(pieces[j][1], search)
            if g < search:
                out.append((float(g), pieces[i][0], pieces[j][0]))
    return sorted(out)


def closest_points(va, vb, limit=5000, reach=None):
    """About where two meshes come closest: the nearest pair among (up to `limit`) vertices of each, taken from
    where each comes within `reach` mm of the other's box."""
    va, vb = np.asarray(va, float), np.asarray(vb, float)
    if reach is not None:
        lo_a, hi_a, lo_b, hi_b = va.min(0), va.max(0), vb.min(0), vb.max(0)
        ka = np.all((va >= lo_b - reach) & (va <= hi_b + reach), axis=1)
        kb = np.all((vb >= lo_a - reach) & (vb <= hi_a + reach), axis=1)
        va, vb = (va[ka] if ka.any() else va), (vb[kb] if kb.any() else vb)

    def pick(v):
        return v[np.linspace(0, len(v) - 1, limit).astype(np.int64)] if len(v) > limit else v
    a, b = pick(va), pick(vb)
    best = (np.inf, None, None)
    for k in range(0, len(a), 2000):
        d = np.linalg.norm(a[k:k + 2000, None, :] - b[None, :, :], axis=2)
        i, j = np.unravel_index(np.argmin(d), d.shape)
        if d[i, j] < best[0]:
            best = (float(d[i, j]), a[k + i], b[j])
    return best


def plate_offset(o):
    return meshops.offset(o)
