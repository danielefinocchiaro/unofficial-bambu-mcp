"""unofficial-bambu-mcp: build, edit, slice and preview Bambu Studio projects from an AI assistant.

Unofficial community project, not affiliated with or endorsed by Bambu Lab.
"""
import functools
import os
import zipfile

import numpy as np
from mcp.server.mcpserver import Image, MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from . import calibration, geometry, presets, preview, printer, slicer, studio, threemf
from .project import LayerGcode, Obj, Part, Plate, Project, next_free_path

INSTRUCTIONS = """Work on Bambu Studio projects (.3mf) for Bambu Lab printers. Typical flow:
new_project or open_project -> import_model / add_shape -> move/arrange -> set_filament / set_setting ->
preview_plate (look at it) -> save_project -> slice_project -> preview_layer -> send_to_printer.
Coordinates are millimeters on the plate, origin at the front-left corner, objects are placed by the center
of their footprint and always sit on the bed. Plates and filament slots are numbered from 1.
Files are never overwritten: saving picks a new name if the file exists. Opened files are read as a copy.
Always look at preview_plate after changing the layout, and report slicing warnings to the user.
send_to_printer never starts a print: it opens an official Bambu app where the user presses Print/Send."""

mcp = MCPServer("unofficial-bambu-mcp", instructions=INSTRUCTIONS, version="0.1.0")


