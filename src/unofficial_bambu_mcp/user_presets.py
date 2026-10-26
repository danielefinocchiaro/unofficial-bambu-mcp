"""Bambu Studio user presets (filament, process, printer): save, edit, list, rename and delete them the way the
app keeps them. A user preset is a JSON file in the user's preset folder with only what differs from the preset
it inherits (or all its settings, for a preset of its own), next to a .info file that Bambu Studio uses to sync it
with the user's Bambu account: setting_id (its id in the cloud), base_id (the parent's), updated_time, sync_info.

At start, Bambu Studio downloads a cloud preset that is missing on disk or newer in the cloud, uploads one that is
newer on disk or marked "update", and creates in the cloud one that has no setting_id yet. So the changes made
here stamp the .info to be uploaded. A preset that is in the cloud cannot be deleted or renamed from here: only
Bambu Studio's own Delete removes the cloud copy (it keeps the request in memory and sends it while signed in),
and a file deleted here would be downloaded again. Bambu Studio reads presets when it starts."""
import hashlib
import json
import os
import re
import shutil
import time

from . import presets, studio
from .presets import META, PresetError

BACKUPS = os.path.expanduser(os.environ.get("UBMCP_PRESET_BACKUPS", "~/.config/unofficial-bambu-mcp/preset-backups"))
KINDS = {"filament": "filament", "process": "process", "print": "process", "printer": "machine", "machine": "machine"}
SHOWN = {"filament": "filament", "process": "process", "machine": "printer", "project": "project"}
SETTINGS_ID = {"filament": "filament_settings_id", "process": "print_settings_id", "machine": "printer_settings_id"}
# written by Bambu Studio in every user preset: the extruder variants (Standard, High Flow...) its lists are for
VARIANT_KEYS = {"filament": ("filament_extruder_variant",), "process": ("print_extruder_id", "print_extruder_variant"),
                "machine": ("printer_extruder_id", "printer_extruder_variant")}
RESTART = "restart Bambu Studio to see it: it reads presets only when it starts"
_NUMBER = re.compile(r"-?(\d+\.?\d*|\.\d+)%?")


def kind(name):
    """'filament', 'process' or 'machine' from what a user may call it (printer = machine)."""
    k = KINDS.get((name or "").strip().lower())
    if not k:
        raise PresetError("kind must be filament, process or printer")
    return k


# ---------------------------------------------------------------- values
def _current(key, ref):
    cur = ref.get(key)
    if cur is None:                              # not in the preset chain: the default, one entry if a list
        cur = presets.default(key)
        if isinstance(cur, list):
            cur = cur[:1]
    return cur


def shaped(key, v, ref):
    """v in the shape Bambu Studio writes `key` in a preset: as many entries as the inherited value has (one per
    extruder variant for temperatures, flow ratio, retraction, speeds...), one entry for the other list settings,
    a plain string for the rest. ref: the flattened preset the value goes over."""
    cur = _current(key, ref)
    if isinstance(v, list):
        if isinstance(cur, list) and len(v) == len(cur):
            return [str(x) for x in v]
        v = v[0] if v else ""
    if isinstance(cur, list):
        return [str(v)] * max(1, len(cur))
    return str(v)


def value(key, v, ref):
    """v checked against what the setting holds now (how many values, a number or not) and shaped for the file."""
    cur = _current(key, ref)
    vals = v if isinstance(v, list) else [v]
    n = len(cur) if isinstance(cur, list) else 1
    if len(vals) not in (1, n):
        raise PresetError(f"{key} takes 1 value or {n} (one per extruder variant), not {len(vals)}")
    sample = (cur[0] if cur else None) if isinstance(cur, list) else cur
    if isinstance(sample, str) and _NUMBER.fullmatch(sample.strip()):
        fixed = []
        for x in vals:
            s = str(x).strip()
            if sample in ("0", "1") and s.lower() in ("true", "false"):
                s = "1" if s.lower() == "true" else "0"
            if s != "nil" and not _NUMBER.fullmatch(s):
                raise PresetError(f"{key} is a number (now {sample}), not {x!r}")
            fixed.append(s)
        vals = fixed
    return shaped(key, vals if isinstance(v, list) else vals[0], ref)


