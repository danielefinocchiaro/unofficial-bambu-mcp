"""SVG files as flat shapes (shapely, millimeters, y up, centered on the origin): paths, rectangles, circles,
ellipses, polygons and polylines, inside groups with transforms. Filled areas follow the fill rule (nonzero or
evenodd); a stroke without fill becomes an area as wide as the stroke. Curves and arcs become short segments."""
import math
import re
import xml.etree.ElementTree as ET

import numpy as np
from shapely import affinity
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

from .geometry import _fill_nonzero

_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_UNITS = {"mm": 1.0, "cm": 10.0, "in": 25.4, "pt": 25.4 / 72, "pc": 25.4 / 6, "px": 25.4 / 96, "": 25.4 / 96}
SEG = 24                      # segments per curve


def _nums(s):
    return [float(x) for x in _NUM.findall(s or "")]


def _length(s):
    """A length attribute in mm (None if missing or relative, e.g. 100%)."""
    m = re.fullmatch(r"\s*([-+]?[\d.eE+-]+)\s*([a-z%]*)\s*", s or "")
    if not m or m.group(2) == "%":
        return None
    return float(m.group(1)) * _UNITS.get(m.group(2), 25.4 / 96)


def _matrix(s):
    """3×3 matrix of an SVG transform attribute."""
    out = np.eye(3)
    for name, args in re.findall(r"(\w+)\s*\(([^)]*)\)", s or ""):
        a = _nums(args)
        m = np.eye(3)
        if name == "matrix" and len(a) == 6:
            m = np.array([[a[0], a[2], a[4]], [a[1], a[3], a[5]], [0, 0, 1]])
        elif name == "translate":
            m[0, 2], m[1, 2] = a[0], (a[1] if len(a) > 1 else 0)
        elif name == "scale":
            m[0, 0], m[1, 1] = a[0], (a[1] if len(a) > 1 else a[0])
        elif name == "rotate":
            r = math.radians(a[0])
            rot = np.array([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1]])
            if len(a) == 3:
                t1, t2 = np.eye(3), np.eye(3)
                t1[:2, 2], t2[:2, 2] = (a[1], a[2]), (-a[1], -a[2])
                rot = t1 @ rot @ t2
            m = rot
        elif name == "skewX":
            m[0, 1] = math.tan(math.radians(a[0]))
        elif name == "skewY":
            m[1, 0] = math.tan(math.radians(a[0]))
        out = out @ m
    return out


def _style(el, parent):
    st = dict(parent)
    for k in ("fill", "stroke", "stroke-width", "fill-rule", "display", "visibility", "opacity", "fill-opacity"):
        if el.get(k) is not None:
            st[k] = el.get(k).strip()
    for item in (el.get("style") or "").split(";"):
        k, _, v = item.partition(":")
        if v:
            st[k.strip()] = v.strip()
    return st


def _arc(p0, rx, ry, phi, large, sweep, p1):
    """Points of an elliptical arc (SVG endpoint form), without the start point."""
    if rx == 0 or ry == 0:
        return [p1]
    rx, ry = abs(rx), abs(ry)
    c, s = math.cos(math.radians(phi)), math.sin(math.radians(phi))
    dx, dy = (p0[0] - p1[0]) / 2, (p0[1] - p1[1]) / 2
    x1, y1 = c * dx + s * dy, -s * dx + c * dy
    lam = x1 * x1 / (rx * rx) + y1 * y1 / (ry * ry)
    if lam > 1:
        rx, ry = rx * math.sqrt(lam), ry * math.sqrt(lam)
    num = rx * rx * ry * ry - rx * rx * y1 * y1 - ry * ry * x1 * x1
    k = math.sqrt(max(0.0, num / (rx * rx * y1 * y1 + ry * ry * x1 * x1)))
    if large == sweep:
        k = -k
    cx1, cy1 = k * rx * y1 / ry, -k * ry * x1 / rx
    cx = c * cx1 - s * cy1 + (p0[0] + p1[0]) / 2
    cy = s * cx1 + c * cy1 + (p0[1] + p1[1]) / 2

    def ang(ux, uy, vx, vy):
        a = math.atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        return a
    t0 = ang(1, 0, (x1 - cx1) / rx, (y1 - cy1) / ry)
    dt = ang((x1 - cx1) / rx, (y1 - cy1) / ry, (-x1 - cx1) / rx, (-y1 - cy1) / ry)
    if not sweep and dt > 0:
        dt -= 2 * math.pi
    elif sweep and dt < 0:
        dt += 2 * math.pi
    n = max(4, int(abs(dt) / (2 * math.pi) * SEG * 2))
    pts = []
    for i in range(1, n + 1):
        t = t0 + dt * i / n
        pts.append((cx + rx * math.cos(t) * c - ry * math.sin(t) * s, cy + rx * math.cos(t) * s + ry * math.sin(t) * c))
    return pts