def tool():
    """mcp.tool() that lets the model read why a call failed. The SDK shows the text of a ToolError only, and
    our errors say what to do next (wrong slot, printer refused, preset not found...)."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            try:
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
        out.append(_place(pr, plate, o, x if len(objs) == 1 else None, y if len(objs) == 1 else None))
    return out


@tool()
def add_shape(shape: str, plate: int = 1, x: float | None = None, y: float | None = None, filament: int = 1,
              name: str = "", width: float = 20, depth: float = 20, height: float = 20, diameter: float = 20,
              diameter_top: float = 0, text: str = "", text_height: float = 10, font: str = "",
              base: float = 0, base_filament: int = 0) -> dict:
    """Create a simple solid: box (width, depth, height), cylinder (diameter, height), cone (diameter,
    diameter_top, height), sphere (diameter), text (text, text_height = capital letters in mm, height = depth
    of the letters; base > 0 puts the text on a plate that thick, as a separate part 'Base' with filament
    base_filament (0 = same as the text), e.g. white letters on a black tag; font = path to a .ttf/.otf)."""
    pr = P(True)
    for f in (filament, base_filament or filament):
        if not 1 <= f <= len(pr.filaments):
            raise ValueError(f"filament slot must be 1..{len(pr.filaments)} (add slots with set_filament)")
    shape = shape.lower().strip()
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
    if f != 1.0:
        o.transform(lambda v: geometry.scale(v, f))
    for ang, ax in ((rotate_x, "x"), (rotate_y, "y"), (rotate_z, "z")):
        if ang:
            o.transform(lambda v, a=ang, axis=ax: geometry.rotate(v, a, axis))
    res = {"name": o.name, "size_mm": [round(float(v), 1) for v in o.size()]}
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


@tool()
def arrange(plate: int = 0, gap: float = 6.0) -> dict:
    """Re-place the objects of a plate (0 = all plates) close to the center without overlaps.
    Objects that do not fit are moved to a new plate."""
    pr = P(True)
    moved = pr.arrange([plate] if plate else None, gap)
    res = _short()
    if moved:
        res["moved_to_new_plate"] = [o.name for o in moved]
    return res


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
    return {"key": key, "kind": kind, "value": cfg.get(key), "overridden": key in pr.overrides}


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
    cur = cfg[key]
    kind = pr.key_kind(key)
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
    filament changes, layers and warnings. The sliced project is saved next to the project file."""
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
    for st in stats:
        st["plate"] = numbers[st["plate"] - 1]
    S.sliced = out
    S.sliced_plates = {n: k + 1 for k, n in enumerate(numbers)}
    res = {"sliced_file": out, "plates": stats}
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
def send_to_printer(plate: int = 1, via: str = "auto") -> dict:
    """Prepare the print file of one plate (.gcode.3mf) and hand it to an official Bambu app, where the user
    checks printer and AMS mapping and presses Print/Send. Nothing starts printing by itself.
    via: auto (Bambu Connect if installed, otherwise Bambu Studio) | bambu_connect | bambu_studio | file (only export).
    Tell the user what to press, and the time, weight and filaments of the plate."""
    pr = P()
    pl = pr.plate(plate)
    if not pl.objects:
        raise ValueError(f"plate {plate} is empty")
    if via not in ("auto", "bambu_connect", "bambu_studio", "file"):
        raise ValueError("via must be auto, bambu_connect, bambu_studio or file")
    used = sorted({f for o in pl.objects for f in o.filaments()})
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
    if target == "bambu_connect":
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
def printer_status() -> dict:
    """Read-only status of the printer on the local network: state, job, progress, remaining time, layer
    (or the last job's result when idle), temperatures, AMS trays (type, color, remaining %; 'unknown' = a spool
    the AMS has not been told about), AMS humidity and temperature, active slot, errors, objects skipped during the
    print, and warnings (the spool being fed is unknown or not the project's filament, sport speed on a long print).
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
    warnings = printer.advice(out, expected)
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
def save_filament_preset(slot: int, name: str, replace: bool = False) -> dict:
    """Save the filament of a slot, with this project's changes for that slot (temperatures, flow ratio, plate
    temperatures...), as a Bambu Studio user preset; it appears after Bambu Studio restarts.
    A new filament (made from a Generic preset, or with another filament_vendor) is saved like Bambu Studio's
    Create Filament does: its own filament id, so it can be picked for an AMS slot (Device > AMS). Changes to a
    Bambu filament are saved as a variant of it, so its RFID spools still match it.
    replace=True updates an existing user preset with that name (e.g. after a calibration): it keeps its
    filament id, so AMS slots set to it stay valid, and a backup copy is kept. Never overwrites otherwise."""
    pr = P()
    if not 1 <= slot <= len(pr.filaments):
        raise ValueError(f"slot must be 1..{len(pr.filaments)}")
    preset = pr.filaments[slot - 1][0]
    values = {}
    fkeys = set(presets.settings("filament", preset))
    for k, v in pr.overrides.items():
        if k in fkeys:
            values[k] = v[slot - 1] if isinstance(v, list) and len(v) >= slot else v
    base = presets.flat("filament", preset)
    own = presets.source("filament", preset) == "user"
    if own and not replace and presets.raw("filament", preset).get("inherits"):
        values = {**{k: (v[0] if isinstance(v, list) and v else v) for k, v in presets.raw("filament", preset).items()
                     if k not in presets.META and k != "filament_extruder_variant"}, **values}
    if not values and not replace:
        raise ValueError("this slot has no changes to save: use set_setting(..., slot=N) first")
    vendor = (base.get("filament_vendor") or [""])[0]
    new_filament = vendor == "Generic" or values.get("filament_vendor", vendor) != vendor or (own and not base.get("inherits"))
    path, saved, fid = presets.write_user_filament(name, preset, values, machine=pr.machine if new_filament else None,
                                                   replace=replace)
    res = {"saved": path, "name": saved, "values": values}
    if fid:
        res["filament_id"] = fid
    res["note"] = ("restart Bambu Studio to see it" + ("; it is listed for AMS slots (Device > AMS) as "
                   f"'{saved.split(' @')[0]}'" if new_filament or fid else "; it matches the spools of " + preset))
    return res


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
    o.transform(lambda v: v @ R.T)
    res = {"name": o.name, "face_area_mm2": round(float(area), 1), "size_mm": [round(float(v), 1) for v in o.size()]}
    if pr.out_of_bed(o):
        res["warning"] = "now (partly) outside the printable area: move_object or arrange"
    return res


@tool()
def cut_object(object: str, z: float, keep: str = "both", flip_top: bool = True) -> dict:
    """Cut an object horizontally at height z (mm from its bottom). keep: both | bottom | top. With flip_top the top
    piece is turned upside down so it prints on the flat cut face. Modifiers and painted colors are not kept."""
    pr = P(True)
    pi, o = pr.find(object)
    lo, hi = o.bbox()
    if not 0 < z < hi[2] - lo[2]:
        raise ValueError(f"z must be between 0 and the object height ({hi[2] - lo[2]:.1f} mm)")
    below, above = [], []
    for p in o.solid_parts():
        b, a = geometry.split_z(p.verts, p.tris, lo[2] + z)
        if b:
            below.append(Part(p.name, b[0], b[1], p.filament))
        if a:
            above.append(Part(p.name, a[0], a[1], p.filament))
    pl = pr.plates[pi]
    pl.objects.remove(o)
    made = []
    if keep in ("both", "bottom") and below:
        ob = Obj(pr.unique_name(f"{o.name} bottom"), below, settings=dict(o.settings))
        made.append(_place(pr, pi + 1, ob, o.at[0], o.at[1]))
    if keep in ("both", "top") and above:
        ot = Obj(pr.unique_name(f"{o.name} top"), above, settings=dict(o.settings))
        if flip_top:
            ot.transform(lambda v: geometry.rotate(v, 180, "x"))
        made.append(_place(pr, pi + 1, ot, None if keep == "both" else o.at[0], None if keep == "both" else o.at[1]))
    return {"cut": o.name, "at_z": z, "pieces": made}


# ---------------------------------------------------------------- modifiers
SUBTYPES = {"modifier": "modifier_part", "negative": "negative_part", "support_blocker": "support_blocker",
            "support_enforcer": "support_enforcer"}


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
