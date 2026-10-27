"""unofficial-bambu-mcp: build, edit, slice and preview Bambu Studio projects from an AI assistant.

Unofficial community project, not affiliated with or endorsed by Bambu Lab.
"""
import functools
import os
import time
import zipfile
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

import numpy as np
from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import arrange as arrange_mod
from . import (
    brim,
    calibration,
    camera,
    cutting,
    geometry,
    lan,
    measure,
    meshops,
    orient,
    paint,
    painting,
    presets,
    preview,
    printer,
    relief,
    sdcard,
    slicer,
    studio,
    svg,
    threemf,
    user_presets,
)
from .project import TOWER_BOX, LayerGcode, Obj, Part, Plate, Project, next_free_path

INSTRUCTIONS = """Work on Bambu Studio projects (.3mf) for Bambu Lab printers. Typical flow:
new_project or open_project -> import_model / add_shape -> move/arrange -> set_filament / set_setting ->
preview_plate (look at it) -> save_project -> slice_project -> preview_layer -> send_to_printer.
Coordinates are millimeters on the plate, origin at the front-left corner, objects are placed by the center
of their footprint and always sit on the bed. Plates and filament slots are numbered from 1.
Files are never overwritten: saving picks a new name if the file exists. Opened files are read as a copy.
Always look at preview_plate after changing the layout, and report slicing warnings to the user.
send_to_printer opens an official Bambu app where the user presses Print/Send. Only with via='lan' (printers in
Developer Mode) does it start the print itself, after the user confirmed with the code it gives."""

try:
    __version__ = _pkg_version("unofficial-bambu-mcp")
except PackageNotFoundError:                     # running from a source tree that was not installed
    __version__ = "0.0.0"

mcp = MCPServer("unofficial-bambu-mcp", instructions=INSTRUCTIONS, version=__version__)


def tool():
    """mcp.tool() that lets the model read why a call failed. The SDK shows the text of a ToolError only, and
    our errors say what to do next (wrong slot, printer refused, preset not found...)."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
                presets.refresh_if_changed()
                return fn(*args, **kwargs)
            except (ValueError, LookupError, OSError, RuntimeError, SyntaxError, zipfile.BadZipFile) as e:
                raise ToolError(str(e) or type(e).__name__) from e
        return mcp.tool()(wrapper)
    return deco


class Session:
    project = None
    saved = None
    sliced = None
    sliced_plates = {}    # project plate -> plate number inside the sliced file (they differ when empty plates were left out)
    watch = None          # project file that Bambu Studio may save (the last one opened or saved here)
    watch_mtime = 0.0
    dirty = False         # changes made here and not saved yet
    note = None           # one-shot message for the next answer (e.g. "reloaded from Bambu Studio")
    exported = {}         # job name (project name) -> last print file made by send_to_printer


S = Session()


def out_dir():
    d = os.path.abspath(os.path.expanduser(os.environ.get("UBMCP_DIR", "~/Documents/unofficial-bambu-mcp")))
    os.makedirs(d, exist_ok=True)
    return d


def _watch(path):
    S.watch = path
    S.watch_mtime = os.path.getmtime(path) if path and os.path.exists(path) else 0.0


def _file_changed():
    return bool(S.watch and os.path.exists(S.watch) and os.path.getmtime(S.watch) > S.watch_mtime + 0.5)


def P(write=False):
    """Current project. If the project file was saved in Bambu Studio meanwhile and there are no unsaved changes
    here, it is reloaded first, so edits made by hand in the app are not lost."""
    if S.project is None:
        raise ValueError("no project open: call new_project or open_project first")
    if _file_changed() and not S.dirty:
        S.project = threemf.read(S.watch)
        S.saved = S.watch
        _watch(S.watch)
        S.note = f"reloaded {os.path.basename(S.watch)}: it was saved in Bambu Studio"
    if write:
        S.dirty = True
    return S.project


def _color(c):
    c = (c or "#FFFFFF").strip()
    if not c.startswith("#"):
        c = "#" + c
    if len(c) != 7 or any(ch not in "0123456789abcdefABCDEF" for ch in c[1:]):
        raise ValueError(f"color '{c}' must be #RRGGBB")
    return c.upper()


def _short():
    p = P().summary()
    p.pop("overrides", None)
    return _with_note(p)


def _use_preferred_bed(pr):
    """Build plate = the one the user picked in Bambu Studio for this printer, when there is one."""
    bed = studio.preferred_bed_type(pr.machine)
    if bed:
        pr.overrides["curr_bed_type"] = bed


def _with_note(d):
    if S.note:
        d["note"] = S.note
        S.note = None
    if _file_changed() and S.dirty:
        d["conflict"] = ("the project file was saved in Bambu Studio, but there are unsaved changes here: "
                         "save_project to keep these, or sync_with_bambu_studio(force=True) to take the app's version")
    return d


# ---------------------------------------------------------------- environment
@tool()
def bambu_status() -> dict:
    """Where Bambu Studio is installed, its version, whether it is running, and the current project."""
    return {
        "bambu_studio": studio.executable(), "version": studio.version(), "running": studio.is_running(),
        "data_dir": studio.data_dir(), "profile_roots": studio.profile_roots(),
        "user_presets": studio.user_dir(), "output_dir": out_dir(), "bambu_connect": studio.bambu_connect(),
        "project": P().name if S.project else None, "last_saved": S.saved, "last_sliced": S.sliced,
    }


@tool()
def list_printers() -> list:
    """Printer short names that can be used anywhere a printer is asked (a full machine preset name works too)."""
    out = []
    for alias, machine in presets.PRINTER_ALIASES.items():
        if alias == "A1MINI" or not presets.exists("machine", machine):
            continue
        info = presets.machine_info(machine)
        out.append({"printer": alias, "machine_preset": machine, "bed_mm": list(info["bed"]),
                    "max_height_mm": info["max_height"], "default_process": info["default_process"]})
    return out


@tool()
def search_presets(kind: str, query: str = "", printer: str = "", limit: int = 30) -> list:
    """Find presets. kind: filament | process | machine. query: words to match (e.g. 'eSUN PLA+', '0.16mm').
    With printer, only presets compatible with it. User presets come first."""
    if kind not in presets.KINDS:
        raise ValueError("kind must be filament, process or machine")
    return presets.search(kind, query, printer or None, limit)


@tool()
def filament_colors(preset: str) -> list:
    """Official colors (name, hex) of a Bambu filament line, e.g. 'Bambu PLA Basic @BBL X1C'."""
    return presets.filament_colors(preset)


# ---------------------------------------------------------------- project
@tool()
def new_project(name: str, printer: str = "P1S", process: str = "", filaments: list[dict] | None = None) -> dict:
    """Start an empty project. filaments: AMS slots in order, e.g.
    [{"preset": "Bambu PLA Basic", "color": "#000000"}, {"preset": "eSUN PLA+", "color": "#FFFFFF"}].
    A filament name without '@...' is matched to the printer automatically. The build plate type is the one
    picked in Bambu Studio for this printer (change it with set_setting('curr_bed_type', ...))."""
    fils = [(f.get("preset") or "Bambu PLA Basic", _color(f.get("color"))) for f in (filaments or [])] or None
    S.project = Project(name, printer, process or None, fils)
    _use_preferred_bed(S.project)
    S.saved = S.sliced = None
    S.sliced_plates = {}
    _watch(None)
    S.dirty = True
    return _short()


@tool()
def open_project(path: str) -> dict:
    """Open a .3mf saved by Bambu Studio (or downloaded from MakerWorld). The file is never modified:
    save_project writes a new file. Returns the project summary and what could not be carried over."""
    path = os.path.abspath(os.path.expanduser(path))
    S.project = threemf.read(path)
    S.saved, S.sliced = None, None
    S.sliced_plates = {}
    _watch(path)
    S.dirty = False
    return P().summary()


@tool()
def get_project() -> dict:
    """Current project: printer, process, filament slots, plates, objects (id, name, center, size, filaments),
    setting overrides and warnings. If the project was saved in Bambu Studio in the meantime it is re-read first."""
    return _with_note(P().summary())


@tool()
def set_printer(printer: str, process: str = "", rearrange: bool = True) -> dict:
    """Switch printer (e.g. P1S -> A1M). Filament presets are swapped for the same filaments on the new printer.
    With rearrange, objects are re-placed to fit the new bed (extra plates are added if needed)."""
    pr = P(True)
    old = pr.set_printer(printer, process or None)
    _use_preferred_bed(pr)
    if rearrange:
        pr.arrange()
    res = _short()
    res["previous_printer"] = old
    return res


@tool()
def set_filament(slot: int, preset: str = "", color: str = "") -> dict:
    """Change one filament slot (1-based); a new slot number = add a slot. Leave a field empty to keep it."""
    pr = P(True)
    if slot < 1 or slot > len(pr.filaments) + 1:
        raise ValueError(f"slot must be 1..{len(pr.filaments) + 1}")
    cur = pr.filaments[slot - 1] if slot <= len(pr.filaments) else ("Bambu PLA Basic", "#FFFFFF")
    name = presets.filament_for(preset, pr.machine) if preset else cur[0]
    entry = (name, _color(color) if color else cur[1])
    if slot <= len(pr.filaments):
        pr.filaments[slot - 1] = entry
    else:
        pr.filaments.append(entry)
    pr.ams_slots.pop(slot, None)
    return {"filaments": pr.summary()["filaments"]}


# ---------------------------------------------------------------- plates
@tool()
def add_plate(name: str = "") -> dict:
    """Add an empty plate at the end."""
    pr = P(True)
    pr.plates.append(Plate(name or f"Plate {len(pr.plates) + 1}"))
    return {"plate": len(pr.plates), "plates": len(pr.plates)}


@tool()
def rename_plate(plate: int, name: str) -> dict:
    """Give a plate a name (shown in Bambu Studio)."""
    P(True).plate(plate).name = name
    return {"plate": plate, "name": name}


SEQUENCES = ("by layer", "by object")


@tool()
def set_plate_settings(plate: int, bed_type: str = "", print_sequence: str = "",
                       first_layer_filaments: list[int] | None = None, spiral_vase: str = "",
                       prime_tower: list[float] | None = None) -> dict:
    """Settings of one plate, like Bambu Studio's plate settings; they win over the project's on that plate.
    bed_type: Cool Plate, Engineering Plate, High Temp Plate, Textured PEI Plate or Supertack Plate.
    print_sequence: 'by layer', or 'by object' (each object printed to the end before the next).
    first_layer_filaments: order of the filament slots on the first layer, e.g. [2, 1].
    spiral_vase: 'on' or 'off'. prime_tower: [x, y] in mm, where its corner goes (e.g. between objects).
    'global' (or [] for the lists) goes back to the project's choice; empty leaves it as it is."""
    pr = P(True)
    pl = pr.plate(plate)
    n = len(pr.filaments)
    if bed_type:
        if bed_type == "global":
            pl.settings.pop("bed_type", None)
        elif bed_type in PLATE_TEMP:
            pl.settings["bed_type"] = bed_type
        else:
            raise ValueError(f"bed_type must be one of {list(PLATE_TEMP)} or 'global'")
    if print_sequence:
        if print_sequence == "global":
            pl.settings.pop("print_sequence", None)
        elif print_sequence in SEQUENCES:
            pl.settings["print_sequence"] = print_sequence
        else:
            raise ValueError("print_sequence must be 'by layer', 'by object' or 'global'")
    if first_layer_filaments is not None:
        if not first_layer_filaments:
            pl.settings.pop("first_layer_print_sequence", None)
        elif sorted(set(first_layer_filaments)) != sorted(first_layer_filaments) or \
                not all(1 <= f <= n for f in first_layer_filaments):
            raise ValueError(f"first_layer_filaments: filament slots 1..{n}, each once")
        else:
            pl.settings["first_layer_print_sequence"] = " ".join(str(int(f)) for f in first_layer_filaments)
    if spiral_vase:
        if spiral_vase not in ("on", "off", "global"):
            raise ValueError("spiral_vase must be 'on', 'off' or 'global'")
        if spiral_vase == "global":
            pl.settings.pop("spiral_mode", None)
        else:
            pl.settings["spiral_mode"] = "true" if spiral_vase == "on" else "false"
    if prime_tower is not None:
        if not prime_tower:
            pl.tower = None
        else:
            bw, bd = pr.info["bed"]
            if len(prime_tower) != 2 or not (0 <= prime_tower[0] < bw and 0 <= prime_tower[1] < bd):
                raise ValueError(f"prime_tower is [x, y] on the {bw:g} × {bd:g} mm plate")
            pl.tower = (float(prime_tower[0]), float(prime_tower[1]))
    res = {"plate": plate, "name": pl.name, "settings": dict(pl.settings)}
    if pl.tower:
        res["prime_tower_xy"] = list(pl.tower)
    if pl.settings.get("print_sequence") == "by object" and len(pl.objects) > 1:
        res["note"] = ("by object: the print head must pass over finished objects, so keep them apart and not too "
                       "tall (Bambu Studio's slicing says if they collide)")
    return res


@tool()
def remove_plate(plate: int, move_objects_to: int = 0) -> dict:
    """Delete a plate. Its objects are moved to plate `move_objects_to` (0 = delete them too)."""
    pr = P(True)
    pl = pr.plate(plate)
    if move_objects_to:
        dest = pr.plate(move_objects_to)
        for o in pl.objects:
            w, d, _ = o.size()
            spot = pr.find_spot(dest, w, d)
            if spot:
                o.at = spot
            dest.objects.append(o)
    pr.plates.pop(plate - 1)
    if not pr.plates:
        pr.plates.append(Plate("Plate 1"))
    return _short()


# ---------------------------------------------------------------- objects
def _place(pr, plate, obj, x, y):
    pl = pr.plate(plate)
    if x is None or y is None:
        w, d, _ = obj.size()
        spot = pr.find_spot(pl, w, d)
        if spot is None:
            raise ValueError(f"no free space on plate {plate} for {w:.0f}×{d:.0f} mm: use another plate or arrange")
        obj.at = spot
    else:
        obj.at = (float(x), float(y))
    pl.objects.append(obj)
    pr.objects()                                      # gives the new object its id
    res = {"id": obj.uid, "name": obj.name, "plate": plate,
           "center_xy": [round(float(obj.at[0]), 1), round(float(obj.at[1]), 1)], "size_mm": [round(float(v), 1) for v in obj.size()]}
    if pr.out_of_bed(obj):
        res["warning"] = "the object is (partly) outside the printable area"
    return res


@tool()
def import_model(path: str, plate: int = 1, x: float | None = None, y: float | None = None, rotate_z: float = 0,
                 scale: float = 1.0, filament: int = 1, name: str = "") -> list:
    """Put an STL, OBJ or 3MF on a plate. Without x/y it goes to the free spot closest to the center.
    From a 3MF every object is imported (with its parts and filament assignments)."""
    pr = P(True)
    path = os.path.abspath(os.path.expanduser(path))
    ext = os.path.splitext(path)[1].lower()
    objs = []
    if ext == ".3mf":
        src = threemf.read(path)
        for _, o in src.objects():
            o.name = pr.unique_name(o.name)
            objs.append(o)
    else:
        verts, tris = geometry.load_stl(path) if ext == ".stl" else geometry.load_obj(path)
        nm = pr.unique_name(name or os.path.splitext(os.path.basename(path))[0])
        objs.append(Obj(nm, [Part(nm, verts, tris, filament)]))
    out = []
    for o in objs:
        if scale != 1.0:
            o.transform(lambda v: geometry.scale(v, scale))
        if rotate_z:
            o.transform(lambda v: geometry.rotate(v, rotate_z))
        res = _place(pr, plate, o, x if len(objs) == 1 else None, y if len(objs) == 1 else None)
        big = float(max(o.size()))
        if big < 3:
            res["hint"] = (f"only {big:.2f} mm across: if it was modeled in inches, cm or meters, "
                           "convert_units(object, 'inch' / 'cm' / 'meter')")
        out.append(res)
    return out


def _svg_shape(path, size):
    """(shape in mm scaled so its longest side is `size` (0 = as in the file), (width, height))."""
    from shapely import affinity
    shape, (w, h) = svg.load(os.path.abspath(os.path.expanduser(path)))
    if size > 0:
        k = size / max(w, h)
        shape, w, h = affinity.scale(shape, k, k, origin=(0, 0)), w * k, h * k
    return shape, (w, h)


