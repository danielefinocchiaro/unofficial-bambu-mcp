"""unofficial-bambu-mcp: build, edit, slice and preview Bambu Studio projects from an AI assistant.

Unofficial community project, not affiliated with or endorsed by Bambu Lab.
"""
import os

from mcp.server.mcpserver import Image, MCPServer

from . import geometry, presets, preview, slicer, studio, threemf
from .project import Obj, Part, Plate, Project, next_free_path

INSTRUCTIONS = """Work on Bambu Studio projects (.3mf) for Bambu Lab printers. Typical flow:
new_project or open_project -> import_model / add_shape -> move/arrange -> set_filament / set_setting ->
preview_plate (look at it) -> save_project -> slice_project -> preview_layer -> open_in_bambu_studio.
Coordinates are millimeters on the plate, origin at the front-left corner, objects are placed by the center
of their footprint and always sit on the bed. Plates and filament slots are numbered from 1.
Files are never overwritten: saving picks a new name if the file exists. Opened files are read as a copy.
Always look at preview_plate after changing the layout, and report slicing warnings to the user."""

mcp = MCPServer("unofficial-bambu-mcp", instructions=INSTRUCTIONS, version="0.1.0")


class Session:
    project = None
    saved = None
    sliced = None


S = Session()


def out_dir():
    d = os.path.abspath(os.path.expanduser(os.environ.get("UBMCP_DIR", "~/Documents/unofficial-bambu-mcp")))
    os.makedirs(d, exist_ok=True)
    return d


def P():
    if S.project is None:
        raise ValueError("no project open: call new_project or open_project first")
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
    return p


# ---------------------------------------------------------------- environment
@mcp.tool()
def bambu_status() -> dict:
    """Where Bambu Studio is installed, its version, whether it is running, and the current project."""
    return {
        "bambu_studio": studio.executable(), "version": studio.version(), "running": studio.is_running(),
        "data_dir": studio.data_dir(), "profile_roots": studio.profile_roots(),
        "user_presets": studio.user_dir(), "output_dir": out_dir(),
        "project": P().name if S.project else None, "last_saved": S.saved, "last_sliced": S.sliced,
    }


@mcp.tool()
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


@mcp.tool()
def search_presets(kind: str, query: str = "", printer: str = "", limit: int = 30) -> list:
    """Find presets. kind: filament | process | machine. query: words to match (e.g. 'eSUN PLA+', '0.16mm').
    With printer, only presets compatible with it. User presets come first."""
    if kind not in presets.KINDS:
        raise ValueError("kind must be filament, process or machine")
    return presets.search(kind, query, printer or None, limit)


@mcp.tool()
def filament_colors(preset: str) -> list:
    """Official colors (name, hex) of a Bambu filament line, e.g. 'Bambu PLA Basic @BBL X1C'."""
    return presets.filament_colors(preset)


# ---------------------------------------------------------------- project
@mcp.tool()
def new_project(name: str, printer: str = "P1S", process: str = "", filaments: list[dict] | None = None) -> dict:
    """Start an empty project. filaments: AMS slots in order, e.g.
    [{"preset": "Bambu PLA Basic", "color": "#000000"}, {"preset": "eSUN PLA+", "color": "#FFFFFF"}].
    A filament name without '@...' is matched to the printer automatically."""
    fils = [(f.get("preset") or "Bambu PLA Basic", _color(f.get("color"))) for f in (filaments or [])] or None
    S.project = Project(name, printer, process or None, fils)
    S.saved = S.sliced = None
    return _short()


@mcp.tool()
def open_project(path: str) -> dict:
    """Open a .3mf saved by Bambu Studio (or downloaded from MakerWorld). The file is never modified:
    save_project writes a new file. Returns the project summary and what could not be carried over."""
    path = os.path.abspath(os.path.expanduser(path))
    S.project = threemf.read(path)
    S.saved, S.sliced = None, None
    return P().summary()


@mcp.tool()
def get_project() -> dict:
    """Current project: printer, process, filament slots, plates, objects (id, name, center, size, filaments),
    setting overrides and warnings."""
    return P().summary()


