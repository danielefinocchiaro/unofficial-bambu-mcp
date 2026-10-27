"""Arranging objects on plates by what they really take on the bed, not by their bounding box: the outline seen
from above, the brim and the brim ears, with a gap around. Shapes can nest (a snowflake's arm between two of the
next one's). Bambu Studio arranges convex hulls, so its engine cannot do that.

The bed is a grid of RES mm cells; each object, inflated by half the gap, becomes a mask, and the places where it
does not touch what is already there come from one FFT correlation per object and rotation. Objects go to the
lowest free place (then the leftmost), biggest first; at the end each plate's group is centered. The result is
checked again on the exact outlines."""
import math

import manifold3d as m3
import numpy as np
import shapely
from PIL import Image, ImageDraw
from shapely import affinity
from shapely.geometry import MultiPoint, Point, Polygon, box
from shapely.ops import unary_union

from .geometry import rotate as rotate_verts

RES = 0.5                     # mm per grid cell
SLACK = RES * 0.75            # added to the inflation so a rasterized shape always covers the real one


def _solid(p):
    try:
        man = m3.Manifold(m3.Mesh(vert_properties=np.asarray(p.verts, np.float32),
                                  tri_verts=np.asarray(p.tris, np.uint32)))
    except Exception:  # noqa: BLE001 - any mesh manifold3d cannot take falls back below
        return None
    return man if man.status() == m3.Error.NoError and not man.is_empty() else None


def _from_above(p):
    """A part's outline seen from above (holes kept)."""
    man = _solid(p)
    if man is not None:
        shape = Polygon()
        for ring in man.project().to_polygons():
            if len(ring) >= 3:
                shape = shape.symmetric_difference(Polygon(ring).buffer(0))
        return shape
    xy = np.asarray(p.verts)[np.asarray(p.tris)][:, :, :2]
    if len(xy) <= 300_000:
        return shapely.union_all(shapely.polygons(xy)).buffer(0.01)
    return MultiPoint(np.asarray(p.verts)[:, :2]).convex_hull


def footprint(obj, cfg):
    """What the object takes on the bed, around its footprint center (the point `at` is set to): the parts seen
    from above, its brim when one is set (auto brim is not counted) and its brim ears."""
    lo, hi = obj.bbox()
    cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
    shape = unary_union([_from_above(p) for p in obj.solid_parts()])
    btype = obj.settings.get("brim_type") or cfg.get("brim_type") or "auto_brim"
    if btype in ("outer_only", "outer_and_inner"):
        width = float(obj.settings.get("brim_width") or cfg.get("brim_width") or 5)
        shape = shape.buffer(width + float(obj.settings.get("brim_object_gap") or cfg.get("brim_object_gap") or 0))
    if obj.brim_ears:
        shape = unary_union([shape] + [Point(x, y).buffer(r, 32) for x, y, r in obj.brim_ears])
    return affinity.translate(shape.buffer(0), -cx, -cy)


def _mask(shape, inflate):
    """(mask, x0, y0): the grown shape on the grid; cell (i, j) is y = y0 + i * RES, x = x0 + j * RES."""
    g = shape.buffer(inflate + SLACK, 16)
    x0, y0, x1, y1 = g.bounds
    w, h = max(1, math.ceil((x1 - x0) / RES)), max(1, math.ceil((y1 - y0) / RES))
    img = Image.new("1", (w, h), 0)
    d = ImageDraw.Draw(img)
    for q in getattr(g, "geoms", [g]):
        if isinstance(q, Polygon):
            d.polygon([((x - x0) / RES, (y - y0) / RES) for x, y in q.exterior.coords], fill=1)
            for hole in q.interiors:
                d.polygon([((x - x0) / RES, (y - y0) / RES) for x, y in hole.coords], fill=0)
    return np.asarray(img, dtype=bool), x0, y0


