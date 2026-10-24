"""Cutting a solid with a plane, with connectors that line the pieces up when they are glued, like the connectors
of Bambu Studio's Cut tool: a plug (a peg on one piece, a hole with clearance in the other) or a dowel (a hole in
both pieces and a separate pin). Everything is done with manifold3d booleans in the "cut frame": the plane is z = 0,
the piece below it is A and the piece above it is B."""
import math

import manifold3d as m3
import numpy as np
from shapely.geometry import Point, Polygon
from shapely.ops import nearest_points, polylabel, unary_union

from .geometry import rotation_between

SHAPES = ("cylinder", "square", "hexagon")
STYLES = ("prism", "frustum")
TAPER = math.tan(math.radians(10))     # a frustum's sides lean in by 10°
SINK = 0.2                             # mm a peg goes into its own piece, so the union is one solid
EXTRA = 0.3                            # mm of room at the bottom of a hole, so the peg does not bottom out
WALL = 1.0                             # mm of material a hole needs around it, down to its bottom


def frame(point, normal):
    """(R, p, n): R rotates the cut plane's normal n onto +z; cut frame = R @ (x - p). n is turned to point up
    (or kept for a vertical plane), so A is the lower piece."""
    n = np.asarray(normal, float)
    if np.linalg.norm(n) < 1e-9:
        raise ValueError("the plane's normal cannot be [0, 0, 0]")
    n = n / np.linalg.norm(n)
    if n[2] < -1e-9:
        n = -n
    return rotation_between(n, [0, 0, 1]), np.asarray(point, float), n


def _affine(R, t):
    return np.hstack([R, np.asarray(t, float).reshape(3, 1)])


def to_frame(m, R, p):
    return m.transform(_affine(R, -R @ p))


def from_frame(m, R, p):
    return m.transform(_affine(R.T, p))


def section(solids):
    """Shape of the cut (shapely), from the solids already in the cut frame."""
    shapes = []
    for m in solids:
        shape = Polygon()
        for ring in m.slice(0.0).to_polygons():
            if len(ring) >= 3:
                shape = shape.symmetric_difference(Polygon(ring).buffer(0))
        shapes.append(shape)
    return unary_union(shapes).buffer(0)


def _profile(shape, size, grow=0.0):
    """Cross-section centered on 0: cylinder of diameter `size`, square of side `size`, hexagon `size` across flats,
    grown by `grow` on every side."""
    if shape == "cylinder":
        return m3.CrossSection.circle(size / 2 + grow, 64)
    if shape == "square":
        return m3.CrossSection.square((size + 2 * grow, size + 2 * grow), True)
    if shape == "hexagon":
        return m3.CrossSection.circle((size / 2 + grow) / math.cos(math.pi / 6), 6)
    raise ValueError(f"connector shape must be one of {SHAPES}")


def _prism(shape, size, height, z0=0.0, grow=0.0, shrink=0.0):
    """The profile from z0 up to z0 + height, its sides moving in by `shrink` mm at the top."""
    w = size + 2 * grow
    k = max(0.05, (w - 2 * shrink) / w)
    return m3.Manifold.extrude(_profile(shape, size, grow), height, 0, 0.0, (k, k)).translate((0, 0, z0))


def peg(shape, style, size, depth, chamfer):
    """The male part, standing on z = 0 up to `depth` (and SINK below), with a chamfer at the tip."""
    lean = TAPER if style == "frustum" else 0.0
    body_h = depth - chamfer
    body = _prism(shape, size, body_h + SINK, -SINK, shrink=lean * body_h)
    top = size - 2 * lean * body_h
    tip = _prism(shape, top, chamfer, body_h, shrink=chamfer)
    return body + tip


def hole(shape, style, size, depth, clearance, chamfer, wall=0.0):
    """The female part for a peg of that size and depth: `clearance` mm wider on every side, EXTRA deeper, with a
    chamfer at the mouth (z = 0). wall > 0 gives the hole grown by that much, to check the material around it."""
    lean = TAPER if style == "frustum" else 0.0
    h = depth + EXTRA + clearance
    body = _prism(shape, size, h + SINK, -SINK, grow=clearance + wall, shrink=lean * h)
    mouth = _prism(shape, size, chamfer + SINK, -SINK, grow=clearance + chamfer + SINK + wall, shrink=chamfer + SINK)
    return body + mouth


def fits(cavity, solid):
    """Does the cavity (above z = 0) stay inside the solid? A hole that pierces the other side, or leaves less
    than WALL around it, does not."""
    inside = cavity.split_by_plane((0.0, 0.0, 1.0), 0.05)[0]
    return (inside - solid).volume() < 0.01