@mcp.tool()
def set_printer(printer: str, process: str = "", rearrange: bool = True) -> dict:
    """Switch printer (e.g. P1S -> A1M). Filament presets are swapped for the same filaments on the new printer.
    With rearrange, objects are re-placed to fit the new bed (extra plates are added if needed)."""
    pr = P()
    old = pr.set_printer(printer, process or None)
    if rearrange:
        pr.arrange()
    res = _short()
    res["previous_printer"] = old
    return res


@mcp.tool()
def set_filament(slot: int, preset: str = "", color: str = "") -> dict:
    """Change one filament slot (1-based); a new slot number = add a slot. Leave a field empty to keep it."""
    pr = P()
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
@mcp.tool()
def add_plate(name: str = "") -> dict:
    """Add an empty plate at the end."""
    pr = P()
    pr.plates.append(Plate(name or f"Plate {len(pr.plates) + 1}"))
    return {"plate": len(pr.plates), "plates": len(pr.plates)}


@mcp.tool()
def rename_plate(plate: int, name: str) -> dict:
    """Give a plate a name (shown in Bambu Studio)."""
    P().plate(plate).name = name
    return {"plate": plate, "name": name}


@mcp.tool()
def remove_plate(plate: int, move_objects_to: int = 0) -> dict:
    """Delete a plate. Its objects are moved to plate `move_objects_to` (0 = delete them too)."""
    pr = P()
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
    res = {"id": [o for _, o in pr.objects()].index(obj) + 1, "name": obj.name, "plate": plate,
           "center_xy": [round(float(obj.at[0]), 1), round(float(obj.at[1]), 1)], "size_mm": [round(float(v), 1) for v in obj.size()]}
    if pr.out_of_bed(obj):
        res["warning"] = "the object is (partly) outside the printable area"
    return res


@mcp.tool()
def import_model(path: str, plate: int = 1, x: float | None = None, y: float | None = None, rotate_z: float = 0,
                 scale: float = 1.0, filament: int = 1, name: str = "") -> list:
    """Put an STL, OBJ or 3MF on a plate. Without x/y it goes to the free spot closest to the center.
    From a 3MF every object is imported (with its parts and filament assignments)."""
    pr = P()
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


@mcp.tool()
def add_shape(shape: str, plate: int = 1, x: float | None = None, y: float | None = None, filament: int = 1,
              name: str = "", width: float = 20, depth: float = 20, height: float = 20, diameter: float = 20,
              diameter_top: float = 0, text: str = "", text_height: float = 10, font: str = "",
              base: float = 0) -> dict:
    """Create a simple solid: box (width, depth, height), cylinder (diameter, height), cone (diameter,
    diameter_top, height), sphere (diameter), text (text, text_height = capital letters in mm, height = depth
    of the letters; base > 0 puts the text on a plate that thick; font = path to a .ttf/.otf)."""
    pr = P()
    shape = shape.lower().strip()
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


@mcp.tool()
def move_object(object: str, x: float | None = None, y: float | None = None, dx: float = 0, dy: float = 0,
                rotate_z: float = 0, plate: int = 0) -> dict:
    """Move an object (by name or id): absolute x/y, relative dx/dy, rotate around Z by rotate_z degrees,
    or move it to another plate (it keeps x/y if given, otherwise it goes to a free spot)."""
    pr = P()
    pi, o = pr.find(object)
    if rotate_z:
        o.transform(lambda v: geometry.rotate(v, rotate_z))
    if plate and plate != pi + 1:
        pr.plates[pi].objects.remove(o)
        return _place(pr, plate, o, x, y)
    nx = x if x is not None else o.at[0]
    ny = y if y is not None else o.at[1]
    o.at = (nx + dx, ny + dy)
    res = {"name": o.name, "plate": pi + 1, "center_xy": [round(float(o.at[0]), 1), round(float(o.at[1]), 1)],
           "size_mm": [round(float(v), 1) for v in o.size()]}
    if pr.out_of_bed(o):
        res["warning"] = "the object is (partly) outside the printable area"
    overlaps = [b.name for b in pr.plates[pi].objects if b is not o and _overlap(o.footprint(), b.footprint())]
    if overlaps:
        res["warning_overlap"] = overlaps
    return res