# ---------------------------------------------------------------- files and cloud sync
def info_path(path):
    return os.path.splitext(path)[0] + ".info"


def read_info(path):
    """The .info next to a preset file as a dict (empty if there is none)."""
    d = {}
    try:
        with open(info_path(path), encoding="utf-8") as f:
            for line in f:
                k, sep, v = line.partition("=")
                if sep:
                    d[k.strip()] = v.strip()
    except OSError:
        pass
    return d


def _write_info(path, d):
    with open(info_path(path), "w", encoding="utf-8") as f:
        for k in ("sync_info", "user_id", "setting_id", "base_id", "updated_time"):
            f.write(f"{k} = {d.get(k, '')}\n")


def in_cloud(path):
    """The cloud id of the preset at path, or None if it is only on this computer."""
    d = read_info(path)
    sid = d.get("setting_id", "")
    return sid if sid and sid != "null" and sid != d.get("base_id") else None


def _setting_id(kind, name):
    src = presets.source(kind, name)
    if src == "system":
        return presets.raw(kind, name).get("setting_id", "")
    if src == "user":
        return in_cloud(presets.path_of(kind, name)) or ""
    return ""


def _stamp(path, kind, data):
    """Tell Bambu Studio's cloud sync that the preset at path changed: one already in the cloud is uploaded at the
    next start, a new one is created there, as when a preset is saved in Bambu Studio while signed in."""
    d = read_info(path)
    if not d:
        uid = studio.user_id() or ""
        parent = data.get("inherits") or ""
        d = {"sync_info": "", "user_id": uid if uid.isdigit() else "", "setting_id": "",
             "base_id": _setting_id(kind, parent) if parent else ""}
    elif in_cloud(path):
        d["sync_info"] = "update"
    d["updated_time"] = str(int(time.time()))
    _write_info(path, d)


def backup(path):
    """Copy a preset file and its .info to BACKUPS; returns the copy's path."""
    os.makedirs(BACKUPS, exist_ok=True)
    stem = os.path.join(BACKUPS, f"{os.path.basename(path)[:-5]} {time.strftime('%Y%m%d-%H%M%S')}")
    dst, k = stem + ".json", 2
    while os.path.exists(dst):
        dst, k = f"{stem}-{k}.json", k + 1
    shutil.copy2(path, dst)
    if os.path.exists(info_path(path)):
        shutil.copy2(info_path(path), info_path(dst))
    return dst


def _write(path, out):
    ver = studio.version() or "02.08.00.00"
    out["version"] = ".".join(str(int(x)) for x in ver.split("."))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(dict(sorted(out.items())), f, indent=4)
    presets.refresh()
    return path


def _file_for(kind, name):
    folder = studio.user_dir(kind)
    if not folder:
        raise PresetError("Bambu Studio user preset folder not found (sign in to Bambu Studio once)")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, name.replace("/", "-") + ".json")


def _done(kind, path, name, bak=None, **extra):
    """What a change did, and what the user has to do to see it."""
    out = {"kind": SHOWN[kind], "name": name, "file": path}
    if bak:
        out["backup"] = bak
    out.update(extra)
    d, data = read_info(path), presets.raw(kind, name)
    if in_cloud(path):
        out["cloud"] = "in your Bambu cloud: Bambu Studio uploads the change at its next start"
    elif d.get("base_id") or not data.get("inherits"):
        out["cloud"] = "Bambu Studio adds it to your Bambu cloud at its next start, if you are signed in"
    else:
        out["cloud"] = "only on this computer (its parent preset is not in the cloud)"
    out["restart"] = RESTART
    if studio.is_running():
        out["warning"] = ("Bambu Studio is open and still has the old presets: close it and open it again. "
                          "Do not save this preset in Bambu Studio before that, or it writes its own copy over this one")
    return out


