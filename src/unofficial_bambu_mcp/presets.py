"""Bambu Studio presets: system profiles (BBL) and the user's own, resolved the way the app does.

The CLI does not follow "inherits"/"include" when it loads a project, so a project must carry the full,
flattened values. This module flattens presets and picks the right filament preset for a printer.
"""
import glob
import json
import os
from functools import lru_cache
from importlib import resources

from . import studio

KINDS = ("machine", "process", "filament")
# keys that describe the preset itself, not a setting
META = {"inherits", "include", "name", "from", "setting_id", "instantiation", "type", "filament_id",
        "compatible_printers", "compatible_printers_condition", "compatible_prints",
        "compatible_prints_condition", "description", "renamed_from", "version", "base_id", "user_id",
        "updated_time", "filament_settings_id", "print_settings_id", "printer_settings_id"}

# Setting keys that Bambu's system profiles never write, so the profile files alone do not say whose they are
# (Bambu Studio keeps them in its option lists). The other keys of a project that no profile has are process
# settings, except PROJECT_KEYS: the plate, the slots, purge volumes, the prime tower... which no preset holds.
UNLISTED = {
    "filament": frozenset({"pressure_advance", "enable_pressure_advance", "enable_overhang_bridge_fan", "filament_notes",
                           "first_x_layer_part_fan_speed", "ironing_fan_speed",
                           "overhang_threshold_participating_cooling"}),
    "machine": frozenset({"bed_custom_model", "bed_custom_texture", "before_layer_change_gcode", "printer_notes",
                          "printing_by_object_gcode", "template_custom_gcode", "thumbnail_size",
                          "use_firmware_retraction", "use_relative_e_distances", "wrapping_detection_layers"}),
}
PROJECT_KEYS = frozenset({
    "curr_bed_type", "different_settings_to_system", "inherits_group", "print_compatible_printers",
    "filament_colour", "default_filament_colour", "filament_ids", "filament_self_index", "filament_map",
    "filament_map_2", "filament_map_mode", "enable_filament_dynamic_map", "filament_nozzle_map", "filament_volume_map",
    "filament_is_mixed", "filament_mixed_components", "filament_mixed_gradient", "filament_mixed_gradient_curve",
    "filament_mixed_gradient_per_part", "filament_mixed_gradient_range", "filament_mixed_sublayer_ratios",
    "flush_multiplier", "flush_multiplier_fast", "flush_volumes_matrix", "flush_volumes_vector", "prime_volume_mode",
    "wipe_tower_x", "wipe_tower_y", "wipe_tower_rotation_angle", "first_layer_print_sequence",
    "other_layers_print_sequence", "other_layers_print_sequence_nums", "start_end_points", "extruder_ams_count",
    "extruder_nozzle_stats", "nozzle_volume_type", "has_filament_switcher", "has_scarf_joint_seam"})

# short names for common single-nozzle printers (any full machine preset name works too)
PRINTER_ALIASES = {
    "X1C": "Bambu Lab X1 Carbon 0.4 nozzle", "X1": "Bambu Lab X1 0.4 nozzle", "X1E": "Bambu Lab X1E 0.4 nozzle",
    "P1S": "Bambu Lab P1S 0.4 nozzle", "P1P": "Bambu Lab P1P 0.4 nozzle", "P2S": "Bambu Lab P2S 0.4 nozzle",
    "A1": "Bambu Lab A1 0.4 nozzle", "A1M": "Bambu Lab A1 mini 0.4 nozzle", "A1MINI": "Bambu Lab A1 mini 0.4 nozzle",
    "H2S": "Bambu Lab H2S 0.4 nozzle",
}


class PresetError(ValueError):
    pass


@lru_cache(maxsize=1)
def _index():
    """name -> (kind, path, source) for system and user presets. System roots: newest first."""
    idx = {}
    for kind in KINDS:
        for root in studio.profile_roots():
            for p in glob.glob(os.path.join(root, kind, "*.json")):
                name = os.path.splitext(os.path.basename(p))[0]
                idx.setdefault((kind, name), (p, "system"))
        ud = studio.user_dir(kind)
        if ud and os.path.isdir(ud):
            for p in glob.glob(os.path.join(ud, "*.json")):
                try:
                    with open(p, encoding="utf-8") as f:
                        name = json.load(f).get("name") or os.path.splitext(os.path.basename(p))[0]
                except (OSError, ValueError):
                    continue
                idx[(kind, name)] = (p, "user")
    return idx


