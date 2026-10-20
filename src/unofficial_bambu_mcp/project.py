"""In-memory Bambu Studio project: printer, process, filaments (AMS slots), plates, objects, parts.

Objects keep their mesh in their own coordinates; `at` is where the center of their footprint sits on
the plate (mm from the plate origin). When written, every object is dropped onto the bed.
"""
import json
import math
import os
from importlib import resources

import numpy as np

from . import geometry, presets

TOWER_BOX = 60.0      # free square kept for the prime tower when more than one filament is used (mm)
GAP = 6.0             # default gap between objects (mm)


class Part:
    """A mesh with its filament. subtype: normal_part | modifier_part | negative_part | support_enforcer |
    support_blocker. tri_attrs keeps per-triangle painting (paint_color, paint_supports, paint_seam)."""

    def __init__(self, name, verts, tris, filament=1, subtype="normal_part", tri_attrs=None, meta=None):
        self.name = name
        self.verts = np.asarray(verts, float)
        self.tris = np.asarray(tris, np.int64)
        self.filament = int(filament)
        self.subtype = subtype
        self.tri_attrs = tri_attrs or {}
        self.meta = meta or {}


class Obj:
    def __init__(self, name, parts, at=(0.0, 0.0), settings=None):
        self.name, self.parts, self.at, self.settings = name, parts, tuple(at), settings or {}

    def solid_parts(self):
        return [p for p in self.parts if p.subtype == "normal_part"] or self.parts

    def bbox(self):
        """(min, max) of the solid parts, in object coordinates."""
        allv = np.concatenate([p.verts for p in self.solid_parts()])
        return allv.min(0), allv.max(0)

    def size(self):
        lo, hi = self.bbox()
        return hi - lo

    def footprint(self):
        """(x0, y0, x1, y1) on the plate."""
        w, d, _ = self.size()
        return (self.at[0] - w / 2, self.at[1] - d / 2, self.at[0] + w / 2, self.at[1] + d / 2)

    def transform(self, fn):
        """Apply fn(verts) -> verts to all parts, keeping the footprint centered on `at`."""
        lo, hi = self.bbox()
        c = (lo + hi) / 2
        for p in self.parts:
            p.verts = fn(p.verts - c) + c

    def filaments(self):
        return sorted({p.filament for p in self.parts})


# custom G-code at a height (Bambu Studio CustomGCode::Type)
GCODE_TYPES = {"color_change": 0, "pause": 1, "tool_change": 2, "template": 3, "custom": 4}


class LayerGcode:
    """Something to do when the print reaches `z` (mm): pause, filament change or custom G-code."""

    def __init__(self, z, kind="custom", gcode="", filament=1, color="", message=""):
        if kind not in GCODE_TYPES:
            raise ValueError(f"kind must be one of {sorted(GCODE_TYPES)}")
        self.z, self.kind, self.gcode, self.filament, self.color, self.message = float(z), kind, gcode, int(filament), color, message

    def as_dict(self):
        d = {"z": round(self.z, 3), "kind": self.kind}
        if self.kind == "custom":
            d["gcode"] = self.gcode
        if self.kind in ("color_change", "tool_change"):
            d["filament"] = self.filament
        if self.message:
            d["message"] = self.message
        return d


class Plate:
    def __init__(self, name, objects=None, settings=None):
        self.name, self.objects, self.settings = name, objects or [], settings or {}
        self.layer_gcodes = []          # [LayerGcode], kept sorted by z


