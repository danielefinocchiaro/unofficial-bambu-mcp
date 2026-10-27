"""Meshes: load/save STL and OBJ, primitives, text, transforms and checks. Units: mm, Z up."""
import math
import os
import struct

import numpy as np

try:
    import manifold3d as m3
except ImportError:  # optional: only primitives, text and checks need it
    m3 = None


# ---------------------------------------------------------------- I/O
def load_stl(path):
    with open(path, "rb") as f:
        data = f.read()
    if len(data) >= 84:
        n = struct.unpack("<I", data[80:84])[0]
        if 84 + 50 * n == len(data):
            rec = np.frombuffer(data[84:], dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")], count=n)
            return _weld(rec["v"].reshape(-1, 3).astype(np.float64))
    verts = []
    for line in data.decode("utf-8", "ignore").splitlines():
        line = line.strip()
        if line.startswith("vertex"):
            verts.append([float(x) for x in line.split()[1:4]])
    if not verts:
        raise ValueError(f"{path}: not a valid STL")
    return _weld(np.asarray(verts, float))


def _weld(corners, decimals=5):
    """Triangle soup (3 rows per triangle) -> shared vertices + index triangles."""
    keys = np.round(corners, decimals)
    uniq, inv = np.unique(keys, axis=0, return_inverse=True)
    tris = inv.reshape(-1, 3)
    good = (tris[:, 0] != tris[:, 1]) & (tris[:, 1] != tris[:, 2]) & (tris[:, 0] != tris[:, 2])
    return uniq.astype(np.float64), tris[good].astype(np.int64)


def load_obj(path):
    verts, faces = [], []
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("v "):
                verts.append([float(x) for x in line.split()[1:4]])
            elif line.startswith("f "):
                idx = [int(tok.split("/")[0]) for tok in line.split()[1:]]
                idx = [i - 1 if i > 0 else len(verts) + i for i in idx]
                for k in range(1, len(idx) - 1):
                    faces.append([idx[0], idx[k], idx[k + 1]])
    return np.asarray(verts, float), np.asarray(faces, np.int64)


def save_stl(path, verts, tris, header=b"unofficial-bambu-mcp"):
    tri = np.asarray(verts)[np.asarray(tris)]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-12)
    rec = np.zeros(len(tri), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["n"], rec["v"] = n, tri
    with open(path, "wb") as f:
        f.write(header[:80].ljust(80, b" "))
        f.write(struct.pack("<I", len(tri)))
        f.write(rec.tobytes())
    return path


# ---------------------------------------------------------------- transforms
def bounds(verts):
    v = np.asarray(verts)
    return v.min(0), v.max(0)


def rotate(verts, deg, axis="z"):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    i, j = {"z": (0, 1), "x": (1, 2), "y": (2, 0)}[axis]
    v = np.array(verts, float)
    vi, vj = v[:, i].copy(), v[:, j].copy()
    v[:, i], v[:, j] = c * vi - s * vj, s * vi + c * vj
    return v


def scale(verts, factor):
    f = np.broadcast_to(np.asarray(factor, float), (3,))
    return np.asarray(verts, float) * f


def apply_matrix(verts, m):
    """m: 4x4 (column vectors, p' = M @ p)."""
    v = np.asarray(verts, float)
    return v @ m[:3, :3].T + m[:3, 3]


# ---------------------------------------------------------------- solids (manifold3d)
def _need_manifold():
    if m3 is None:
        raise RuntimeError("manifold3d is not installed")


def to_manifold(verts, tris):
    _need_manifold()
    mesh = m3.Mesh(vert_properties=np.asarray(verts, np.float32), tri_verts=np.asarray(tris, np.uint32))
    return m3.Manifold(mesh)


def from_manifold(m):
    me = m.to_mesh()
    return np.asarray(me.vert_properties)[:, :3].astype(np.float64), np.asarray(me.tri_verts).astype(np.int64)


def check(verts, tris):
    """Is it a closed solid? Volume, pieces, and a short verdict."""
    info = {"triangles": int(len(tris)), "vertices": int(len(verts))}
    lo, hi = bounds(verts)
    info["size_mm"] = [round(float(x), 2) for x in hi - lo]
    if m3 is None:
        return info
    try:
        m = to_manifold(verts, tris)
        st = m.status()
        ok = st == m3.Error.NoError and not m.is_empty()
        info.update({"manifold": bool(ok), "status": str(st).split(".")[-1]})
        if ok:
            info.update({"volume_mm3": round(m.volume(), 1), "pieces": len(m.decompose()), "genus": m.genus()})
    except Exception as e:  # noqa: BLE001
        info.update({"manifold": False, "status": str(e)[:120]})
    return info


def box(w, d, h, chamfer=0.0):
    _need_manifold()
    m = m3.Manifold.cube((w, d, h), center=False).translate((-w / 2, -d / 2, 0))
    return from_manifold(m)


def cylinder(diameter, h, segments=96):
    _need_manifold()
    return from_manifold(m3.Manifold.cylinder(h, diameter / 2, circular_segments=segments))


def cone(d_bottom, d_top, h, segments=96):
    _need_manifold()
    return from_manifold(m3.Manifold.cylinder(h, d_bottom / 2, d_top / 2, circular_segments=segments))


def sphere(diameter, segments=96):
    _need_manifold()
    m = m3.Manifold.sphere(diameter / 2, circular_segments=segments).translate((0, 0, diameter / 2))
    return from_manifold(m)


# ---------------------------------------------------------------- text
def default_font():
    cands = {
        "Darwin": ["/System/Library/Fonts/Supplemental/Arial Bold.ttf", "/System/Library/Fonts/Supplemental/Arial.ttf",
                   "/Library/Fonts/Arial.ttf"],
        "Windows": [r"C:\Windows\Fonts\arialbd.ttf", r"C:\Windows\Fonts\arial.ttf"],
    }
    import platform
    for p in cands.get(platform.system(), []) + ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
                                                 "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf"]:
        if os.path.exists(p):
            return p
    raise FileNotFoundError("no default font found: pass a .ttf/.otf path")