def _free(occ, mask):
    """Boolean map of the offsets (i, j) where mask fits in occ without touching anything, or None."""
    H, W = occ.shape
    h, w = mask.shape
    if h > H or w > W:
        return None
    shape = (H + h - 1, W + w - 1)
    conv = np.fft.irfft2(np.fft.rfft2(occ.astype(np.float32), shape) *
                         np.fft.rfft2(mask[::-1, ::-1].astype(np.float32), shape), shape)
    return conv[h - 1:H, w - 1:W] < 0.5


class Bed:
    """One plate's grid: what is fixed (outside the plate, excluded area, other objects, prime tower) and what this
    arrangement put there."""

    def __init__(self, size, exclude=None, fixed=(), gap=6.0, tower=None):
        self.bw, self.bd = size
        self.H, self.W = math.ceil(self.bd / RES), math.ceil(self.bw / RES)
        self.fixed = np.zeros((self.H, self.W), bool)
        self.gap, self.tower, self.tower_on = gap, tower, False
        if exclude is not None and not exclude.is_empty:
            self._paint(self.fixed, exclude, 0)
        for shape in fixed:
            self._paint(self.fixed, shape, gap / 2)
        self.placed = np.zeros_like(self.fixed)
        self.items, self.filaments = [], set()
        self.group = None             # with one material per plate: the filaments this plate is for

    def _paint(self, grid, shape, inflate):
        m, x0, y0 = _mask(shape, inflate)
        i0, j0 = int(math.floor(y0 / RES)), int(math.floor(x0 / RES))
        self._or(grid, m, i0, j0)

    def _or(self, grid, m, i0, j0):
        h, w = m.shape
        a0, b0 = max(0, i0), max(0, j0)
        a1, b1 = min(self.H, i0 + h), min(self.W, j0 + w)
        if a1 > a0 and b1 > b0:
            grid[a0:a1, b0:b1] |= m[a0 - i0:a1 - i0, b0 - j0:b1 - j0]

    def occupied(self):
        return self.fixed | self.placed

    def try_place(self, shape, filaments):
        """Lowest-then-leftmost place for the shape (around 0, 0) inflated by half the gap: (x, y) of its 0, 0 point
        and the mask's extent, or None. A second material on the plate needs the prime tower's corner free."""
        occ = self.occupied()
        tower = None
        if self.tower is not None and not self.tower_on and len(self.filaments | set(filaments)) > 1:
            tower = np.zeros_like(occ)
            self._paint(tower, self.tower, self.gap / 2)
            if (tower & occ).any():
                return None
            occ = occ | tower
        m, x0, y0 = _mask(shape, self.gap / 2)
        free = _free(occ, m)
        if free is None or not free.any():
            return None
        i, j = np.argwhere(free)[0]
        top = i + m.shape[0]
        return {"i": int(i), "j": int(j), "mask": m, "x0": x0, "y0": y0, "top": int(top), "tower": tower}

    def commit(self, spot, item, filaments):
        self._or(self.placed, spot["mask"], spot["i"], spot["j"])
        if spot["tower"] is not None:
            self.fixed |= spot["tower"]
            self.tower_on = True
        self.filaments |= set(filaments)
        # position of the shape's 0, 0 point: the mask's first cell is at x0, y0 relative to it
        x = spot["j"] * RES - spot["x0"]
        y = spot["i"] * RES - spot["y0"]
        self.items.append((item, x, y))

    def center(self):
        """Move this arrangement's group toward the middle of the plate as far as it stays clear: (dx, dy) mm."""
        if not self.items or not self.placed.any():
            return 0.0, 0.0
        rows, cols = np.nonzero(self.placed)
        di = int(round((self.H - 1 - rows.max() - rows.min()) / 2))
        dj = int(round((self.W - 1 - cols.max() - cols.min()) / 2))
        for k in range(20, -1, -1):
            si, sj = round(di * k / 20), round(dj * k / 20)
            shifted = np.zeros_like(self.placed)
            src = self.placed[max(0, -si):self.H - max(0, si), max(0, -sj):self.W - max(0, sj)]
            shifted[max(0, si):max(0, si) + src.shape[0], max(0, sj):max(0, sj) + src.shape[1]] = src
            if shifted.sum() == self.placed.sum() and not (shifted & self.fixed).any():
                self.placed = shifted
                self.items = [(it, x + sj * RES, y + si * RES) for it, x, y in self.items]
                return sj * RES, si * RES
        return 0.0, 0.0