class Project:
    def __init__(self, name="Untitled", printer="P1S", process=None, filaments=None):
        self.name = name
        self.machine = presets.machine_name(printer)
        info = presets.machine_info(self.machine)
        self.process = process or info["default_process"]
        if not presets.exists("process", self.process):
            raise presets.PresetError(f"unknown process preset '{self.process}'")
        default_fil = info["default_filament"] or "Bambu PLA Basic @BBL X1C"
        self.filaments = [(presets.filament_for(n, self.machine), c) for n, c in (filaments or [(default_fil, "#FFFFFF")])]
        self.overrides = {}
        self.plates = [Plate("Plate 1")]
        self.extras = {}          # files carried over from an opened 3MF (e.g. custom G-code per layer)
        self.warnings = []
        self.source_path = None

    # ------------------------------------------------------------ printer
    @property
    def info(self):
        return presets.machine_info(self.machine)

    def set_printer(self, printer, process=None):
        """Switch printer; filament presets are swapped for the same filament on the new printer."""
        old = self.machine
        self.machine = presets.machine_name(printer)
        self.process = process or self.info["default_process"]
        self.filaments = [(presets.filament_for(n, self.machine), c) for n, c in self.filaments]
        self.overrides = {k: v for k, v in self.overrides.items() if not k.startswith("wipe_tower")}
        return old

    # ------------------------------------------------------------ lookup
    def objects(self):
        """[(plate_index, object)] in order (plate_index is 0-based)."""
        return [(i, o) for i, pl in enumerate(self.plates) for o in pl.objects]

    def find(self, ref):
        """Object by name (case-insensitive), by 1-based global id, or 'plate:index'."""
        items = self.objects()
        if isinstance(ref, int) or (isinstance(ref, str) and ref.strip().isdigit()):
            k = int(ref) - 1
            if 0 <= k < len(items):
                return items[k]
        if isinstance(ref, str):
            if ":" in ref and all(x.strip().isdigit() for x in ref.split(":", 1)):
                p, k = (int(x) for x in ref.split(":", 1))
                if 1 <= p <= len(self.plates) and 1 <= k <= len(self.plates[p - 1].objects):
                    return p - 1, self.plates[p - 1].objects[k - 1]
            low = ref.strip().lower()
            for pi, o in items:
                if o.name.lower() == low:
                    return pi, o
            hits = [(pi, o) for pi, o in items if low in o.name.lower()]
            if len(hits) == 1:
                return hits[0]
            if len(hits) > 1:
                raise KeyError(f"'{ref}' matches {len(hits)} objects: {[o.name for _, o in hits][:8]}")
        raise KeyError(f"no object '{ref}'")

    def plate(self, number):
        if not 1 <= int(number) <= len(self.plates):
            raise KeyError(f"plate {number} does not exist (1..{len(self.plates)})")
        return self.plates[int(number) - 1]

    def unique_name(self, name):
        names = {o.name for _, o in self.objects()}
        if name not in names:
            return name
        k = 2
        while f"{name} {k}" in names:
            k += 1
        return f"{name} {k}"

    # ------------------------------------------------------------ placement
    def blocked(self, plate, skip=None):
        """Rectangles that a new object must avoid on this plate."""
        rects = [o.footprint() for o in plate.objects if o is not skip]
        ex = self.info["exclude"]
        if ex:
            xs, ys = [p[0] for p in ex], [p[1] for p in ex]
            rects.append((min(xs), min(ys), max(xs), max(ys)))
        return rects

    def find_spot(self, plate, w, d, gap=GAP, skip=None):
        """Free position for a w×d footprint, as close to the bed center as possible."""
        bw, bd = self.info["bed"]
        if w > bw - 2 or d > bd - 2:
            return None
        rects = self.blocked(plate, skip)
        step = 2.0
        cands = []
        for x in np.arange(w / 2 + 1, bw - w / 2 - 1 + 1e-6, step):
            for y in np.arange(d / 2 + 1, bd - d / 2 - 1 + 1e-6, step):
                cands.append((math.hypot(x - bw / 2, y - bd / 2), x, y))
        cands.sort()
        for _, x, y in cands:
            r = (x - w / 2, y - d / 2, x + w / 2, y + d / 2)
            if all(r[2] + gap <= b[0] or r[0] >= b[2] + gap or r[3] + gap <= b[1] or r[1] >= b[3] + gap for b in rects):
                return float(x), float(y)
        return None

    def out_of_bed(self, obj):
        bw, bd = self.info["bed"]
        x0, y0, x1, y1 = obj.footprint()
        return x0 < 0 or y0 < 0 or x1 > bw or y1 > bd or obj.size()[2] > self.info["max_height"]

    def arrange(self, plate_numbers=None, gap=GAP):
        """Re-place objects of the given plates (default all), biggest first, near the center.
        Objects that no longer fit go to a new plate."""
        targets = [self.plates[n - 1] for n in (plate_numbers or range(1, len(self.plates) + 1))]
        moved = []
        for pl in targets:
            objs = sorted(pl.objects, key=lambda o: -float(np.prod(o.size()[:2])))
            pl.objects = []
            for o in objs:
                w, d, _ = o.size()
                spot = self.find_spot(pl, w, d, gap)
                if spot is None:
                    for deg in (90,):
                        o.transform(lambda v, a=deg: geometry.rotate(v, a))
                        w, d, _ = o.size()
                        spot = self.find_spot(pl, w, d, gap)
                        if spot:
                            break
                if spot is None:
                    moved.append(o)
                    continue
                o.at = spot
                pl.objects.append(o)
        if moved:
            extra = Plate(f"Plate {len(self.plates) + 1}")
            self.plates.append(extra)
            for o in moved:
                w, d, _ = o.size()
                spot = self.find_spot(extra, w, d, gap)
                if spot is None:
                    raise ValueError(f"'{o.name}' ({w:.0f}×{d:.0f} mm) does not fit the bed")
                o.at = spot
                extra.objects.append(o)
        return moved

    def tower_spot(self, plate):
        """Free corner for the prime tower (x, y of its lower-left corner), or None."""
        bw, bd = self.info["bed"]
        m = 4.0
        rects = self.blocked(plate)
        for x, y in ((bw - m - TOWER_BOX, bd - m - TOWER_BOX), (m + 20, bd - m - TOWER_BOX),
                     (bw - m - TOWER_BOX, m + 30), (bw / 2 - TOWER_BOX / 2, bd - m - TOWER_BOX)):
            r = (x, y, x + TOWER_BOX, y + TOWER_BOX)
            if all(r[2] <= b[0] or r[0] >= b[2] or r[3] <= b[1] or r[1] >= b[3] for b in rects):
                return x + 2, y + 2
        return None

    # ------------------------------------------------------------ settings
    def preset_settings(self):
        """(machine, process, [filament...]) flattened settings."""
        return (presets.settings("machine", self.machine), presets.settings("process", self.process),
                [presets.settings("filament", n) for n, _ in self.filaments])

    def key_kind(self, key):
        m, p, fl = self.preset_settings()
        if any(key in f for f in fl):
            return "filament"
        if key in p:
            return "process"
        if key in m:
            return "machine"
        return None

    def config(self):
        """Full project_settings.config: template + machine + process + per-slot filament values + overrides."""
        with resources.files("unofficial_bambu_mcp").joinpath("data/bambu_template.config").open(encoding="utf-8") as f:
            cfg = json.load(f)
        m, p, fl = self.preset_settings()
        fkeys = set().union(*[set(f) for f in fl]) if fl else set()
        for k, v in {**m, **p}.items():
            if k not in fkeys:
                cfg[k] = v
        for k in fkeys:
            vals = []
            for f in fl:
                v = f.get(k, cfg.get(k, [""]))
                vals.append(v[0] if isinstance(v, list) and v else v)
            cfg[k] = vals
        n = len(self.filaments)
        cols = [c for _, c in self.filaments]
        cfg.update({
            "printer_settings_id": self.machine, "print_settings_id": self.process,
            "filament_settings_id": [name for name, _ in self.filaments],
            "filament_colour": cols, "default_filament_colour": [""] * n,
            "filament_ids": [presets.flat("filament", nm).get("filament_id", "") for nm, _ in self.filaments],
            "filament_self_index": [str(i + 1) for i in range(n)],
            "filament_map": ["1"] * n,
            "flush_volumes_matrix": [str(flush_volume(a, b)) for a in cols for b in cols],
            "flush_volumes_vector": ["140"] * (2 * max(n, 4)),
            "print_compatible_printers": presets.flat("process", self.process).get("compatible_printers", []),
            "inherits_group": [""] * (n + 2),
            "enable_prime_tower": "1" if n > 1 else "0",
        })
        used = self.used_filaments()
        towers = []
        for pl in self.plates:
            multi = len({f for o in pl.objects for f in o.filaments()}) > 1
            towers.append(self.tower_spot(pl) if multi else None)
        default = (15.0, 220.0) if self.info["bed"][0] >= 250 else (self.info["bed"][0] - 50, self.info["bed"][1] - 50)
        cfg["wipe_tower_x"] = [f"{(t or default)[0]:g}" for t in towers]
        cfg["wipe_tower_y"] = [f"{(t or default)[1]:g}" for t in towers]
        cfg["enable_prime_tower"] = "1" if len(used) > 1 else "0"
        diff_p, diff_f, diff_m = [], [[] for _ in range(n)], []
        for k, v in self.overrides.items():
            cfg[k] = v
            kind = self.key_kind(k)
            if kind == "filament":
                for i in range(n):
                    diff_f[i].append(k)
            elif kind == "machine":
                diff_m.append(k)
            else:
                diff_p.append(k)
        cfg["different_settings_to_system"] = [";".join(sorted(diff_p))] + [";".join(sorted(d)) for d in diff_f] + [
            ";".join(sorted(diff_m))]
        return cfg

    def used_filaments(self):
        return sorted({f for _, o in self.objects() for f in o.filaments()})

    # ------------------------------------------------------------ summary
    def summary(self):
        info = self.info
        out = {
            "name": self.name, "printer": self.machine, "process": self.process,
            "bed_mm": list(info["bed"]), "source_file": self.source_path,
            "filaments": [{"slot": i + 1, "preset": n, "color": c} for i, (n, c) in enumerate(self.filaments)],
            "overrides": self.overrides, "plates": [], "warnings": self.warnings,
        }
        gid = 0
        for pi, pl in enumerate(self.plates):
            objs = []
            for o in pl.objects:
                gid += 1
                w, d, h = o.size()
                entry = {"id": gid, "name": o.name, "center_xy": [round(float(o.at[0]), 1), round(float(o.at[1]), 1)],
                         "size_mm": [round(float(w), 1), round(float(d), 1), round(float(h), 1)], "filaments": o.filaments(),
                         "parts": len(o.parts)}
                if len(o.parts) > 1:
                    entry["part_list"] = [{"name": p.name, "filament": p.filament, "type": p.subtype} for p in o.parts]
                if o.settings:
                    entry["settings"] = o.settings
                if self.out_of_bed(o):
                    entry["warning"] = "outside the printable area"
                if any(p.tri_attrs.get("paint_color") for p in o.parts):
                    entry["painted_colors"] = True
                objs.append(entry)
            entry = {"plate": pi + 1, "name": pl.name, "objects": objs}
            if pl.layer_gcodes:
                entry["layer_gcodes"] = [g.as_dict() for g in pl.layer_gcodes]
            out["plates"].append(entry)
        return out


def _lum(hexcol):
    h = hexcol.lstrip("#")[:6].ljust(6, "0")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def flush_volume(c_from, c_to):
    """Estimated purge (mm³) from one color to another: going lighter needs more."""
    if c_from.upper() == c_to.upper():
        return 0
    up = max(0.0, _lum(c_to) - _lum(c_from))
    down = max(0.0, _lum(c_from) - _lum(c_to))
    return int(round(min(800, 120 + 560 * up + 120 * down)))


def next_free_path(path):
    """Never overwrite: name.3mf -> name-2.3mf -> name-3.3mf ..."""
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    k = 2
    while os.path.exists(f"{base}-{k}{ext}"):
        k += 1
    return f"{base}-{k}{ext}"
