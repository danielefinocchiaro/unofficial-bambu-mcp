"""Splitting, merging and boolean operations on objects, like Bambu Studio's Split, Assemble/Merge and Mesh boolean.
Painted colors, seams and supports stay on their triangles: they are kept per triangle, so a piece takes the
triangles it is made of, and a boolean result is followed back to its source triangles (see paint.py)."""
import numpy as np

from . import geometry, paint
from .project import Obj, Part

MAX_PIECES = 100


def offset(o):
    """Plate position of an object's vertices: plate = vertices + offset (the object sits on the bed)."""
    lo, hi = o.bbox()
    c = (lo + hi) / 2
    return np.array([o.at[0] - c[0], o.at[1] - c[1], -lo[2]])


def components(verts, tris):
    """Label (0, 1, ...) of the connected piece each triangle belongs to; vertices at the same place count as one."""
    tris = np.asarray(tris, np.int64)
    if not len(tris):
        return np.zeros(0, np.int64)
    _, vid = np.unique(np.round(np.asarray(verts, float), 5), axis=0, return_inverse=True)
    t = vid.reshape(-1)[tris]
    parent = np.arange(int(t.max()) + 1)
    edges = np.concatenate([t[:, [0, 1]], t[:, [1, 2]]])
    while True:                                       # hook roots to the smaller one, then shortcut the paths
        a, b = parent[edges[:, 0]], parent[edges[:, 1]]
        if (a == b).all():
            break
        low = np.minimum(a, b)
        np.minimum.at(parent, a, low)
        np.minimum.at(parent, b, low)
        while True:
            pp = parent[parent]
            if (pp == parent).all():
                break
            parent = pp
    _, labels = np.unique(parent[t[:, 0]], return_inverse=True)
    return labels.reshape(-1)


def _sub(p, sel, name):
    """The part made of the triangles `sel` of part p (vertices renumbered, painting kept)."""
    tris = np.asarray(p.tris)[sel]
    used, inv = np.unique(tris.reshape(-1), return_inverse=True)
    attrs = {k: [v[i] for i in np.nonzero(sel)[0]] for k, v in p.tri_attrs.items() if v is not None and len(v) == len(p.tris)}
    return Part(name, p.verts[used], inv.reshape(-1, 3), p.filament, p.subtype,
                tri_attrs={k: v for k, v in attrs.items() if any(v)}, meta=dict(p.meta))


def _overlap(a, b):
    lo, hi = np.maximum(a[0], b[0]), np.minimum(a[1], b[1])
    return float(np.prod(np.clip(hi - lo, 0, None)))


def pieces(o):
    """The solid pieces of an object: every connected piece of every solid part, as parts, biggest first."""
    out = []
    for p in o.solid_parts():
        if p.subtype != "normal_part":
            continue
        labels = components(p.verts, p.tris)
        n = int(labels.max()) + 1 if len(labels) else 0
        for k in range(n):
            out.append(_sub(p, labels == k, p.name if n == 1 else f"{p.name} {k + 1}"))
    out.sort(key=lambda q: -float(np.prod(np.ptp(q.verts, axis=0))))
    return out


def split(o, into="objects"):
    """into='objects': [Obj] one per piece, at their places on the plate; into='parts': one Obj whose parts are the
    pieces. Modifiers, negative parts and support painting volumes go with the piece they overlap most; brim ears
    with the nearest piece."""
    ps = pieces(o)
    others = [p for p in o.parts if p.subtype != "normal_part"]
    solids = [p for p in o.parts if p.subtype == "normal_part"]
    if len(ps) <= (len(solids) if into == "parts" else 1):
        raise ValueError(f"'{o.name}' is a single piece" + (" in each part" if len(solids) > 1 else "")
                         + ": there is nothing to split")
    if len(ps) > MAX_PIECES:
        raise ValueError(f"'{o.name}' has {len(ps)} separate pieces (more than {MAX_PIECES}): it looks like a "
                         "mesh with loose fragments; check_object tells more")
    if into == "parts":
        return [Obj(o.name, ps + others, at=o.at, settings=dict(o.settings))], []
    boxes = [(q.verts.min(0), q.verts.max(0)) for q in ps]
    groups = [[q] for q in ps]
    notes = []
    for p in others:
        b = (p.verts.min(0), p.verts.max(0))
        k = int(np.argmax([_overlap(b, bb) for bb in boxes]))
        groups[k].append(p)
    off = offset(o)
    made = []
    for g in groups:
        ob = Obj(o.name, g, settings=dict(o.settings))
        lo, hi = ob.bbox()
        c = (lo + hi) / 2
        ob.at = (float(c[0] + off[0]), float(c[1] + off[1]))
        made.append(ob)
    for x, y, r in o.brim_ears:
        k = int(np.argmin([np.hypot(*(np.clip([x, y], b[0][:2], b[1][:2]) - [x, y])) for b in boxes]))
        made[k].brim_ears.append((x, y, r))
    bottom = o.bbox()[0][2]
    if any(ob.bbox()[0][2] > bottom + 0.05 for ob in made):
        notes.append("pieces that did not touch the bed now stand on it, as in Bambu Studio")
    for ob in made:                                  # height bands count from the bottom: kept where it is the same
        if o.height_ranges and ob.bbox()[0][2] <= bottom + 0.05:
            ob.height_ranges = [dict(r, settings=dict(r["settings"])) for r in o.height_ranges]
    if o.height_ranges and any(not ob.height_ranges for ob in made):
        notes.append("the height ranges were kept only on the pieces standing on the bed")
    return made, notes