@tool()
def add_relief(object: str, text: str = "", svg: str = "", face: str = "top", at: list[float] | None = None,
               size: float = 10, depth: float = 1.0, engrave: bool = False, filament: int = 0, rotate: float = 0,
               font: str = "") -> dict:
    """Text or an SVG logo on a face of an object, raised or engraved, like Bambu Studio's Text and SVG tools. It
    follows the surface, curved faces too. face: top, bottom, front, back, left, right (the side it is read from);
    at: [x, y, z] plate point to center it on (default: the middle of that face); size: capital letter height for
    text, longest side for an SVG (mm); depth: how far it stands out or goes in; rotate: degrees within the face.
    Raised, it is a new part (filament=N prints it in another color); engraved, a negative part (set_part_type
    turns it back). Look at preview_plate afterwards."""
    pr = P(True)
    _, o = pr.find(object)
    if bool(text) == bool(svg):
        raise ValueError("give text or svg (one of them)")
    if not 0 < depth <= 20:
        raise ValueError("depth must be between 0 and 20 mm")
    fil = filament or o.solid_parts()[0].filament
    if not 1 <= fil <= len(pr.filaments):
        raise ValueError(f"filament must be a slot 1..{len(pr.filaments)}")
    if text:
        shape = geometry.text_outline(text, size, font or None)
    else:
        shape, _ = _svg_shape(svg, size)
    solids = [p for p in o.parts if p.subtype == "normal_part"]
    verts = np.concatenate([p.verts for p in solids])
    base = np.cumsum([0] + [len(p.verts) for p in solids[:-1]])
    tris = np.concatenate([p.tris + b for p, b in zip(solids, base, strict=True)])
    off = meshops.offset(o)
    U, V, _ = relief.frame(face)
    if at:
        if len(at) != 3:
            raise ValueError("at is [x, y, z] in plate mm")
        p = np.asarray(at, float) - off
    else:
        lo, hi = o.bbox()
        p = (lo + hi) / 2
    v, t, info = relief.build(verts, tris, shape, face, (float(p @ U), float(p @ V)), depth, engrave, rotate)
    label = (f"Text {text[:20]}" if text else f"Logo {os.path.splitext(os.path.basename(svg))[0]}")
    used = o.filaments()
    part = Part(label, v, t, fil, "negative_part" if engrave else "normal_part")
    o.parts.append(part)
    lo, hi = o.bbox()
    c = (lo + hi) / 2
    o.at = (float(c[0] + off[0]), float(c[1] + off[1]))
    res = {"name": o.name, "part": part.name, "type": "engraved (negative part)" if engrave else "raised",
           "face": face, "size_mm": _r(np.ptp(v, axis=0)), **info}
    notes = []
    if not engrave and face not in ("top",):
        notes.append("raised on a side or bottom face: the undersides of the letters print as small overhangs, "
                     "keep it shallow (about 1 mm) or engrave instead")
    if not engrave and fil not in used and len(used) == 1:
        notes.append(f"printed with filament {fil}: the object now has two colors, a prime tower is added")
    if info["surface_relief_mm"] > 0.05:
        notes.append(f"the surface under it is curved ({info['surface_relief_mm']} mm of height difference): "
                     "the shape follows it")
    if notes:
        res["notes"] = notes
    return res


@tool()
def add_shape(shape: str, plate: int = 1, x: float | None = None, y: float | None = None, filament: int = 1,
              name: str = "", width: float = 20, depth: float = 20, height: float = 20, diameter: float = 20,
              diameter_top: float = 0, text: str = "", text_height: float = 10, font: str = "",
              base: float = 0, base_filament: int = 0, svg: str = "", size: float = 0) -> dict:
    """Create a simple solid: box (width, depth, height), cylinder (diameter, height), cone (diameter,
    diameter_top, height), sphere (diameter), text (text, text_height = capital letters in mm, height = depth
    of the letters; base > 0 puts the text on a plate that thick, as a separate part 'Base' with filament
    base_filament (0 = same as the text), e.g. white letters on a black tag; font = path to a .ttf/.otf),
    svg (svg = path of an .svg file, a logo raised `height` mm; size = its longest side in mm, 0 = the file's
    own size; base works as for text). To put text or a logo on an existing object, use add_relief."""
    pr = P(True)
    for f in (filament, base_filament or filament):
        if not 1 <= f <= len(pr.filaments):
            raise ValueError(f"filament slot must be 1..{len(pr.filaments)} (add slots with set_filament)")
    shape = shape.lower().strip()
    if shape == "svg":
        if not svg:
            raise ValueError("give the .svg file: svg='/path/logo.svg'")
        outline, _ = _svg_shape(svg, size)          # `svg` here is the file path
        nm = pr.unique_name(name or os.path.splitext(os.path.basename(svg))[0])
        if base > 0:
            parts = [Part(pn, v, t, (base_filament or filament) if pn == "Base" else filament)
                     for pn, v, t in geometry.shape_parts(outline, height, base, label="Logo")]
        else:
            v, t = geometry.extrude(outline, height)
            parts = [Part(nm, v, t, filament)]
        return _place(pr, plate, Obj(nm, parts), x, y)
    if shape == "text" and base > 0:
        if not text:
            raise ValueError("text is empty")
        nm = pr.unique_name(name or text[:20])
        parts = [Part(pn, v, t, (base_filament or filament) if pn == "Base" else filament)
                 for pn, v, t in geometry.text_parts(text, text_height, height, font or None, base)]
        return _place(pr, plate, Obj(nm, parts), x, y)
    if shape == "box":
        v, t = geometry.box(width, depth, height)
    elif shape == "cylinder":
        v, t = geometry.cylinder(diameter, height)
    elif shape == "cone":
        v, t = geometry.cone(diameter, diameter_top, height)
    elif shape == "sphere":
        v, t = geometry.sphere(diameter)
    elif shape == "text":
        if not text:
            raise ValueError("text is empty")
        v, t = geometry.text_solid(text, text_height, height, font or None, base)
    else:
        raise ValueError("shape must be box, cylinder, cone, sphere or text")
    nm = pr.unique_name(name or (text[:20] if shape == "text" else shape.capitalize()))
    return _place(pr, plate, Obj(nm, [Part(nm, v, t, filament)]), x, y)


@tool()
def move_object(object: str, x: float | None = None, y: float | None = None, dx: float = 0, dy: float = 0,
                rotate_z: float = 0, plate: int = 0) -> dict:
    """Move an object (by name or id): absolute x/y, relative dx/dy, rotate around Z by rotate_z degrees,
    or move it to another plate (it keeps x/y if given, otherwise it goes to a free spot)."""
    pr = P(True)
    pi, o = pr.find(object)
    if rotate_z:
        o.transform(lambda v: geometry.rotate(v, rotate_z))
    if plate and plate != pi + 1:
        pr.plates[pi].objects.remove(o)
        return _place(pr, plate, o, x, y)
    nx = x if x is not None else o.at[0]
    ny = y if y is not None else o.at[1]
    o.at = (nx + dx, ny + dy)
    res = {"id": o.uid, "name": o.name, "plate": pi + 1, "center_xy": [round(float(o.at[0]), 1), round(float(o.at[1]), 1)],
           "size_mm": [round(float(v), 1) for v in o.size()]}
    if pr.out_of_bed(o):
        res["warning"] = "the object is (partly) outside the printable area"
    overlaps = [b.name for b in pr.plates[pi].objects if b is not o and _overlap(o.footprint(), b.footprint())]
    if overlaps:
        res["warning_overlap"] = overlaps
    return res


def _overlap(a, b):
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


@tool()
def transform_object(object: str, scale: float = 1.0, scale_xyz: list[float] | None = None, rotate_x: float = 0,
                     rotate_y: float = 0, rotate_z: float = 0) -> dict:
    """Scale (uniform or per axis) and rotate an object around its center. It stays on the bed."""
    pr = P(True)
    pi, o = pr.find(object)
    f = scale_xyz if scale_xyz else scale
    dropped = False
    if f != 1.0:
        dropped |= o.transform(lambda v: geometry.scale(v, f))
    for ang, ax in ((rotate_x, "x"), (rotate_y, "y"), (rotate_z, "z")):
        if ang:
            dropped |= o.transform(lambda v, a=ang, axis=ax: geometry.rotate(v, a, axis))
    res = {"name": o.name, "size_mm": [round(float(v), 1) for v in o.size()]}
    if dropped:
        res["note"] = _EARS_GONE
    if pr.out_of_bed(o):
        res["warning"] = "now (partly) outside the printable area: move_object or arrange"
    return res


@tool()
def duplicate_object(object: str, copies: int = 1, plate: int = 0) -> list:
    """Copy an object `copies` times onto free spots (same plate unless `plate` is given)."""
    import copy
    pr = P(True)
    pi, o = pr.find(object)
    out = []
    for _ in range(max(1, copies)):
        c = copy.deepcopy(o)
        c.uid = None
        c.name = pr.unique_name(o.name)
        out.append(_place(pr, plate or pi + 1, c, None, None))
    return out


@tool()
def fill_plate(object: str, copies: int = 0, gap: float = 6.0, rotate: bool = False, rotation_step: float = 90.0,
               keep_original: bool = False) -> dict:
    """Fill the free area of an object's plate with copies of it, like Bambu Studio's Fill bed with copies.
    copies: 0 = as many as fit, N = at most N. Shapes nest by their real outline (brim and brim ears counted), and
    rotate=True also tries turning them by rotation_step degrees. The original is placed again together with the
    copies (more fit), unless keep_original=True; the other objects on the plate stay where they are."""
    import copy
    pr = P(True)
    pi, o = pr.find(object)
    first, spots = arrange_mod.fill(pr, pr.config(), o, pi, copies, gap, rotate, rotation_step, keep_original)
    if not spots:
        raise ValueError(f"no room for a copy of '{o.name}' on plate {pi + 1} with a {gap:g} mm gap"
                         + ("" if keep_original else " (even placing the original again)"))

    def put(ob, spot):
        x, y, ang = spot
        if ang:
            lo, hi = ob.bbox()
            c0 = (lo + hi) / 2
            ob.transform(lambda v, a=ang: geometry.rotate(v, a))
            lo, hi = ob.bbox()
            c1 = (lo + hi) / 2
            x, y = x + c1[0] - c0[0], y + c1[1] - c0[1]
        ob.at = (float(x), float(y))

    template = copy.deepcopy(o)
    pr.plates[pi].tower = None                       # the fill kept the tower's corner free
    if first:
        put(o, first)
    made = []
    for spot in spots:
        c = copy.deepcopy(template)
        c.uid = None
        c.name = pr.unique_name(o.name)
        put(c, spot)
        pr.plates[pi].objects.append(c)
        made.append(c.name)
    pr.objects()
    res = {"object": o.name, "plate": pi + 1, "copies_added": len(made), "objects_on_plate": len(pr.plates[pi].objects),
           "next": "preview_plate to look at it"}
    if copies and len(made) < copies:
        res["note"] = f"only {len(made)} of the {copies} copies fit"
    if rotate:
        res["rotated"] = sum(1 for s in spots if s[2])
    return res


UNITS = {"inch": 25.4, "inches": 25.4, "in": 25.4, "cm": 10.0, "centimeter": 10.0, "centimeters": 10.0,
         "meter": 1000.0, "meters": 1000.0, "metre": 1000.0, "metres": 1000.0, "m": 1000.0}


@tool()
def convert_units(object: str, unit: str = "inch", restore: bool = False) -> dict:
    """An object modeled in other units, like Bambu Studio's Convert from inch / meter: unit 'inch', 'cm' or
    'meter' scales it up from that unit to millimeters (a 1-unit cube becomes 25.4, 10 or 1000 mm);
    restore=True scales it back down. import_model says when a model looks like it is in inches or meters."""
    pr = P(True)
    _, o = pr.find(object)
    f = UNITS.get(unit.strip().lower())
    if not f:
        raise ValueError("unit must be inch, cm or meter")
    dropped = o.transform(lambda v: geometry.scale(v, 1 / f if restore else f))
    res = {"name": o.name, "scaled_by": round(1 / f if restore else f, 6), "size_mm": [round(float(v), 2) for v in o.size()]}
    if dropped:
        res["note"] = _EARS_GONE
    if pr.out_of_bed(o):
        res["warning"] = "now (partly) outside the printable area: move_object or arrange"
    return res


@tool()
def set_object_printable(object: str, printable: bool = True) -> dict:
    """Keep an object on the plate but leave it out of the print (printable=False), like unticking Printable in
    Bambu Studio; True puts it back. The other objects slice and print as usual."""
    pr = P(True)
    _, o = pr.find(object)
    o.printable = bool(printable)
    return {"name": o.name, "printable": o.printable}


@tool()
def copy_object_settings(from_object: str, to_objects: list[str], keys: list[str] | None = None,
                         height_ranges: bool = False, replace: bool = False) -> dict:
    """Copy one object's own settings (set_object_setting: infill, walls, brim...) to other objects, like Bambu
    Studio's Copy / Paste process settings. keys: only these; replace=True first removes the targets' own
    settings; height_ranges=True copies the height bands too."""
    pr = P(True)
    _, src = pr.find(from_object)
    chosen = {k: v for k, v in src.settings.items() if not keys or k in keys}
    if keys:
        missing = [k for k in keys if k not in src.settings]
        if missing:
            raise ValueError(f"'{src.name}' has no setting of its own named {missing}: it has {sorted(src.settings)}")
    if not chosen and not (height_ranges and src.height_ranges):
        raise ValueError(f"'{src.name}' has no settings of its own to copy (see set_object_setting)")
    out = []
    for ref in to_objects:
        _, o = pr.find(ref)
        if o is src:
            continue
        if replace:
            o.settings = {}
        o.settings.update(chosen)
        if height_ranges:
            o.height_ranges = [dict(r, settings=dict(r["settings"])) for r in src.height_ranges]
        out.append(o.name)
    return {"from": src.name, "to": out, "settings": chosen,
            **({"height_ranges": len(src.height_ranges)} if height_ranges else {})}


ALIGN = ("left", "right", "center_x", "front", "back", "center_y")


@tool()
def align_objects(objects: list[str], align: str = "", distribute: str = "") -> dict:
    """Line up objects of one plate, like Bambu Studio's Align / Distribute, by their outer boxes.
    align: left, right, center_x (along X); front, back, center_y (along Y). distribute: 'x' or 'y' spaces them
    evenly between the two outermost ones. Both can be given."""
    pr = P(True)
    if len(objects or []) < 2:
        raise ValueError("give at least two objects")
    found = [pr.find(r) for r in objects]
    if len({pi for pi, _ in found}) > 1:
        raise ValueError("the objects are on different plates")
    objs = list({id(o): o for _, o in found}.values())
    if align and align not in ALIGN:
        raise ValueError(f"align must be one of {', '.join(ALIGN)}")
    if distribute and distribute not in ("x", "y"):
        raise ValueError("distribute must be 'x' or 'y'")
    if not align and not distribute:
        raise ValueError("say how: align and/or distribute")
    boxes = {id(o): o.footprint() for o in objs}
    if align:
        k = 0 if align in ("left", "right", "center_x") else 1
        lows = [boxes[id(o)][k] for o in objs]
        highs = [boxes[id(o)][k + 2] for o in objs]
        for o in objs:
            lo, hi = boxes[id(o)][k], boxes[id(o)][k + 2]
            if align in ("left", "front"):
                shift = min(lows) - lo
            elif align in ("right", "back"):
                shift = max(highs) - hi
            else:
                shift = (min(lows) + max(highs)) / 2 - (lo + hi) / 2
            at = list(o.at)
            at[k] += shift
            o.at = (float(at[0]), float(at[1]))
    if distribute:
        k = 0 if distribute == "x" else 1
        boxes = {id(o): o.footprint() for o in objs}
        order = sorted(objs, key=lambda o: boxes[id(o)][k])
        span = boxes[id(order[-1])][k + 2] - boxes[id(order[0])][k]
        sizes = sum(boxes[id(o)][k + 2] - boxes[id(o)][k] for o in order)
        gap = (span - sizes) / (len(order) - 1)
        edge = boxes[id(order[0])][k]
        for o in order:
            lo, hi = boxes[id(o)][k], boxes[id(o)][k + 2]
            at = list(o.at)
            at[k] += edge - lo
            o.at = (float(at[0]), float(at[1]))
            edge += hi - lo + gap
    res = {"objects": [{"name": o.name, "center_xy": [round(float(o.at[0]), 1), round(float(o.at[1]), 1)]} for o in objs]}
    if distribute and gap < 0:
        res["warning"] = "they do not fit between the outermost two: they overlap (arrange, or move one further out)"
    else:
        rects = [o.footprint() for o in objs]
        if any(a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]
               for i, a in enumerate(rects) for b in rects[i + 1:]):
            res["warning"] = "some objects now overlap: look at preview_plate"
    if any(pr.out_of_bed(o) for o in objs):
        res.setdefault("warning", "an object is (partly) outside the printable area")
    return res


def _object_mesh(o):
    """One mesh of what an object prints, where it is on the plate: its solid parts minus its negative parts."""
    off = meshops.offset(o)
    solids = [geometry.to_manifold(p.verts + off, p.tris) for p in o.parts if p.subtype == "normal_part"]
    holes = [geometry.to_manifold(p.verts + off, p.tris) for p in o.parts if p.subtype == "negative_part"]
    ok = all(m.status() == geometry.m3.Error.NoError for m in solids + holes)
    if ok:
        m = geometry.m3.Manifold.batch_boolean(solids, geometry.m3.OpType.Add) if len(solids) > 1 else solids[0]
        for h in holes:
            m = m - h
        return geometry.from_manifold(m), bool(holes)
    vs, ts, n = [], [], 0                             # not closed solids: the parts as they are
    for p in o.parts:
        if p.subtype == "normal_part":
            vs.append(p.verts + off)
            ts.append(p.tris + n)
            n += len(p.verts)
    return (np.vstack(vs), np.vstack(ts)), False


def _file_name(s):
    return "".join(c if c.isalnum() or c in " -_." else "_" for c in s).strip() or "object"