# ---------------------------------------------------------------- saving
def _filament_ids():
    ids = set()
    for kind, name in presets.names():
        if kind != "filament":
            continue
        try:
            with open(presets.path_of(kind, name), encoding="utf-8") as f:
                fid = json.load(f).get("filament_id")
        except (OSError, ValueError):
            continue
        if fid:
            ids.add(fid)
    return ids


def new_filament_id(name):
    """Id for a new filament, made like Bambu Studio's Create Filament: 'P' + 7 hex digits, not used yet."""
    taken, seed, k = _filament_ids(), f"{name}@{studio.user_id() or ''}", 0
    fid = "P" + hashlib.md5(seed.encode()).hexdigest()[:7]
    while fid in taken:
        k += 1
        fid = "P" + hashlib.md5(f"{seed}#{k}".encode()).hexdigest()[:7]
    return fid


def write_filament(name, base, values, machine=None, replace=False):
    """Save a Bambu Studio user filament preset with `values` (key -> single value).
    machine given: a new filament of its own, as Create Filament makes it ('<name> @<machine>', full settings,
    own filament_id, no parent), which Bambu Studio lists for AMS slots. Otherwise a variant of the system
    preset `base` (inherits it, keeps its filament id, so RFID spools of that filament still match).
    replace: update the existing user preset `name` in place (same filament id, so AMS slots set to it stay
    valid); the old file is copied to BACKUPS first. Returns what _done says, with filament_id when it has one."""
    full = f"{name} @{machine}" if machine and " @" not in name else name
    target = next((n for n in (name, full) if presets.exists("filament", n)), None)
    if target and not replace:
        raise PresetError(f"a filament preset named '{target}' already exists: choose another name, or replace=True")
    if replace:
        if not target or presets.source("filament", target) != "user":
            raise PresetError(f"there is no user filament preset '{name}' to replace")
        path = presets.path_of("filament", target)
        bak = backup(path)
        out = dict(presets.raw("filament", target))
        ref = presets.flat("filament", target)
        for k, v in values.items():
            out[k] = shaped(k, v, ref)
        _stamp(_write(path, out), "filament", out)
        return _done("filament", path, target, bak, filament_id=out.get("filament_id") or ref.get("filament_id"))
    if machine:
        fl = presets.flat("filament", base)
        out = {k: v for k, v in fl.items() if k not in META}
        for k, v in values.items():
            out[k] = shaped(k, v, fl)
        fid = new_filament_id(name)
        out.update({"name": full, "filament_settings_id": [full], "from": "User", "inherits": "",
                    "filament_id": fid, "compatible_printers": [machine]})
        path = _write(_file_for("filament", full), out)
        _stamp(path, "filament", out)
        return _done("filament", path, full, filament_id=fid)
    if presets.source("filament", base) == "user":
        base = presets.raw("filament", base).get("inherits") or base
    if presets.source("filament", base) != "system":
        raise PresetError(f"'{base}' is not a system filament preset")
    fl = presets.flat("filament", base)
    out = {"filament_settings_id": [name], "from": "User", "inherits": base, "name": name}
    if "filament_extruder_variant" in fl:
        out["filament_extruder_variant"] = fl["filament_extruder_variant"]
    for k, v in values.items():
        out[k] = shaped(k, v, fl)
    path = _file_for("filament", name)
    if os.path.exists(path):
        raise PresetError(f"{path} already exists")
    _stamp(_write(path, out), "filament", out)
    return _done("filament", path, name)


