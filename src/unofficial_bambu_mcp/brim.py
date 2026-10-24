"""Brim ears: small round brims only where a part needs them (fingertips, thin tips of a print-in-place model),
like Bambu Studio's "Painted" brim (brim_type = brim_ears). Bambu Studio keeps them as points per object in
Metadata/brim_ear_points.txt (x y z radius volume, object coordinates) and prints a disc of that radius around each
point on the first layer, minus the object itself, holes included: an ear that reaches another piece or a joint gap
welds it, so ears are placed only where their disc touches one piece."""
import math

import manifold3d as m3
import numpy as np
import shapely
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

EARS_FILE = "Metadata/brim_ear_points.txt"
STEP = 0.25                  # mm between points along an outline when looking for tips


def _polys(geom):
    if geom is None or geom.is_empty:
        return []
    return [g for g in getattr(geom, "geoms", [geom]) if isinstance(g, Polygon) and not g.is_empty]


def first_layer(parts, z):
    """Islands (shapely Polygons with their holes) of the solid parts cut at height z above their lowest point.
    parts: [(verts, tris)] in one frame. Meshes that are not closed fall back to the faces lying on the bed."""
    lo = min(float(v[:, 2].min()) for v, _ in parts)
    shapes = []
    for v, t in parts:
        mesh = m3.Mesh(vert_properties=np.ascontiguousarray(v - [0, 0, lo], np.float32),
                       tri_verts=np.ascontiguousarray(t, np.uint32))
        man = m3.Manifold(mesh)
        if man.status() == m3.Error.NoError and not man.is_empty():
            rings = [Polygon(r) for r in man.slice(z).to_polygons() if len(r) >= 3]
            shape = Polygon()
            for r in rings:                       # outlines and holes come as rings: even-odd
                shape = shape.symmetric_difference(r.buffer(0))
            shapes.append(shape)
        else:
            tri = v[t]
            flat = tri[(tri[:, :, 2] <= lo + 0.05).all(axis=1)]
            if len(flat):
                shapes.append(shapely.union_all(shapely.polygons(flat[:, :, :2])).buffer(0.01))
    return _polys(unary_union(shapes).buffer(0)) if shapes else []


def _ends(P):
    """The two outline points of P farthest apart (about)."""
    xy = np.asarray(shapely.segmentize(P.exterior, STEP).coords)[:-1]
    c = np.asarray(P.centroid.coords[0])
    a = xy[np.argmax(np.hypot(*(xy - c).T))]
    return a, xy[np.argmax(np.hypot(*(xy - a).T))]


def _tips(P, narrow):
    """Points at the end of the thin parts of island P: outline points that stand at least `narrow` mm away from
    the part of P that is thicker than `narrow` (a fingertip), or both ends of P if all of it is thin. A thin part
    between two thick ones (the shaft of a bone touching the bed along a strip) has no tip."""
    xy = np.asarray(shapely.segmentize(P.exterior, STEP).coords)[:-1]
    core = P.buffer(-narrow / 2).buffer(narrow / 2)
    if core.is_empty:
        a, b = _ends(P)
        return [a, b] if math.dist(a, b) >= 2 * narrow else [a]
    pts = shapely.points(xy)
    d = shapely.distance(pts, core)
    k = max(1, int(narrow / STEP))
    padded = np.concatenate([d[-k:], d, d[:k]])
    window = np.lib.stride_tricks.sliding_window_view(padded, 2 * k + 1).max(1)
    idx = np.nonzero((d >= narrow) & (d >= window))[0]
    cores = _polys(core)
    out = []
    for i in idx[np.argsort(-d[idx])]:
        arm = next((c for c in _polys(P.difference(core)) if c.distance(pts[i]) < STEP), None)
        if arm is not None and sum(arm.distance(c) < STEP for c in cores) >= 2:
            continue                                     # thin between two thick parts: not a tip
        out.append(xy[i])
    return out


