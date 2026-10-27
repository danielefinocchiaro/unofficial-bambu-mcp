"""Auto orientation: which way up an object prints best, like Bambu Studio's Auto orientation (with a method of
its own). Every candidate "down" direction (the big flat faces of the convex hull, plus directions spread over the
sphere) is scored on three things, from the triangles:

- support: area of the faces that look down more steeply than the overhang angle and are not on the bed;
- on the bed: area of the faces lying on the bed (adhesion), which helps up to a point;
- height: lower is steadier and quicker.
"""
import math

import numpy as np

from . import geometry

MAX_FACES = 150_000           # bigger meshes are scored on an even sample of their faces
CONTACT_ENOUGH = 0.15         # share of the surface on the bed beyond which more contact does not help
W_CONTACT, W_HEIGHT = 0.08, 0.04


def _sphere(n):
    """n directions spread evenly over the sphere (Fibonacci)."""
    k = np.arange(n) + 0.5
    phi = np.arccos(1 - 2 * k / n)
    theta = math.pi * (1 + 5 ** 0.5) * k
    return np.stack([np.cos(theta) * np.sin(phi), np.sin(theta) * np.sin(phi), np.cos(phi)], axis=1)


def _faces(verts, tris):
    corners = np.asarray(verts, float)[np.asarray(tris)]
    if len(corners) > MAX_FACES:
        idx = np.linspace(0, len(corners) - 1, MAX_FACES).astype(np.int64)
        scale = len(corners) / MAX_FACES
        corners = corners[idx]
    else:
        scale = 1.0
    n = np.cross(corners[:, 1] - corners[:, 0], corners[:, 2] - corners[:, 0])
    area = np.linalg.norm(n, axis=1) / 2
    ok = area > 1e-12
    return corners[ok], n[ok] / (2 * area[ok, None]), area[ok] * scale


def score(corners, normals, area, down, overhang_deg=45.0, total=None, diag=None):
    """Numbers for putting `down` toward the bed: {support_mm2, on_bed_mm2, height_mm, cost} (lower cost = better)."""
    rot = geometry.rotation_between(down, (0, 0, -1))
    up = rot[2]                                       # the new z of a point p is up · p
    z = corners @ up
    zmin = z.min()
    nz = normals @ up
    on_bed = (z.max(axis=1) < zmin + 0.05) & (nz < -0.99)
    near_bed = z.max(axis=1) < zmin + 0.3
    steep = nz < -math.cos(math.radians(overhang_deg))
    support = float(area[steep & ~near_bed].sum())
    contact = float(area[on_bed].sum())
    height = float(z.max() - zmin)
    total = total or float(area.sum())
    diag = diag or height or 1.0
    cost = (support / total + W_CONTACT * (1 - min(contact / total, CONTACT_ENOUGH) / CONTACT_ENOUGH)
            + W_HEIGHT * height / diag)
    return {"support_mm2": support, "on_bed_mm2": contact, "height_mm": height, "cost": cost, "rotation": rot}


def options(verts, tris, overhang_deg=45.0, top=3):
    """(current, [best options]): scores of the current orientation and of the `top` best distinct ones."""
    corners, normals, area = _faces(verts, tris)
    if not len(area):
        raise ValueError("the object has no faces to orient")
    total = float(area.sum())
    pts = corners.reshape(-1, 3)
    diag = float(np.linalg.norm(pts.max(0) - pts.min(0))) or 1.0
    dirs = [np.array([0.0, 0.0, -1.0])]
    try:
        dirs += [np.asarray(nrm, float) for _, nrm in geometry.flat_faces(pts, top=30)]   # that face on the bed
    except Exception:  # noqa: BLE001 - no hull (flat or broken mesh): the sphere directions are enough
        pass
    dirs += list(_sphere(240))
    scored = [(d, score(corners, normals, area, d, overhang_deg, total, diag)) for d in dirs]
    current = scored[0][1]
    ranked = sorted(scored, key=lambda s: s[1]["cost"])
    picked = []
    for d, s in ranked:
        apart = all(np.dot(d, q) < math.cos(math.radians(12)) for q, _ in picked)
        same = any(all(abs(s[k] - t[k]) <= 0.01 * max(1.0, t[k]) for k in ("support_mm2", "on_bed_mm2", "height_mm"))
                   for _, t in picked)            # the same numbers, e.g. the other end of a cylinder
        if apart and not same:
            picked.append((d, s))
        if len(picked) == top:
            break
    best = picked[0][1]
    if current["cost"] <= best["cost"] + 0.002:       # as good as it gets: keep it as it is
        picked = [(dirs[0], current)] + [p for p in picked if np.dot(p[0], dirs[0]) < math.cos(math.radians(12))]
        picked = picked[:top]
    return current, [s for _, s in picked]