def save(kind, name, base, values, replace=False):
    """A user process or printer preset `name` with `values` over the preset `base`, as Bambu Studio's Save as
    makes it: a child of base (of base's parent, if base is a user preset), with only what differs.
    replace: update the user preset `name` in place instead (a backup copy is kept)."""
    if presets.exists(kind, name):
        if not replace:
            raise PresetError(f"a {SHOWN[kind]} preset named '{name}' already exists: choose another name, "
                              "or replace=True")
        if presets.source(kind, name) != "user":
            raise PresetError(f"'{name}' is a system preset: choose another name")
        path = presets.path_of(kind, name)
        bak = backup(path)
        out, ref = dict(presets.raw(kind, name)), presets.flat(kind, name)
    else:
        if replace:
            raise PresetError(f"there is no user {SHOWN[kind]} preset '{name}' to replace")
        ref = presets.flat(kind, base)
        own = presets.raw(kind, base) if presets.source(kind, base) == "user" else None
        if own is not None and not own.get("inherits"):          # a preset of its own: a full copy
            out = {k: v for k, v in ref.items() if k not in META}
            out.update({"from": "User", "inherits": "", "name": name})
        else:
            if own is not None:
                values = {**{k: v for k, v in own.items() if k not in META and k not in VARIANT_KEYS[kind]
                             and k != SETTINGS_ID[kind]}, **values}
                base = own["inherits"]
                ref = presets.flat(kind, base)
            out = {"from": "User", "inherits": base, "name": name}
            for vk in VARIANT_KEYS[kind]:
                if vk in ref:
                    out[vk] = ref[vk]
        out[SETTINGS_ID[kind]] = shaped(SETTINGS_ID[kind], name, {})
        path, bak = _file_for(kind, name), None
        if os.path.exists(path):
            raise PresetError(f"{path} already exists")
    for k, v in values.items():
        out[k] = shaped(k, v, ref)
    _stamp(_write(path, out), kind, out)
    return _done(kind, path, name, bak, values={k: out[k] for k in values})


# ---------------------------------------------------------------- managing
def _user_path(kind, name):
    if not presets.exists(kind, name):
        close = [n for k, n in presets.names() if k == kind and presets.source(k, n) == "user"
                 and name.lower() in n.lower()][:10]
        raise PresetError(f"no user {SHOWN[kind]} preset named '{name}'" + (f". Similar: {close}" if close else ""))
    if presets.source(kind, name) != "user":
        raise PresetError(f"'{name}' is a Bambu system preset and cannot be changed: save a user preset from it first")
    return presets.path_of(kind, name)


def children(kind, name):
    """User presets that inherit the preset `name`."""
    return sorted(n for k, n in presets.names() if k == kind and presets.source(k, n) == "user"
                  and presets.raw(k, n).get("inherits") == name)


def _cloud_refusal(kind, name, action, new_name=None):
    how = (f"in Bambu Studio open it, save it as '{new_name}', then delete '{name}' with the trash icon next to "
           "its name" if new_name else "in Bambu Studio open it and delete it with the trash icon next to its name")
    return PresetError(f"'{name}' is in your Bambu cloud: if its file is {action} here, Bambu Studio downloads it "
                       f"again at its next start. Only Bambu Studio's own Delete removes the cloud copy: {how}")


def _short(v):
    if isinstance(v, str) and len(v) > 80:
        return v[:70] + "…"
    if isinstance(v, list):
        return [_short(x) for x in v]
    return v


def listing(kinds=("filament", "process", "machine")):
    """The user's presets: parent, what they change, cloud state, presets that inherit them."""
    out = []
    for kind in kinds:
        for n in sorted((n for k, n in presets.names() if k == kind and presets.source(k, n) == "user"), key=str.lower):
            path, d = presets.path_of(kind, n), presets.raw(kind, n)
            own = {k: _short(v) for k, v in sorted(d.items()) if k not in META and k not in VARIANT_KEYS[kind]
                   and k != SETTINGS_ID[kind]}
            entry = {"kind": SHOWN[kind], "name": n, "inherits": d.get("inherits") or None,
                     "in_cloud": bool(in_cloud(path)),
                     "modified": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(path)))}
            if d.get("inherits"):
                entry["changes"] = own
            else:
                entry["own_settings"] = len(own)
            if kind == "filament" and d.get("filament_id"):
                entry["filament_id"] = d["filament_id"]
            kids = children(kind, n)
            if kids:
                entry["inherited_by"] = kids
            out.append(entry)
    return out