@tool()
def export_stl(objects: list[str] | None = None, plate: int = 0, one_file: bool = False) -> dict:
    """Save objects as STL files (e.g. to print them on other printers of a farm, or to share them): the named
    objects, all of a plate, or all of the project. One file per object, or one_file=True for all of them where
    they are on the plate. Negative parts (holes) are cut out; colors and settings are not part of an STL."""
    pr = P()
    if objects:
        objs = [pr.find(r)[1] for r in objects]
    elif plate:
        objs = list(pr.plate(plate).objects)
    else:
        objs = [o for _, o in pr.objects()]
    if not objs:
        raise ValueError("no objects to export")
    folder = os.path.join(out_dir(), "stl")
    os.makedirs(folder, exist_ok=True)
    meshes = [(o, *_object_mesh(o)) for o in objs]
    files = []
    if one_file:
        vs, ts, n = [], [], 0
        for _, (v, t), _ in meshes:
            vs.append(v)
            ts.append(t + n)
            n += len(v)
        path = next_free_path(os.path.join(folder, _file_name(pr.name) + (f" plate {plate}" if plate else "") + ".stl"))
        geometry.save_stl(path, np.vstack(vs), np.vstack(ts))
        files.append({"file": path, "objects": len(objs)})
    else:
        for o, (v, t), _ in meshes:
            path = next_free_path(os.path.join(folder, _file_name(o.name) + ".stl"))
            v = v - [*(v.min(0)[:2] + v.max(0)[:2]) / 2, v.min(0)[2]]       # centered, on z = 0
            geometry.save_stl(path, v, t)
            files.append({"file": path, "object": o.name, "triangles": int(len(t))})
    res = {"files": files}
    if any(cut for _, _, cut in meshes):
        res["note"] = "negative parts were cut out of the objects"
    return res


def _load_mesh(path):
    path = os.path.abspath(os.path.expanduser(path))
    ext = os.path.splitext(path)[1].lower()
    if ext == ".stl":
        return geometry.load_stl(path)
    if ext == ".obj":
        return geometry.load_obj(path)
    if ext == ".3mf":
        src = threemf.read(path)
        parts = [p for _, o in src.objects() for p in o.solid_parts() if p.subtype == "normal_part"]
        if len(parts) != 1:
            raise ValueError(f"{os.path.basename(path)} has {len(parts)} solid parts: use an STL or a 3MF with one part")
        return parts[0].verts, parts[0].tris
    raise ValueError("the file must be .stl, .obj or .3mf")


@tool()
def replace_with_stl(object: str, path: str, part: str = "") -> dict:
    """Swap the shape of an object (or of its part `part`) for the one in an STL/OBJ/3MF file, like Bambu
    Studio's Replace with STL, e.g. after fixing it in CAD. Name, filament, settings, place on the plate and the
    other parts stay; the new shape takes the old one's center, standing on the same bottom. Painting on the old
    shape is dropped (it was for other triangles)."""
    pr = P(True)
    _, o = pr.find(object)
    solids = [p for p in o.parts if p.subtype == "normal_part"]
    if part:
        hits = [p for p in o.parts if p.name.lower() == part.lower()]
        if not hits:
            raise ValueError(f"'{o.name}' has no part named '{part}': {[p.name for p in o.parts]}")
        target = hits[0]
    elif len(solids) == 1:
        target = solids[0]
    else:
        raise ValueError(f"'{o.name}' has {len(solids)} solid parts: say which one with part= {[p.name for p in solids]}")
    v, t = _load_mesh(path)
    off = meshops.offset(o)
    old_lo, old_hi = target.verts.min(0), target.verts.max(0)
    lo, hi = v.min(0), v.max(0)
    shift = np.array([(old_lo[0] + old_hi[0] - lo[0] - hi[0]) / 2, (old_lo[1] + old_hi[1] - lo[1] - hi[1]) / 2,
                      old_lo[2] - lo[2]])
    old_size = old_hi - old_lo
    target.verts, target.tris = np.asarray(v, float) + shift, np.asarray(t, np.int64)
    painted = bool(target.tri_attrs)
    target.tri_attrs = {}
    blo, bhi = o.bbox()
    c = (blo + bhi) / 2
    o.at = (float(c[0] + off[0]), float(c[1] + off[1]))
    res = {"name": o.name, "part": target.name, "old_size_mm": [round(float(x), 2) for x in old_size],
           "new_size_mm": [round(float(x), 2) for x in hi - lo], "check": geometry.check(target.verts, target.tris)}
    if painted:
        res["note"] = "the old painting was dropped"
    if pr.out_of_bed(o):
        res["warning"] = "now (partly) outside the printable area: move_object or arrange"
    return res


@tool()
def delete_object(object: str) -> dict:
    """Remove an object from the project."""
    pr = P(True)
    pi, o = pr.find(object)
    pr.plates[pi].objects.remove(o)
    return {"deleted": o.name, "plate": pi + 1}


@tool()
def set_object_filament(object: str, filament: int, part: str = "") -> dict:
    """Assign a filament slot to a whole object, or to one of its parts (by part name)."""
    pr = P(True)
    if not 1 <= filament <= len(pr.filaments):
        raise ValueError(f"filament slot must be 1..{len(pr.filaments)} (add slots with set_filament)")
    _, o = pr.find(object)
    hits = [p for p in o.parts if not part or p.name.lower() == part.lower()]
    if not hits:
        raise ValueError(f"no part '{part}' in {o.name}: {[p.name for p in o.parts]}")
    for p in hits:
        p.filament = filament
    return {"name": o.name, "parts": [{"name": p.name, "filament": p.filament} for p in o.parts]}


@tool()
def set_object_setting(object: str, key: str, value: str) -> dict:
    """Per-object print setting (e.g. sparse_infill_density '40%', wall_loops '4', layer_height '0.12').
    An empty value removes the override."""
    pr = P(True)
    _, o = pr.find(object)
    if pr.key_kind(key) not in ("process", None):
        raise ValueError(f"'{key}' is a {pr.key_kind(key)} setting: use set_setting")
    if value == "":
        o.settings.pop(key, None)
    else:
        o.settings[key] = value
    return {"name": o.name, "settings": o.settings}


@tool()
def check_object(object: str) -> dict:
    """Is the mesh a closed, printable solid? Size, volume, number of separate pieces."""
    _, o = P().find(object)
    return {"name": o.name, "parts": [{"name": p.name, **geometry.check(p.verts, p.tris)} for p in o.parts]}


def _line_width(pr):
    cfg = pr.config()
    nozzle = float((cfg.get("nozzle_diameter") or ["0.4"])[0])
    lw = str(cfg.get("outer_wall_line_width") or nozzle)
    return float(lw[:-1]) / 100 * nozzle if lw.endswith("%") else float(lw)


def _r(v, nd=2):
    return [round(float(x), nd) for x in v]


def _solids(pr, o, part):
    """[(name, manifold in plate mm, part)] of an object's solid parts (or the one named), and the parts that are
    not closed solids."""
    off = meshops.offset(o)
    parts = [p for p in o.parts if p.subtype == "normal_part" and (not part or p.name.lower() == part.lower())]
    if not parts:
        raise ValueError(f"'{o.name}' has no solid part named '{part}': {[p.name for p in o.parts]}")
    good, bad = [], []
    for p in parts:
        m = measure.solid(p, off)
        (good if m is not None else bad).append((p.name, m, p) if m is not None else p.name)
    return good, bad, off


@tool()
def measure_object(object: str, z: float = -1, part: str = "", min_wall: float = 0) -> dict:
    """Measure an object (or its part `part`), in plate mm: size and where it is, each part's size, volume and
    surface, the area standing on the bed, the smallest gaps between its separate pieces or parts (the clearance of
    print-in-place joints, with where), and walls thinner than the nozzle's line width (or min_wall mm), with
    where and at which heights. z >= 0: also the cross-section at that height above the bed, every island with
    its length, width and thickest point and its holes (how long and thick a bar is, how wide a hole is)."""
    pr = P()
    _, o = pr.find(object)
    good, bad, off = _solids(pr, o, part)
    parts = [p for _, _, p in good] + [p for p in o.parts if p.name in bad]
    allv = np.concatenate([p.verts for p in parts]) + off
    lo, hi = allv.min(0), allv.max(0)
    res = {"name": o.name, "size_mm": _r(hi - lo), "from_xyz": _r(lo), "to_xyz": _r(hi),
           "parts": [{"name": n, "size_mm": _r(np.ptp(p.verts, axis=0)), "volume_mm3": round(m.volume(), 1),
                      "surface_mm2": round(m.surface_area(), 1)} for n, m, p in good]}
    ms = [measure.light(m) for _, m, _ in good]
    if bad:
        res["not_closed"] = bad
    if not ms:
        res["note"] = "no closed solid to measure further: check_object tells why"
        return res
    res["on_bed_mm2"] = round(sum(g.area for g in measure.section(ms, float(lo[2]) + 0.05)), 1)
    pieces = []
    for (n, _, _), m in zip(good, ms, strict=True):
        bits = m.decompose()
        pieces += [(n if len(bits) == 1 else f"{n} #{k + 1}", b) for k, b in enumerate(bits)]
    if 1 < len(pieces) <= measure.MAX_PIECES:
        gaps = measure.gaps_between(pieces)
        if gaps:
            out = []
            by = dict(pieces)
            for g, a, b in gaps[:5]:
                _, pa, pb = measure.closest_points(by[a].to_mesh().vert_properties[:, :3],
                                                   by[b].to_mesh().vert_properties[:, :3], reach=g + 0.5)
                out.append({"between": [a, b], "gap_mm": round(g, 2), "near_xyz": _r((pa + pb) / 2, 1)})
            res["smallest_gaps"] = out
        else:
            res["smallest_gaps"] = f"no two pieces closer than {measure.GAP_SEARCH:g} mm"
        res["pieces"] = len(pieces)
    elif len(pieces) > measure.MAX_PIECES:
        res["pieces"] = len(pieces)
        res["note"] = f"more than {measure.MAX_PIECES} separate pieces: gaps between them not measured"
    w = min_wall or _line_width(pr)
    thinnest, spots = measure.scan_thin(ms, float(lo[2]), float(hi[2]), w, 0.0, 0.0)
    res["thin_walls"] = ({"thinner_than_mm": round(w, 2), "thinnest_about_mm": thinnest, "where": spots[:10]}
                         if spots else f"none thinner than {w:.2f} mm (the line width)")
    if z >= 0:
        if not lo[2] <= z <= hi[2]:
            raise ValueError(f"z must be between {lo[2]:.2f} and {hi[2]:.2f} mm")
        islands = sorted(measure.section(ms, float(z)), key=lambda g: -g.area)
        res["section"] = {"z": z, "islands": [measure.describe(g, 0.0, 0.0) for g in islands]}
    return res


@tool()
def measure_between(object_a: str, object_b: str, part_a: str = "", part_b: str = "") -> dict:
    """Distance between two objects or two parts (part_a / part_b; the same object twice with two parts measures
    the clearance between them), in plate mm: the smallest gap with about where it is, the distance between their
    centers, the gap along each axis between their outer boxes (negative = they overlap along it) and, if they
    overlap, the volume they share."""
    pr = P()
    _, oa = pr.find(object_a)
    _, ob = pr.find(object_b)
    ga, _, _ = _solids(pr, oa, part_a)
    gb, _, _ = _solids(pr, ob, part_b)
    if not ga or not gb:
        raise ValueError("both need a closed solid part (see check_object)")
    if oa is ob and not (part_a and part_b):
        raise ValueError("the same object twice: give part_a and part_b")
    ma = measure.light(ga[0][1] if len(ga) == 1 else
                       geometry.m3.Manifold.batch_boolean([m for _, m, _ in ga], geometry.m3.OpType.Add))
    mb = measure.light(gb[0][1] if len(gb) == 1 else
                       geometry.m3.Manifold.batch_boolean([m for _, m, _ in gb], geometry.m3.OpType.Add))
    va, vb = ma.to_mesh().vert_properties[:, :3], mb.to_mesh().vert_properties[:, :3]
    la, ha, lb, hb = va.min(0), va.max(0), vb.min(0), vb.max(0)
    shared = (ma ^ mb).volume()
    upper, pa, pb = measure.closest_points(va, vb, limit=3000)        # vertices: at least this close
    if shared > 1e-6:
        gap = 0.0
    else:
        gap = float(ma.min_gap(mb, upper + 0.01))
        _, pa, pb = measure.closest_points(va, vb, reach=gap + 0.5)
    ca, cb = (la + ha) / 2, (lb + hb) / 2
    res = {"a": oa.name + (f" / {part_a}" if part_a else ""), "b": ob.name + (f" / {part_b}" if part_b else ""),
           "gap_mm": round(gap, 3), "near_xyz": {"a": _r(pa, 1), "b": _r(pb, 1)},
           "centers_mm": round(float(np.linalg.norm(cb - ca)), 2), "centers_dxyz": _r(cb - ca),
           "box_gap_xyz": _r(np.maximum(lb - ha, la - hb))}
    if shared > 1e-6:
        res["overlap_mm3"] = round(shared, 2)
    return res


@tool()
def arrange(plate: int = 0, objects: list[str] | None = None, plates: int = 0, gap: float = 6.0,
            rotate: bool = False, rotation_step: float = 90.0, multi_material: bool = True,
            avoid_calibration_area: bool = True, align_to_y: bool = False) -> dict:
    """Arrange objects by their real outline seen from above, brim and brim ears included, so shapes can nest
    (like Bambu Studio's Arrange, which only uses convex hulls). gap: mm between those outlines (and from the
    plate's edge half of it). Which objects: plate N, the named `objects` (ids or names), or all (plate=0).
    plates: 0 = each object stays on its plate; N = spread them over plates 1..N, evenly; -1 = as few plates as
    possible. rotate: allow turning them by multiples of rotation_step degrees (e.g. 60 for snowflakes);
    multi_material false = one material (set of filaments) per plate; avoid_calibration_area: keep off the
    printer's flow calibration corner (P1S/X1: front left); align_to_y: long side along Y first.
    Plates with more than one material keep the back right corner free for the prime tower.
    If something does not fit, nothing is moved: the answer says what is left over and how many plates it needs.
    Objects not being arranged stay where they are. Look at preview_plate(view='top') afterwards."""
    pr = P(True)
    if gap < 0:
        raise ValueError("gap must be 0 or more")
    return arrange_mod.run(pr, pr.config(), plate=plate, objects=objects, plates=plates, gap=gap, rotate=rotate,
                           rotation_step=rotation_step, multi_material=multi_material,
                           avoid_calibration_area=avoid_calibration_area, align_to_y=align_to_y,
                           tower_box=TOWER_BOX)


# ---------------------------------------------------------------- settings
@tool()
def get_setting(key: str) -> dict:
    """Current value of a print/filament/printer setting, where it comes from, and the preset value."""
    pr = P()
    cfg = pr.config()
    kind = pr.key_kind(key)
    if key not in cfg and kind is None:
        close = [k for k in cfg if key.lower() in k.lower()][:15]
        raise ValueError(f"unknown setting '{key}'. Similar: {close}")
    value = pr.slot_values(key, cfg) if kind == "filament" else cfg.get(key)
    return {"key": key, "kind": kind, "value": value, "overridden": key in pr.overrides}


PA_KEYS = ("pressure_advance", "enable_pressure_advance")
PA_NOTE = ("Bambu Lab printers do not use the pressure advance of a filament preset (Bambu Studio writes no M900 "
           "for them, checked on a sliced P1S file): they use the K of the AMS slot, from Flow Dynamics calibration. "
           "To print with this K, set it on the printer: Device > AMS > slot > PA Profile / Factor K, and untick "
           "Flow Dynamics Calibration when sending")
PLATE_TEMP = {"Cool Plate": "cool_plate_temp", "Engineering Plate": "eng_plate_temp", "High Temp Plate": "hot_plate_temp",
              "Textured PEI Plate": "textured_plate_temp", "Supertack Plate": "supertack_plate_temp"}


@tool()
def set_setting(key: str, value: str, slot: int = 0) -> dict:
    """Override a project setting. For filament settings (temperatures, plate temperatures...) slot = filament
    slot (0 = all slots). Values are Bambu Studio strings, e.g. '0.16', '15%', '65'. Useful keys:
    layer_height, wall_loops, sparse_infill_density, top_shell_layers, enable_support, brim_type,
    initial_layer_speed, ironing_type, textured_plate_temp(_initial_layer) for Textured PEI,
    hot_plate_temp(_initial_layer) for the smooth/High Temp plate, nozzle_temperature(_initial_layer),
    close_fan_the_first_x_layers, print_sequence ('by object'), curr_bed_type ('Textured PEI Plate')."""
    pr = P(True)
    cfg = pr.config()
    if key not in cfg:
        close = [k for k in cfg if key.lower() in k.lower()][:15]
        raise ValueError(f"unknown setting '{key}'. Similar: {close}")
    kind = pr.key_kind(key)
    cur = pr.slot_values(key, cfg) if kind == "filament" else cfg[key]
    if isinstance(cur, list):
        new = list(cur)
        if kind == "filament" and slot:
            if not 1 <= slot <= len(new):
                raise ValueError(f"slot must be 1..{len(new)}")
            new[slot - 1] = value
        else:
            new = [value] * len(new)
        pr.overrides[key] = new
    else:
        pr.overrides[key] = value
    res = {"key": key, "kind": kind, "value": pr.overrides[key], "previous": cur}
    if key in PA_KEYS:
        res["pressure_advance_note"] = PA_NOTE
    family = next((f for f in PLATE_TEMP.values() if key in (f, f + "_initial_layer")), None)
    bed = pr.config().get("curr_bed_type")
    if family and PLATE_TEMP.get(bed, family) != family:
        res["warning"] = (f"this project prints on the {bed}, whose temperatures are {PLATE_TEMP[bed]}"
                          f"(_initial_layer): {key} is not used unless the plate is changed with "
                          "set_setting('curr_bed_type', ...)")
    return res


@tool()
def reset_setting(key: str) -> dict:
    """Drop an override: the setting goes back to the preset value."""
    pr = P(True)
    pr.overrides.pop(key, None)
    return {"key": key, "value": pr.config().get(key)}


