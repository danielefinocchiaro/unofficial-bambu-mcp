"""Read and write Bambu Studio project files (.3mf).

Writing: multi-plate projects, multi-part objects, per-part filaments, per-object settings, painted
triangles. Reading: the same from projects saved by Bambu Studio (or MakerWorld downloads); things this
module does not understand are reported as warnings instead of being silently dropped.
"""
import json
import re
import uuid
import xml.etree.ElementTree as ET
import zipfile
from xml.sax.saxutils import escape, quoteattr

import numpy as np

from . import presets
from .project import GCODE_TYPES, LayerGcode, Obj, Part, Plate, Project

CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
NS = (f'xmlns="{CORE}" xmlns:BambuStudio="http://schemas.bambulab.com/package/2021" '
      f'xmlns:p="{PROD}" requiredextensions="p"')
HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n'
TRI_ATTRS = ("paint_color", "paint_supports", "paint_seam", "face_property")
# extra files we can carry over unchanged when plates are not renumbered
PASSTHROUGH = ()
LAYER_GCODE_FILE = "Metadata/custom_gcode_per_layer.xml"


def plate_stride(bed_w):
    return bed_w * 1.2            # Bambu Studio lays plates out on a grid with a 1/5 bed gap


def plate_origin(i, n, bed_w):
    cols = _columns(n)
    s = plate_stride(bed_w)
    return np.array([(i % cols) * s, -(i // cols) * s, 0.0])


def _columns(n):
    v = n ** 0.5
    r = round(v)
    return int(r + 1 if v > r else r)


# ================================================================ WRITE
def write(project, path, title=None):
    def uid():
        return str(uuid.uuid4())

    bed_w = project.info["bed"][0]
    n_pl = len(project.plates)
    title = title or project.name
    model = [HEAD, f'<model unit="millimeter" xml:lang="en-US" {NS}>\n',
             ' <metadata name="Application">BambuStudio-02.07.01.57</metadata>\n',
             ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n',
             f' <metadata name="Title">{escape(title)}</metadata>\n', ' <resources>\n']
    build, rels, conf = [], [], [HEAD, "<config>\n"]
    plate_objs = []
    next_id, n_file = 1, 0
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for pi, plate in enumerate(project.plates):
            origin = plate_origin(pi, n_pl, bed_w)
            ids = []
            for ob in plate.objects:
                n_file += 1
                lo, hi = ob.bbox()
                c = (lo + hi) / 2
                part_xml = [HEAD, f'<model unit="millimeter" xml:lang="en-US" {NS}>\n',
                            ' <metadata name="BambuStudio:3mfVersion">1</metadata>\n <resources>\n']
                comps, part_conf, faces = [], [], 0
                for part in ob.parts:
                    mid = next_id
                    next_id += 1
                    v = part.verts - c
                    part_xml.append(f'  <object id="{mid}" p:UUID="{uid()}" type="model">\n   <mesh>\n    <vertices>\n')
                    part_xml += [f'     <vertex x="{x:.4f}" y="{y:.4f}" z="{zz:.4f}"/>\n' for x, y, zz in v]
                    part_xml.append("    </vertices>\n    <triangles>\n")
                    attrs = {k: a for k, a in part.tri_attrs.items() if a is not None and len(a) == len(part.tris)}
                    if attrs:
                        for ti, (a, b, cc) in enumerate(part.tris):
                            extra = "".join(f' {k}="{escape(str(vals[ti]))}"' for k, vals in attrs.items() if vals[ti])
                            part_xml.append(f'     <triangle v1="{a}" v2="{b}" v3="{cc}"{extra}/>\n')
                    else:
                        part_xml += [f'     <triangle v1="{a}" v2="{b}" v3="{cc}"/>\n' for a, b, cc in part.tris]
                    part_xml.append("    </triangles>\n   </mesh>\n  </object>\n")
                    comps.append(f'    <component p:path="/3D/Objects/object_{n_file}.model" objectid="{mid}" '
                                 f'p:UUID="{uid()}" transform="1 0 0 0 1 0 0 0 1 0 0 0"/>\n')
                    faces += len(part.tris)
                    meta = "".join(f'      <metadata key={quoteattr(k)} value={quoteattr(str(v))}/>\n'
                                   for k, v in part.meta.items())
                    part_conf.append(f'    <part id="{mid}" subtype="{part.subtype}">\n'
                                     f'      <metadata key="name" value={quoteattr(part.name)}/>\n'
                                     '      <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n'
                                     f'      <metadata key="extruder" value="{part.filament}"/>\n' + meta +
                                     f'      <mesh_stat face_count="{len(part.tris)}" edges_fixed="0" degenerate_facets="0" '
                                     'facets_removed="0" facets_reversed="0" backwards_edges="0"/>\n    </part>\n')
                part_xml.append(" </resources>\n <build/>\n</model>\n")
                z.writestr(f"3D/Objects/object_{n_file}.model", "".join(part_xml))
                rels.append(f' <Relationship Target="/3D/Objects/object_{n_file}.model" Id="rel-{n_file}" '
                            'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n')
                oid = next_id
                next_id += 1
                model.append(f'  <object id="{oid}" p:UUID="{uid()}" type="model">\n   <components>\n'
                             + "".join(comps) + "   </components>\n  </object>\n")
                pos = origin + np.array([ob.at[0], ob.at[1], c[2] - lo[2]])
                build.append(f'  <item objectid="{oid}" p:UUID="{uid()}" '
                             f'transform="1 0 0 0 1 0 0 0 1 {pos[0]:.4f} {pos[1]:.4f} {pos[2]:.4f}" printable="1"/>\n')
                conf.append(f'  <object id="{oid}">\n    <metadata key="name" value={quoteattr(ob.name)}/>\n'
                            f'    <metadata key="extruder" value="{ob.solid_parts()[0].filament}"/>\n')
                conf += [f'    <metadata key={quoteattr(k)} value={quoteattr(str(v))}/>\n' for k, v in ob.settings.items()]
                conf.append(f'    <metadata face_count="{faces}"/>\n')
                conf += part_conf
                conf.append("  </object>\n")
                ids.append(oid)
            plate_objs.append(ids)
        for pi, (plate, ids) in enumerate(zip(project.plates, plate_objs, strict=True)):
            conf.append(f'  <plate>\n    <metadata key="plater_id" value="{pi + 1}"/>\n'
                        f'    <metadata key="plater_name" value={quoteattr(plate.name)}/>\n'
                        '    <metadata key="locked" value="false"/>\n'
                        '    <metadata key="filament_map_mode" value="Auto For Flush"/>\n'
                        '    <metadata key="gcode_file" value=""/>\n')
            conf += [f'    <metadata key={quoteattr(k)} value={quoteattr(str(v))}/>\n' for k, v in plate.settings.items()]
            for j, oid in enumerate(ids):
                conf.append(f'    <model_instance>\n      <metadata key="object_id" value="{oid}"/>\n'
                            '      <metadata key="instance_id" value="0"/>\n'
                            f'      <metadata key="identify_id" value="{100 * (pi + 1) + j}"/>\n    </model_instance>\n')
            conf.append("  </plate>\n")
        conf.append("  <assemble>\n  </assemble>\n</config>\n")
        model += [" </resources>\n", f' <build p:UUID="{uid()}">\n'] + build + [" </build>\n</model>\n"]
        z.writestr("[Content_Types].xml", HEAD +
                   '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\n'
                   ' <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>\n'
                   ' <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>\n'
                   ' <Default Extension="png" ContentType="image/png"/>\n'
                   ' <Default Extension="gcode" ContentType="text/x.gcode"/>\n</Types>\n')
        z.writestr("_rels/.rels", HEAD +
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
                   ' <Relationship Target="/3D/3dmodel.model" Id="rel-1" '
                   'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>\n</Relationships>\n')
        z.writestr("3D/3dmodel.model", "".join(model))
        z.writestr("3D/_rels/3dmodel.model.rels", HEAD +
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
                   + "".join(rels) + "</Relationships>\n")
        z.writestr("Metadata/model_settings.config", "".join(conf))
        z.writestr("Metadata/project_settings.config", json.dumps(project.config(), indent=4))
        z.writestr("Metadata/slice_info.config", HEAD + "<config>\n  <header>\n"
                   '    <header_item key="X-BBL-Client-Type" value="slicer"/>\n'
                   '    <header_item key="X-BBL-Client-Version" value="02.07.01.57"/>\n  </header>\n</config>\n')
        xml = _layer_gcodes_xml(project)
        if xml:
            z.writestr(LAYER_GCODE_FILE, xml)
        for name, data in project.extras.items():
            z.writestr(name, data)
    return path


def _layer_gcodes_xml(project):
    """Metadata/custom_gcode_per_layer.xml in Bambu Studio's format (see bbs_3mf.cpp)."""
    plates = [(i, pl) for i, pl in enumerate(project.plates) if pl.layer_gcodes]
    if not plates:
        return None
    pause = project.config().get("machine_pause_gcode", "M400 U1")
    out = ['<?xml version="1.0" encoding="utf-8"?>', "<custom_gcodes_per_layer>"]
    for i, pl in plates:
        out += ["<plate>", f'<plate_info id="{i + 1}"/>']
        for g in sorted(pl.layer_gcodes, key=lambda g: g.z):
            typ = GCODE_TYPES[g.kind]
            extra = g.gcode if g.kind == "custom" else (g.message if g.kind == "pause" else "")
            gcode = {"pause": pause, "tool_change": "tool_change", "template": ""}.get(g.kind, extra)
            out.append(f'<layer top_z="{g.z:g}" type="{typ}" extruder="{g.filament}" color={quoteattr(g.color or "")} '
                       f'extra={quoteattr(extra)} gcode={quoteattr(gcode)}/>')
        used = {f for o in pl.objects for f in o.filaments()}
        mode = "SingleExtruder" if len(project.filaments) == 1 else ("MultiAsSingle" if len(used) <= 1 else "MultiExtruder")
        out += [f'<mode value="{mode}"/>', "</plate>"]
    out.append("</custom_gcodes_per_layer>")
    return "\n".join(out) + "\n"


def _read_layer_gcodes(xml_bytes):
    """{plate_index (0-based): [LayerGcode]} from custom_gcode_per_layer.xml."""
    kinds = {v: k for k, v in GCODE_TYPES.items()}
    out = {}
    root = ET.fromstring(xml_bytes)
    for pl in root.findall("plate"):
        info = pl.find("plate_info")
        idx = int(info.get("id")) - 1 if info is not None else 0
        for ly in pl.findall("layer"):
            typ = int(ly.get("type", "4"))
            kind = kinds.get(typ, "custom")
            extra = ly.get("extra", "")
            out.setdefault(idx, []).append(LayerGcode(
                float(ly.get("top_z", "0")), kind, gcode=extra if kind == "custom" else "",
                filament=int(ly.get("extruder", "1") or 1), color=ly.get("color", ""),
                message=extra if kind == "pause" else ""))
    return out


# ================================================================ READ
def _matrix(s):
    """3MF transform 'm00 m01 m02 m10 m11 m12 m20 m21 m22 m30 m31 m32' (row vectors) -> 4x4 column form."""
    if not s:
        return np.eye(4)
    v = [float(x) for x in s.split()]
    m = np.eye(4)
    m[:3, :3] = np.array(v[:9]).reshape(3, 3).T
    m[:3, 3] = v[9:12]
    return m


def _bambu_matrix(s):
    """model_settings 'matrix' metadata: 16 numbers, row-major 4x4."""
    if not s:
        return np.eye(4)
    v = [float(x) for x in s.split()]
    return np.array(v).reshape(4, 4) if len(v) == 16 else np.eye(4)


def _parse_model(xml_bytes):
    """{object_id: ('mesh', verts, tris, attrs) | ('components', [(path, objid, matrix)])}"""
    root = ET.fromstring(xml_bytes)
    q = f"{{{CORE}}}"
    out = {}
    for obj in root.iter(q + "object"):
        oid = obj.get("id")
        mesh = obj.find(q + "mesh")
        if mesh is not None:
            vs = mesh.find(q + "vertices")
            verts = np.array([[float(v.get("x")), float(v.get("y")), float(v.get("z"))]
                              for v in vs.iter(q + "vertex")], float)
            tris, attrs = [], {k: [] for k in TRI_ATTRS}
            for t in mesh.find(q + "triangles").iter(q + "triangle"):
                tris.append([int(t.get("v1")), int(t.get("v2")), int(t.get("v3"))])
                for k in TRI_ATTRS:
                    attrs[k].append(t.get(k))
            attrs = {k: a for k, a in attrs.items() if any(a)}
            out[oid] = ("mesh", verts, np.array(tris, np.int64).reshape(-1, 3), attrs)
            continue
        comps = obj.find(q + "components")
        if comps is not None:
            lst = []
            for c in comps.iter(q + "component"):
                lst.append((c.get(f"{{{PROD}}}path"), c.get("objectid"), _matrix(c.get("transform"))))
            out[oid] = ("components", lst)
    build = []
    b = root.find(q + "build")
    if b is not None:
        for it in b.iter(q + "item"):
            build.append((it.get("objectid"), _matrix(it.get("transform")), it.get("printable", "1")))
    return out, build


def _meta(el):
    return {m.get("key"): m.get("value") for m in el.findall("metadata") if m.get("key")}


def read(path):
    """Open a Bambu Studio .3mf as a Project (copy semantics: the file itself is never modified)."""
    warnings = []
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        cfg = json.loads(z.read("Metadata/project_settings.config")) if "Metadata/project_settings.config" in names else {}
        main, build = _parse_model(z.read("3D/3dmodel.model"))
        sub_cache = {n: _parse_model(z.read(n))[0] for n in names
                     if n.startswith("3D/") and n.endswith(".model") and n != "3D/3dmodel.model"}

        def sub(p):
            return sub_cache.get(p.lstrip("/"), {})

        ms = ET.fromstring(z.read("Metadata/model_settings.config")) if "Metadata/model_settings.config" in names else None
        extras = {n: z.read(n) for n in PASSTHROUGH if n in names}
        layer_gcodes = _read_layer_gcodes(z.read(LAYER_GCODE_FILE)) if LAYER_GCODE_FILE in names else {}
        for n in ("Metadata/layer_heights_profile.txt", "Metadata/layer_config_ranges.xml"):
            if n in names:
                warnings.append(f"{n.split('/')[-1]} (variable layer height / height ranges) is not carried over")
        if any(n.startswith("Metadata/plate_") and n.endswith(".gcode") for n in names):
            warnings.append("the file contains sliced G-code: it will be re-sliced after changes")

    machine = cfg.get("printer_settings_id") or "Bambu Lab X1 Carbon 0.4 nozzle"
    if not presets.exists("machine", machine):
        warnings.append(f"printer preset '{machine}' not found, using P1S")
        machine = presets.machine_name("P1S")
    process = cfg.get("print_settings_id")
    if not process or not presets.exists("process", process):
        warnings.append(f"process preset '{process}' not found, using the printer default")
        process = None
    fil_names = cfg.get("filament_settings_id") or []
    colors = cfg.get("filament_colour") or ["#FFFFFF"] * len(fil_names)
    fils = []
    for i, n in enumerate(fil_names or ["Bambu PLA Basic @BBL X1C"]):
        if not presets.exists("filament", n):
            base = n.split(" @")[0]
            try:
                n = presets.filament_for(n, machine)
            except presets.PresetError:
                warnings.append(f"filament '{n}' not found, slot {i + 1} uses Generic PLA")
                n = presets.filament_for("Generic PLA", machine)
            else:
                warnings.append(f"filament '{base}...' mapped to '{n}'")
        fils.append((n, (colors[i] if i < len(colors) else "#FFFFFF")[:7]))
    proj = Project(name=path.rsplit("/", 1)[-1].rsplit(".", 1)[0], printer=machine, process=process, filaments=fils)
    proj.filaments = fils
    # project-level changes made by the author (keys listed in different_settings_to_system)
    diff = cfg.get("different_settings_to_system") or []
    keys = set()
    for d in diff:
        keys |= {k for k in (d or "").split(";") if k}
    for k in sorted(keys):
        if k in cfg:
            proj.overrides[k] = cfg[k]
    if cfg.get("curr_bed_type"):      # a project choice, not a preset setting: never listed in the diff above
        proj.overrides["curr_bed_type"] = cfg["curr_bed_type"]

    # objects from model_settings (names, parts, filaments, settings) + plates
    obj_meta, plates_meta = {}, []
    if ms is not None:
        for o in ms.findall("object"):
            parts = {p.get("id"): (p.get("subtype", "normal_part"), _meta(p)) for p in o.findall("part")}
            obj_meta[o.get("id")] = (_meta(o), parts)
        for pl in ms.findall("plate"):
            md = _meta(pl)
            inst = [(_meta(mi).get("object_id"), int(_meta(mi).get("instance_id") or 0))
                    for mi in pl.findall("model_instance")]
            plates_meta.append((md, inst))
    bed_w, bed_d = proj.info["bed"]
    n_plates = max(1, len(plates_meta))

    def world_parts(oid, m_item):
        kind = main.get(oid)
        out = []
        if kind is None:
            return out
        if kind[0] == "mesh":
            out.append((oid, m_item, kind[1], kind[2], kind[3]))
        else:
            for pth, cid, m_c in kind[1]:
                src = sub(pth) if pth else main
                mesh = src.get(cid)
                if mesh and mesh[0] == "mesh":
                    out.append((cid, m_item @ m_c, mesh[1], mesh[2], mesh[3]))
        return out

    built, seen = {}, {}
    for oid, m_item, printable in build:
        k_inst = seen.get(oid, 0)
        seen[oid] = k_inst + 1
        md, parts_md = obj_meta.get(oid, ({}, {}))
        parts = []
        for cid, m, verts, tris, attrs in world_parts(oid, m_item):
            subtype, pmd = parts_md.get(cid, ("normal_part", {}))
            fil = int(pmd.get("extruder") or md.get("extruder") or 1)
            keep = {k: v for k, v in pmd.items() if k not in ("name", "matrix", "extruder", "source_file",
                                                                   "source_object_id", "source_volume_id",
                                                                   "source_offset_x", "source_offset_y",
                                                                   "source_offset_z", "source_in_inches")}
            w = verts @ m[:3, :3].T + m[:3, 3]
            parts.append(Part(pmd.get("name") or f"Part {len(parts) + 1}", w, tris, fil, subtype, attrs, keep))
        if not parts:
            warnings.append(f"object {oid}: no mesh found, skipped")
            continue
        settings = {k: v for k, v in md.items() if k not in ("name", "extruder")}
        name = md.get("name") or f"Object {oid}"
        built[(oid, k_inst)] = Obj(name if k_inst == 0 else f"{name} {k_inst + 1}", parts, settings=settings)
        if printable == "0":
            warnings.append(f"'{name}' was marked not printable")

    proj.plates = []
    placed = set()
    for i, (md, inst) in enumerate(plates_meta or [({}, list(built))]):
        pl = Plate(md.get("plater_name") or f"Plate {i + 1}",
                   settings={k: v for k, v in md.items() if k in ("print_sequence", "bed_type", "first_layer_print_sequence",
                                                                  "spiral_mode", "nozzle_diameters")})
        origin = plate_origin(i, n_plates, bed_w)
        for key in inst:
            ob = built.get(key)
            if ob is None or key in placed:
                continue
            placed.add(key)
            lo, hi = ob.bbox()
            for p in ob.parts:
                p.verts = p.verts - origin
            lo, hi = ob.bbox()
            ob.at = (float((lo[0] + hi[0]) / 2), float((lo[1] + hi[1]) / 2))
            pl.objects.append(ob)
        proj.plates.append(pl)
    for key, ob in built.items():                     # objects not assigned to any plate
        if key not in placed:
            lo, hi = ob.bbox()
            ob.at = (float((lo[0] + hi[0]) / 2), float((lo[1] + hi[1]) / 2))
            proj.plates[0].objects.append(ob)
            warnings.append(f"'{ob.name}' was not on a plate: put on plate 1")
    if not proj.plates:
        proj.plates = [Plate("Plate 1")]
    if any(p.tri_attrs.get("paint_color") for _, o in proj.objects() for p in o.parts):
        warnings.append("painted colors are kept")
    for idx, items in layer_gcodes.items():
        if idx < len(proj.plates):
            proj.plates[idx].layer_gcodes = sorted(items, key=lambda g: g.z)
    proj.extras = extras
    proj.warnings = warnings
    proj.source_path = path
    return proj


def sliced_stats(path):
    """Per-plate time, weight and filaments from a sliced .3mf (Metadata/slice_info.config)."""
    with zipfile.ZipFile(path) as z:
        info = z.read("Metadata/slice_info.config").decode()
    plates = []
    for blk in re.findall(r"<plate>(.*?)</plate>", info, re.S):
        idx = int(re.search(r'key="index" value="(\d+)"', blk).group(1))
        pred = float((re.search(r'key="prediction" value="([\d.]+)"', blk) or [0, 0])[1])
        fil = {int(a): float(b) for a, b in re.findall(r'<filament id="(\d+)"[^>]*used_g="([\d.]+)"', blk)}
        m = re.search(r'key="weight" value="([\d.]+)"', blk)
        wt = float(m.group(1)) if m else sum(fil.values())
        warn = re.findall(r'<warning msg="([^"]+)"', blk)
        plates.append({"plate": idx, "minutes": round(pred / 60, 1), "grams": round(wt, 1),
                       "grams_per_filament": fil, "warnings": warn})
        pauses = int((re.search(r'key="pause_count" value="(\d+)"', blk) or [0, 0])[1])
        if pauses:
            plates[-1]["pauses"] = pauses
    return plates