def merge(objs, name):
    """One object with the parts of all objs, where they are on the plate; the first object's settings."""
    parts, ears = [], []
    for o in objs:
        off = offset(o)
        for p in o.parts:
            parts.append(Part(p.name, p.verts + off, p.tris, p.filament, p.subtype, tri_attrs=dict(p.tri_attrs),
                              meta=dict(p.meta)))
        ears += [(x + off[0], y + off[1], r) for x, y, r in o.brim_ears]
    ob = Obj(name, parts, settings=dict(objs[0].settings))
    lo, hi = ob.bbox()
    ob.at = (float((lo[0] + hi[0]) / 2), float((lo[1] + hi[1]) / 2))
    ob.brim_ears = ears
    ob.height_ranges = [dict(r, settings=dict(r["settings"])) for r in objs[0].height_ranges]   # all on the bed
    dropped = sorted({k for o in objs[1:] for k, v in o.settings.items() if objs[0].settings.get(k) != v})
    if any(o.height_ranges != objs[0].height_ranges for o in objs[1:]):
        dropped.append("height_ranges")
    return ob, dropped


def _solid(p, what):
    m = geometry.to_manifold(p.verts, p.tris)
    if m.status() != geometry.m3.Error.NoError or m.is_empty():
        raise ValueError(f"{what} '{p.name}' is not a closed solid (see check_object)")
    return m


OPS = ("union", "difference", "intersection")


def boolean(target, tool, operation, part=""):
    """Change target's solid parts with the solid of `tool` (an Obj), where both are on the plate.
    difference / intersection: every solid part of target; union: the part named `part` (default: the biggest).
    Returns (new parts, {part name: (volume before, after)}, volume the two share); painted triangles keep their
    painting."""
    if operation not in OPS:
        raise ValueError(f"operation must be one of {', '.join(OPS)}")
    shift = offset(tool) - offset(target)             # tool vertices -> target's frame
    tool_m = None
    for p in tool.solid_parts():
        if p.subtype != "normal_part":
            continue
        m = geometry.to_manifold(p.verts + shift, p.tris)
        if m.status() != geometry.m3.Error.NoError or m.is_empty():
            raise ValueError(f"part '{p.name}' of '{tool.name}' is not a closed solid (see check_object)")
        tool_m = m if tool_m is None else tool_m + m
    if tool_m is None:
        raise ValueError(f"'{tool.name}' has no solid part")
    solids = [p for p in target.parts if p.subtype == "normal_part"]
    if operation == "union":
        if part:
            chosen = [p for p in solids if p.name.lower() == part.lower()]
            if not chosen:
                raise ValueError(f"'{target.name}' has no solid part named '{part}': {[p.name for p in solids]}")
        else:
            chosen = [max(solids, key=lambda p: _solid(p, "part").volume())]
    else:
        chosen = solids
    new, volumes, shared = [], {}, 0.0
    for p in target.parts:
        if p not in chosen:
            new.append(p)
            continue
        _solid(p, "part")
        m, oid = paint.tracked(p.verts, p.tris)
        before = m.volume()
        shared += (m ^ tool_m).volume()
        r = m + tool_m if operation == "union" else (m - tool_m if operation == "difference" else m ^ tool_m)
        volumes[p.name] = (before, r.volume())
        if r.is_empty():
            continue
        v, t, attrs = paint.carry(r, oid, p.verts, p.tris, p.tri_attrs)
        new.append(Part(p.name, v, t, p.filament, p.subtype, tri_attrs=attrs, meta=dict(p.meta)))
    if not any(q.subtype == "normal_part" for q in new):
        raise ValueError(f"nothing of '{target.name}' would be left: check where the two objects are "
                         "(preview_plate) and the operation")
    return new, volumes, shared
