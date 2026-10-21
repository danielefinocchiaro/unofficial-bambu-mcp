"""Quick images so the assistant (and you) can see the plate: flat-shaded meshes, and sliced layers."""
import io
import math

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BG = (36, 38, 42)
BED = (70, 74, 80)
BED_LINE = (88, 93, 100)
EXCL = (95, 60, 60)


def _hex(c):
    h = c.lstrip("#")[:6].ljust(6, "0")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], float)


def _view(points, view):
    """World mm -> 2D (u, v, depth). Larger depth = closer to the viewer."""
    p = np.asarray(points, float)
    if view == "top":
        return np.column_stack([p[:, 0], p[:, 1], p[:, 2]])
    az, el = math.radians(-35), math.radians(55)       # iso-like: from front-left, looking down
    x, y, z = p[:, 0], p[:, 1], p[:, 2]
    xr = x * math.cos(az) - y * math.sin(az)
    yr = x * math.sin(az) + y * math.cos(az)
    u = xr
    v = yr * math.cos(el) + z * math.sin(el)
    d = -yr * math.sin(el) + z * math.cos(el)
    return np.column_stack([u, v, d])


def _rasterize(px, z, rgb, W, H, budget=2_000_000):
    """Z-buffer: for each pixel the color of the nearest triangle (larger z = nearer). Sorting triangles by
    their center (painter's algorithm) fails where big faces lie under small ones: text on a tag, parts.
    px: (n, 3, 2) pixel coordinates, z: (n, 3) depths, rgb: (n, 3). Returns (covered mask, colors), flat."""
    zbuf = np.full(W * H, -np.inf)
    cbuf = np.zeros((W * H, 3), np.uint8)
    (x0, y0), (x1, y1), (x2, y2) = px[:, 0].T, px[:, 1].T, px[:, 2].T
    a2 = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0)
    ok = np.abs(a2) > 1e-9
    lo = np.clip(np.floor(px.min(1)), 0, [W - 1, H - 1]).astype(np.int64)
    hi = np.clip(np.ceil(px.max(1)), 0, [W - 1, H - 1]).astype(np.int64)
    ok &= (px[:, :, 0].max(1) >= 0) & (px[:, :, 0].min(1) < W) & (px[:, :, 1].max(1) >= 0) & (px[:, :, 1].min(1) < H)
    a2 = np.where(ok, a2, 1.0)
    # barycentric weights as planes in pixel space: w0 = A0 x + B0 y + C0, w1 likewise, w2 = 1 - w0 - w1
    A0, B0, C0 = (y1 - y2) / a2, (x2 - x1) / a2, (x1 * y2 - x2 * y1) / a2
    A1, B1, C1 = (y2 - y0) / a2, (x0 - x2) / a2, (x2 * y0 - x0 * y2) / a2
    dz0, dz1 = z[:, 0] - z[:, 2], z[:, 1] - z[:, 2]
    Dz, Ez, Fz = A0 * dz0 + A1 * dz1, B0 * dz0 + B1 * dz1, z[:, 2] + C0 * dz0 + C1 * dz1
    tris = np.nonzero(ok)[0]
    w = hi[tris, 0] - lo[tris, 0] + 1
    n = w * (hi[tris, 1] - lo[tris, 1] + 1)
    ends = np.cumsum(n)
    i = 0
    while i < len(tris):
        j = max(i + 1, int(np.searchsorted(ends, (ends[i - 1] if i else 0) + budget, "right")))
        cnt = n[i:j]
        t = np.repeat(tris[i:j], cnt)
        off = np.arange(cnt.sum()) - np.repeat(np.cumsum(cnt) - cnt, cnt)
        ww = np.repeat(w[i:j], cnt)
        xs = lo[t, 0] + off % ww
        ys = lo[t, 1] + off // ww
        cx, cy = xs + 0.5, ys + 0.5
        b0 = A0[t] * cx + B0[t] * cy + C0[t]
        b1 = A1[t] * cx + B1[t] * cy + C1[t]
        inside = (b0 >= -1e-6) & (b1 >= -1e-6) & (b0 + b1 <= 1 + 1e-6)
        pix = (ys * W + xs)[inside]
        d = (Dz[t] * cx + Ez[t] * cy + Fz[t])[inside]
        t = t[inside]
        order = np.lexsort((d, pix))                    # by pixel, then depth: the last of each pixel is nearest
        pix, d, t = pix[order], d[order], t[order]
        last = np.r_[pix[1:] != pix[:-1], True]
        pix, d, t = pix[last], d[last], t[last]
        near = d > zbuf[pix]
        zbuf[pix[near]] = d[near]
        cbuf[pix[near]] = rgb[t[near]]
        i = j
    return np.isfinite(zbuf), cbuf