def auto_size(sec):
    """Connector size from the cut: 40 % of the largest circle that fits in the biggest piece, 3..10 mm."""
    big = max(_polys(sec), key=lambda q: q.area)
    rho = big.exterior.distance(polylabel(big, 0.1)) if big.area else 0
    return round(min(10.0, max(3.0, 0.8 * rho)), 1)


def _polys(geom):
    return [g for g in getattr(geom, "geoms", [geom]) if isinstance(g, Polygon) and not g.is_empty]


def auto_positions(sec, radius, margin, count=0):
    """Where connectors of that radius fit with `margin` mm of material around them. count 0: one per piece of the
    cut, two along a long piece; count N: N points spread over the cut."""
    room = sec.buffer(-(radius + margin))
    pieces = [q for q in _polys(room) if q.area > 0.01]
    if not pieces:
        return []
    if count <= 0:
        out = []
        for q in pieces:
            x, y = q.minimum_rotated_rectangle.exterior.coords.xy
            sides = sorted(math.dist((x[i], y[i]), (x[i + 1], y[i + 1])) for i in range(2))
            out += _spread(q, 2) if sides[1] >= 4 * radius + 2 * margin and sides[1] >= 2 * sides[0] else _spread(q, 1)
        return out
    return _spread(unary_union(pieces), count)


def _spread(region, n):
    """n points inside region, evenly spaced along its length (in two rows for 4 or more on a squarish cut);
    one point goes where there is the most room."""
    best = max(_polys(region), key=lambda q: q.area)
    if n == 1:
        c = polylabel(best, 0.05)
        mid = best.centroid                      # the middle, when it has as much room (a rectangle, a disc)
        if best.contains(mid) and best.exterior.distance(mid) >= 0.9 * best.exterior.distance(c):
            c = mid
        return [(c.x, c.y)]
    x, y = region.minimum_rotated_rectangle.exterior.coords.xy
    corners = np.column_stack([x, y])[:4]
    e1, e2 = corners[1] - corners[0], corners[3] - corners[0]
    if np.linalg.norm(e1) < np.linalg.norm(e2):
        e1, e2 = e2, e1
    rows = 2 if n >= 4 and np.linalg.norm(e1) < 2 * np.linalg.norm(e2) else 1
    cols = math.ceil(n / rows)
    out = []
    for k in range(n):
        i, j = k % cols, k // cols
        q = corners[0] + e1 * (i + 0.5) / cols + e2 * ((j + 0.5) / rows if rows > 1 else 0.5)
        pt = Point(q)
        if not region.contains(pt):                # snap inside, a little past the edge
            near = nearest_points(region, pt)[0]
            inward = np.asarray(region.centroid.coords[0]) - np.asarray(near.coords[0])
            pt = Point(np.asarray(near.coords[0]) + 0.05 * inward / (np.linalg.norm(inward) or 1))
        out.append((float(pt.x), float(pt.y)))
    return out


FLIP = np.diag([1.0, -1.0, -1.0])      # half a turn around x: in the cut frame, puts A on its cut face


def _circumradius(shape, size):
    return size / 2 * {"cylinder": 1.0, "square": math.sqrt(2), "hexagon": 1 / math.cos(math.pi / 6)}[shape]


def _pin(shape, size, length, chamfer):
    """A dowel lying along z from 0 to length, chamfered at both ends."""
    core = _prism(shape, size, length - 2 * chamfer, chamfer)
    top = _prism(shape, size, chamfer, length - chamfer, shrink=chamfer)
    bottom = _prism(shape, size - 2 * chamfer, chamfer, 0.0, shrink=-chamfer)
    return core + top + bottom


