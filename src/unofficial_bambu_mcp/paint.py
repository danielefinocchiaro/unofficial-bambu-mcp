"""Painting (colors, supports, seams) carried through booleans. Bambu Studio keeps it per triangle as a string:
nibbles read from the end, each node 2 bits "split sides" + 2 bits state or special side (TriangleSelector's
format); a split triangle has 2, 3 or 4 children. manifold3d remembers, for every output triangle, the input
triangle it comes from (face_id): a triangle that came out whole keeps its string exactly, a piece of a triangle
gets the state covering most of it, and new faces (the cut, holes, pegs) get none (the part's filament)."""
import manifold3d as m3
import numpy as np

# area of each child, for 1, 2 and 3 split sides (sides split at their middle)
_CHILDREN = {1: (0.5, 0.5), 2: (0.25, 0.375, 0.375), 3: (0.25, 0.25, 0.25, 0.25)}


def areas(s):
    """{state: share of the triangle's area} of a painting string."""
    nib = [int(c, 16) for c in reversed(s)]
    out, pos = {}, 0

    def node(weight):
        nonlocal pos
        code = nib[pos]
        pos += 1
        split = code & 3
        if split:
            for w in _CHILDREN[split]:
                node(weight * w)
            return
        if code & 0b1100 == 0b1100:                 # state 3 and above: more nibbles follow
            nxt, num = nib[pos], 0
            pos += 1
            while nxt == 15:
                num += 1
                nxt = nib[pos]
                pos += 1
            state = nxt + 15 * num + 3
        else:
            state = code >> 2
        out[state] = out.get(state, 0.0) + weight

    try:
        node(1.0)
    except (IndexError, KeyError):
        return {}
    return out


def leaf(state):
    """The string of a whole triangle in one state ("" = not painted)."""
    if state <= 0:
        return ""
    if state < 3:
        return format(state << 2, "X")
    v = state - 3
    nibbles = [0b1100] + [15] * (v // 15) + [v % 15]
    return "".join(format(n, "X") for n in reversed(nibbles))


def dominant(s):
    a = areas(s) if s else {}
    return leaf(max(a, key=a.get)) if a else ""


def tracked(verts, tris):
    """(Manifold, id): a solid whose triangles remember their index, under an id of their own."""
    oid = m3.Manifold.reserve_ids(1)
    mesh = m3.Mesh(vert_properties=np.asarray(verts, np.float32), tri_verts=np.asarray(tris, np.uint32),
                   run_index=np.array([0, 3 * len(tris)], np.uint32), run_original_id=np.array([oid], np.uint32),
                   face_id=np.arange(len(tris), dtype=np.uint32))
    return m3.Manifold(mesh), oid


def carry(m, oid, src_verts, src_tris, attrs):
    """(verts, tris, attrs) of the solid m, with the painting of the source triangles it comes from."""
    me = m.to_mesh()
    verts = np.asarray(me.vert_properties)[:, :3].astype(np.float64)
    tris = np.asarray(me.tri_verts).astype(np.int64)
    n = len(tris)
    face = np.full(n, -1, np.int64)
    ri = np.asarray(me.run_index).astype(np.int64)
    fid = np.asarray(me.face_id).astype(np.int64)
    for r, o in enumerate(me.run_original_id):
        if o == oid:
            a, b = ri[r] // 3, ri[r + 1] // 3
            face[a:b] = fid[a:b]
    if not attrs:
        return verts, tris, {}
    mine = np.nonzero(face >= 0)[0]
    src = np.asarray(src_verts, float)[np.asarray(src_tris)[face[mine]]]       # (k, 3, 3) original corners
    out = verts[tris[mine]]

    def edges(t):
        return np.linalg.norm(t - np.roll(t, -1, axis=1), axis=2)              # |v1-v0|, |v2-v1|, |v0-v2|

    e_src = edges(src)
    best, shift = np.full(len(mine), np.inf), np.zeros(len(mine), np.int64)
    for k in range(3):
        d = np.abs(edges(np.roll(out, -k, axis=1)) - e_src).sum(1)
        better = d < best
        best[better], shift[better] = d[better], k
    whole = best <= 1e-4 * (1 + e_src.sum(1))
    rows = mine[whole]                                   # same triangle: same corner order as the source
    for k in (1, 2):
        sel = rows[shift[whole] == k]
        tris[sel] = np.roll(tris[sel], -k, axis=1)
    new = {}
    for key, vals in attrs.items():
        if vals is None or len(vals) != len(src_tris):
            continue
        col = [""] * n
        cache = {}
        for i, w in zip(mine, whole, strict=True):
            s = vals[face[i]]
            if s:
                if w:
                    col[i] = s
                else:
                    col[i] = cache.setdefault(s, dominant(s))
        if any(col):
            new[key] = col
    return verts, tris, new