def render_plate(project, plate_index, view="iso", size=900, label=True, zoom=False):
    """PNG bytes of one plate (0-based index) with its objects in their filament colors.
    zoom: frame the objects instead of the whole bed."""
    pl = project.plates[plate_index]
    bw, bd = project.info["bed"]
    colors = [_hex(c) for _, c in project.filaments]
    faces, cols = [], []
    max_h = 1.0
    for ob in pl.objects:
        lo, hi = ob.bbox()
        c = (lo + hi) / 2
        off = np.array([ob.at[0] - c[0], ob.at[1] - c[1], -lo[2]])
        max_h = max(max_h, hi[2] - lo[2])
        for p in ob.parts:
            if p.subtype != "normal_part":
                continue
            v = p.verts + off
            tri = v[p.tris]
            base = colors[(p.filament - 1) % len(colors)] if colors else np.array([200, 200, 200.0])
            paint = p.tri_attrs.get("paint_color")
            if paint:
                tc = np.tile(base, (len(tri), 1))
                for i, s in enumerate(paint):
                    if s:
                        k = _paint_slot(s)
                        if k:
                            tc[i] = colors[(k - 1) % len(colors)]
                faces.append(tri)
                cols.append(tc)
            else:
                faces.append(tri)
                cols.append(np.tile(base, (len(tri), 1)))
    S = 2                                   # supersampling
    W = H = size * S
    corners = np.array([[0, 0, 0], [bw, 0, 0], [bw, bd, 0], [0, bd, 0], [0, 0, max_h], [bw, bd, max_h],
                        [bw, 0, max_h], [0, bd, max_h]], float)
    cv = _view(corners, view)
    allpts = cv
    if faces:
        F = np.concatenate(faces)
        C = np.concatenate(cols)
        objpts = _view(F.reshape(-1, 3), view)
        allpts = objpts if zoom else np.concatenate([cv, objpts])
    umin, umax = allpts[:, 0].min(), allpts[:, 0].max()
    vmin, vmax = allpts[:, 1].min(), allpts[:, 1].max()
    margin = 0.12 if zoom and faces else 0.06
    sc = min(W * (1 - 2 * margin) / (umax - umin), H * (1 - 2 * margin) / (vmax - vmin))
    ox = W / 2 - sc * (umin + umax) / 2
    oy = H / 2 + sc * (vmin + vmax) / 2

    def to_px(uv):
        return np.column_stack([ox + sc * uv[:, 0], oy - sc * uv[:, 1]])

    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)
    bed = to_px(_view(corners[:4], view))
    dr.polygon([tuple(p) for p in bed], fill=BED)
    for g in range(10, int(max(bw, bd)), 10):          # 10 mm grid, 50 mm lines brighter
        w_ = 1 if g % 50 else 2
        for a, b in (([g, 0, 0], [g, bd, 0]), ([0, g, 0], [bw, g, 0])):
            if a[0] <= bw and a[1] <= bd and b[0] <= bw and b[1] <= bd:
                seg = to_px(_view(np.array([a, b], float), view))
                dr.line([tuple(seg[0]), tuple(seg[1])], fill=BED_LINE, width=w_ * S)
    ex = project.info["exclude"]
    if ex:
        poly = to_px(_view(np.array([[x, y, 0] for x, y in ex], float), view))
        dr.polygon([tuple(p) for p in poly], fill=EXCL)
    if faces:
        n = np.cross(F[:, 1] - F[:, 0], F[:, 2] - F[:, 0])
        nl = np.linalg.norm(n, axis=1)
        ok = nl > 1e-12
        F, C, n = F[ok], C[ok], n[ok] / nl[ok, None]
        light = np.array([-0.35, -0.5, 0.8])
        light /= np.linalg.norm(light)
        shade = 0.35 + 0.65 * np.clip(n @ light, 0, 1)
        if view == "top":
            front = n[:, 2] > -1e-6
        else:
            az, el = math.radians(-35), math.radians(55)
            # gradient of the depth used in _view: points toward the viewer
            viewdir = np.array([-math.sin(az) * math.sin(el), -math.cos(az) * math.sin(el), math.cos(el)])
            front = n @ viewdir > -1e-6
        F, C, shade = F[front], C[front], shade[front]
        P = _view(F.reshape(-1, 3), view).reshape(-1, 3, 3)
        px = to_px(P.reshape(-1, 3)[:, :2]).reshape(-1, 3, 2)
        base = np.maximum(C, 58.0)                     # very dark filaments: keep the shading readable
        rgb = np.clip(base * shade[:, None], 0, 255).astype(np.uint8)
        covered, colors = _rasterize(px, P[:, :, 2], rgb, W, H)
        arr = np.asarray(img).reshape(-1, 3).copy()
        arr[covered] = colors[covered]
        img = Image.fromarray(arr.reshape(H, W, 3))
    img = img.resize((size, size), Image.LANCZOS)
    if label:
        d2 = ImageDraw.Draw(img)
        txt = f"Plate {plate_index + 1}: {pl.name}  |  {project.machine}  |  {len(pl.objects)} objects"
        d2.text((12, 10), txt, fill=(230, 230, 230), font=_font(15))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _paint_slot(s):
    """Filament (1-based) of a painted triangle from Bambu's paint_color string, read from the last nibble:
    2 low bits = split, 2 high bits = state; state 3 means 'read the next nibble + 3'.
    '4' -> 1, '8' -> 2, '0C' -> 3, '1C' -> 4. Subdivided triangles return None (drawn in the part color)."""
    try:
        n0 = int(s[-1], 16)
    except (ValueError, IndexError):
        return None
    if n0 & 3:
        return None
    state = n0 >> 2
    if state == 3:
        try:
            state = int(s[-2], 16) + 3
        except (ValueError, IndexError):
            return None
    return state or None