def cut(parts, point, normal, connector="none", shape="cylinder", style="prism", size=0.0, depth=0.0, count=0,
        positions=None, clearance=0.2, margin=2.0, place="auto"):
    """Cut solids with the plane through `point` with that `normal`, optionally with connectors.
    parts: [(Manifold, tag, is_solid)] in one frame; positions: points of that frame. place: auto (A as it is,
    B on its cut face) | cut_down (both on their cut faces) | keep (both as they are).
    Returns {"A": [(Manifold, tag)], "B": [...], "pins": Manifold or None, "connectors": [...], "skipped": [...],
    "size", "depth", "male"} with the pieces in their printing orientation (A in the original frame if kept)."""
    if connector not in ("none", "plug", "dowel", "dovetail"):
        raise ValueError("connector must be none, plug, dowel or dovetail")
    if shape not in SHAPES or style not in STYLES:
        raise ValueError(f"shape must be one of {SHAPES} and style one of {STYLES}")
    if place not in ("auto", "cut_down", "keep"):
        raise ValueError("place must be auto, cut_down or keep")
    R, p, n = frame(point, normal)
    framed = [(to_frame(m, R, p), tag, solid) for m, tag, solid in parts]
    A, B = [], []
    for m, tag, solid in framed:
        above, below = m.split_by_plane((0.0, 0.0, 1.0), 0.0)
        if not below.is_empty():
            A.append([below, tag, solid])
        if not above.is_empty():
            B.append([above, tag, solid])
    if not any(s for _, _, s in A) or not any(s for _, _, s in B):
        raise ValueError("the plane does not cross the object")
    Rt = R.T
    M_A = Rt if place in ("keep", "auto") else FLIP
    M_B = Rt if place == "keep" else np.eye(3)
    res = {"normal": [round(float(c), 4) for c in n], "connectors": [], "skipped": [], "pins": None}
    if connector != "none":
        solids = [m for m, _, s in framed if s]
        sec = section(solids)
        if sec.is_empty:
            raise ValueError("the cut has no area")
        size = size or auto_size(sec)
        if connector == "dovetail":
            depth = depth or round(min(12.0, max(3.0, 0.8 * size)), 1)
        else:
            depth = depth or (min(15.0, max(3.0, size)) if connector == "plug" else min(30.0, max(6.0, 2 * size)))
        chamfer = round(min(0.6, 0.12 * size), 2)
        r_hole = _circumradius(shape, size) + clearance
        if positions:
            uv = [tuple((R @ (np.asarray(q, float) - p))[:2]) for q in positions]
        else:
            uv = auto_positions(sec, r_hole, margin, count)
            if not uv:
                res["skipped"].append({"why": f"no room for a {size:g} mm connector with {margin:g} mm around it: "
                                              "give a smaller size or positions"})
        male = None
        if connector in ("plug", "dovetail"):
            if (M_A @ [0, 0, 1])[2] >= 0.7:
                male = "A"
            elif (M_B @ [0, 0, -1])[2] >= 0.7:
                male = "B"
            else:
                raise ValueError("a plug would stick out sideways or downwards on both pieces: use connector='dowel', "
                                 "or a plane closer to horizontal")
        res.update(size=size, depth=depth, chamfer=chamfer, male=male)
        a_all = _union([m for m, _, s in A if s]).mirror((0.0, 0.0, 1.0))      # A seen from below, to check holes
        b_all = _union([m for m, _, s in B if s])
        if connector == "dovetail":
            res.update(size=size, depth=depth, chamfer=0.0, male=male)
            _dovetail(res, sec, A, B, a_all, b_all, R, p, male, size, depth, clearance, positions)
            uv = []
        pins = []
        for u, v in uv:
            q3 = R.T @ np.array([u, v, 0.0]) + p
            where = [round(float(c), 2) for c in q3]
            if not sec.buffer(-(r_hole + min(margin, 0.5))).contains(Point(u, v)):
                res["skipped"].append({"at": where, "why": "too close to the edge of the cut"})
                continue
            d = depth if connector == "plug" else depth / 2
            while d >= 2.0:
                check = hole(shape, style, size, d, clearance, chamfer, wall=WALL).translate((u, v, 0))
                if connector == "plug":
                    ok = fits(check, b_all if male == "A" else a_all)
                else:
                    ok = fits(check, b_all) and fits(check, a_all)
                if ok:
                    break
                d = round(d * 0.8, 1)
            else:
                res["skipped"].append({"at": where, "why": "the piece is too thin there for a hole"})
                continue
            cav = hole(shape, style, size, d, clearance, chamfer).translate((u, v, 0))
            if connector == "plug":
                pg = peg(shape, style, size, d, chamfer).translate((u, v, 0))
                if male == "B":
                    pg, cav = pg.mirror((0.0, 0.0, 1.0)), cav.mirror((0.0, 0.0, 1.0))
                own, other = (A, B) if male == "A" else (B, A)
                host = _host(own, u, v)
                host[0] = host[0] + pg
                for item in other:
                    if item[2]:
                        item[0] = item[0] - cav
                res["connectors"].append({"at": where, "depth": d})
            else:
                for item in B:
                    if item[2]:
                        item[0] = item[0] - cav
                for item in A:
                    if item[2]:
                        item[0] = item[0] - cav.mirror((0.0, 0.0, 1.0))
                pins.append(_pin(shape, size, 2 * d, chamfer))
                res["connectors"].append({"at": where, "depth": 2 * d})
        if pins:
            step = size + 4
            res["pins"] = _union([pin.translate((i * step, 0, 0)) for i, pin in enumerate(pins)])
    # a piece kept as it was goes back to the original frame (R.T, then + p); the others stay in the cut frame
    res["A"] = [(m.transform(_affine(M_A, p if M_A is Rt else np.zeros(3))), tag) for m, tag, _ in A]
    res["B"] = [(m.transform(_affine(M_B, p if M_B is Rt else np.zeros(3))), tag) for m, tag, _ in B]
    return res