# ---------------------------------------------------------------- purge volumes
MAX_PURGE, MAX_PURGE_MULTIPLIER = 900, 3.0      # Bambu Studio's limits in its purge dialog


def _purge_table(pr):
    m, hand = pr.purge_volumes()
    cfg = pr.config()
    mult = float((cfg.get("flush_multiplier") or ["1"])[0])
    return {"multiplier": mult,
            "slots": [{"slot": i + 1, "filament": n.split(" @")[0], "color": c} for i, (n, c) in enumerate(pr.filaments)],
            "volumes_mm3": [[round(v) for v in row] for row in m],
            "set_by_hand": sorted([list(k) for k in hand]),
            "how_to_read": "volumes_mm3[from - 1][to - 1]: purged when going from one slot to the other; "
                           "the purge is multiplier × volume. The others are estimated from the colors"}


@tool()
def get_purge_volumes() -> dict:
    """Purge (flush) volumes between filament slots, in mm³, and the multiplier: the filament wasted at each
    change on the prime tower (or into infill/objects, see set_purge_volumes)."""
    return _purge_table(P())


@tool()
def set_purge_volumes(volumes: list[dict] | None = None, matrix: list[list[float]] | None = None,
                      multiplier: float = 0, reset: bool = False) -> dict:
    """Change the purge (flush) volumes, as in Bambu Studio's Purging volumes dialog.
    volumes: [{"from": 1, "to": 2, "volume": 350}, ...] mm³ for single changes; matrix: every value at once,
    rows = from, columns = to (the diagonal is ignored); multiplier: scales all of them (0..3, 1 = as written);
    reset: back to the values estimated from the colors and multiplier 1. A value set by hand stays while both
    slots keep their color. Values are 0..900 mm³. Less purge saves filament but the new color can come out mixed
    at first; to waste less without that, purge into the infill or into an object with
    set_setting('flush_into_infill', '1') or set_object_setting(object, 'flush_into_objects', '1')."""
    pr = P(True)
    n = len(pr.filaments)
    if reset:
        pr.flush_set, pr.flush_multiplier = {}, None
    cols = [c for _, c in pr.filaments]
    todo = []
    if matrix is not None:
        if len(matrix) != n or any(len(r) != n for r in matrix):
            raise ValueError(f"matrix must be {n} × {n} (one row and one column per filament slot)")
        todo += [(i + 1, j + 1, matrix[i][j]) for i in range(n) for j in range(n) if i != j]
    for v in volumes or []:
        try:
            todo.append((int(v["from"]), int(v["to"]), v["volume"]))
        except (KeyError, TypeError, ValueError):
            raise ValueError('each entry is {"from": slot, "to": slot, "volume": mm³}') from None
    for i, j, vol in todo:
        if not (1 <= i <= n and 1 <= j <= n) or i == j:
            raise ValueError(f"slots must be two different numbers in 1..{n}: got {i} → {j}")
        vol = float(vol)
        if not 0 <= vol <= MAX_PURGE:
            raise ValueError(f"a purge volume is 0..{MAX_PURGE} mm³: got {vol:g} for {i} → {j}")
        pr.flush_set[(i, j)] = (vol, cols[i - 1], cols[j - 1])
    if multiplier:
        if not 0 < multiplier <= MAX_PURGE_MULTIPLIER:
            raise ValueError(f"multiplier is 0..{MAX_PURGE_MULTIPLIER:g}")
        pr.flush_multiplier = float(multiplier)
    res = _purge_table(pr)
    if n < 2:
        res["note"] = "one filament: nothing is purged"
    return res


# ---------------------------------------------------------------- files, slicing, previews
@tool()
def save_project(path: str = "", open_in_bambu: bool = False) -> dict:
    """Write the project as a Bambu Studio .3mf (default folder: the output dir, name from the project).
    Never overwrites: if the file exists a -2, -3... suffix is added. Optionally open it in Bambu Studio."""
    pr = P()
    if not path:
        path = os.path.join(out_dir(), f"{pr.name}.3mf")
    path = os.path.abspath(os.path.expanduser(path))
    if not path.endswith(".3mf"):
        path += ".3mf"
    path = next_free_path(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    threemf.write(pr, path)
    S.saved = path
    _watch(path)
    S.dirty = False
    res = {"saved": path, "warnings": [f"'{o.name}' is outside the printable area" for _, o in pr.objects()
                                       if pr.out_of_bed(o)]}
    if open_in_bambu:
        studio.open_in_gui(path)
        res["opened_in_bambu_studio"] = True
    return res


@tool()
def open_in_bambu_studio(path: str = "") -> dict:
    """Open a .3mf in the Bambu Studio window: by default the last saved project (else the last sliced one).
    Bambu Studio re-slices a project when asked (Slice plate), it does not reuse the slicing done here; to open
    a plate sliced and ready to print, use send_to_printer(via='bambu_studio')."""
    target = path or S.saved or S.sliced
    if not target:
        raise ValueError("nothing saved yet: call save_project first")
    return {"opened": studio.open_in_gui(os.path.expanduser(target))}


@tool()
def slice_project(plate: int = 0) -> dict:
    """Slice with Bambu Studio (plate 0 = all). Returns per plate: minutes, grams (total and per filament slot),
    cost (from the presets' price per kg), filament changes, layers and warnings. The sliced project is saved next to the project file."""
    import copy
    pr = P()
    full = [i + 1 for i, pl in enumerate(pr.plates) if pl.objects]
    if plate and plate not in full:
        pr.plate(plate)
        raise ValueError(f"plate {plate} is empty")
    if not full:
        raise ValueError("nothing to slice: every plate is empty")
    # Bambu Studio refuses to slice 'all plates' when one is empty: slice a copy without the empty plates
    sub = pr
    if not plate and len(full) < len(pr.plates):
        sub = copy.copy(pr)
        sub.plates = [pr.plates[n - 1] for n in full]
    numbers = full if sub is not pr else list(range(1, len(pr.plates) + 1))    # sliced file plate k = numbers[k-1]
    base = S.saved or os.path.join(out_dir(), f"{pr.name}.3mf")
    tmp = next_free_path(os.path.join(out_dir(), f".{pr.name}-slicing.3mf"))
    threemf.write(sub, tmp)
    out = next_free_path(base.replace(".3mf", "-sliced.3mf"))
    try:
        stats = slicer.slice_3mf(tmp, out, numbers.index(plate) + 1 if plate else 0)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    costs = pr.config().get("filament_cost") or []
    priced = False
    for st in stats:
        st["plate"] = numbers[st["plate"] - 1]
        per = {}
        for slot, g in st.get("grams_per_filament", {}).items():
            try:
                per[slot] = round(g * float(costs[slot - 1]) / 1000, 2)
            except (IndexError, TypeError, ValueError):
                continue
        if any(per.values()):
            st["cost"], st["cost_per_filament"], priced = round(sum(per.values()), 2), per, True
    S.sliced = out
    S.sliced_plates = {n: k + 1 for k, n in enumerate(numbers)}
    res = {"sliced_file": out, "plates": stats}
    if priced:
        res["cost_note"] = ("cost = grams × each slot's price per kg (filament_cost of its preset, in the currency "
                            "you use there); change it with set_setting('filament_cost', '25', slot=N)")
    if not plate and sub is not pr:
        res["skipped_empty_plates"] = [n for n in range(1, len(pr.plates) + 1) if n not in full]
        res["note"] = "the sliced file leaves the empty plates out, so its plates are numbered without them"
    if plate:
        res["note"] = f"the sliced file holds plate {plate} only (Bambu Studio exports just the sliced plate)"
    return res


@tool()
def preview_plate(plate: int = 1, view: str = "iso", zoom: bool = False, labels: bool = False) -> Image:
    """Image of a plate with its objects in their filament colors (painted colors too).
    view: iso | top. zoom: frame the objects instead of the whole bed, to see details.
    labels: write each object's id and name on it, e.g. view='top', labels=True to tell which part is which
    (a part that came off the plate, the list in Bambu Handy's skip objects)."""
    pr = P()
    pr.plate(plate)
    return Image(data=preview.render_plate(pr, plate - 1, "top" if view == "top" else "iso", zoom=zoom,
                                           object_labels=labels), format="png")


def _footing(o):
    """What holds an object during the first layers: (mm² on the bed, narrowest width in mm and smallest area in mm²
    of its separate contact areas, e.g. each pin of a set), from the solid faces lying on the bed."""
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    lo = o.bbox()[0][2]
    polys = []
    for p in o.solid_parts():
        tri = p.verts[p.tris]
        n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
        for t in tri[(tri[:, :, 2] <= lo + 0.05).all(axis=1) & (n[:, 2] < 0)]:
            pg = Polygon(t[:, :2])
            if pg.area > 1e-6:
                polys.append(pg.buffer(0.01))
    if not polys:
        return 0.0, 0.0, 0.0
    shape = unary_union(polys)
    pieces = [pc for pc in getattr(shape, "geoms", [shape]) if pc.area >= 1.0]
    widths = []
    for pc in pieces:
        x, y = pc.minimum_rotated_rectangle.exterior.coords.xy
        sides = [((x[i + 1] - x[i]) ** 2 + (y[i + 1] - y[i]) ** 2) ** 0.5 for i in range(2)]
        widths.append(min(sides))
    return float(shape.area), (min(widths) if widths else 0.0), (min(pc.area for pc in pieces) if pieces else 0.0)


@tool()
def check_print_risks(plate: int = 0) -> list:
    """Before a long print: parts likely to come off or topple, and settings that do not fit. Per plate (0 = all):
    tall and narrow parts (height against the smaller side of the footprint), parts standing on a narrow or tiny
    footing without a brim (e.g. pins lying on their side), filaments whose temperature for this build plate is 0
    (not meant for it), and plates where tall parts share a long print with many others (a part that fails late can
    knock the others: print them apart)."""
    pr = P()
    cfg = pr.config()
    bed = cfg.get("curr_bed_type") or "Textured PEI Plate"
    fam = PLATE_TEMP.get(bed)
    plates = [plate] if plate else list(range(1, len(pr.plates) + 1))
    out = []
    pr.objects()
    for n in plates:
        pl = pr.plate(n)
        risks, tall = [], []
        for o in pl.objects:
            w, d, h = (float(x) for x in o.size())
            btype = o.settings.get("brim_type") or cfg.get("brim_type") or "auto_brim"
            area, width, piece = _footing(o)
            why = []
            slender = h >= 40 and h / max(min(w, d), 0.1) >= 4
            if slender:
                why.append(f"{h:.0f} mm high on a {min(w, d):.0f} mm side")
            if btype in ("no_brim", "auto_brim"):
                if area < 1:
                    why.append("almost no flat face on the bed")
                elif width and (h / width >= 4 or (width < 15 and h / width >= 1.5)):
                    why.append(f"stands on a {width:.1f} mm wide footing for {h:.1f} mm of height")
                elif piece < 250:
                    why.append(f"a piece holds on {piece:.0f} mm² of the bed only")
            try:
                islands = _first_layer(pr, o)[0]
            except Exception:                            # an odd mesh must not stop the other checks
                islands = []
            gap = brim.gaps(islands)
            jointed = gap is not None and gap < 1.5     # print-in-place or articulated: pieces close together
            if why:
                if btype in ("no_brim", "auto_brim"):
                    if jointed:
                        fix = (f"ears only on the thin parts: add_brim_ears(object); a full brim would weld pieces "
                               f"{gap:.1f} mm apart on the first layer")
                    else:
                        fix = "give it an outer brim: set_object_setting(object, 'brim_type', 'outer_only')"
                    if slender:
                        fix += "; or lay it down / cut it, and avoid sport speed"
                    has = ", no brim" if btype == "no_brim" else ", brim left to auto"
                else:
                    fix = "it has a brim; if it can lie down or be cut, print it that way, and avoid sport speed"
                    has = f", brim {btype}"
                risks.append({"object": o.name, "id": o.uid, "risk": "; ".join(why) + has, "advice": fix})
            if jointed and btype in ("outer_only", "inner_only", "outer_and_inner"):
                risks.append({"object": o.name, "id": o.uid,
                              "risk": f"pieces {gap:.1f} mm apart on the first layer (print-in-place or articulated) "
                                      f"with a {btype} brim: it can fill the gaps and weld them",
                              "advice": "set_object_setting(object, 'brim_type', 'no_brim'), then add_brim_ears(object)"})
            if btype == "brim_ears" and not o.brim_ears:
                risks.append({"object": o.name, "id": o.uid,
                              "risk": "brim type brim_ears (Painted) but no ears: no brim is printed",
                              "advice": "add_brim_ears(object)"})
            if h >= 120:
                tall.append(o.name)
        used = sorted({f for o in pl.objects for f in o.filaments()})
        for f in used:
            for key in (fam, fam + "_initial_layer") if fam else ():
                vals = cfg.get(key) or []
                if f <= len(vals) and str(vals[f - 1]).strip() in ("0", ""):
                    risks.append({"filament": f, "risk": f"{pr.filaments[f - 1][0].split(' @')[0]} has {key} = 0: "
                                                         f"not meant for the {bed}",
                                  "advice": "use another plate (set_setting('curr_bed_type', ...)) or another filament"})
                    break
        if tall and len(pl.objects) >= 5:
            risks.append({"risk": f"{len(tall)} part(s) over 120 mm ({', '.join(tall[:4])}) share the plate with "
                                  f"{len(pl.objects) - len(tall)} others",
                          "advice": "print the tall parts on their own plate: if one fails late it can ruin the rest"})
        out.append({"plate": n, "objects": len(pl.objects), "risks": risks or "none found"})
    return out


@tool()
def reprint_objects(objects: list[str], brim: bool = True, name: str = "", slice: bool = True) -> dict:
    """A new project with only some objects of the open one, e.g. a part that came off the plate and was skipped:
    same printer, process, filaments and settings, laid out again (more plates if needed); brim=True gives each
    an outer brim. Saved as a new file (never overwrites) and sliced; the open project is not changed:
    open_project(file) then send_to_printer to print it. objects: names or ids (see get_project)."""
    import copy
    pr = P()
    if not objects:
        raise ValueError("list the objects to reprint (names or ids, see get_project)")
    picked = []
    for ref in objects:
        _, o = pr.find(ref)
        if all(o is not x for x in picked):
            picked.append(o)
    t = Project(name or f"{pr.name} reprint", pr.machine, pr.process, list(pr.filaments))
    t.overrides = copy.deepcopy(pr.overrides)
    t.flush_set, t.flush_multiplier = dict(pr.flush_set), pr.flush_multiplier
    for o in picked:
        c = copy.deepcopy(o)
        c.uid = None
        if brim:
            c.settings["brim_type"] = "outer_only"
        t.plates[0].objects.append(c)
    t.arrange()
    path = next_free_path(os.path.join(out_dir(), f"{t.name}.3mf"))
    threemf.write(t, path)
    res = {"file": path, "objects": [o.name for o in picked], "plates": len(t.plates),
           "brim": "outer_only" if brim else "as in the project"}
    if slice:
        sliced = next_free_path(path.replace(".3mf", "-sliced.3mf"))
        res["sliced"] = [{k: st.get(k) for k in ("plate", "minutes", "grams", "warnings")}
                         for st in slicer.slice_3mf(path, sliced)]
    res["next"] = "open_project(file) then send_to_printer(plate=1)"
    return res


@tool()
def preview_layer(plate: int = 1, layer: int = 0, z: float = 0, zoom: bool = True) -> Image:
    """Image of one sliced layer seen from the top (needs slice_project first). Choose by layer number (1 = first)
    or by height z in mm. Extrusions are drawn in the filament colors. zoom: frame the extrusions (default),
    or False for the whole bed."""
    pr = P()
    if not S.sliced:
        raise ValueError("slice the project first (slice_project)")
    g = slicer.gcode(S.sliced, S.sliced_plates.get(plate, plate))
    if not g:
        raise ValueError(f"plate {plate} was not sliced")
    segs, k, zz, n = slicer.layer_paths(g, layer or (None if z else 1), z or None)
    title = f"Plate {plate} - layer {k}/{n} - z {zz:.2f} mm - {len(segs)} moves"
    return Image(data=preview.render_layer(segs, pr.info["bed"], [c for _, c in pr.filaments], title,
                                           exclude=pr.info["exclude"], zoom=zoom), format="png")


@tool()
def make_first_layer_test(plate: int = 1, height: float = 0.8, objects: list[str] | None = None) -> dict:
    """Add a plate with the first `height` mm of the objects of a plate (or of the listed objects):
    a short print to check bed adhesion and the first layers before a long print. Slice it with
    slice_project(plate=<new plate>)."""
    import copy
    pr = P(True)
    src = [pr.find(o)[1] for o in objects] if objects else list(pr.plate(plate).objects)
    if not src:
        raise ValueError("no objects to test")
    test = Plate(f"First {height:g} mm test")
    pr.plates.append(test)
    for o in src:
        c = copy.deepcopy(o)
        c.uid = None
        lo, _ = c.bbox()
        keep = []
        for p in c.parts:
            if p.subtype != "normal_part":
                continue
            v = p.verts.copy()
            v[:, 2] -= lo[2]
            nv, nt = geometry.crop_height(v, p.tris, height)
            if len(nt):
                keep.append(Part(p.name, nv, nt, p.filament))
        if not keep:
            continue
        c.parts = keep
        c.name = pr.unique_name(f"{o.name} test")
        c.at = o.at
        test.objects.append(c)
    return {"plate": len(pr.plates), "objects": [o.name for o in test.objects],
            "note": "painted colors are not kept in the test copy"}


@tool()
def send_to_printer(plate: int = 1, via: str = "auto", ams_slots: list[int] | None = None,
                    bed_leveling: bool = True, timelapse: bool = False, confirm: str = "") -> dict:
    """Make the print file of one plate (.gcode.3mf) and send it.
    via = auto (Bambu Connect if installed, otherwise Bambu Studio) | bambu_connect | bambu_studio: open it in an
      official Bambu app, where the user checks printer and AMS mapping and presses Print/Send.
    via = file: only make the file.
    via = lan: copy it to the printer on the local network and START PRINTING, for printers in LAN-only mode with
      Developer Mode (print farms; in cloud mode the printer refuses and the answer says so). Two steps: without
      confirm nothing is sent, the answer gives the AMS slots it would use and a code; check with the user that the
      plate is clear, then call again with confirm=<code>. AMS slots: from use_ams_filaments, or ams_slots (one AMS
      slot per project filament slot, 0 = automatic), or the tray with the same type and the closest color.
    Tell the user the time, weight and filaments of the plate (and for lan, follow it with printer_status)."""
    pr = P()
    pl = pr.plate(plate)
    if not pl.objects:
        raise ValueError(f"plate {plate} is empty")
    if via not in ("auto", "lan", "bambu_connect", "bambu_studio", "file"):
        raise ValueError("via must be auto, lan, bambu_connect, bambu_studio or file")
    used = sorted({f for o in pl.objects for f in o.filaments()})
    mapping = None
    if via == "lan":            # check the printer and the AMS before the slow export: what is missing fails fast
        rep, _ = printer.status(max_age=5)
        st = printer.summarize(rep)
        if rep.get("gcode_state") in lan.BUSY:
            raise ValueError(f"the printer is {st['state']}: wait for the current job to end")
        trays = st["ams_trays"]
        chosen = dict(pr.ams_slots)
        chosen.update({k: a for k, a in enumerate(ams_slots or [], start=1) if a})
        types = pr.config().get("filament_type") or []
        fils = [(types[i] if i < len(types) else "PLA", c) for i, (_, c) in enumerate(pr.filaments)]
        try:
            if trays:
                mapping = lan.ams_mapping(fils, used, trays, chosen)
            elif len(used) > 1:
                raise ValueError("this plate uses several filaments but the printer has no AMS")
        except printer.PrinterError as e:
            raise ValueError(str(e)) from e
        code = f"print plate {plate}"
        if confirm.strip() != code:
            return {"would_print": plate, "printer_state": st["state"],
                    "ams_slots": {k: mapping[k - 1] + 1 for k in used} if mapping else "external spool",
                    "bed_leveling": bed_leveling, "timelapse": timelapse, "confirm": code,
                    "next": "the printer will start by itself: check with the user that the plate is clear and the "
                            "AMS slots are right, then call again with confirm set to the code above"}
    tmp = next_free_path(os.path.join(out_dir(), f".{pr.name}-export.3mf"))
    # pin the bed type on the plate: Bambu Studio re-applies the user's own bed choice when it opens the file,
    # and a global bed change throws away the slicing of plates without one (no Print button)
    pinned = "bed_type" not in pl.settings
    if pinned:
        pl.settings["bed_type"] = pr.config().get("curr_bed_type") or "Textured PEI Plate"
    try:
        threemf.write(pr, tmp)
    finally:
        if pinned:
            pl.settings.pop("bed_type")
    out = next_free_path(os.path.join(out_dir(), f"{pr.name}-plate{plate}.gcode.3mf"))
    try:
        st = slicer.export_plate(tmp, plate, out, model_id=pr.info.get("model_id"))
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    S.exported[pr.name] = out             # Bambu apps name the job after the project
    res = {"print_file": out, "plate": plate, "printer": pr.machine, "build_plate": pl.settings.get("bed_type")
           or pr.config().get("curr_bed_type"), "minutes": st.get("minutes"), "grams": st.get("grams"),
           "warnings": st.get("warnings", []),
           "filaments": [{"slot": k, "preset": pr.filaments[k - 1][0], "color": pr.filaments[k - 1][1]}
                         for k in used if k <= len(pr.filaments)]}
    target = via
    if via == "auto":
        target = "bambu_connect" if studio.bambu_connect() else "bambu_studio"
    if target == "lan":
        if mapping:
            for f in res["filaments"]:
                f["ams_slot"] = mapping[f["slot"] - 1] + 1
        try:
            res.update(lan.start_print(out, mapping, bed_leveling=bed_leveling, timelapse=timelapse))
        except printer.PrinterError as e:
            raise ValueError(str(e)) from e
        res["next_step"] = "Printing: follow it with printer_status (printer_camera to see the plate)."
    elif target == "bambu_connect":
        if not studio.bambu_connect():
            raise ValueError("Bambu Connect is not installed (https://wiki.bambulab.com/en/software/bambu-connect); "
                             "use via='bambu_studio'")
        studio.send_to_bambu_connect(out, f"{pr.name} - {pl.name}")
        res["next_step"] = "Bambu Connect is open with the file: choose the printer, check the AMS slots, press Send."
    elif target == "bambu_studio":
        studio.open_in_gui(out)
        res["next_step"] = ("Bambu Studio is open on the sliced plate: check printer and AMS mapping, then press "
                            "'Print plate' (Stampa piatto).")
    else:
        res["next_step"] = "File exported only."
    res["via"] = target
    return res


@tool()
def skip_objects(ids: list[int], confirm: str = "") -> dict:
    """Stop printing some objects of the print running now, e.g. a part that came off the plate. It CANNOT be undone.
    ids: the objects' ids as the printer knows them (identify_id; Bambu Handy's skip list, or printer_status
    'skipped_objects'). Do not list every object: to stop the whole print, cancel it on the printer.
    First call without confirm: nothing is sent, the answer says what would be skipped and the confirm code; tell
    the user, and only after they agree call again with confirm=<code>.
    Bambu firmware accepts it only in LAN-only mode with Developer Mode; otherwise use Bambu Handy or the printer."""
    ids = sorted({int(i) for i in ids})
    if not ids:
        raise ValueError("list the ids of the objects to skip")
    code = "skip " + ",".join(str(i) for i in ids)
    if confirm.strip() != code:
        rep, _ = printer.status(max_age=5)
        st = printer.summarize(rep)
        already = sorted({int(x) for x in rep.get("s_obj") or []})
        res = {"would_skip": [i for i in ids if i not in already], "job": st.get("job"), "state": st.get("state"),
               "already_skipped": already, "confirm": code,
               "next": "this cannot be undone: ask the user, then call again with confirm set to the code above"}
        if not res["would_skip"]:
            res["next"] = "nothing to do: these objects are already skipped"
        return res
    try:
        res = lan.skip_objects(ids)
    except printer.PrinterError as e:
        raise ValueError(str(e)) from e
    res["next"] = "follow the print with printer_status"
    return res


def _ams_step(slot, confirm, code, label):
    rep, _ = printer.status(max_age=0)
    st = printer.summarize(rep)
    why = lan.check_ams_change(rep, slot)
    if confirm.strip() != code or why:
        tray = next((t for t in st.get("ams_trays", []) if t["slot"] == slot), None) if slot else None
        res = {"would": label, "state": st.get("state"), "loaded_now": lan.loaded_slot(rep)}
        if tray:
            res["slot"] = tray
        if why:
            res["cannot"] = why
        else:
            res.update(confirm=code, next="the nozzle heats up and filament moves: ask the user, then call again "
                                          "with confirm set to the code above")
        return res
    try:
        res = lan.ams_change(slot)
    except printer.PrinterError as e:
        raise ValueError(str(e)) from e
    res["next"] = "printer_status shows the loaded slot"
    return res


@tool()
def ams_load(slot: int, confirm: str = "") -> dict:
    """Load the filament of an AMS slot into the nozzle, like Load in Bambu Studio's Device tab: the nozzle heats,
    the filament loaded now (if any) goes back to its slot, the new one comes in and is purged. slot: as in
    printer_status (AMS 1 = slots 1-4, AMS 2 = 5-8). Only when the printer is not printing.
    First call without confirm: nothing is sent, the answer says what would happen and the confirm code; tell the
    user, and only after they agree call again with confirm=<code>.
    Bambu firmware accepts it only in LAN-only mode with Developer Mode; otherwise use the printer screen, Bambu
    Handy or Bambu Studio."""
    if slot < 1:
        raise ValueError("slot is 1-based, as in printer_status")
    return _ams_step(slot, confirm, f"load {slot}", f"load AMS slot {slot}")


@tool()
def ams_unload(confirm: str = "") -> dict:
    """Unload the filament in the nozzle back to its AMS slot, like Unload in Bambu Studio's Device tab (the nozzle
    heats). Only when the printer is not printing. First call without confirm: nothing is sent, the answer gives
    the confirm code; call again with confirm=<code> only after the user agrees.
    Bambu firmware accepts it only in LAN-only mode with Developer Mode; otherwise use the printer screen, Bambu
    Handy or Bambu Studio."""
    return _ams_step(None, confirm, "unload", "unload the filament in the nozzle")


@tool()
def printer_status() -> dict:
    """Read-only status of the printer on the local network: state, job, progress, remaining time, layer
    (or the last job's result when idle), temperatures, AMS trays (type, color, remaining %; 'unknown' = a spool
    the AMS has not been told about), AMS humidity and temperature, active slot, errors, objects skipped during the
    print, and warnings (the spool being fed is unknown or not the project's filament, sport speed on a long print,
    a report that looks old). read_at = when the printer sent it; age_s = seconds since, when a reading of a few
    seconds ago is given again (the printer is asked at most every 20 s).
    Works with the printer in normal cloud mode (Bambu Handy keeps working). Nothing is sent to the printer except a
    status request."""
    rep, serial = printer.status()
    out = printer.summarize(rep)
    out["printer"] = f"...{serial[-4:]}"
    job = out.get("job") or ""
    expected = []
    if S.project and job and job.rsplit(".", 1)[0] == S.project.name:
        for i, (preset, _) in enumerate(S.project.filaments, start=1):
            try:
                expected.append((i, preset, presets.flat("filament", preset).get("filament_id")))
            except presets.PresetError:
                pass
    warnings = rep.get("_stale", []) + printer.advice(out, expected)
    if out.get("skipped_objects"):
        names = threemf.object_names(S.exported[job]) if job in S.exported else {}
        out["skipped_objects"] = [{"id": i, **({"name": names[i]} if i in names else {})}
                                  for i in out["skipped_objects"]]
        if not names:
            warnings.append("skipped objects are listed by the ids Bambu Studio gave them when slicing; their names "
                            "are known only for jobs sent with send_to_printer")
    if warnings:
        out["warnings"] = warnings
    return out


@tool()
def printer_camera(max_size: int = 1280) -> Image:
    """A picture from the printer's camera right now (P1 and A1 series), to see the plate: how a print is going,
    whether something came off or made spaghetti, what is left on the bed. Read-only; works with the printer in
    cloud mode. With the chamber light off the picture is dark. max_size: longest side in pixels."""
    from io import BytesIO

    from PIL import Image as PILImage
    jpg = camera.snapshot()
    img = PILImage.open(BytesIO(jpg))
    if max_size and max(img.size) > max_size:
        img.thumbnail((max_size, max_size))
        buf = BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=85)
        jpg = buf.getvalue()
    return Image(data=jpg, format="jpeg")