def angles(rotate, step):
    if not rotate:
        return [0.0]
    step = float(step) if step and step > 0 else 90.0
    return [k * step for k in range(max(1, int(round(360 / step))))]


def pack(items, beds, rotations, new_bed=None, balanced=True, one_material=False):
    """Place items [(key, shape, filaments, base angle)] on beds. Biggest first; each goes to the least filled bed
    where it fits (balanced) or the first one; new_bed() makes another bed when given. Returns
    (placements {key: (bed index, x, y, angle)}, left over keys)."""
    order = sorted(items, key=lambda it: -it[1].area)
    out, left = {}, []
    for key, shape, fils, base in order:
        tried = sorted(range(len(beds)), key=lambda b: beds[b].placed.sum()) if balanced else range(len(beds))
        done = False
        for b in list(tried) + ([None] if new_bed else []):
            fresh = b is None
            if fresh:
                beds.append(new_bed())
                b = len(beds) - 1
            if one_material and beds[b].group not in (None, tuple(fils)):
                continue
            best = None
            for a in rotations:
                ang = base + a
                s = affinity.rotate(shape, ang, origin=(0, 0)) if ang else shape
                spot = beds[b].try_place(s, fils)
                if spot and (best is None or (spot["top"], spot["j"]) < (best[0]["top"], best[0]["j"])):
                    best = (spot, ang)
            if best:
                beds[b].commit(best[0], key, fils)
                if one_material:
                    beds[b].group = tuple(fils)
                out[key] = (b, best[1])
                done = True
                break
            if fresh:                                    # it does not fit even an empty plate
                beds.pop()
        if not done:
            left.append(key)
    return out, left


def align_angle(shape):
    """Rotation (degrees) that puts the shape's longest side along Y."""
    rect = shape.minimum_rotated_rectangle
    xs, ys = rect.exterior.coords.xy
    sides = [((xs[i + 1] - xs[i]), (ys[i + 1] - ys[i])) for i in range(2)]
    dx, dy = max(sides, key=lambda v: math.hypot(*v))
    return 90.0 - math.degrees(math.atan2(dy, dx))


def check(placed, bed_size, gap, exclude=None):
    """Problems with a final arrangement of one plate: [(name, problem)]. placed: [(name, shape on the plate)]."""
    out = []
    plate = box(0, 0, *bed_size)
    for name, s in placed:
        if not plate.contains(s):
            out.append((name, "goes outside the plate"))
        if exclude is not None and not exclude.is_empty and s.intersects(exclude):
            out.append((name, "touches the extrusion calibration area"))
    tree = shapely.STRtree([s for _, s in placed])
    for i, (name, s) in enumerate(placed):
        for j in tree.query(s.buffer(gap)):
            if j > i and s.distance(placed[j][1]) < gap - 0.05:
                out.append((name, f"less than {gap:g} mm from {placed[j][0]}"))
    return out


TOWER_MARGIN = 4.0


def plate_bed(pr, cfg, t, moving, gap, exclude, tower, one_material=False):
    """The grid of plate t (0-based) with its objects that are not in `moving` (ids) as obstacles."""
    bw, bd = pr.info["bed"]
    others = [o for o in (pr.plates[t].objects if t < len(pr.plates) else []) if id(o) not in moving]
    fixed = [affinity.translate(footprint(o, cfg), o.at[0], o.at[1]) for o in others]
    b = Bed((bw, bd), exclude, fixed, gap, tower)
    b.filaments = {f for o in others for f in o.filaments()}
    if len(b.filaments) > 1:                         # already several materials: keep the tower's corner
        b._paint(b.fixed, tower, gap / 2)
        b.tower_on = True
    if one_material and others:
        b.group = tuple(sorted(b.filaments))
    return b