_user_state = None


def _user_files():
    """(preset folder, (kind, file, mtime)...) of the user's presets: what Bambu Studio changes on disk."""
    files = []
    for kind in KINDS:
        ud = studio.user_dir(kind)
        try:
            with os.scandir(ud or "") as it:
                files += [(kind, e.name, e.stat().st_mtime_ns) for e in it if e.name.endswith(".json")]
        except OSError:
            continue
    return studio.user_id(), tuple(sorted(files))


def refresh_if_changed():
    """Forget what was read about presets when the user's preset files changed since the last call (saved, renamed
    or deleted in Bambu Studio while the server runs). System presets change only with an app update."""
    global _user_state
    state = _user_files()
    if state != _user_state:
        refresh()
        _user_state = state


def refresh():
    _index.cache_clear()
    _profile_keys.cache_clear()
    kind_of.cache_clear()
    raw.cache_clear()
    flat.cache_clear()
    _fid_index.cache_clear()


@lru_cache(maxsize=4096)
def raw(kind, name):
    hit = _index().get((kind, name))
    if not hit:
        raise PresetError(f"no {kind} preset named '{name}'")
    with open(hit[0], encoding="utf-8") as f:
        return json.load(f)


def path_of(kind, name):
    hit = _index().get((kind, name))
    if not hit:
        raise PresetError(f"no {kind} preset named '{name}'")
    return hit[0]


def source(kind, name):
    hit = _index().get((kind, name))
    return hit[1] if hit else None


def exists(kind, name):
    return (kind, name) in _index()


def names():
    """(kind, name) of every preset, system and user."""
    return list(_index())


@lru_cache(maxsize=2048)
def _flat_cached(kind, name):
    d = raw(kind, name)
    out = {}
    parent = d.get("inherits")
    if parent:
        out.update(_flat_cached(kind, parent))
    for inc in d.get("include", []) or []:
        if exists(kind, inc):
            out.update({k: v for k, v in _flat_cached(kind, inc).items()})
    out.update(d)
    return out


def flat(kind, name):
    """All values of a preset, following inherits and include. Returns a new dict."""
    return dict(_flat_cached(kind, name))


flat.cache_clear = _flat_cached.cache_clear


def settings(kind, name):
    """Only the setting keys of a flattened preset (no metadata)."""
    return {k: v for k, v in flat(kind, name).items() if k not in META}


@lru_cache(maxsize=1)
def _template():
    with resources.files("unofficial_bambu_mcp").joinpath("data/bambu_template.config").open(encoding="utf-8") as f:
        return json.load(f)


def template():
    """Every setting of a Bambu Studio project with a default value (a new dict)."""
    return json.loads(json.dumps(_template()))


def default(key):
    return _template().get(key)


@lru_cache(maxsize=1)
def _profile_keys():
    """{kind: keys that some system profile of that kind sets}."""
    out = {k: set() for k in KINDS}
    for (kind, _), (p, src) in _index().items():
        if src != "system":
            continue
        try:
            with open(p, encoding="utf-8") as f:
                out[kind].update(json.load(f))
        except (OSError, ValueError):
            continue
    return out


@lru_cache(maxsize=1024)
def kind_of(key):
    """Whose setting a key is: 'filament', 'process', 'machine', 'project' (only in a project) or None (unknown)."""
    for kind, keys in UNLISTED.items():
        if key in keys:
            return kind
    if key in PROJECT_KEYS:
        return "project"
    pk = _profile_keys()
    for kind in ("filament", "process", "machine"):
        if key in pk[kind] and key not in META:
            return kind
    return "process" if key in _template() else None


def machine_name(printer):
    """Accept an alias (P1S, A1M...) or a full machine preset name."""
    if not printer:
        raise PresetError("printer is required")
    full = PRINTER_ALIASES.get(printer.replace(" ", "").replace("-", "").upper(), printer)
    if not exists("machine", full):
        raise PresetError(f"unknown printer '{printer}'. Use one of {sorted(PRINTER_ALIASES)} or a machine preset name")
    return full