def _sd_kind(kind):
    if kind not in sdcard.FOLDERS:
        raise ValueError(f"kind must be one of {', '.join(sdcard.FOLDERS)}")
    return kind


def _mb(n):
    return round(n / 1e6, 1)


@tool()
def printer_files(kind: str = "all", limit: int = 30) -> dict:
    """Files on the printer's SD card, newest first, with name, size and date and the total per folder:
    timelapse (videos of past prints), prints (files of past prints the printer keeps), thumbnails (timelapse
    thumbnails whose video was deleted). Read-only; works with the printer in cloud mode."""
    kinds = list(sdcard.FOLDERS) if kind == "all" else [_sd_kind(kind)]
    out = {}
    with sdcard.session() as f:
        for k in kinds:
            files = sdcard.listing(f, k)
            out[k] = {"files": len(files), "total_mb": _mb(sum(x["size"] for x in files)),
                      "newest": [{"name": x["name"], "mb": _mb(x["size"]), "date": x["date"]} for x in files[:limit]]}
            if len(files) > limit:
                out[k]["more"] = len(files) - limit
    out["next"] = "download_printer_file to get one; delete_printer_files to free space"
    return out


@tool()
def download_printer_file(name: str = "latest", kind: str = "timelapse") -> list:
    """Copy a file from the printer's SD card into the projects folder: a timelapse video (name from printer_files,
    or 'latest') or the file of a past print (kind='prints'). For a timelapse its last frame is shown too: the
    finished print. Read-only on the printer."""
    _sd_kind(kind)
    with sdcard.session() as f:
        files = sdcard.listing(f, kind)
        if not files:
            raise ValueError(f"there are no {kind} files on the SD card")
        hit = files[0] if name == "latest" else next((x for x in files if x["name"] == name), None)
        if hit is None:
            close = [x["name"] for x in files if name.lower() in x["name"].lower()][:10]
            raise ValueError(f"no {kind} file named '{name}' on the SD card" + (f". Similar: {close}" if close else ""))
        path = sdcard.download(f, kind, hit["name"], os.path.join(out_dir(), "printer-files"))
    res = {"saved": path, "name": hit["name"], "mb": _mb(hit["size"]), "date": hit["date"]}
    if kind == "timelapse":
        with open(path, "rb") as fh:
            frame = sdcard.last_frame(fh.read())
        if frame:
            return [res, Image(data=frame, format="jpeg")]
    return [res]


@tool()
def delete_printer_files(kind: str, names: list[str] | None = None, older_than_days: int = 0,
                         confirm: str = "") -> dict:
    """Free space on the printer's SD card: delete timelapse videos (with their thumbnails), files of past prints
    (kind='prints') or thumbnails whose video is gone (kind='thumbnails'). Pick them by names (from printer_files)
    or all those older than older_than_days. Two steps: without confirm nothing is deleted, the answer lists what
    would go, the space freed and a code; show the list to the user and only if they agree call again with
    confirm=<code>. Deleted files cannot be recovered. Nothing is deleted while a print is running."""
    _sd_kind(kind)
    if not names and older_than_days <= 0:
        raise ValueError("say which files: names=[...] from printer_files, or older_than_days=N")
    state = printer.summarize(printer.status(max_age=5)[0]).get("state")
    if state in ("printing", "paused", "preparing"):
        raise ValueError(f"the printer is {state}: delete files when the print has finished")
    with sdcard.session() as f:
        files = sdcard.listing(f, kind)
        by_name = {x["name"]: x for x in files}
        if names:
            missing = [n for n in names if n not in by_name]
            if missing:
                raise ValueError(f"not on the SD card ({kind}): {missing}")
            chosen = [by_name[n] for n in dict.fromkeys(names)]
        else:
            limit = time.time() - older_than_days * 86400
            chosen = [x for x in files if x["t"] < limit]
        if not chosen:
            return {"kind": kind, "would_delete": [], "note": f"no {kind} files older than {older_than_days} days"}
        code = sdcard.confirm_code(kind, [x["name"] for x in chosen])
        size = sum(x["size"] for x in chosen)
        if not confirm:
            return {"kind": kind, "would_delete": [{"name": x["name"], "mb": _mb(x["size"]), "date": x["date"]}
                                                   for x in chosen],
                    "files": len(chosen), "frees_mb": _mb(size), "confirm": code,
                    "next": f"show the list to the user; only if they agree, call again with confirm='{code}'"}
        if confirm != code:
            raise ValueError("the code does not match these files (wrong code, or the files changed): call again "
                             "without confirm to get the current list and code")
        done = sdcard.delete(f, kind, [x["name"] for x in chosen])
        left = sdcard.listing(f, kind)
    return {"kind": kind, "deleted": len(done), "freed_mb": _mb(size), "left": len(left),
            "left_mb": _mb(sum(x["size"] for x in left))}


@tool()
def use_ams_filaments(ams_slots: list[int] | None = None) -> dict:
    """Set the project's filament slots from what is loaded in the AMS right now (preset and color), like
    Bambu Studio's 'sync AMS'. Default: every loaded tray in order (project slot 1 = first loaded tray).
    ams_slots: pick trays explicitly, e.g. [1, 3] -> project slot 1 = AMS slot 1, project slot 2 = AMS slot 3."""
    pr = P(True)
    rep, _ = printer.status()
    trays = {t["slot"]: t for t in printer.summarize(rep)["ams_trays"]}
    order = ams_slots or [k for k, t in sorted(trays.items()) if t.get("type")]
    if not order:
        raise ValueError("no known filament in the AMS")
    new, mapping = [], []
    for k in order:
        t = trays.get(k)
        if t and t.get("unknown"):
            raise ValueError(f"AMS slot {k} holds a spool the AMS does not know: set its type and color on the "
                             "printer, in Bambu Handy or in Bambu Studio, or use set_filament for that slot")
        if not t or not t.get("type"):
            raise ValueError(f"AMS slot {k} is empty")
        preset = printer.preset_for_tray(t.get("filament_id"), t.get("type"), pr.machine)
        new.append((preset, t.get("color") or "#FFFFFF"))
        mapping.append({"project_slot": len(new), "ams_slot": k, "preset": preset, "color": t.get("color"),
                        "loaded": t.get("name")})
    used = pr.used_filaments()
    pr.filaments = new
    pr.ams_slots = {m["project_slot"]: m["ams_slot"] for m in mapping}     # send_to_printer(via='lan') prints from these
    res = {"filaments": mapping}
    skipped = [k for k, t in sorted(trays.items()) if t.get("unknown")]
    if skipped and not ams_slots:
        res["skipped"] = f"AMS slot(s) {skipped} hold a spool the AMS does not know (type not set): left out"
    missing = [f for f in used if f > len(new)]
    if missing:
        res["warning"] = f"objects use slots {missing} that no longer exist: reassign them with set_object_filament"
    return res