def _overlap(a, b):
    return not (a[2] <= b[0] or a[0] >= b[2] or a[3] <= b[1] or a[1] >= b[3])


@mcp.tool()
def transform_object(object: str, scale: float = 1.0, scale_xyz: list[float] | None = None, rotate_x: float = 0,
                     rotate_y: float = 0, rotate_z: float = 0) -> dict:
    """Scale (uniform or per axis) and rotate an object around its center. It stays on the bed."""
    pr = P()
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


@mcp.tool()
def duplicate_object(object: str, copies: int = 1, plate: int = 0) -> list:
    """Copy an object `copies` times onto free spots (same plate unless `plate` is given)."""
    import copy
    pr = P()
    pi, o = pr.find(object)
    out = []
    for _ in range(max(1, copies)):
        c = copy.deepcopy(o)
        c.name = pr.unique_name(o.name)
        out.append(_place(pr, plate or pi + 1, c, None, None))
    return out


@mcp.tool()
def delete_object(object: str) -> dict:
    """Remove an object from the project."""
    pr = P()
    pi, o = pr.find(object)
    pr.plates[pi].objects.remove(o)
    return {"deleted": o.name, "plate": pi + 1}


@mcp.tool()
def set_object_filament(object: str, filament: int, part: str = "") -> dict:
    """Assign a filament slot to a whole object, or to one of its parts (by part name)."""
    pr = P()
    if not 1 <= filament <= len(pr.filaments):
        raise ValueError(f"filament slot must be 1..{len(pr.filaments)} (add slots with set_filament)")
    _, o = pr.find(object)
    hits = [p for p in o.parts if not part or p.name.lower() == part.lower()]
    if not hits:
        raise ValueError(f"no part '{part}' in {o.name}: {[p.name for p in o.parts]}")
    for p in hits:
        p.filament = filament
    return {"name": o.name, "parts": [{"name": p.name, "filament": p.filament} for p in o.parts]}


@mcp.tool()
def set_object_setting(object: str, key: str, value: str) -> dict:
    """Per-object print setting (e.g. sparse_infill_density '40%', wall_loops '4', layer_height '0.12').
    An empty value removes the override."""
    pr = P()
    _, o = pr.find(object)
    if pr.key_kind(key) not in ("process", None):
        raise ValueError(f"'{key}' is a {pr.key_kind(key)} setting: use set_setting")
    if value == "":
        o.settings.pop(key, None)
    else:
        o.settings[key] = value
    return {"name": o.name, "settings": o.settings}


@mcp.tool()
def check_object(object: str) -> dict:
    """Is the mesh a closed, printable solid? Size, volume, number of separate pieces."""
    _, o = P().find(object)
    return {"name": o.name, "parts": [{"name": p.name, **geometry.check(p.verts, p.tris)} for p in o.parts]}


@mcp.tool()
def arrange(plate: int = 0, gap: float = 6.0) -> dict:
    """Re-place the objects of a plate (0 = all plates) close to the center without overlaps.
    Objects that do not fit are moved to a new plate."""
    pr = P()
    moved = pr.arrange([plate] if plate else None, gap)
    res = _short()
    if moved:
        res["moved_to_new_plate"] = [o.name for o in moved]
    return res


# ---------------------------------------------------------------- settings
@mcp.tool()
def get_setting(key: str) -> dict:
    """Current value of a print/filament/printer setting, where it comes from, and the preset value."""
    pr = P()
    cfg = pr.config()
    kind = pr.key_kind(key)
    if key not in cfg and kind is None:
        close = [k for k in cfg if key.lower() in k.lower()][:15]
        raise ValueError(f"unknown setting '{key}'. Similar: {close}")
    return {"key": key, "kind": kind, "value": cfg.get(key), "overridden": key in pr.overrides}


@mcp.tool()
def set_setting(key: str, value: str, slot: int = 0) -> dict:
    """Override a project setting. For filament settings (temperatures, plate temperatures...) slot = filament
    slot (0 = all slots). Values are Bambu Studio strings, e.g. '0.16', '15%', '65'. Useful keys:
    layer_height, wall_loops, sparse_infill_density, top_shell_layers, enable_support, brim_type,
    initial_layer_speed, ironing_type, textured_plate_temp(_initial_layer) for Textured PEI,
    hot_plate_temp(_initial_layer) for the smooth/High Temp plate, nozzle_temperature(_initial_layer),
    close_fan_the_first_x_layers, print_sequence ('by object'), curr_bed_type ('Textured PEI Plate')."""
    pr = P()
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
    return {"key": key, "kind": kind, "value": pr.overrides[key], "previous": cur}


