"""Painting whole regions of an object, like Bambu Studio's painting tools: colors, supports, seams, fuzzy skin.
A region is a height band and/or the faces looking one way. Triangles that cross the edge of a band are split
first (the shape does not change, neighbors share the new vertices), so the painted edge is sharp; a triangle
that is split keeps the state covering most of it, the others keep their painting exactly (see paint.py)."""
import math

import numpy as np

from . import paint

ATTR = {"color": "paint_color", "support": "paint_supports", "block_support": "paint_supports",
        "seam": "paint_seam", "block_seam": "paint_seam", "fuzzy_skin": "paint_fuzzy_skin"}
STATE = {"support": 1, "block_support": 2, "seam": 1, "block_seam": 2, "fuzzy_skin": 1}   # enforcer, blocker
FACING = ("all", "top", "bottom", "sides", "front", "back", "left", "right", "overhangs")
EPS = 1e-6


def split_at(verts, tris, z, attrs):
    """(verts, tris, attrs) with the triangles crossing the plane at height z split along it."""
    verts = np.asarray(verts, float)
    tris = np.asarray(tris, np.int64)
    d = verts[:, 2] - z
    cross = (d[tris].min(axis=1) < -EPS) & (d[tris].max(axis=1) > EPS)
    if not cross.any():
        return verts, tris, attrs
    cut, extra = {}, []

    def at(i, j):
        key = (min(i, j), max(i, j))
        if key not in cut:
            t = d[i] / (d[i] - d[j])
            extra.append(verts[i] + (verts[j] - verts[i]) * t)
            cut[key] = len(verts) + len(extra) - 1
        return cut[key]

    out_tris, src = [], []
    for k, t in enumerate(tris):
        if not cross[k]:
            out_tris.append(t)
            src.append((k, True))
            continue
        below, above = [], []
        for n in range(3):
            i, j = int(t[n]), int(t[(n + 1) % 3])
            if d[i] <= EPS:
                below.append(i)
            if d[i] >= -EPS:
                above.append(i)
            if (d[i] < -EPS and d[j] > EPS) or (d[i] > EPS and d[j] < -EPS):
                m = at(i, j)
                below.append(m)
                above.append(m)
        for poly in (below, above):                 # a triangle or a quad, in the original winding order
            for q in range(1, len(poly) - 1):
                out_tris.append((poly[0], poly[q], poly[q + 1]))
                src.append((k, False))
    new_attrs = {}
    for key, vals in attrs.items():
        if vals is None or len(vals) != len(tris):
            continue
        cache = {}
        new_attrs[key] = [vals[k] if whole or not vals[k] else cache.setdefault(vals[k], paint.dominant(vals[k]))
                          for k, whole in src]
    return np.vstack([verts, np.asarray(extra)]), np.asarray(out_tris, np.int64), new_attrs


def region(verts, tris, z_lo=None, z_hi=None, facing="all", angle=45.0, bed_z=None):
    """Which triangles are in the region: centroid inside the height band, normal looking the given way."""
    corners = np.asarray(verts, float)[np.asarray(tris)]
    cz = corners[:, :, 2].mean(axis=1)
    sel = np.ones(len(tris), bool)
    if z_lo is not None:
        sel &= cz >= z_lo - EPS
    if z_hi is not None:
        sel &= cz <= z_hi + EPS
    if facing == "all":
        return sel
    n = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    n = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    c45 = math.cos(math.radians(45))
    if facing == "overhangs":
        bed = corners[:, :, 2].max(axis=1) < (bed_z if bed_z is not None else corners[:, :, 2].min()) + 0.3
        return sel & (n[:, 2] < -math.cos(math.radians(angle))) & ~bed
    look = {"top": n[:, 2] >= c45, "bottom": n[:, 2] <= -c45, "sides": np.abs(n[:, 2]) < c45,
            "front": n[:, 1] <= -c45, "back": n[:, 1] >= c45, "left": n[:, 0] <= -c45, "right": n[:, 0] >= c45}
    return sel & look[facing]


def apply(part, what, state, z_lo=None, z_hi=None, facing="all", angle=45.0, bed_z=None):
    """Paint (state > 0) or clear (state 0) `what` on the region of a part, splitting triangles at the band's edges.
    Returns how many triangles got it."""
    verts, tris, attrs = part.verts, part.tris, dict(part.tri_attrs)
    zmin, zmax = float(verts[:, 2].min()), float(verts[:, 2].max())
    for z in (z_lo, z_hi):
        if z is not None and zmin + EPS < z < zmax - EPS:
            verts, tris, attrs = split_at(verts, tris, z, attrs)
    sel = region(verts, tris, z_lo, z_hi, facing, angle, bed_z)
    key = ATTR[what]
    col = list(attrs.get(key) or [""] * len(tris))
    leaf = paint.leaf(state)
    for i in np.nonzero(sel)[0]:
        col[i] = leaf
    attrs = {k: v for k, v in attrs.items() if len(v) == len(tris)}
    if any(col):
        attrs[key] = col
    else:
        attrs.pop(key, None)
    part.verts, part.tris, part.tri_attrs = np.asarray(verts, float), np.asarray(tris, np.int64), attrs
    return int(sel.sum())