# ---------------------------------------------------------------- layer actions and calibration
def _layers(pr):
    cfg = pr.config()
    lh = float(cfg.get("layer_height", "0.2"))
    fh = float(cfg.get("initial_layer_print_height", lh))
    return lh, fh


@tool()
def add_layer_action(plate: int, z: float, action: str, filament: int = 0, gcode: str = "", message: str = "") -> dict:
    """Do something when the print reaches height z (mm), before that layer is printed:
    action = pause (e.g. to insert magnets or nuts; message is shown in Bambu Studio),
    filament_change (switch to filament slot `filament` from that height on, with the AMS),
    gcode (any G-code line(s), e.g. 'M104 S210'). z is snapped to the nearest real layer at or above it."""
    pr = P(True)
    pl = pr.plate(plate)
    lh, fh = _layers(pr)
    zz = calibration.snap(z, lh, fh)
    if action == "pause":
        item = LayerGcode(zz, "pause", message=message)
    elif action == "filament_change":
        if not 1 <= filament <= len(pr.filaments):
            raise ValueError(f"filament must be a slot 1..{len(pr.filaments)}")
        item = LayerGcode(zz, "tool_change", filament=filament, color=pr.filaments[filament - 1][1])
    elif action == "gcode":
        if not gcode.strip():
            raise ValueError("gcode is empty")
        item = LayerGcode(zz, "custom", gcode=gcode)
    else:
        raise ValueError("action must be pause, filament_change or gcode")
    pl.layer_gcodes = sorted(pl.layer_gcodes + [item], key=lambda g: g.z)
    return {"plate": plate, "z_requested": z, "z": zz, "layer_actions": [g.as_dict() for g in pl.layer_gcodes]}


@tool()
def remove_layer_action(plate: int, index: int = 0) -> dict:
    """Remove a layer action (1-based index as listed by get_project), or all of them with index 0."""
    pl = P(True).plate(plate)
    if index == 0:
        pl.layer_gcodes = []
    else:
        if not 1 <= index <= len(pl.layer_gcodes):
            raise ValueError(f"index must be 1..{len(pl.layer_gcodes)}")
        pl.layer_gcodes.pop(index - 1)
    return {"plate": plate, "layer_actions": [g.as_dict() for g in pl.layer_gcodes]}


def _fil_label(pr, slot):
    """Short filament name for file names: the preset without its '@printer' part."""
    return pr.filaments[slot - 1][0].split(" @")[0]


def _calib_plate(pr, name, objs, positions=None):
    pl = pr.plates[-1]
    if pl.objects or pl.layer_gcodes:       # the last plate is in use: add one (an empty one, e.g. plate 1, is reused)
        pl = Plate(name)
        pr.plates.append(pl)
    pl.name = name
    bw, bd = pr.info["bed"]
    for i, o in enumerate(objs):
        dx, dy = positions[i] if positions else (0.0, 0.0)
        o.at = (bw / 2 + dx, bd / 2 + dy)
        o.name = pr.unique_name(o.name)
        pl.objects.append(o)
    return len(pr.plates), pl


@tool()
def make_temperature_tower(filament: int = 1, start: float = 0, end: float = 0, step: float = 5) -> dict:
    """Add a plate with a temperature tower for a filament slot: one 8 mm block per temperature (hottest at the
    bottom), each with a bridge and its temperature engraved on the front. Defaults: the filament's
    temperature +15 down to -25 °C, within its allowed range. Pick the block with the best bridge, surface and
    least stringing."""
    pr = P(True)
    if not 1 <= filament <= len(pr.filaments):
        raise ValueError(f"filament must be a slot 1..{len(pr.filaments)}")
    fl = presets.flat("filament", pr.filaments[filament - 1][0])
    nominal = float((fl.get("nozzle_temperature") or ["220"])[0])
    r_hi = float((fl.get("nozzle_temperature_range_high") or ["240"])[0])
    r_lo = float((fl.get("nozzle_temperature_range_low") or ["190"])[0])
    hi = start or min(r_hi, nominal + 15)           # default: 9 blocks around the preset temperature
    lo = end or max(r_lo, nominal - 25)
    if hi < lo:
        hi, lo = lo, hi
    temps = list(reversed(calibration.frange(lo, hi, abs(step) or 5)))[:12]
    lh, fh = _layers(pr)
    ob, actions = calibration.temperature_tower(temps, lh, fh, filament)
    n, pl = _calib_plate(pr, f"Temperature tower {temps[0]:g}-{temps[-1]:g}", [ob])
    pl.layer_gcodes = actions
    return {"plate": n, "filament": pr.filaments[filament - 1][0], "temperatures_bottom_to_top": temps,
            "block_height_mm": 8, "how_to_read": "each block is printed at the temperature engraved on it",
            "next": f"slice_project(plate={n}) and send it; then set nozzle_temperature for this filament"}


@tool()
def make_flow_test(filament: int = 1, low: float = -20, high: float = 20, step: float = 5) -> dict:
    """Add a plate of flow-rate squares for a filament slot, each printed with a different flow modifier (percent)
    engraved on top. Pass 1: -20..+20 step 5. Pass 2: around the best one, e.g. low=-4 high=4 step=1.
    Pick the square with the smoothest top surface (no gaps, no ridges)."""
    pr = P(True)
    if not 1 <= filament <= len(pr.filaments):
        raise ValueError(f"filament must be a slot 1..{len(pr.filaments)}")
    mods = calibration.frange(low, high, abs(step) or 5)[:16]
    blocks = calibration.flow_blocks(mods, filament)
    objs = [b[0] for b in blocks]
    cols = 3 if len(objs) <= 9 else 4
    n, pl = _calib_plate(pr, f"Flow test {low:+g}..{high:+g}%", objs, calibration.grid(objs, cols))
    base = float((presets.flat("filament", pr.filaments[filament - 1][0]).get("filament_flow_ratio") or ["1"])[0])
    cur = pr.overrides.get("filament_flow_ratio")
    if isinstance(cur, list) and len(cur) >= filament:
        base = float(cur[filament - 1])
    return {"plate": n, "filament": pr.filaments[filament - 1][0], "current_flow_ratio": base,
            "squares": [{"modifier_percent": m, "resulting_flow_ratio": round(base * r, 4)}
                        for m, (_, r) in zip(mods, blocks, strict=True)],
            "next": f"slice_project(plate={n}), print, pick the best square; then "
                    f"set_setting('filament_flow_ratio', <resulting value>, slot={filament}) or save_filament_preset"}


@tool()
def make_pa_tower(filament: int = 1, start: float = 0.0, end: float = 0.06, step: float = 0.004) -> dict:
    """Add a plate with a pressure advance (flow dynamics) tower: a thin square tube printed fast, the K value grows
    by `step` every millimeter. Find the height with the sharpest corners and no gaps: K = start + floor(height) * step.
    When sending it, turn off the printer's automatic flow dynamics calibration."""
    pr = P(True)
    if not 1 <= filament <= len(pr.filaments):
        raise ValueError(f"filament must be a slot 1..{len(pr.filaments)}")
    values = calibration.frange(start, end, step)[:60]
    lh, fh = _layers(pr)
    ob, actions = calibration.pa_tower(values, lh, fh, filament)
    n, pl = _calib_plate(pr, f"PA tower K {values[0]:g}-{values[-1]:g}", [ob])
    pl.layer_gcodes = actions
    return {"plate": n, "filament": pr.filaments[filament - 1][0], "height_mm": len(values),
            "k_by_height": {f"{i}-{i + 1} mm": k for i, k in enumerate(values)},
            "next": f"slice_project(plate={n}); in the send dialog untick 'Flow Dynamics Calibration'"}


@tool()
def make_vfa_test(filament: int = 1, start: float = 40, end: float = 200, step: float = 20) -> dict:
    """Add a plate with a VFA test (vertical fine artifacts: fine vertical ripples on walls that some speeds cause):
    one block per outer wall speed from start to end mm/s, the speed engraved on top. Look at the long faces with
    light from the side and pick the fastest speed without ripples for outer_wall_speed. Bambu Studio's VFA tower
    changes the speed inside one object; here each block has its own speed."""
    pr = P(True)
    if not 1 <= filament <= len(pr.filaments):
        raise ValueError(f"filament must be a slot 1..{len(pr.filaments)}")
    speeds = calibration.frange(start, end, abs(step) or 20)[:16]
    objs = calibration.vfa_blocks(speeds, filament)
    n, _ = _calib_plate(pr, f"VFA {speeds[0]:g}-{speeds[-1]:g} mm/s", objs, calibration.grid(objs, 3 if len(objs) <= 9 else 4))
    cfg = pr.config()
    try:
        q = float(cfg["filament_max_volumetric_speed"][filament - 1])
        lw = str(cfg.get("outer_wall_line_width") or "0.42")
        nozzle = float(cfg["nozzle_diameter"][0])
        lw = float(lw[:-1]) / 100 * nozzle if lw.endswith("%") else float(lw)
        lh = float(cfg["layer_height"])
        cap = q / (lw * lh)
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError):
        cap = 0
    res = {"plate": n, "filament": pr.filaments[filament - 1][0], "speeds_mm_s": speeds,
           "next": f"slice_project(plate={n}), print, look at the long faces; then "
                   "set_setting('outer_wall_speed', <fastest clean speed>) or save_process_preset"}
    if cap and speeds[-1] > cap:
        res["note"] = (f"this filament's max volumetric speed ({q:g} mm³/s) limits an outer wall of {lw:g} × {lh:g} mm "
                       f"to about {cap:.0f} mm/s: the blocks above it print at that speed")
    return res


@tool()
def save_filament_preset(slot: int, name: str, replace: bool = False) -> dict:
    """Save the filament of a slot, with this project's changes for that slot (temperatures, flow ratio, pressure
    advance, plate temperatures...), as a Bambu Studio user preset; it appears after Bambu Studio restarts.
    A new filament (made from a Generic preset, or with another filament_vendor) is saved like Bambu Studio's
    Create Filament does: its own filament id, so it can be picked for an AMS slot (Device > AMS). Changes to a
    Bambu filament are saved as a variant of it, so its RFID spools still match it.
    replace=True updates an existing user preset with that name (e.g. after a calibration): it keeps its
    filament id, so AMS slots set to it stay valid, and a backup copy is kept. Never overwrites otherwise."""
    pr = P()
    if not 1 <= slot <= len(pr.filaments):
        raise ValueError(f"slot must be 1..{len(pr.filaments)}")
    preset = pr.filaments[slot - 1][0]
    changes = {}
    for k, v in pr.overrides.items():
        if pr.key_kind(k) == "filament":
            changes[k] = v[slot - 1] if isinstance(v, list) and len(v) >= slot else v
    if replace and not changes:
        raise ValueError(f"slot {slot} has no changes to save, so '{name}' was not touched: "
                         f"set_setting(key, value, slot={slot}) first")
    values = dict(changes)
    base = presets.flat("filament", preset)
    own = presets.source("filament", preset) == "user"
    if own and not replace and presets.raw("filament", preset).get("inherits"):
        values = {**{k: (v[0] if isinstance(v, list) and v else v) for k, v in presets.raw("filament", preset).items()
                     if k not in presets.META and k != "filament_extruder_variant"}, **values}
    if not values:
        raise ValueError(f"slot {slot} has no changes to save: use set_setting(key, value, slot={slot}) first")
    vendor = (base.get("filament_vendor") or [""])[0]
    new_filament = vendor == "Generic" or values.get("filament_vendor", vendor) != vendor or (own and not base.get("inherits"))
    res = user_presets.write_filament(name, preset, values, machine=pr.machine if new_filament else None,
                                      replace=replace)
    saved = res["name"]
    res["values"] = changes
    line = presets.raw("filament", preset).get("inherits") or preset if own else preset
    res["note"] = ("it is listed for AMS slots (Device > AMS) as " f"'{saved.split(' @')[0]}'"
                   if new_filament or res.get("filament_id") else "it matches the spools of " + line)
    if any(k in changes for k in PA_KEYS):
        res["pressure_advance_note"] = PA_NOTE
    return res


def _project_values(pr, kind):
    values = {k: v for k, v in pr.overrides.items() if pr.key_kind(k) == kind}
    if not values:
        what = "wall_loops, sparse_infill_density, brim_type" if kind == "process" else "machine_start_gcode"
        raise ValueError(f"this project has no {user_presets.SHOWN[kind]} changes to save: "
                         f"use set_setting first (e.g. {what})")
    return values


@tool()
def save_process_preset(name: str, replace: bool = False) -> dict:
    """Save this project's process changes (layer height, walls, infill, speeds, brim, supports, ironing...:
    the set_setting changes that belong to the process) as a Bambu Studio user process preset, a child of the
    project's process preset, like Save as in Bambu Studio. replace=True updates your user preset with that name
    (a backup copy is kept). It appears after Bambu Studio restarts."""
    pr = P()
    return user_presets.save("process", name, pr.process, _project_values(pr, "process"), replace)


@tool()
def save_printer_preset(name: str, replace: bool = False) -> dict:
    """Save this project's printer changes (start/end G-code, retraction, printable area...: the set_setting
    changes that belong to the printer) as a Bambu Studio user printer preset, a child of the project's printer
    preset. replace=True updates your user preset with that name (a backup copy is kept). It appears after
    Bambu Studio restarts."""
    pr = P()
    return user_presets.save("machine", name, pr.machine, _project_values(pr, "machine"), replace)


@tool()
def list_user_presets(kind: str = "") -> list:
    """Your own Bambu Studio presets (kind: filament | process | printer; empty = all): the preset each one
    inherits and what it changes, whether it is in your Bambu cloud (then only Bambu Studio can delete or
    rename it), and which presets inherit it. To find system presets too, use search_presets."""
    kinds = (user_presets.kind(kind),) if kind else ("filament", "process", "machine")
    return user_presets.listing(kinds)


@tool()
def edit_preset(kind: str, name: str, values: dict) -> dict:
    """Change settings of one of your user presets directly, without a project (a backup copy is kept).
    kind: filament | process | printer. values: {"key": "value"}, e.g. {"pressure_advance": "0.025",
    "enable_pressure_advance": "1"} or {"nozzle_temperature": "215"}; a list gives one value per extruder variant
    (Standard / High Flow nozzle); null removes the key, so the value comes from the parent preset again.
    Bambu system presets are read-only: save a user preset from them first. Bambu Studio sees the change after it
    restarts, and uploads it to your Bambu cloud if the preset is there."""
    res = user_presets.edit(user_presets.kind(kind), name, values)
    if any(k in values for k in PA_KEYS):
        res["pressure_advance_note"] = PA_NOTE
    return res


@tool()
def rename_preset(kind: str, name: str, new_name: str) -> dict:
    """Rename one of your user presets (a backup copy is kept). A preset in your Bambu cloud cannot be renamed
    from here, because Bambu Studio would download the old one again: the answer says how to do it in Bambu
    Studio."""
    return user_presets.rename(user_presets.kind(kind), name, new_name)


@tool()
def delete_preset(kind: str, name: str) -> dict:
    """Delete one of your user presets (a backup copy is kept, see the answer). A preset in your Bambu cloud
    cannot be deleted from here, because Bambu Studio would download it again at its next start: only its own
    Delete removes the cloud copy, and the answer says where it is."""
    return user_presets.delete(user_presets.kind(kind), name)


# ---------------------------------------------------------------- Bambu Studio sync
@tool()
def sync_with_bambu_studio(force: bool = False) -> dict:
    """Re-read the project file after you changed it by hand in Bambu Studio and saved (same file).
    This also happens automatically on the next command when there are no unsaved changes here;
    force=True takes the app's version even if there are (they are lost)."""
    if not S.watch:
        raise ValueError("no project file to sync: save_project, open it in Bambu Studio, change it and save")
    if not _file_changed() and not force:
        return {"changed": False, "file": S.watch}
    if S.dirty and not force:
        raise ValueError("there are unsaved changes here: save_project first, or force=True to discard them")
    S.project = threemf.read(S.watch)
    S.saved = S.watch
    _watch(S.watch)
    S.dirty = False
    res = _short()
    res["reloaded_from"] = S.watch
    return res


# ---------------------------------------------------------------- mirror, lay flat, cut
_EARS_GONE = "its brim ears were removed (the side on the bed changed): add_brim_ears again"


@tool()
def mirror_object(object: str, axis: str = "x") -> dict:
    """Mirror an object across its own center (axis x, y or z)."""
    pr = P(True)
    _, o = pr.find(object)
    if axis not in ("x", "y", "z"):
        raise ValueError("axis must be x, y or z")
    lo, hi = o.bbox()
    c = (lo + hi) / 2
    painted = False
    for p in o.parts:
        v, t = geometry.mirror(p.verts - c, p.tris, axis)
        p.verts, p.tris = v + c, t
        painted = painted or bool(p.tri_attrs)
    res = {"name": o.name, "mirrored": axis, "size_mm": [round(float(v), 1) for v in o.size()]}
    if o.brim_ears and axis == "z":
        o.brim_ears = []
        res["note"] = _EARS_GONE
    elif o.brim_ears:
        k = "xy".index(axis)
        o.brim_ears = [(2 * c[0] - x, y, r) if k == 0 else (x, 2 * c[1] - y, r) for x, y, r in o.brim_ears]
    if painted:
        res["warning"] = "painted colors or seams may not follow the mirror exactly: check in Bambu Studio"
    return res