@mcp.tool()
def reset_setting(key: str) -> dict:
    """Drop an override: the setting goes back to the preset value."""
    pr = P()
    pr.overrides.pop(key, None)
    return {"key": key, "value": pr.config().get(key)}


# ---------------------------------------------------------------- files, slicing, previews
@mcp.tool()
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
    res = {"saved": path, "warnings": [f"'{o.name}' is outside the printable area" for _, o in pr.objects()
                                       if pr.out_of_bed(o)]}
    if open_in_bambu:
        studio.open_in_gui(path)
        res["opened_in_bambu_studio"] = True
    return res


@mcp.tool()
def open_in_bambu_studio(path: str = "") -> dict:
    """Open a .3mf in the Bambu Studio window: by default the last sliced file (to see the preview there),
    otherwise the last saved one. Bambu Studio may ask what to do with the project already open."""
    target = path or S.sliced or S.saved
    if not target:
        raise ValueError("nothing saved yet: call save_project first")
    return {"opened": studio.open_in_gui(os.path.expanduser(target))}


@mcp.tool()
def slice_project(plate: int = 0) -> dict:
    """Slice with Bambu Studio (plate 0 = all). Returns per plate: minutes, grams (total and per filament slot),
    filament changes, layers and warnings. The sliced project is saved next to the project file."""
    pr = P()
    base = S.saved or os.path.join(out_dir(), f"{pr.name}.3mf")
    tmp = next_free_path(os.path.join(out_dir(), f".{pr.name}-slicing.3mf"))
    threemf.write(pr, tmp)
    out = next_free_path(base.replace(".3mf", "-sliced.3mf"))
    try:
        stats = slicer.slice_3mf(tmp, out, plate)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    S.sliced = out
    return {"sliced_file": out, "plates": stats}


@mcp.tool()
def preview_plate(plate: int = 1, view: str = "iso", zoom: bool = False) -> Image:
    """Image of a plate with its objects in their filament colors (painted colors too).
    view: iso | top. zoom: frame the objects instead of the whole bed, to see details."""
    pr = P()
    pr.plate(plate)
    return Image(data=preview.render_plate(pr, plate - 1, "top" if view == "top" else "iso", zoom=zoom), format="png")


@mcp.tool()
def preview_layer(plate: int = 1, layer: int = 0, z: float = 0) -> Image:
    """Image of one sliced layer seen from the top (needs slice_project first). Choose by layer number (1 = first)
    or by height z in mm. Extrusions are drawn in the filament colors."""
    pr = P()
    if not S.sliced:
        raise ValueError("slice the project first (slice_project)")
    g = slicer.gcode(S.sliced, plate)
    if not g:
        raise ValueError(f"plate {plate} was not sliced")
    segs, k, zz, n = slicer.layer_paths(g, layer or (None if z else 1), z or None)
    title = f"Plate {plate} - layer {k}/{n} - z {zz:.2f} mm - {len(segs)} moves"
    return Image(data=preview.render_layer(segs, pr.info["bed"], [c for _, c in pr.filaments], title,
                                           exclude=pr.info["exclude"]), format="png")


@mcp.tool()
def make_first_layer_test(plate: int = 1, height: float = 0.8, objects: list[str] | None = None) -> dict:
    """Add a plate with the first `height` mm of the objects of a plate (or of the listed objects):
    a short print to check bed adhesion and the first layers before a long print. Slice it with
    slice_project(plate=<new plate>)."""
    import copy
    pr = P()
    src = [pr.find(o)[1] for o in objects] if objects else list(pr.plate(plate).objects)
    if not src:
        raise ValueError("no objects to test")
    test = Plate(f"First {height:g} mm test")
    pr.plates.append(test)
    for o in src:
        c = copy.deepcopy(o)
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


def main():
    mcp.run()


if __name__ == "__main__":
    main()