def _bezier(pts, n=SEG):
    p = np.asarray(pts, float)
    t = np.linspace(0, 1, n + 1)[1:, None]
    if len(p) == 3:
        return list((1 - t) ** 2 * p[0] + 2 * (1 - t) * t * p[1] + t ** 2 * p[2])
    return list((1 - t) ** 3 * p[0] + 3 * (1 - t) ** 2 * t * p[1] + 3 * (1 - t) * t ** 2 * p[2] + t ** 3 * p[3])


def path_rings(d):
    """Subpaths of a path's d attribute: [(points, closed)]."""
    toks = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?", d or "")
    out, pts, closed = [], [], False
    cur, start, last_c, cmd, i = (0.0, 0.0), (0.0, 0.0), None, None, 0

    def num():
        nonlocal i
        v = float(toks[i])
        i += 1
        return v

    def flush():
        nonlocal pts, closed
        if len(pts) >= 2:
            out.append((np.asarray(pts, float), closed))
        pts, closed = [], False

    while i < len(toks):
        if re.fullmatch(r"[A-Za-z]", toks[i]):
            cmd = toks[i]
            i += 1
            if cmd in "Zz":
                closed = True
                cur = start
                flush()
                last_c = None
                continue
        elif cmd is None:
            i += 1
            continue
        rel = cmd.islower()
        c = cmd.upper()
        ox, oy = cur if rel else (0.0, 0.0)
        if c == "M":
            flush()
            cur = (ox + num(), oy + num())
            start = cur
            pts = [cur]
            cmd = "l" if rel else "L"                # further pairs are lines
            last_c = None
        elif c == "L":
            cur = (ox + num(), oy + num())
            pts.append(cur)
            last_c = None
        elif c == "H":
            cur = ((cur[0] if rel else 0.0) + num(), cur[1])
            pts.append(cur)
            last_c = None
        elif c == "V":
            cur = (cur[0], (cur[1] if rel else 0.0) + num())
            pts.append(cur)
            last_c = None
        elif c in "CS":
            if c == "C":
                c1 = (ox + num(), oy + num())
            else:
                c1 = (2 * cur[0] - last_c[0], 2 * cur[1] - last_c[1]) if last_c and last_c[2] == "C" else cur
            c2 = (ox + num(), oy + num())
            end = (ox + num(), oy + num())
            pts += _bezier([cur, c1, c2, end])
            last_c = (c2[0], c2[1], "C")
            cur = end
        elif c in "QT":
            if c == "Q":
                c1 = (ox + num(), oy + num())
            else:
                c1 = (2 * cur[0] - last_c[0], 2 * cur[1] - last_c[1]) if last_c and last_c[2] == "Q" else cur
            end = (ox + num(), oy + num())
            pts += _bezier([cur, c1, end])
            last_c = (c1[0], c1[1], "Q")
            cur = end
        elif c == "A":
            rx, ry, phi, large, sweep = num(), num(), num(), num(), num()
            end = (ox + num(), oy + num())
            pts += _arc(cur, rx, ry, phi, int(large), int(sweep), end)
            cur = end
            last_c = None
        else:
            i += 1
        if not pts:
            pts = [cur]
    flush()
    return out