def check(islands, i, x, y, r, clearance):
    """Why an ear at (x, y) with radius r next to island i would harm the print, or None."""
    disc = Point(x, y).buffer(r)
    near = disc.buffer(clearance)
    for j, Q in enumerate(islands):
        if j != i and near.intersects(Q):
            return "it would reach another piece"
        for h in Q.interiors:
            if near.intersects(Polygon(h)):
                return "it would fill a gap or hole"
    if i is not None:
        own = [g for g in _polys(islands[i].intersection(near)) if g.area > 0.05]
        if len(own) > 1:
            return "it would join two thin parts of the same piece"
        if not disc.intersects(islands[i]):
            return "it does not touch the object"
    return None


def auto_ears(islands, radius, narrow=3.0, small=0.0, clearance=0.6, min_radius=2.0):
    """Ears for the thin tips of each island (and for islands under `small` mm², at their ends), each as large as
    possible up to `radius` without reaching another piece, a hole or a second thin part; when something is close,
    the ear moves out past the tip (it still covers the last millimeter of it). Bambu Studio prints an ear a bit
    smaller than its radius (gap and line width), so ears under `min_radius` would not hold anything.
    Returns ([(x, y, r)], [(x, y, reason)])."""
    ears, skipped = [], []
    for i, P in enumerate(islands):
        tips = _tips(P, narrow) if narrow > 0 else []
        if small > 0 and P.area < small:
            tips += list(_ends(P))                      # both ends of a small piece
        for tip in tips:
            x, y = tip
            if any(math.dist((x, y), (ex, ey)) < max(er, min_radius) for ex, ey, er in ears):
                continue
            out = np.asarray(tip) - np.asarray(P.centroid.coords[0])
            out = out / (np.linalg.norm(out) or 1.0)
            found, why = None, None
            r = radius
            while r >= min_radius and not found:
                for shift in np.arange(0.0, r - 1.0 + 1e-9, 0.5):
                    cx, cy = x + out[0] * shift, y + out[1] * shift
                    why = check(islands, i, cx, cy, r, clearance)
                    if not why:
                        found = (float(cx), float(cy), float(r))
                        break
                r -= 0.5
            if found:
                ears.append(found)
            elif all(math.dist((x, y), (sx, sy)) > radius for sx, sy, _ in skipped):
                skipped.append((float(x), float(y), why))
    return ears, skipped


def island_of(islands, x, y):
    """Index of the island closest to (x, y), or None."""
    if not islands:
        return None
    p = Point(x, y)
    return int(np.argmin([P.distance(p) for P in islands]))


def gaps(islands):
    """Smallest distance between two islands (mm), or None with fewer than two."""
    if len(islands) < 2:
        return None
    best = math.inf
    tree = shapely.STRtree(islands)
    for i, P in enumerate(islands):
        for j in tree.query(P.buffer(5)):
            if j != i:
                best = min(best, P.distance(islands[j]))
    return best if best < math.inf else None


def write_points(objects):
    """Text of Metadata/brim_ear_points.txt. objects: [(1-based object index, [(x, y, z, r)])] in the coordinates
    of the object's mesh as written; volume -1 = relative to the object, not to one of its parts."""
    lines = [f"object_id={k}|" + " ".join(f"{x:f} {y:f} {z:f} {r:f} -1" for x, y, z, r in pts)
             for k, pts in objects if pts]
    return "brim_points_format_version=1\n" + "\n".join(lines) + "\n" if lines else ""


def read_points(text):
    """{1-based object index: [(x, y, z, r, volume)]} from Metadata/brim_ear_points.txt (format 0 or 1)."""
    out = {}
    lines = text.strip().splitlines()
    version = 0
    if lines and lines[0].startswith("brim_points_format_version="):
        version = int(lines.pop(0).split("=", 1)[1])
    n = 5 if version >= 1 else 4
    for line in lines:
        head, _, data = line.partition("|")
        if not head.startswith("object_id="):
            continue
        vals = [float(s) for s in data.split()]
        pts = [tuple(vals[i:i + n]) + ((-1.0,) if n == 4 else ()) for i in range(0, len(vals) - n + 1, n)]
        if pts:
            out[int(head.split("=", 1)[1])] = pts
    return out