def _glyph_polys(font, gname):
    from fontTools.pens.basePen import BasePen

    class Flat(BasePen):
        def __init__(self, gs):
            super().__init__(gs)
            self.rings, self.cur = [], []

        def _moveTo(self, p):
            self.cur = [p]

        def _lineTo(self, p):
            self.cur.append(p)

        def _curveToOne(self, p1, p2, p3):
            p0 = self.cur[-1]
            for t in np.linspace(0, 1, 13)[1:]:
                a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t ** 2, t ** 3
                self.cur.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                                 a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))

        def _qCurveToOne(self, p1, p2):
            p0 = self.cur[-1]
            for t in np.linspace(0, 1, 9)[1:]:
                self.cur.append(((1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0],
                                 (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]))

        def _closePath(self):
            if len(self.cur) >= 3:
                self.rings.append(self.cur)
            self.cur = []

        _endPath = _closePath

    gs = font.getGlyphSet()
    pen = Flat(gs)
    gs[gname].draw(pen)
    return pen.rings


def _fill_nonzero(rings):
    from shapely.geometry import LinearRing, LineString, Polygon
    from shapely.ops import polygonize, unary_union
    rings = [LinearRing(r) for r in rings if len(set(map(tuple, r))) >= 3]
    if not rings:
        return Polygon()
    polys = [(Polygon(r).buffer(0), 1 if r.is_ccw else -1) for r in rings]
    keep = []
    for face in polygonize(unary_union([LineString(list(r.coords)) for r in rings])):
        p = face.representative_point()
        if sum(s for poly, s in polys if poly.contains(p)) != 0:
            keep.append(face)
    return unary_union(keep).buffer(0)


def text_outline(s, height=10.0, font=None, spacing=0.0, line_gap=1.4):
    """Text as a shapely shape; `height` = capital letter height in mm. Centered on the origin."""
    from fontTools.ttLib import TTCollection, TTFont
    from shapely import affinity
    from shapely.ops import unary_union
    path = font or default_font()
    f = TTCollection(path).fonts[0] if path.lower().endswith(".ttc") else TTFont(path)
    cmap = f.getBestCmap()
    hmtx = f["hmtx"]
    capu = getattr(f["OS/2"], "sCapHeight", 0) or f["head"].unitsPerEm * 0.7
    k = height / capu
    rows = []
    lines = s.split("\n")
    for li, line in enumerate(lines):
        x, glyphs = 0.0, []
        for ch in line:
            g = cmap.get(ord(ch))
            if g is None:
                continue
            shape = _fill_nonzero(_glyph_polys(f, g))
            if not shape.is_empty:
                glyphs.append(affinity.translate(shape, x, 0))
            x += hmtx[g][0] + spacing / k
        row = unary_union(glyphs)
        rows.append(affinity.translate(row, -(x - spacing / k) / 2, (len(lines) - 1 - li) * capu * line_gap))
    out = affinity.scale(unary_union(rows), k, k, origin=(0, 0))
    x0, y0, x1, y1 = out.bounds
    return affinity.translate(out, -(x0 + x1) / 2, -(y0 + y1) / 2)