def _shape_rings(el, tag):
    g = el.get
    if tag == "path":
        return path_rings(g("d"))
    if tag == "rect":
        x, y, w, h = (float(g(k) or 0) for k in ("x", "y", "width", "height"))
        if w <= 0 or h <= 0:
            return []
        rx = float(g("rx") or g("ry") or 0)
        ry = float(g("ry") or g("rx") or 0)
        if rx > 0 or ry > 0:
            box = Polygon([(x, y), (x + w, y), (x + w, y + h), (x, y + h)])
            r = min(max(rx, ry), w / 2, h / 2)
            shape = box.buffer(-r).buffer(r, quad_segs=SEG // 4)
            return [(np.asarray(shape.exterior.coords), True)]
        return [(np.array([(x, y), (x + w, y), (x + w, y + h), (x, y + h)]), True)]
    if tag in ("circle", "ellipse"):
        cx, cy = float(g("cx") or 0), float(g("cy") or 0)
        rx = float(g("r") or g("rx") or 0)
        ry = float(g("r") or g("ry") or 0)
        if rx <= 0 or ry <= 0:
            return []
        t = np.linspace(0, 2 * math.pi, SEG * 4, endpoint=False)
        return [(np.stack([cx + rx * np.cos(t), cy + ry * np.sin(t)], axis=1), True)]
    if tag in ("polygon", "polyline"):
        v = _nums(g("points"))
        pts = np.asarray(v[:len(v) // 2 * 2], float).reshape(-1, 2)
        return [(pts, tag == "polygon")] if len(pts) >= 2 else []
    return []


def _area(rings, st, m):
    """The area an element covers: its fill and/or its stroke, after the transform m."""
    def tf(p):
        q = np.c_[p, np.ones(len(p))] @ m.T
        return q[:, :2]
    shapes = []
    fill = st.get("fill", "black")
    if fill != "none" and st.get("fill-opacity", "1") not in ("0", "0.0"):
        closed = [tf(p) for p, _ in rings if len(p) >= 3]
        if closed:
            if st.get("fill-rule") == "evenodd":
                shape = Polygon()
                for r in closed:
                    shape = shape.symmetric_difference(Polygon(r).buffer(0))
            else:
                shape = _fill_nonzero(closed)
            shapes.append(shape)
    stroke = st.get("stroke", "none")
    if stroke != "none":
        w = _length(st.get("stroke-width", "1")) / (25.4 / 96) if st.get("stroke-width") else 1.0
        w *= math.sqrt(abs(np.linalg.det(m[:2, :2]))) or 1.0
        for p, closed in rings:
            q = tf(p)
            line = LineString(np.vstack([q, q[:1]]) if closed else q)
            shapes.append(line.buffer(w / 2, quad_segs=4))
    return unary_union(shapes) if shapes else Polygon()


def load(path):
    """(shape in mm, y up, centered on the origin, (width, height) in mm)."""
    root = ET.parse(path).getroot()

    def tag(el):
        return el.tag.split("}")[-1]

    vb = _nums(root.get("viewBox"))
    w_mm, h_mm = _length(root.get("width")), _length(root.get("height"))
    if len(vb) == 4 and vb[2] > 0 and vb[3] > 0:
        sx = (w_mm / vb[2]) if w_mm else 25.4 / 96
        sy = (h_mm / vb[3]) if h_mm else sx
    else:
        sx = sy = 25.4 / 96
    base = np.array([[sx, 0, 0], [0, sy, 0], [0, 0, 1]])
    if len(vb) == 4:
        t = np.eye(3)
        t[:2, 2] = (-vb[0], -vb[1])
        base = base @ t
    areas = []

    def walk(el, m, st):
        name = tag(el)
        if name in ("defs", "clipPath", "mask", "symbol", "title", "desc", "metadata", "style", "pattern", "marker"):
            return
        st = _style(el, st)
        if st.get("display") == "none" or st.get("visibility") == "hidden":
            return
        m = m @ _matrix(el.get("transform"))
        rings = _shape_rings(el, name)
        if rings:
            areas.append(_area(rings, st, m))
        for child in el:
            walk(child, m, st)

    walk(root, base, {})
    shape = unary_union([a for a in areas if not a.is_empty]).buffer(0)
    if shape.is_empty:
        raise ValueError("no filled shape found in the SVG (paths, rectangles, circles, polygons...)")
    shape = affinity.scale(shape, 1, -1, origin=(0, 0))      # SVG y goes down
    x0, y0, x1, y1 = shape.bounds
    return affinity.translate(shape, -(x0 + x1) / 2, -(y0 + y1) / 2), (x1 - x0, y1 - y0)