def _areas(pr, avoid_calibration_area, tower_box):
    bw, bd = pr.info["bed"]
    exclude = Polygon(pr.info["exclude"]) if avoid_calibration_area and pr.info["exclude"] else None
    tower = box(bw - TOWER_MARGIN - tower_box, bd - TOWER_MARGIN - tower_box, bw - TOWER_MARGIN, bd - TOWER_MARGIN)
    return exclude, tower


def fill(pr, cfg, obj, plate, count=0, gap=6.0, rotate=False, rotation_step=90.0, keep_place=False,
         avoid_calibration_area=True, tower_box=60.0):
    """Places for copies of obj on plate (0-based), as many as fit or at most `count`, with Bambu Studio's
    Fill bed with copies in mind. The original is placed again with them (lowest free place first, then the group
    is centered) unless keep_place. Returns (original's (x, y, angle) or None, [(x, y, angle)] for the copies)."""
    exclude, tower = _areas(pr, avoid_calibration_area, tower_box)
    bed = plate_bed(pr, cfg, plate, set() if keep_place else {id(obj)}, gap, exclude, tower)
    shape, fils = footprint(obj, cfg), tuple(sorted(obj.filaments()))
    want = (count if count > 0 else 10_000) + (0 if keep_place else 1)
    rotations = angles(rotate, rotation_step)
    placed = []
    while len(placed) < want:
        best = None
        for a in rotations:
            s = affinity.rotate(shape, a, origin=(0, 0)) if a else shape
            spot = bed.try_place(s, fils)
            if spot and (best is None or (spot["top"], spot["j"]) < (best[0]["top"], best[0]["j"])):
                best = (spot, a)
        if best is None:
            break
        bed.commit(best[0], len(placed), fils)
        placed.append(best[1])
    if not keep_place and not placed:
        raise ValueError(f"'{obj.name}' does not fit on its plate with a {gap:g} mm gap")
    bed.center()
    spots = [(x, y, placed[k]) for k, x, y in bed.items]
    return (None, spots) if keep_place else (spots[0], spots[1:])