@tool()
def lay_flat(object: str, face: int = 1) -> dict:
    """Rotate an object so one of its flat faces lies on the bed: face 1 = the biggest flat face,
    2 = the second biggest, and so on."""
    pr = P(True)
    _, o = pr.find(object)
    allv = np.concatenate([p.verts for p in o.solid_parts()])
    R, area = geometry.lay_flat_matrix(allv, face)
    dropped = o.transform(lambda v: v @ R.T)
    res = {"name": o.name, "face_area_mm2": round(float(area), 1), "size_mm": [round(float(v), 1) for v in o.size()]}
    if dropped:
        res["note"] = _EARS_GONE
    if pr.out_of_bed(o):
        res["warning"] = "now (partly) outside the printable area: move_object or arrange"
    return res


def _orient_numbers(s):
    return {"support_mm2": round(s["support_mm2"]), "on_bed_mm2": round(s["on_bed_mm2"]),
            "height_mm": round(s["height_mm"], 1)}


@tool()
def orient_object(object: str, choice: int = 1, overhang_angle: float = 45.0, apply: bool = True) -> dict:
    """Turn an object the way up it prints best, like Bambu Studio's Auto orientation: least area that needs support
    (faces leaning more than overhang_angle degrees from vertical, not on the bed), enough area on the bed, low
    height. Returns the 3 best options with those numbers and the current ones; choice=2 or 3 applies another
    option, apply=False only compares. Look at preview_plate afterwards."""
    pr = P(apply)
    _, o = pr.find(object)
    solids = o.solid_parts()
    verts = np.concatenate([p.verts for p in solids])
    base = np.cumsum([0] + [len(p.verts) for p in solids[:-1]])
    tris = np.concatenate([p.tris + b for p, b in zip(solids, base, strict=True)])
    current, opts = orient.options(verts, tris, overhang_angle)
    if not 1 <= choice <= len(opts):
        raise ValueError(f"choice must be 1..{len(opts)}")
    res = {"name": o.name, "current": _orient_numbers(current),
           "options": [{"option": i + 1, **_orient_numbers(s)} for i, s in enumerate(opts)]}
    pick = opts[choice - 1]
    if np.allclose(pick["rotation"], np.eye(3), atol=1e-6):
        res["result"] = "it is already the best way up" if choice == 1 else "this option is how it is now"
        return res
    if not apply:
        res["result"] = "not applied: orient_object(..., choice=N) turns it"
        return res
    R = pick["rotation"]
    dropped = o.transform(lambda v: v @ R.T)
    res["applied"] = choice
    res["size_mm"] = [round(float(v), 1) for v in o.size()]
    if dropped:
        res["note"] = _EARS_GONE
    if pr.out_of_bed(o):
        res["warning"] = "now (partly) outside the printable area: move_object or arrange"
    return res


@tool()
def split_object(object: str, into: str = "objects") -> dict:
    """Split an object into its separate pieces, like Bambu Studio's Split: into='objects' makes one object per
    piece (each part of a multi-part object becomes an object too), into='parts' keeps one object whose parts are
    the pieces, so each can get its own filament. Pieces stay where they are; painted colors are kept, modifiers
    and negative parts go with the piece they overlap."""
    if into not in ("objects", "parts"):
        raise ValueError("into must be objects or parts")
    pr = P(True)
    pi, o = pr.find(object)
    made, notes = meshops.split(o, into)
    pl = pr.plates[pi]
    k = pl.objects.index(o)
    pl.objects.remove(o)
    by_part = into == "objects" and len([p for p in o.parts if p.subtype == "normal_part"]) > 1
    for i, ob in enumerate(made):                    # named after their part, or the object's name, numbered
        ob.name = pr.unique_name(ob.parts[0].name if by_part else (o.name if i == 0 else f"{o.name} {i + 1}"))
        pl.objects.insert(k + i, ob)
    pr.objects()
    res = {"split": o.name, "into": into,
           "result": [{"id": ob.uid, "name": ob.name, "parts": len(ob.parts),
                       "size_mm": [round(float(v), 1) for v in ob.size()]} for ob in made]}
    if into == "parts":
        res["parts"] = [p.name for p in made[0].parts]
    if notes:
        res["notes"] = notes
    return res


@tool()
def merge_objects(objects: list[str], name: str = "") -> dict:
    """Join objects of the same plate into one object with several parts, where they are now, like Bambu Studio's
    Assemble: they move and print as one (e.g. a model and its base in another color). Each part keeps its filament
    and painting; the merged object takes the first object's settings (the others' are listed if they differ)."""
    pr = P(True)
    if len(objects or []) < 2:
        raise ValueError("give at least two objects")
    found = [pr.find(r) for r in objects]
    if len({id(o) for _, o in found}) < len(found):
        raise ValueError("the same object is named twice")
    if len({pi for pi, _ in found}) > 1:
        raise ValueError("the objects are on different plates: move them onto one plate first")
    pi = found[0][0]
    objs = [o for _, o in found]
    ob, dropped = meshops.merge(objs, name or objs[0].name)
    pl = pr.plates[pi]
    k = min(pl.objects.index(o) for o in objs)
    for o in objs:
        pl.objects.remove(o)
    if name:
        ob.name = pr.unique_name(name)
    pl.objects.insert(k, ob)
    pr.objects()
    res = {"id": ob.uid, "name": ob.name, "plate": pi + 1, "parts": [p.name for p in ob.parts],
           "size_mm": [round(float(v), 1) for v in ob.size()]}
    if dropped:
        res["note"] = f"settings of the other objects that differ from the first one's were not kept: {dropped}"
    return res


@tool()
def boolean_objects(object: str, tool_object: str, operation: str = "difference", keep_tool: bool = False,
                    part: str = "") -> dict:
    """Mesh boolean between two objects where they are on the plate, like Bambu Studio's Mesh boolean.
    difference: cut tool_object's shape out of object (a hole, a slot, a lettering); intersection: keep only what
    they share; union: weld tool_object onto object (onto its part `part`, default the biggest). The result keeps
    object's name, settings and filaments; painted colors stay, new faces take the part's filament. The tool object
    is removed unless keep_tool=True. Both must be closed solids (check_object)."""
    pr = P(True)
    pi, o = pr.find(object)
    ti, t = pr.find(tool_object)
    if o is t:
        raise ValueError("object and tool_object are the same object")
    if pi != ti:
        raise ValueError("the two objects are on different plates")
    off = meshops.offset(o)
    new, volumes, shared = meshops.boolean(o, t, operation, part)
    o.parts = new
    lo, hi = o.bbox()
    c = (lo + hi) / 2
    o.at = (float(c[0] + off[0]), float(c[1] + off[1]))
    if not keep_tool:
        pr.plates[ti].objects.remove(t)
    res = {"name": o.name, "operation": operation,
           "volume_mm3": {n: {"before": round(a, 1), "after": round(b, 1)} for n, (a, b) in volumes.items()},
           "size_mm": [round(float(v), 1) for v in o.size()], "tool_object": "kept" if keep_tool else "removed"}
    if shared < 1e-3:
        res["warning"] = ("the two objects do not touch (look at preview_plate): " +
                          ("nothing was cut out" if operation == "difference" else
                           "the part is now two separate pieces"))
    notes = []
    if any(p.tri_attrs for p in o.parts):
        notes.append("painted colors are kept; the new faces take the part's filament")
    if o.brim_ears:
        notes.append("the brim ears were kept where they were: check them (add_brim_ears again if needed)")
    if notes:
        res["notes"] = notes
    return res


@tool()
def cut_object(object: str, z: float = 0, keep: str = "both", normal: list[float] | None = None,
               point: list[float] | None = None, place: str = "auto", connector: str = "none",
               shape: str = "cylinder", style: str = "prism", size: float = 0, depth: float = 0, count: int = 0,
               positions: list[list[float]] | None = None, clearance: float = 0.2) -> dict:
    """Cut an object with a plane, optionally with connectors that line the pieces up for gluing (like the
    connectors of Bambu Studio's Cut tool). keep: both | bottom | top.
    The plane is horizontal at height z (mm from the object's bottom), or goes through `point` [x, y, z] (plate mm,
    z above the bed) with `normal` [nx, ny, nz]: [1, 0, 0] cuts vertically across x, [0.5, 0, 1] is tilted.
    place: auto = the lower piece stays as it is and the upper one lies on its cut face; cut_down = both lie on their
    cut faces; keep = both as they were.
    connector: none | plug (a peg on the piece whose cut face is up, a hole with `clearance` mm per side in the
    other) | dowel (holes in both pieces and a separate pin, added to the plate) | dovetail (a tongue across the
    whole cut, along its length, and a slot in the other piece: they slide together from the side).
    shape: cylinder | square | hexagon; style: prism | frustum (tapered, centers itself); size: diameter or side in
    mm, or the dovetail's narrow width (0 = from the cut); depth: peg, pin or dovetail height (0 = automatic);
    count: 0 = one per piece of the cut (two along a long one), N = spread over the cut; positions: [[x, y], ...] or
    [[x, y, z]] in plate mm, taken on the plane (for a dovetail: a point on its middle line). Holes keep 2 mm of material from the
    edge and get shallower where a piece is thin; connectors that do not fit are listed as skipped.
    Modifiers, negative parts and painted colors are kept on the pieces."""
    pr = P(True)
    pi, o = pr.find(object)
    if keep not in ("both", "bottom", "top"):
        raise ValueError("keep must be both, bottom or top")
    lo, hi = o.bbox()
    c = (lo + hi) / 2
    off = np.array([o.at[0] - c[0], o.at[1] - c[1], -lo[2]])          # plate = vertices + off
    if point is None:
        if normal is None and not 0 < z < hi[2] - lo[2]:
            raise ValueError(f"z must be between 0 and the object height ({hi[2] - lo[2]:.1f} mm)")
        pt = np.array([c[0], c[1], lo[2] + z])
    elif len(point) == 3:
        pt = np.asarray(point, float) - off
    else:
        raise ValueError("point is [x, y, z] in plate mm")
    nrm = normal or [0.0, 0.0, 1.0]
    parts, notes, tracked = [], [], {}
    for p in o.parts:
        if p.tri_attrs:                                  # painted: its triangles are followed through the cut
            m, tracked[id(p)] = paint.tracked(p.verts, p.tris)
        else:
            m = geometry.to_manifold(p.verts, p.tris)
        if m.status() != geometry.m3.Error.NoError or m.is_empty():
            if p.subtype == "normal_part":
                raise ValueError(f"part '{p.name}' is not a closed solid (see check_object): it cannot be cut")
            notes.append(f"'{p.name}' ({p.subtype}) is not a closed solid and was dropped")
            continue
        parts.append((m, p, p.subtype == "normal_part"))
    pos = None
    if positions:
        _, p0, n = cutting.frame(pt, nrm)
        pos = []
        for q in positions:
            if len(q) == 2:
                if abs(n[2]) < 0.1:
                    raise ValueError("on a vertical plane give positions as [x, y, z]")
                x, y = q[0] - off[0], q[1] - off[1]
                q3 = np.array([x, y, p0[2] - (n[0] * (x - p0[0]) + n[1] * (y - p0[1])) / n[2]])
            elif len(q) == 3:
                q3 = np.asarray(q, float) - off
            else:
                raise ValueError("each position is [x, y] or [x, y, z] in plate mm")
            pos.append(q3 - np.dot(q3 - p0, n) * n)
    res = cutting.cut(parts, pt, nrm, connector=connector, shape=shape, style=style, size=size, depth=depth,
                      count=count, positions=pos, clearance=clearance, place=place)
    settings = {k: v for k, v in o.settings.items() if not (k == "brim_type" and v == "brim_ears")}

    def build(items, label):
        new = []
        for m, p in items:
            if m.is_empty():
                continue
            if id(p) in tracked:
                v, t, attrs = paint.carry(m, tracked[id(p)], p.verts, p.tris, p.tri_attrs)
            else:
                (v, t), attrs = geometry.from_manifold(m), {}
            new.append(Part(p.name, v, t, p.filament, p.subtype, tri_attrs=attrs, meta=dict(p.meta)))
        if not any(q.subtype == "normal_part" for q in new):
            return None
        return Obj(pr.unique_name(f"{o.name} {label}"), new, settings=dict(settings))

    pr.plates[pi].objects.remove(o)
    made, names = [], {}
    if keep in ("both", "bottom"):
        a = build(res["A"], "bottom")
        if a:
            names["A"] = a.name
            if place == "cut_down":
                made.append(_place(pr, pi + 1, a, None, None))
            else:                                        # kept as it was: it stays where it was
                alo, ahi = a.bbox()
                made.append(_place(pr, pi + 1, a, (alo[0] + ahi[0]) / 2 + off[0], (alo[1] + ahi[1]) / 2 + off[1]))
    if keep in ("both", "top"):
        b = build(res["B"], "top")
        if b:
            names["B"] = b.name
            made.append(_place(pr, pi + 1, b, None, None))
    out = {"cut": o.name, "plane": {"point": [round(float(v), 2) for v in pt + off], "normal": res["normal"]},
           "pieces": made}
    if connector != "none":
        info = {"type": connector, "shape": shape, "style": style, "size_mm": res.get("size"),
                "clearance_mm": clearance,
                "placed": [{"at": [round(float(v), 1) for v in np.asarray(k["at"]) + off], "depth_mm": k["depth"],
                            **({"along": k["along"]} if "along" in k else {})} for k in res["connectors"]]}
        if res.get("male"):
            info["peg_on"] = names.get(res["male"], "a piece not kept")
        out["connectors"] = info
        if res["pins"] is not None:
            v, t = geometry.from_manifold(res["pins"])
            pins = Obj(pr.unique_name(f"{o.name} pins"), [Part("pins", v, t, o.solid_parts()[0].filament)])
            out["pins"] = _place(pr, pi + 1, pins, None, None)
        if res["skipped"]:
            out["skipped"] = [{**k, "at": [round(float(v), 1) for v in np.asarray(k["at"]) + off]} if "at" in k else k
                              for k in res["skipped"]]
    if tracked:
        notes.append("painted colors, seams and supports are kept; a triangle split by the cut takes the color "
                     "covering most of it, and the new faces (cut, holes, pegs) take the part's filament")
    if o.brim_ears:
        notes.append("the brim ears were not kept on the pieces: add_brim_ears on them if needed")
    if notes:
        out["notes"] = notes
    return out


# ---------------------------------------------------------------- modifiers
SUBTYPES = {"modifier": "modifier_part", "negative": "negative_part", "support_blocker": "support_blocker",
            "support_enforcer": "support_enforcer"}


@tool()
def set_part_type(object: str, part: str, type: str) -> dict:
    """Change what a part of an object is, like Bambu Studio's Change type: 'part' (printed), 'modifier' (its
    settings apply inside it), 'negative' (cut out, a hole), 'support_blocker' or 'support_enforcer'. An object
    keeps at least one printed part."""
    pr = P(True)
    _, o = pr.find(object)
    hits = [p for p in o.parts if p.name.lower() == part.lower()]
    if not hits:
        raise ValueError(f"'{o.name}' has no part named '{part}': {[p.name for p in o.parts]}")
    sub = "normal_part" if type == "part" else SUBTYPES.get(type)
    if not sub:
        raise ValueError(f"type must be part, {', '.join(SUBTYPES)}")
    p = hits[0]
    if p.subtype == "normal_part" and sub != "normal_part" and \
            sum(q.subtype == "normal_part" for q in o.parts) == 1:
        raise ValueError(f"'{p.name}' is the only printed part of '{o.name}': it must stay a part")
    before = p.subtype
    off = meshops.offset(o)
    p.subtype = sub
    lo, hi = o.bbox()                                 # the printed parts decide where the object is
    c = (lo + hi) / 2
    o.at = (float(c[0] + off[0]), float(c[1] + off[1]))
    return {"name": o.name, "part": p.name, "was": before, "now": sub,
            "parts": [{"name": q.name, "type": q.subtype} for q in o.parts]}


@tool()
def add_modifier(object: str, settings: dict[str, str] | None = None, kind: str = "modifier", z_from: float = 0,
                 z_to: float = 0, region: list[float] | None = None, shape: str = "box") -> dict:
    """Add a part to an object, covering its whole footprint between z_from and z_to (mm from the
    object's bottom; z_to 0 = top), or only region [x0, y0, x1, y1] (mm from the object's center).
    kind: modifier (different settings inside, e.g. {"sparse_infill_density": "100%"} for the top 5 mm),
    negative (removes material), support_blocker, support_enforcer.
    shape: box, or cylinder (round, as wide as the smaller side of the region: e.g. a hole for a magnet or a
    screw is kind='negative', shape='cylinder', region=[-4, -4, 4, 4] for 8 mm)."""
    pr = P(True)
    _, o = pr.find(object)
    if kind not in SUBTYPES:
        raise ValueError(f"kind must be one of {sorted(SUBTYPES)}")
    settings = settings or {}
    if kind == "modifier" and not settings:
        raise ValueError("a modifier needs settings, e.g. {'sparse_infill_density': '100%'}")
    for k in settings:
        if pr.key_kind(k) not in ("process", None):
            raise ValueError(f"'{k}' is a {pr.key_kind(k)} setting and cannot change inside a modifier")
    lo, hi = o.bbox()
    c = (lo + hi) / 2
    h = hi[2] - lo[2]
    z1 = z_to if z_to > 0 else h
    if not 0 <= z_from < z1:
        raise ValueError("z_from must be below z_to")
    if region:
        x0, y0, x1, y1 = (float(x) for x in region)
        x0, x1, y0, y1 = c[0] + x0, c[0] + x1, c[1] + y0, c[1] + y1
    else:
        x0, y0, x1, y1 = lo[0] - 1, lo[1] - 1, hi[0] + 1, hi[1] + 1
    height = (z1 - z_from) + (0.02 if z1 >= h else 0)
    if shape == "cylinder":
        d = min(x1 - x0, y1 - y0)
        v, t = geometry.cylinder(d, height)
    elif shape == "box":
        v, t = geometry.box(x1 - x0, y1 - y0, height)
    else:
        raise ValueError("shape must be box or cylinder")
    v = v + np.array([(x0 + x1) / 2, (y0 + y1) / 2, lo[2] + z_from])
    name = f"{kind.replace('_', ' ').capitalize()} {z_from:g}-{z1:g} mm" + (f" Ø{d:g}" if shape == "cylinder" else "")
    o.parts.append(Part(name, v, t, o.solid_parts()[0].filament, SUBTYPES[kind], meta=dict(settings)))
    return {"name": o.name, "added": name, "parts": [{"name": p.name, "type": p.subtype, **({"settings": p.meta} if p.meta else {})}
                                                     for p in o.parts]}