DOVETAIL = math.tan(math.radians(15))  # a dovetail's sides open by 15°: wider at the top, still printable


def _rail(width, height, length, lean, grow=0.0):
    """A dovetail along +y from -length/2 to length/2: width at z = 0, wider by `lean` per mm of height, grown by
    `grow` on its sides and top, and going SINK below z = 0."""
    a0, a1 = width / 2 + grow, width / 2 + grow + lean * height
    h = height + grow
    cs = m3.CrossSection([[(-a0, -SINK), (a0, -SINK), (a0, 0.0), (a1 + lean * grow, h), (-a1 - lean * grow, h),
                           (-a0, 0.0)]])
    m = m3.Manifold.extrude(cs, length)                  # profile in x (across) and y (up), along +z
    return m.transform(_affine(np.array([[1.0, 0, 0], [0, 0, 1.0], [0, 1.0, 0]]), (0, -length / 2, 0)))


def _union(ms):
    out = ms[0]
    for m in ms[1:]:
        out = out + m
    return out


def _host(items, u, v):
    """The solid part whose cut contains (u, v): the peg is joined to it."""
    best, area = None, -1.0
    for item in items:
        if not item[2]:
            continue
        s = section([item[0]])
        if s.contains(Point(u, v)):
            return item
        if s.area > area:
            best, area = item, s.area
    return best



def _dovetail(res, sec, A, B, a_all, b_all, R, p, male, width, depth, clearance, positions):
    """One dovetail across the whole cut, along its length (or along x through the given position): the tongue on
    the male piece, a slot with clearance in the other; the pieces slide together from the side."""
    x, y = sec.minimum_rotated_rectangle.exterior.coords.xy
    corners = np.column_stack([x, y])[:4]
    e1, e2 = corners[1] - corners[0], corners[3] - corners[0]
    if np.linalg.norm(e1) < np.linalg.norm(e2):
        e1 = e2
    e1 = e1 / np.linalg.norm(e1)
    c = np.asarray(sec.centroid.coords[0])
    if positions:
        c = (R @ (np.asarray(positions[0], float) - p))[:2]
    length = 2 * max(sec.bounds[2] - sec.bounds[0], sec.bounds[3] - sec.bounds[1]) + 10
    rot = np.array([[e1[1], e1[0], 0.0], [-e1[0], e1[1], 0.0], [0.0, 0.0, 1.0]])    # +y onto e1
    place = _affine(rot, (c[0], c[1], 0.0))
    rings = [np.asarray(q.exterior.coords)[:-1] for q in _polys(sec)]
    rings += [np.asarray(h.coords)[:-1] for q in _polys(sec) for h in q.interiors]
    outline = m3.CrossSection([r.tolist() for r in rings], m3.FillRule.EvenOdd)
    foot = m3.Manifold.extrude(outline, depth + 5).translate((0, 0, -SINK))   # the cut's outline, upwards
    d = depth
    while d >= 2.0:
        slot = _rail(width, d, length, DOVETAIL, grow=clearance).transform(place)
        under = (slot ^ foot).translate((0, 0, WALL))          # the slot inside the cut's outline, raised by WALL
        other = b_all if male == "A" else a_all
        if (under.split_by_plane((0.0, 0.0, 1.0), 0.05)[0] - other).volume() < 0.01:
            break
        d = round(d * 0.8, 1)
    else:
        res["skipped"].append({"why": "the pieces are too thin for a dovetail"})
        return
    tongue = _rail(width, d, length, DOVETAIL).transform(place) ^ foot
    slot = _rail(width, d, length, DOVETAIL, grow=clearance).transform(place)
    if male == "B":
        tongue, slot = tongue.mirror((0.0, 0.0, 1.0)), slot.mirror((0.0, 0.0, 1.0))
    own, other_items = (A, B) if male == "A" else (B, A)
    host = _host(own, c[0], c[1])
    host[0] = host[0] + tongue
    for item in other_items:
        if item[2]:
            item[0] = item[0] - slot
    q3 = R.T @ np.array([c[0], c[1], 0.0]) + p
    res["connectors"].append({"at": [round(float(v), 2) for v in q3], "depth": d,
                              "along": [round(float(v), 3) for v in R.T @ np.array([e1[0], e1[1], 0.0])]})