def run(pr, cfg, plate=0, objects=None, plates=0, gap=6.0, rotate=False, rotation_step=90.0,
        multi_material=True, avoid_calibration_area=True, align_to_y=False, tower_box=60.0):
    """Arrange a project's objects (all, one plate's, or the named ones) and apply it only if everything fits.
    plates: 0 = each object stays on its plate; N = spread them over plates 1..N, balanced; -1 = as few plates
    as possible. Returns the summary."""
    from .project import Plate
    if objects:
        chosen = [pr.find(r) for r in objects]
    elif plate:
        if not 1 <= plate <= len(pr.plates):
            raise ValueError(f"plate must be 1..{len(pr.plates)}")
        chosen = [(plate - 1, o) for o in pr.plates[plate - 1].objects]
    else:
        chosen = list(pr.objects())
    seen, items = set(), []
    for pi, o in chosen:
        if id(o) not in seen:
            seen.add(id(o))
            items.append((pi, o))
    if not items:
        raise ValueError("no objects to arrange")
    if plates < -1:
        raise ValueError("plates: 0 = keep each object on its plate, N = use N plates, -1 = as few as possible")
    bw, bd = pr.info["bed"]
    exclude, tower = _areas(pr, avoid_calibration_area, tower_box)
    moving = {id(o) for _, o in items}
    shapes = {id(o): footprint(o, cfg) for _, o in items}

    def bed_for(t):
        """The grid of plate t (0-based), with the objects that are not being arranged as obstacles."""
        return plate_bed(pr, cfg, t, moving, gap, exclude, tower, one_material=not multi_material)

    rotations = angles(rotate, rotation_step)
    packed = []
    for _, o in items:
        base = align_angle(shapes[id(o)]) if align_to_y else 0.0
        packed.append((id(o), shapes[id(o)], tuple(sorted(o.filaments())), base))
    by_id = {id(o): (pi, o) for pi, o in items}

    def attempt(targets, grow, balanced):
        beds = [bed_for(t) for t in targets]
        nxt = [max(targets) + 1 if targets else len(pr.plates)]

        def new_bed():
            t = nxt[0]
            nxt[0] += 1
            targets.append(t)
            return bed_for(t)

        if plates == 0:                              # each object on its own plate
            out, left = {}, []
            for k, t in enumerate(targets):
                mine = [it for it in packed if by_id[it[0]][0] == t]
                o2, l2 = pack(mine, [beds[k]], rotations, balanced=False, one_material=not multi_material)
                out.update({key: (k, ang) for key, (_, ang) in o2.items()})
                left += l2
            return beds, targets, out, left
        out, left = pack(packed, beds, rotations, new_bed if grow else None, balanced, not multi_material)
        return beds, targets, out, left

    if plates == 0:
        targets = sorted({pi for pi, _ in items})
        beds, targets, out, left = attempt(targets, False, False)
    elif plates > 0:
        beds, targets, out, left = attempt(list(range(plates)), False, True)
        if left:
            beds2, targets2, out2, left2 = attempt(list(range(plates)), False, False)
            if len(left2) < len(left):
                beds, targets, out, left = beds2, targets2, out2, left2
    else:
        start = sorted({pi for pi, _ in items})[:1] or [0]
        beds, targets, out, left = attempt(start, True, False)
        if not left:                                 # as few plates as possible, then even them out
            beds2, targets2, out2, left2 = attempt(list(targets), False, True)
            if not left2:
                beds, targets, out, left = beds2, targets2, out2, left2
    settings = {"gap_mm": gap, "rotate": rotate, "multi_material": multi_material,
                "avoid_calibration_area": bool(exclude is not None), "align_to_y": align_to_y}
    if rotate:
        settings["rotation_step"] = rotation_step
    if left:
        needed = None
        if plates != 0:
            _, t3, _, l3 = attempt(sorted({pi for pi, _ in items})[:1] or [0], True, False)
            needed = None if l3 else len(t3)
        res = {"applied": False, "settings": settings,
               "does_not_fit": [by_id[k][1].name for k in left],
               "why": f"{len(left)} of {len(items)} objects do not fit" +
                      (f" in {plates} plate(s)" if plates > 0 else " on their plates"),
               "next": "nothing was moved: allow rotation, use a smaller gap, more plates, or plates=-1"}
        if needed:
            res["plates_needed"] = needed
        return res
    for b in beds:
        b.center()
    while len(pr.plates) <= max(targets):
        pr.plates.append(Plate(f"Plate {len(pr.plates) + 1}"))
    rotated = {}
    for k, b in enumerate(beds):
        dest = pr.plates[targets[k]]
        for key, x, y in b.items:
            pi, o = by_id[key]
            ang = out[key][1]
            if ang:
                lo, hi = o.bbox()
                c0 = (lo + hi) / 2
                o.transform(lambda v, a=ang: rotate_verts(v, a))
                lo, hi = o.bbox()
                c1 = (lo + hi) / 2
                x, y = x + c1[0] - c0[0], y + c1[1] - c0[1]
                a = (ang + 180) % 360 - 180
                if abs(a) > 0.01:
                    rotated[o.name] = round(a, 1)
            if o in pr.plates[pi].objects:
                pr.plates[pi].objects.remove(o)
            o.at = (float(x), float(y))
            dest.objects.append(o)
    removed = []
    if plates != 0:                                  # plates left empty after the last one used
        keep = plates if plates > 0 else max(targets) + 1
        while len(pr.plates) > keep and not pr.plates[-1].objects:
            pr.plates.pop()
            removed.append(len(pr.plates) + 1)
    summary, warnings = [], []
    for t in sorted(set(targets)):
        pl = pr.plates[t]
        summary.append({"plate": t + 1, "objects": len(pl.objects), "names": [o.name for o in pl.objects]})
        placed = [(o.name, affinity.translate(footprint(o, cfg), o.at[0], o.at[1])) for o in pl.objects]
        warnings += [f"plate {t + 1}: {n} {w}" for n, w in check(placed, (bw, bd), gap, exclude)]
    res = {"applied": True, "settings": settings, "plates": summary}
    if rotated:
        res["rotated_deg"] = rotated
    if removed:
        res["removed_empty_plates"] = removed
    if warnings:
        res["warnings"] = warnings
    return res

