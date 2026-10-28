"""Text and SVG logos on an object's surface, raised or engraved, like Bambu Studio's Text and SVG tools.
The surface under the shape is measured on a fine grid (the first face met coming from outside), and the raised
or cut shape is wrapped on it: its size is measured along the surface, so a word on the side of a cup is as wide
as asked instead of stretched toward the edges, and it stands out perpendicular to the surface."""
import math
import warnings

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
JUMP = 0.2                  # a jump in the surface over this, and 3 times the ones around it, is a step: not wrapped
SMOOTH = 1.0                # the direction a shape stands out is averaged over this many mm, so it never folds


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
        with np.errstate(all="ignore"), warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)                 # cells with no valid neighbor yet
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


def _steps(dh):
    """Which jumps along a line of heights are steps (an edge, not a curve): over JUMP and 3 times their neighbors."""
    nb = np.maximum(np.pad(dh, (1, 0))[:-1], np.pad(dh, (0, 1))[1:])
    return (dh > JUMP) & (dh > 3 * nb)


def _arc(h, d):
    """Distance along the surface at each point of a line of heights h, d mm apart (NaN where there is none).
    Steps count as flat, so an edge under the shape does not swallow part of it."""
    k = np.arange(len(h))
    ok = ~np.isnan(h)
    h = np.interp(k, k[ok], h[ok]) if ok.sum() >= 2 else np.zeros(len(h))
    dh = np.abs(np.diff(h))
    return np.concatenate([[0.0], np.cumsum(np.hypot(d, np.where(_steps(dh), 0, dh)))])


def _slope(H, d):
    """dH/du at every grid point (along the rows), steps left out, averaged over about SMOOTH mm."""
    D = np.nan_to_num(np.diff(H, axis=1))
    D[np.apply_along_axis(lambda r: _steps(np.abs(r)), 1, D)] = 0
    G = np.pad(D, ((0, 0), (1, 1)), mode="edge")
    G = (G[:, :-1] + G[:, 1:]) / (2 * d)
    k = max(1, round(SMOOTH / d))
    box = np.ones(k) / k
    return np.apply_along_axis(lambda r: np.convolve(np.pad(r, (k // 2, k - 1 - k // 2), mode="edge"), box, "valid"),
                               1, G)


def build(verts, tris, shape, face, center, depth, engrave=False, rotate=0.0):
    """(verts, tris, info) of the raised shape (or of the cutter, engrave=True) on the surface of the mesh, in the
    mesh's own frame. shape: shapely, mm, centered on the origin; center: (u, v) on the face."""
    U, V, N = frame(face)
    if rotate:
        shape = affinity.rotate(shape, rotate, origin=(0, 0))
    cu, cv = center
    x0, y0, x1, y1 = shape.bounds
    step = max(0.05, min(0.25, max(x1 - x0, y1 - y0) / 80))
    uu = np.arange(cu + x0 - 2 * step, cu + x1 + 2 * step, step)        # wrapped, the shape covers less than this
    vv = np.arange(cv + y0 - 2 * step, cv + y1 + 2 * step, step)
    H = height_field(verts, tris, U, V, N, uu, vv)
    su = _arc(H[int(np.argmin(np.abs(vv - cv))), :], step)            # along the surface, through the center
    sv = _arc(H[:, int(np.argmin(np.abs(uu - cu)))], step)
    su0, sv0 = np.interp(cu, uu, su), np.interp(cv, vv, sv)
    gu, gv = np.meshgrid(uu, vv)
    within = shapely.contains_xy(shape, np.interp(gu, uu, su) - su0, np.interp(gv, vv, sv) - sv0)
    if within.any() and np.isnan(H[within]).mean() > 0.002:
        raise ValueError(f"the {face} face does not reach under the whole shape (it goes past an edge or over a "
                         "hole): make it smaller, move it with at=, or pick another face")
    if not within.any() or np.isnan(H).all():
        raise ValueError(f"there is no {face} face under that place")
    span = float(np.nanmax(H[within]) - np.nanmin(H[within]))
    H = _fill(H)
    Gu, Gv = _slope(H, step), _slope(H.T, step).T
    m = geometry.to_manifold(*geometry.extrude(shape, 1.0)).refine_to_length(max(0.3, 2 * step))

    def bend(p):
        p = np.asarray(p, float)
        u, v = np.interp(su0 + p[:, 0], su, uu), np.interp(sv0 + p[:, 1], sv, vv)
        n = np.column_stack([-_sample(Gu, uu, vv, u, v), -_sample(Gv, uu, vv, u, v), np.ones(len(p))])
        n /= np.linalg.norm(n, axis=1, keepdims=True)
        t = (p[:, 2] * (depth + LIFT) - depth) if engrave else (p[:, 2] * (depth + SINK) - SINK)
        q = np.column_stack([u, v, _sample(H, uu, vv, u, v)]) + t[:, None] * n
        return q[:, :1] * U + q[:, 1:2] * V + q[:, 2:3] * N
    m = m.warp_batch(bend)
    if m.status() != geometry.m3.Error.NoError or m.is_empty():
        raise ValueError("the shape could not follow this surface: try a flatter place or a smaller shape")
    v, t = geometry.from_manifold(m)
    return v, t, {"surface_relief_mm": round(span, 2), "grid_mm": round(step, 3)}