def machine_info(machine):
    m = flat("machine", machine)

    def pts(key):
        out = []
        for s in m.get(key, []) or []:
            if "x" in s:
                a, b = s.split("x")
                out.append((float(a), float(b)))
        return out

    area = pts("printable_area")
    xs, ys = [p[0] for p in area] or [0, 256], [p[1] for p in area] or [0, 256]
    excl = pts("bed_exclude_area")
    return {
        "machine": machine,
        "bed": (max(xs) - min(xs), max(ys) - min(ys)),
        "origin": (min(xs), min(ys)),
        "exclude": excl,
        "max_height": float((m.get("printable_height") or "250")),
        "default_process": m.get("default_print_profile"),
        "default_filament": (m.get("default_filament_profile") or [None])[0],
        "nozzle": (m.get("nozzle_diameter") or ["0.4"])[0],
        "extruders": len(m.get("nozzle_diameter") or ["0.4"]),
        "model_id": _model_id(m.get("printer_model")),
    }


def _model_id(printer_model):
    """Bambu's printer model code (e.g. 'C12' for the P1S), from the vendor's model file."""
    try:
        return flat("machine", printer_model).get("model_id") if printer_model else None
    except PresetError:
        return None


def _compatible(fl, machine):
    cp = fl.get("compatible_printers") or []
    return not cp or machine in cp


def filament_for(name, machine):
    """The filament preset to use on `machine`: the given one if compatible, otherwise the same
    filament (same name before ' @') made for that printer. User presets are kept as they are."""
    if exists("filament", name) and (source("filament", name) == "user" or _compatible(flat("filament", name), machine)):
        return name
    base = name.split(" @")[0].strip()
    cands = [n for (k, n) in _index() if k == "filament" and n.startswith(base + " @")]
    good = []
    for n in cands:
        d = raw("filament", n)
        if str(d.get("instantiation", "true")) != "true":
            continue
        fl = flat("filament", n)
        if _compatible(fl, machine):
            good.append(n)
    if not good:
        raise PresetError(f"no '{base}' filament preset for {machine}")
    nozzle = machine.split()[-2] if machine.endswith("nozzle") else "0.4"
    # prefer the plain preset (no special nozzle suffix) for 0.4, the nozzle-specific one otherwise
    good.sort(key=lambda n: (("nozzle" in n) != (nozzle != "0.4"), len(n)))
    return good[0]


def search(kind, query="", printer=None, limit=40):
    """Presets whose name contains all words of `query`. With a printer, only compatible ones."""
    words = [w.lower() for w in (query or "").split()]
    machine = machine_name(printer) if printer else None
    out = []
    for (k, n), (_p, src) in sorted(_index().items(), key=lambda kv: (kv[1][1] != "user", kv[0][1])):
        if k != kind or not all(w in n.lower() for w in words):
            continue
        d = raw(kind, n)
        if src == "system" and str(d.get("instantiation", "true")) != "true":
            continue
        if machine and kind != "machine":
            fl = flat(kind, n)
            if kind == "filament" and src != "user" and not _compatible(fl, machine):
                continue
            if kind == "process":
                cp = fl.get("compatible_printers") or []
                if cp and machine not in cp:
                    continue
        out.append({"name": n, "source": src, "vendor": (flat(kind, n).get("filament_vendor") or [None])[0]
                    if kind == "filament" else None})
        if len(out) >= limit:
            break
    return out


def filament_colors(preset):
    """Known colors of a Bambu filament line, from Bambu Studio's color table (if present)."""
    fid = flat("filament", preset).get("filament_id")
    out = []
    for root in studio.profile_roots():
        p = os.path.join(root, "filament", "filaments_color_codes.json")
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8") as f:
            data = json.load(f)

        def walk(x):
            if isinstance(x, dict):
                if x.get("fila_id") == fid and x.get("fila_color"):
                    out.append({"name": (x.get("fila_color_name") or {}).get("en", ""),
                                "hex": x["fila_color"][0][:7].upper()})
                    return
                for v in x.values():
                    walk(v)
            elif isinstance(x, list):
                for v in x:
                    walk(v)
        walk(data)
        if out:
            break
    return out


@lru_cache(maxsize=1)
def _fid_index():
    """Filament id -> filament line name, from the presets that declare it: Bambu ids (GFA00 -> "Bambu PLA Basic")
    and the user's own filaments (P80ed8f6 -> "eSUN PLA Basic Nero"), system presets first."""
    idx = {}
    for (k, n), (p, _src) in sorted(_index().items(), key=lambda it: it[1][1] != "system"):
        if k != "filament":
            continue
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
        except (OSError, ValueError):
            continue
        fid = d.get("filament_id")
        if fid and fid not in idx:
            idx[fid] = n.split(" @")[0].strip()
    return idx


def line_for_filament_id(fid):
    return _fid_index().get(fid)