def render_layer(segs, bed, colors, title="", size=900, exclude=None, zoom=False):
    """PNG bytes: one sliced layer seen from the top, extrusions colored by filament.
    zoom: frame the extrusions instead of the whole bed."""
    bw, bd = bed
    S = 2
    W = H = size * S
    m = 0.05
    x0, y0, x1, y1 = 0.0, 0.0, bw, bd
    if zoom and segs:
        a = np.array([s[:4] for s in segs], float)
        x0, x1 = min(a[:, 0].min(), a[:, 2].min()) - 3, max(a[:, 0].max(), a[:, 2].max()) + 3
        y0, y1 = min(a[:, 1].min(), a[:, 3].min()) - 3, max(a[:, 1].max(), a[:, 3].max()) + 3
    sc = min(W * (1 - 2 * m) / (x1 - x0), H * (1 - 2 * m) / (y1 - y0))
    ox, oy = W / 2 - sc * (x0 + x1) / 2, H / 2 + sc * (y0 + y1) / 2
    img = Image.new("RGB", (W, H), BG)
    dr = ImageDraw.Draw(img)
    dr.rectangle([ox, oy - sc * bd, ox + sc * bw, oy], fill=BED)
    if exclude:
        dr.polygon([(ox + sc * x, oy - sc * y) for x, y in exclude], fill=EXCL)
    cols = [tuple(int(x) for x in _hex(c)) for c in colors] or [(220, 220, 220)]
    w = max(1, int(round(0.42 * sc)))
    for x0, y0, x1, y1, tool, _feat in segs:
        dr.line([(ox + sc * x0, oy - sc * y0), (ox + sc * x1, oy - sc * y1)], fill=cols[tool % len(cols)], width=w)
    img = img.resize((size, size), Image.LANCZOS)
    if title:
        ImageDraw.Draw(img).text((12, 10), title, fill=(230, 230, 230), font=_font(15))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _font(px):
    for p in ("/System/Library/Fonts/Supplemental/Arial.ttf", r"C:\Windows\Fonts\arial.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(p, px)
        except OSError:
            continue
    return ImageFont.load_default()