def extrude(shape, h, z0=0.0):
    """Extrude a shapely (Multi)Polygon to a solid from z0 to z0+h."""
    _need_manifold()
    from shapely.geometry import Polygon
    polys = [shape] if isinstance(shape, Polygon) else list(getattr(shape, "geoms", []))
    rings = []
    for p in polys:
        if p.is_empty:
            continue
        rings.append(np.asarray(p.exterior.coords)[:-1])
        rings += [np.asarray(i.coords)[:-1] for i in p.interiors]
    cs = m3.CrossSection(rings, m3.FillRule.EvenOdd)
    return from_manifold(m3.Manifold.extrude(cs, h).translate((0, 0, z0)))


def text_solid(s, height=10.0, depth=2.0, font=None, base=0.0, margin=3.0, spacing=0.0):
    """Raised text; with base>0 the text sits on a rounded plate `base` mm thick."""
    shape = text_outline(s, height, font, spacing)
    if base <= 0:
        return extrude(shape, depth)
    _need_manifold()
    plate = shape.envelope.buffer(margin, join_style=1)
    v1, t1 = extrude(plate, base)
    v2, t2 = extrude(shape, depth + 0.01, base - 0.01)
    m = to_manifold(v1, t1) + to_manifold(v2, t2)
    return from_manifold(m)


def text_parts(s, height=10.0, depth=2.0, font=None, base=1.0, margin=3.0, spacing=0.0):
    """Raised text on a rounded plate as two separate solids, so each can get its own filament:
    [("Base", verts, tris), ("Text", verts, tris)]; the letters stand on top of the plate."""
    return shape_parts(text_outline(s, height, font, spacing), depth, base, margin, "Text")


def shape_parts(shape, depth=2.0, base=1.0, margin=3.0, label="Logo"):
    """A flat shape raised on a rounded plate, as two solids: [("Base", ...), (label, ...)]."""
    plate = shape.envelope.buffer(margin, join_style=1)
    return [("Base", *extrude(plate, base)), (label, *extrude(shape, depth, base))]


def crop_height(verts, tris, z_max):
    """Keep only the part of a closed solid below z_max (first-layers test prints)."""
    _need_manifold()
    lo, hi = bounds(verts)
    m = to_manifold(verts, tris)
    cutter = m3.Manifold.cube((hi[0] - lo[0] + 2, hi[1] - lo[1] + 2, z_max - lo[2])).translate(
        (lo[0] - 1, lo[1] - 1, lo[2]))
    return from_manifold(m ^ cutter)


# ---------------------------------------------------------------- mirror, lay flat, cut
def mirror(verts, tris, axis="x"):
    """Mirror across a plane through the origin; triangle winding is flipped so normals stay outward."""
    v = np.array(verts, float)
    v[:, "xyz".index(axis)] *= -1
    return v, np.asarray(tris)[:, [0, 2, 1]]


def rotation_between(a, b):
    """3x3 rotation taking unit vector a onto unit vector b (Rodrigues)."""
    a = np.asarray(a, float) / np.linalg.norm(a)
    b = np.asarray(b, float) / np.linalg.norm(b)
    v = np.cross(a, b)
    c = float(np.dot(a, b))
    if np.linalg.norm(v) < 1e-9:
        if c > 0:
            return np.eye(3)
        axis = np.array([1.0, 0, 0]) if abs(a[0]) < 0.9 else np.array([0, 1.0, 0])
        axis -= axis.dot(a) * a
        axis /= np.linalg.norm(axis)
        return 2 * np.outer(axis, axis) - np.eye(3)
    k = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + k + k @ k * (1 / (1 + c))


def flat_faces(verts, top=5):
    """Biggest flat faces of the convex hull: [(area_mm2, outward normal)], largest first."""
    _need_manifold()
    hull = m3.Manifold.hull_points(np.asarray(verts, float))
    hv, ht = from_manifold(hull)
    tri = hv[ht]
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    area = np.linalg.norm(n, axis=1) / 2
    ok = area > 1e-9
    n = n[ok] / (2 * area[ok, None])
    area = area[ok]
    groups = {}
    for ni, ai in zip(n, area, strict=True):
        key = tuple(np.round(ni, 2))
        g = groups.setdefault(key, [0.0, np.zeros(3)])
        g[0] += ai
        g[1] += ai * ni
    faces = sorted(((a, s / np.linalg.norm(s)) for a, s in groups.values()), key=lambda x: -x[0])
    return faces[:top]


def lay_flat_matrix(verts, face=1):
    """Rotation that puts the face-th biggest hull face on the bed (normal pointing down)."""
    faces = flat_faces(verts, top=max(5, face))
    area, normal = faces[min(face, len(faces)) - 1]
    return rotation_between(normal, (0, 0, -1)), area