@tool()
def remove_part(object: str, part: str) -> dict:
    """Remove a part (e.g. a modifier) from an object, by part name. The last solid part cannot be removed."""
    pr = P(True)
    _, o = pr.find(object)
    hits = [p for p in o.parts if p.name.lower() == part.lower()]
    if not hits:
        raise ValueError(f"no part '{part}' in {o.name}: {[p.name for p in o.parts]}")
    rest = [p for p in o.parts if p is not hits[0]]
    if not any(p.subtype == "normal_part" for p in rest):
        raise ValueError("that is the last solid part: use delete_object instead")
    o.parts = rest
    return {"name": o.name, "parts": [{"name": p.name, "type": p.subtype} for p in o.parts]}


# ---------------------------------------------------------------- brim ears
def _first_layer(pr, o):
    """Islands of the object's first layer, in the frame of its vertices, and the offset from that frame to the
    plate (plate = frame + offset)."""
    cfg = pr.config()
    try:
        z = float(cfg.get("initial_layer_print_height") or 0.2) / 2
    except ValueError:
        z = 0.1
    lo, hi = o.bbox()
    off = (float(o.at[0] - (lo[0] + hi[0]) / 2), float(o.at[1] - (lo[1] + hi[1]) / 2))
    return brim.first_layer([(p.verts, p.tris) for p in o.solid_parts()], z), off


def _ear_radius(pr):
    """Bambu Studio's default ear: 16 first-layer line widths across (a width can be a % of the nozzle)."""
    cfg = pr.config()
    lw = str(cfg.get("initial_layer_line_width") or "0.5")
    nozzle = cfg.get("nozzle_diameter") or ["0.4"]
    try:
        w = float(lw[:-1]) / 100 * float(nozzle[0]) if lw.endswith("%") else float(lw)
    except ValueError:
        w = 0.5
    return round(8 * w, 1)


@tool()
def add_brim_ears(object: str, points: list[list[float]] | None = None, radius: float = 0, narrow: float = 3.0,
                  small: float = 0, clearance: float = 0.6, keep: bool = False) -> dict:
    """Brim ears: small round brims only where a part needs them, instead of a brim all around (Bambu Studio's
    Painted brim). Meant for print-in-place and articulated models: a full brim fills the joint gaps on the first
    layer and welds them. Without points, ears go to the tips of the thin parts of the first layer (fingers, toes,
    any tip thinner than `narrow` mm), each as large as possible up to `radius` without reaching another piece, a
    gap or hole, or a second thin part (those tips are listed as skipped, with the reason). small > 0 also gives
    ears to first-layer pieces smaller than that (mm²), at their ends. points: [[x, y], ...] or [[x, y, radius]]
    in plate mm, placed as given, with a warning when one would weld something. radius 0 = Bambu Studio's default
    (16 first-layer line widths across). keep: add to the ears the object already has.
    Look at them with preview_plate(view='top', zoom=True), then slice_project and preview_layer(layer=1)."""
    pr = P(True)
    _, o = pr.find(object)
    islands, off = _first_layer(pr, o)
    if not islands:
        raise ValueError(f"{o.name} has nothing on the bed to put ears on")
    r0 = radius or _ear_radius(pr)
    ears, skipped, warnings = [], [], []
    if points:
        for pt in points:
            if len(pt) not in (2, 3):
                raise ValueError("each point is [x, y] or [x, y, radius] in plate mm")
            x, y = pt[0] - off[0], pt[1] - off[1]
            r = float(pt[2]) if len(pt) == 3 else r0
            why = brim.check(islands, brim.island_of(islands, x, y), x, y, r, clearance)
            if why:
                warnings.append(f"ear at ({pt[0]:g}, {pt[1]:g}): {why}")
            ears.append((float(x), float(y), r))
    else:
        ears, skipped = brim.auto_ears(islands, r0, narrow=narrow, small=small, clearance=clearance)
    o.brim_ears = (o.brim_ears if keep else []) + ears
    if o.brim_ears:
        o.settings["brim_type"] = "brim_ears"
    res = {"name": o.name, "brim_type": o.settings.get("brim_type"),
           "ears": [{"x": round(x + off[0], 1), "y": round(y + off[1], 1), "radius": r} for x, y, r in o.brim_ears],
           "first_layer": {"pieces": len(islands)}}
    gap = brim.gaps(islands)
    if gap is not None:
        res["first_layer"]["smallest_gap_mm"] = round(gap, 2)
    if skipped:
        res["skipped"] = [{"x": round(x + off[0], 1), "y": round(y + off[1], 1), "why": why} for x, y, why in skipped]
    if warnings:
        res["warnings"] = warnings
    if not o.brim_ears:
        res["note"] = ("no tip needs an ear here: try a larger `narrow`, `small` for little pieces, or give points"
                       if not skipped else "every tip was too close to something: give points, or a smaller clearance")
    res["next"] = "preview_plate(view='top', zoom=True); slice_project, then preview_layer(layer=1)"
    return res


@tool()
def remove_brim_ears(object: str) -> dict:
    """Remove an object's brim ears; its brim goes back to the project's brim type."""
    pr = P(True)
    _, o = pr.find(object)
    n = len(o.brim_ears)
    o.brim_ears = []
    if o.settings.get("brim_type") == "brim_ears":
        del o.settings["brim_type"]
    return {"name": o.name, "removed": n, "brim_type": o.settings.get("brim_type") or pr.config().get("brim_type")}


def _range_value(pr, key, v):
    if key == "extruder":
        f = int(v)
        if not 0 <= f <= len(pr.filaments):
            raise ValueError(f"filament must be a slot 1..{len(pr.filaments)} (0 = the object's)")
        return str(f)
    if pr.key_kind(key) not in ("process", None):
        raise ValueError(f"'{key}' is a {pr.key_kind(key)} setting: it cannot change by height")
    return str(v)


@tool()
def set_height_range(object: str, z_from: float, z_to: float, settings: dict) -> dict:
    """Settings for a height band of an object, like Bambu Studio's Height range modifier. Heights are mm from the
    object's bottom. E.g. z_from=0, z_to=5, settings={"sparse_infill_density": "100%"}; {"layer_height": "0.12"}
    for finer layers there (variable layer height); {"filament": 2} to print that band with another filament slot
    (a color band). A band with the same z_from and z_to is updated (null removes a key); bands cannot overlap."""
    pr = P(True)
    _, o = pr.find(object)
    h = float(o.size()[2])
    if not 0 <= z_from < z_to or z_from >= h:
        raise ValueError(f"the band must be inside the object: 0 <= z_from < z_to, z_from below {h:.2f} mm")
    z_to = min(float(z_to), h)
    same = next((r for r in o.height_ranges if abs(r["from"] - z_from) < 1e-6 and abs(r["to"] - z_to) < 1e-6), None)
    for r in o.height_ranges:
        if r is not same and r["from"] < z_to - 1e-6 and z_from < r["to"] - 1e-6:
            raise ValueError(f"it overlaps the band {r['from']:g}-{r['to']:g} mm: change that one or remove it")
    cur = dict(same["settings"]) if same else {}
    for k, v in (settings or {}).items():
        key = "extruder" if k == "filament" else k
        if v is None:
            cur.pop(key, None)
        else:
            cur[key] = _range_value(pr, key, v)
    if same:
        same["settings"] = cur
    else:
        o.height_ranges.append({"from": float(z_from), "to": z_to, "settings": cur})
        o.height_ranges.sort(key=lambda r: r["from"])
    o.height_ranges = [r for r in o.height_ranges if r["settings"]]
    return {"name": o.name, "height_mm": round(h, 2), "height_ranges": _ranges_view(o)}


def _ranges_view(o):
    return [{"from": r["from"], "to": r["to"],
             "settings": {("filament" if k == "extruder" else k): v for k, v in r["settings"].items()}}
            for r in o.height_ranges]


@tool()
def remove_height_range(object: str, z_from: float = -1) -> dict:
    """Remove the height band of an object that starts at z_from (mm), or all its bands (z_from=-1)."""
    pr = P(True)
    _, o = pr.find(object)
    before = len(o.height_ranges)
    o.height_ranges = [] if z_from < 0 else [r for r in o.height_ranges if abs(r["from"] - z_from) > 1e-6]
    if len(o.height_ranges) == before:
        raise ValueError(f"'{o.name}' has no band starting at {z_from:g} mm: {_ranges_view(o)}")
    return {"name": o.name, "removed": before - len(o.height_ranges), "height_ranges": _ranges_view(o)}


@tool()
def paint_object(object: str, paint: str, filament: int = 0, z_from: float = 0, z_to: float = 0,
                 facing: str = "all", angle: float = 45.0, clear: bool = False, part: str = "") -> dict:
    """Paint a region of an object, like Bambu Studio's painting tools. paint: 'color' (with filament=N),
    'support' (supports there), 'block_support' (none there), 'seam' (put the seam there), 'block_seam',
    'fuzzy_skin'. Region: the height band z_from..z_to (mm from the object's bottom; z_to=0 = to the top) and the
    faces looking 'top', 'bottom', 'sides', 'front', 'back', 'left', 'right', 'overhangs' (leaning more than `angle`
    degrees from vertical, for supports) or 'all'. clear=True removes that painting there. Triangles crossing a
    band's edge are split, so the edge is sharp. part: only that part. Look at preview_plate (colors) afterwards."""
    pr = P(True)
    _, o = pr.find(object)
    if paint not in painting.ATTR:
        raise ValueError(f"paint must be one of {', '.join(painting.ATTR)}")
    if facing not in painting.FACING:
        raise ValueError(f"facing must be one of {', '.join(painting.FACING)}")
    if paint == "color" and not clear and not 1 <= filament <= len(pr.filaments):
        raise ValueError(f"give the filament slot to paint with: filament=1..{len(pr.filaments)}")
    state = 0 if clear else (filament if paint == "color" else painting.STATE[paint])
    lo, hi = o.bbox()
    z_lo = lo[2] + z_from if z_from > 0 else None
    z_hi = lo[2] + z_to if z_to > 0 else None
    if z_lo is not None and z_hi is not None and z_hi <= z_lo:
        raise ValueError("z_to must be above z_from")
    targets = [p for p in o.solid_parts() if p.subtype == "normal_part" and (not part or p.name.lower() == part.lower())]
    if not targets:
        raise ValueError(f"'{o.name}' has no solid part named '{part}': {[p.name for p in o.solid_parts()]}")
    done = {p.name: painting.apply(p, paint, state, z_lo, z_hi, facing, angle, bed_z=lo[2]) for p in targets}
    res = {"name": o.name, "paint": paint, "cleared" if clear else "painted_triangles": done}
    if not sum(done.values()):
        res["warning"] = "no triangle is in that region: check the heights and the facing"
    notes = []
    if paint in ("support", "block_support") and not clear:
        if o.settings.get("enable_support", pr.config().get("enable_support")) != "1":
            notes.append("supports are off for this object: Bambu Studio prints painted supports only with "
                         "set_setting('enable_support', '1') (or set_object_setting)")
        if paint == "support":
            notes.append("with support_type 'normal(manual)' or 'tree(manual)' supports go only where painted; "
                         "the (auto) types add them wherever they are needed too")
    if paint == "color" and not clear and filament not in o.filaments():
        notes.append(f"this object now also prints with filament {filament}: a prime tower is added")
    if notes:
        res["notes"] = notes
    return res


# ---------------------------------------------------------------- standalone test prints
def _standalone(name, slot, objs, overrides, positions=None):
    """A separate one-plate project for tests that change project-wide settings (the open project is not touched)."""
    base = S.project
    if base is None:
        raise ValueError("open or create a project first: the test uses its printer and filament")
    if not 1 <= slot <= len(base.filaments):
        raise ValueError(f"filament must be a slot 1..{len(base.filaments)}")
    fil = base.filaments[slot - 1]
    t = Project(name, base.machine, base.process, [fil])
    for k, v in base.overrides.items():              # keep this slot's filament tweaks (e.g. plate temperature)
        if t.key_kind(k) == "filament" and isinstance(v, list) and len(v) >= slot:
            t.overrides[k] = [v[slot - 1]]
    t.overrides.update(overrides)
    bw, bd = t.info["bed"]
    for i, o in enumerate(objs):
        dx, dy = positions[i] if positions else (0.0, 0.0)
        o.at = (bw / 2 + dx, bd / 2 + dy)
        o.name = t.unique_name(o.name)
        t.plates[0].objects.append(o)
    path = next_free_path(os.path.join(out_dir(), f"{name}.3mf"))
    threemf.write(t, path)
    sliced = next_free_path(path.replace(".3mf", "-sliced.3mf"))
    stats = slicer.slice_3mf(path, sliced)[0]
    return {"file": path, "sliced_file": sliced, "minutes": stats["minutes"], "grams": stats["grams"],
            "warnings": stats["warnings"]}


@tool()
def make_max_flow_test(filament: int = 1, low: float = 0, high: float = 0, step: float = 2) -> dict:
    """Max volumetric speed test for a filament slot, as a separate project file (the open project is not changed):
    single-wall cylinders, each printed at the wall speed that gives the volumetric speed Q (mm³/s) on its tag.
    Default range: around the filament's current limit. The highest Q without gaps or weak walls is the max;
    use a bit less (about 90%) as filament_max_volumetric_speed."""
    pr = P()
    if not 1 <= filament <= len(pr.filaments):
        raise ValueError(f"filament must be a slot 1..{len(pr.filaments)}")
    fl = presets.flat("filament", pr.filaments[filament - 1][0])
    cur = float((fl.get("filament_max_volumetric_speed") or ["15"])[0])
    lo_q = low or max(4.0, round(cur * 0.6))
    hi_q = high or round(cur * 1.5)
    qs = calibration.frange(lo_q, hi_q, abs(step) or 2)[:12]
    cfg = pr.config()
    lw = float(str(cfg.get("outer_wall_line_width", "0.42")).rstrip("%") or 0.42)
    lh = float(cfg.get("layer_height", "0.2"))
    items = calibration.flow_speed_cylinders(qs, lw, lh)
    objs, pos = [], []
    cols = 3 if len(items) <= 9 else 4
    for i, (cyl, tag, _speed) in enumerate(items):
        r, c = divmod(i, cols)
        x = (c - (cols - 1) / 2) * 40
        y = (((len(items) - 1) // cols) / 2 - r) * 48
        objs += [cyl, tag]
        pos += [(x, y + 5), (x, y - 21)]
    over = {"filament_max_volumetric_speed": [f"{max(qs) + 5:g}"], "slow_down_for_layer_cooling": ["0"]}
    res = _standalone(f"{pr.name} max flow test - {_fil_label(pr, filament)}", filament, objs, over, pos)
    res.update({"filament": pr.filaments[filament - 1][0], "current_limit_mm3_s": cur,
                "cylinders": [{"Q_mm3_s": q, "wall_speed_mm_s": round(sp)} for q, (_, _, sp) in zip(qs, items, strict=True)],
                "next": "it is a separate project: to print it, open_project(file) then send_to_printer (the open "
                        "project here is replaced, save it first if needed); keep the last cylinder with clean walls"})
    return res


@tool()
def make_retraction_test(filament: int = 1, lengths: list[float] | None = None) -> dict:
    """Stringing test for a filament slot: one small separate project per retraction length (Bambu printers cannot
    change retraction during a print). Print them one after the other and keep the shortest length without strings
    between the two pillars; then set_setting('filament_retraction_length', value, slot) or save_filament_preset."""
    pr = P()
    if not 1 <= filament <= len(pr.filaments):
        raise ValueError(f"filament must be a slot 1..{len(pr.filaments)}")
    lengths = lengths or [0.4, 0.6, 0.8, 1.0, 1.2]
    files = []
    for L in lengths[:8]:
        ob = calibration.stringing_test()
        r = _standalone(f"{pr.name} retraction {L:g}mm - {_fil_label(pr, filament)}", filament, [ob],
                        {"filament_retraction_length": [f"{L:g}"]})
        files.append({"retraction_mm": L, **r})
    return {"filament": pr.filaments[filament - 1][0], "tests": files,
            "next": "separate projects: to print one, open_project(file) then send_to_printer (the open project here "
                    "is replaced, save it first if needed)"}


def main():
    mcp.run()


if __name__ == "__main__":
    main()
