"""Text and SVG logos on an object's surface, raised or engraved, like Bambu Studio's Text and SVG tools.
The surface under the shape is measured on a fine grid (the first face met coming from outside), and the raised
or cut shape is bent to follow it, so it works on curved faces too, not only flat ones."""
import math

import numpy as np
import shapely
from shapely import affinity

from . import geometry

# u (the text's right), v (its up), n (out of the face, toward whoever reads it)
FACES = {"top": ((1, 0, 0), (0, 1, 0), (0, 0, 1)), "bottom": ((1, 0, 0), (0, -1, 0), (0, 0, -1)),
         "front": ((1, 0, 0), (0, 0, 1), (0, -1, 0)), "back": ((-1, 0, 0), (0, 0, 1), (0, 1, 0)),
         "left": ((0, -1, 0), (0, 0, 1), (-1, 0, 0)), "right": ((0, 1, 0), (0, 0, 1), (1, 0, 0))}
SINK = 0.3                  # a raised shape starts this far inside the surface, so it is welded to it
LIFT = 0.5                  # an engraving cutter sticks out this much, so the cut is clean


def frame(face):
    if face not in FACES:
        raise ValueError(f"face must be one of {', '.join(FACES)}")
    return tuple(np.asarray(a, float) for a in FACES[face])


def height_field(verts, tris, U, V, N, uu, vv):
    """For each grid point (u in uu, v in vv): the n-coordinate of the outermost surface facing n (NaN where none)."""
    c = np.asarray(verts, float)[np.asarray(tris)]
    pu, pv, pn = c @ U, c @ V, c @ N
    facing = np.cross(c[:, 1] - c[:, 0], c[:, 2] - c[:, 0]) @ N > 1e-12
    inside = (pu.max(1) >= uu[0]) & (pu.min(1) <= uu[-1]) & (pv.max(1) >= vv[0]) & (pv.min(1) <= vv[-1])
    du, dv = uu[1] - uu[0], vv[1] - vv[0]
    H = np.full((len(vv), len(uu)), np.nan)
    for k in np.nonzero(facing & inside)[0]:
        i0, i1 = max(0, int(math.ceil((pu[k].min() - uu[0]) / du))), min(len(uu) - 1, int((pu[k].max() - uu[0]) / du))
        j0, j1 = max(0, int(math.ceil((pv[k].min() - vv[0]) / dv))), min(len(vv) - 1, int((pv[k].max() - vv[0]) / dv))
        if i1 < i0 or j1 < j0:
            continue
        gu, gv = np.meshgrid(uu[i0:i1 + 1], vv[j0:j1 + 1])
        x0, x1, x2 = pu[k]
        y0, y1, y2 = pv[k]
        det = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(det) < 1e-12:
            continue
        l0 = ((y1 - y2) * (gu - x2) + (x2 - x1) * (gv - y2)) / det
        l1 = ((y2 - y0) * (gu - x2) + (x0 - x2) * (gv - y2)) / det
        l2 = 1 - l0 - l1
        ok = (l0 >= -1e-9) & (l1 >= -1e-9) & (l2 >= -1e-9)
        if not ok.any():
            continue
        z = l0 * pn[k, 0] + l1 * pn[k, 1] + l2 * pn[k, 2]
        block = H[j0:j1 + 1, i0:i1 + 1]
        block[ok] = np.fmax(block[ok], z[ok])
    return H


def _fill(H):
    """NaN cells take the mean of their valid neighbors, a few rings out (for the shape's very edge)."""
    H = H.copy()
    for _ in range(4):
        nan = np.isnan(H)
        if not nan.any():
            break
        pad = np.pad(H, 1, constant_values=np.nan)
        nb = np.stack([pad[1 + di:pad.shape[0] - 1 + di, 1 + dj:pad.shape[1] - 1 + dj]
                       for di in (-1, 0, 1) for dj in (-1, 0, 1) if di or dj])
        with np.errstate(all="ignore"):
            mean = np.nanmean(nb, axis=0)
        H[nan] = mean[nan]
    return H


def _sample(H, uu, vv, u, v):
    """Bilinear value of the grid H at points (u, v)."""
    fu = np.clip((u - uu[0]) / (uu[1] - uu[0]), 0, len(uu) - 1.000001)
    fv = np.clip((v - vv[0]) / (vv[1] - vv[0]), 0, len(vv) - 1.000001)
    i, j = fu.astype(int), fv.astype(int)
    a, b = fu - i, fv - j
    return (H[j, i] * (1 - a) * (1 - b) + H[j, i + 1] * a * (1 - b) + H[j + 1, i] * (1 - a) * b
            + H[j + 1, i + 1] * a * b)


def build(verts, tris, shape, face, center, depth, engrave=False, rotate=0.0):
    """(verts, tris, info) of the raised shape (or of the cutter, engrave=True) on the surface of the mesh, in the
    mesh's own frame. shape: shapely, mm, centered on the origin; center: (u, v) on the face."""
    U, V, N = frame(face)
    if rotate:
        shape = affinity.rotate(shape, rotate, origin=(0, 0))
    shape = affinity.translate(shape, center[0], center[1])
    x0, y0, x1, y1 = shape.bounds
    step = max(0.05, min(0.25, max(x1 - x0, y1 - y0) / 80))
    uu = np.arange(x0 - 2 * step, x1 + 2 * step, step)
    vv = np.arange(y0 - 2 * step, y1 + 2 * step, step)
    H = height_field(verts, tris, U, V, N, uu, vv)
    gu, gv = np.meshgrid(uu, vv)
    within = shapely.contains_xy(shape, gu, gv)
    if within.any() and np.isnan(H[within]).mean() > 0.002:
        raise ValueError(f"the {face} face does not reach under the whole shape (it goes past an edge or over a "
                         "hole): make it smaller, move it with at=, or pick another face")
    if not within.any() or np.isnan(H).all():
        raise ValueError(f"there is no {face} face under that place")
    span = float(np.nanmax(H[within]) - np.nanmin(H[within]))
    H = _fill(H)
    m = geometry.to_manifold(*geometry.extrude(shape, 1.0)).refine_to_length(max(0.3, 2 * step))

    def bend(p):
        p = np.asarray(p, float)
        s = _sample(H, uu, vv, p[:, 0], p[:, 1])
        n = (s - depth + p[:, 2] * (depth + LIFT)) if engrave else (s - SINK + p[:, 2] * (depth + SINK))
        return p[:, :1] * U + p[:, 1:2] * V + n[:, None] * N
    m = m.warp_batch(bend)
    if m.status() != geometry.m3.Error.NoError or m.is_empty():
        raise ValueError("the shape could not follow this surface: try a flatter place or a smaller shape")
    v, t = geometry.from_manifold(m)
    return v, t, {"surface_relief_mm": round(span, 2), "grid_mm": round(step, 3)}