def edit(kind, name, values):
    """Change settings of the user preset `name` in place (a backup copy is kept). values: {key: value}; a list
    gives one value per extruder variant; None removes the key, so the value comes from the parent again."""
    path = _user_path(kind, name)
    if not values:
        raise PresetError("nothing to change: give values, e.g. {\"nozzle_temperature\": \"215\"}")
    out, ref = dict(presets.raw(kind, name)), presets.flat(kind, name)
    fixed = META | set(VARIANT_KEYS[kind]) | {SETTINGS_ID[kind]}
    for k, v in values.items():
        if k in fixed:
            raise PresetError(f"'{k}' describes the preset itself and cannot be edited"
                              + (": use rename_preset" if k in ("name", SETTINGS_ID[kind]) else ""))
        owner = kind if k in ref else presets.kind_of(k)
        if owner is None:
            close = [x for x in ref if k.lower() in x.lower() and x not in fixed][:12]
            raise PresetError(f"unknown setting '{k}'. Similar: {close}")
        if owner != kind:
            raise PresetError(f"'{k}' is a {SHOWN[owner]} setting, not a {SHOWN[kind]} one")
        if v is None:
            if not out.get("inherits"):
                raise PresetError(f"'{name}' has no parent preset to take {k} from: give it a value")
            out.pop(k, None)
        else:
            out[k] = value(k, v, ref)
    bak = backup(path)
    _stamp(_write(path, out), kind, out)
    now = presets.flat(kind, name)
    return _done(kind, path, name, bak, values={k: _short(now.get(k)) for k in values})


def rename(kind, name, new_name):
    path = _user_path(kind, name)
    new_name = (new_name or "").strip()
    if not new_name or new_name == name:
        raise PresetError("give a new name")
    if presets.exists(kind, new_name):
        raise PresetError(f"a {SHOWN[kind]} preset named '{new_name}' already exists")
    if in_cloud(path):
        raise _cloud_refusal(kind, name, "renamed", new_name)
    kids = children(kind, name)
    if kids:
        raise PresetError(f"{len(kids)} user preset(s) inherit '{name}' and would lose their parent: {kids}")
    new_path = _file_for(kind, new_name)
    if os.path.exists(new_path):
        raise PresetError(f"{new_path} already exists")
    bak = backup(path)
    out = dict(presets.raw(kind, name))
    out["name"] = new_name
    out[SETTINGS_ID[kind]] = shaped(SETTINGS_ID[kind], new_name, out)
    _write(new_path, out)
    if os.path.exists(info_path(path)):
        os.replace(info_path(path), info_path(new_path))
    os.remove(path)
    presets.refresh()
    _stamp(new_path, kind, out)
    return _done(kind, new_path, new_name, bak, renamed_from=name,
                 note=f"projects that use '{name}' will not find it under the new name")


def delete(kind, name):
    path = _user_path(kind, name)
    kids = children(kind, name)
    if kids:
        raise PresetError(f"{len(kids)} user preset(s) inherit '{name}': delete or change them first: {kids}")
    if in_cloud(path):
        raise _cloud_refusal(kind, name, "deleted")
    bak = backup(path)
    os.remove(path)
    if os.path.exists(info_path(path)):
        os.remove(info_path(path))
    presets.refresh()
    out = {"kind": SHOWN[kind], "deleted": name, "file": path, "backup": bak, "restart": RESTART}
    if studio.is_running():
        out["warning"] = "Bambu Studio is open and still lists it: close it and open it again"
    return out
