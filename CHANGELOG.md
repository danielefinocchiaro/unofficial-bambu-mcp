# Changelog

## 0.3.0 (unreleased)

Tested on a P1S with two AMS units: calibration prints for two third-party filaments, live printer status during
prints, projects downloaded from MakerWorld and Printables.

Added
- `reprint_objects`: a new project with only some objects (e.g. a part that came off), with a brim.
- `check_print_risks`: tall and narrow parts, parts on a tiny or narrow footing without a brim, filaments not meant
  for the build plate, tall parts sharing a long plate.
- `preview_plate(labels=True)`: object ids and names on the image.
- `printer_status`: warnings (unknown spool being fed, spool not matching the project, sport speed on a long print),
  skipped objects, AMS humidity in % and temperature, the previous job's result when idle, user filament names.
- `add_shape(text, base_filament=…)`: text on a base of another color, as separate parts.
- `add_modifier(shape="cylinder")`: round modifiers and holes.
- `save_filament_preset`: new filaments saved like Bambu Studio's Create Filament (own filament id, so they can be
  picked for an AMS slot); `replace=True` updates a preset in place, same id, with a backup.
- `preview_layer` frames the extrusions by default; slicing reports pauses.
- Previews darken recesses, so engraved numbers (temperature tower, flow squares) can be read.
- `scripts/make_demo.py`: the README demo, made by driving the server through an MCP client.
- `add_brim_ears` / `remove_brim_ears`: brim ears (Bambu Studio's Painted brim, `Metadata/brim_ear_points.txt`)
  only on the thin tips of the first layer, sized so they reach no other piece, joint gap or hole; or at given
  points. Kept when opening and saving files, drawn in `preview_plate`. Tested on a print-in-place skeleton:
  ears on all ten fingertips, no brim in the joint gaps of the sliced first layer.
- `check_print_risks` warns when a full brim would weld a print-in-place model and suggests ears.
- `arrange` places objects by their real outline seen from above, with brim and brim ears, on a 0.5 mm grid
  (FFT collision test), lowest place first, then centers each plate and checks the exact distances. Options like
  Bambu Studio's Arrange dialog: gap, rotation (any step), one material per plate, avoid the calibration corner,
  align to Y; the prime tower corner stays free on plates with several materials; one plate, given objects or
  all; `plates` N spreads them evenly over N plates, -1 uses as few as possible. If they do not fit, nothing is
  moved and the answer lists what is left over and how many plates are needed. 18 snowflakes with brim ears now
  go in 2 plates (the old rectangles needed 3); Bambu Studio's command line, on hulls, needs 2 mm gaps for that.
- `get_purge_volumes` / `set_purge_volumes`: purge volumes per pair of slots and multiplier; the values of an
  opened file are kept (they were replaced by the estimate from the colors).
- `cut_object` cuts on any plane and adds connectors, like Bambu Studio's Cut tool: plug (peg and hole with
  clearance), dowel (holes in both pieces, pins as a separate object) or dovetail; cylinder, square or hexagon,
  prism or frustum, chamfered; placed one per piece of the cut (two along a long one), N spread over it, or at
  given points; holes keep 2 mm from the edge and 1 mm of material below, and get shallower where a piece is thin.
  The peg goes on the piece whose cut face is up. Modifiers and negative parts are cut with the object, and
  painted colors, seams and supports stay on the pieces (manifold3d tells which original triangle each new one
  comes from; a triangle split by the cut takes the color covering most of it).
- New projects use the build plate picked in Bambu Studio for that printer (`build_plate` in the summary).
- `orient_object`: auto orientation, scored on the area that needs support, the area on the bed and the height
  (candidates: the big flat faces of the hull and directions spread over the sphere); the 3 best options are
  listed and can be picked. A painted gnome tipped by 70° comes back upright.
- `fill_plate`: fill the plate with copies, by the real outline on `arrange`'s grid (61 discs of 25 mm on a P1S).
- `split_object` (into objects or parts), `merge_objects`, `boolean_objects` (difference, union, intersection),
  with painted triangles kept; a warning when the two objects do not touch.
- `make_vfa_test`: blocks with their own outer wall speed (40-200 mm/s), the speed engraved on top, and a note when
  the filament's max volumetric speed caps them.
- `slice_project` gives the cost per plate and per filament, from the presets' price per kg.
- `set_height_range` / `remove_height_range`: settings per height band (`Metadata/layer_config_ranges.xml`):
  infill, walls, layer height (variable layer height) or filament (color by height). Opened files keep their
  ranges and their variable layer height profile (both were dropped before).
- `set_plate_settings`: build plate, print sequence, first-layer filament order, spiral vase, prime tower place.
- `paint_object`: color, support, block support, seam, block seam and fuzzy skin painting on a height band and/or
  faces looking one way (top, bottom, sides, front, back, left, right, overhangs); triangles crossing a band edge are
  split so the edge is sharp. Fuzzy skin painting in opened files is kept (it was dropped).
- `export_stl`, `replace_with_stl`, `align_objects`, `convert_units`, `set_object_printable`, `set_part_type`,
  `copy_object_settings`: the small object tools of Bambu Studio's menus.
- `measure_object` / `measure_between`: sizes, cross-sections (length, width, thickest point, holes), clearances
  between the pieces of print-in-place models, walls thinner than the line width, gaps between objects or parts.
- `printer_camera`: a picture from the camera (P1/A1, port 6000), in cloud mode too.
- `printer_files`, `download_printer_file` (a timelapse comes with its last frame) and `delete_printer_files` (by name
  or age, two steps with a code tied to the exact files, refused during a print): the SD card over FTPS.
- `save_process_preset` / `save_printer_preset`: the project's process or printer changes as a Bambu Studio user
  preset, a child of the project's preset like *Save as*; `replace=True` updates it, with a backup.
- `edit_preset`, `list_user_presets`, `rename_preset`, `delete_preset`: your user presets without a project. Keys
  and values are checked (kind of preset, number or not, one value per extruder variant), `null` goes back to the
  parent's value, and every change keeps a backup (`UBMCP_PRESET_BACKUPS`). Changes are stamped in the `.info` file
  so Bambu Studio uploads them to the Bambu cloud at its next start; presets that are in the cloud are not deleted
  or renamed, because Bambu Studio would download them again, and the answer says how to do it in Bambu Studio.

Fixed
- Tool errors reach the assistant with their message (the MCP SDK hid everything but `ToolError`).
- Bambu Studio 1.6/1.7 projects open (objects in separate model files, undeclared XML prefixes); the author's
  printer settings (e.g. another printer's start G-code) are dropped when the printer is replaced.
- The build plate type is kept when reading a 3MF; print files pin it, so Bambu Studio keeps the slicing.
- Slicing all plates works with empty plates; calibration plates reuse an empty plate.
- Object ids are stable when objects move between plates.
- `x.gcode.3mf` is renamed `x-2.gcode.3mf`, not `x.gcode-2.3mf`; print files carry the printer model id.
- Previews use a z-buffer (a big face under small ones was drawn on top of them).
- Bambu Studio started with a file at cold start no longer stays without a window.
- AMS spools without RFID that were never set are `unknown`, not empty.
- Calibration prints: larger, deeper numbers on the temperature tower and the flow squares.
- `check_print_risks` no longer advises a brim to a part that already has one.
- `save_filament_preset` dropped `pressure_advance` and `enable_pressure_advance` and answered "saved" with
  nothing in it: Bambu profiles never write these keys, so they were not known as filament settings. They are now
  set per slot (in projects with several filaments too) and saved; `replace=True` with no changes is an error and
  leaves the file alone. Bambu printers ignore a preset's K (no M900 in the G-code): the answer says so.
- User presets saved, renamed or deleted in Bambu Studio while the server runs are seen at the next call (the
  list of presets was read once): `list_user_presets` failed on a deleted file, and a project whose preset was
  deleted now says which slot to change.
- `printer_status` kept the first full report and gave it again for 20 s without saying so: it now waits for the
  first change sent after it (P1 printers send only what changed, every 2-4 s), merges by sequence number, says
  when the reading was taken (`read_at`, `age_s`), and warns when a report looks old (no change while the nozzle
  heats or cools, the same report twice) or says "printing" with the heaters off.
- Opened projects keep where the prime tower of each plate was (`wipe_tower_x/y`): Bambu Studio never lists them
  among the changed settings, so they were reset to a corner and a tower placed between objects collided with them.
  `arrange` and `fill_plate` still move it to the corner they keep free; switching printer resets it.
- A Bambu Studio command line that hangs (no CPU use for 90 s) is closed with a clear error instead of waiting up
  to 30 minutes; while it hung, macOS took it for the running app and Bambu Studio could not open files.
  `open_in_bambu_studio` starts the app itself when only command-line runs are alive.
- `cut_object`: the upper piece lies on its cut face (with `flip_top`, the default, it was turned upside down onto
  its top). `flip_top` is replaced by `place` (auto, cut_down, keep).

## 0.2.0 (unreleased)

- Calibration plates for any filament: temperature tower (M104 per block, temperatures engraved), flow rate test
  (per-object `print_flow_ratio`, modifier engraved), pressure advance tower (M900 K every millimeter).
- Layer actions: pause, AMS filament change and custom G-code at a height, read from and written to
  `Metadata/custom_gcode_per_layer.xml` in Bambu Studio's format.
- `save_filament_preset`: save a slot's tuned settings as a Bambu Studio user preset (never overwrites).
- `mirror_object`, `lay_flat` (biggest flat face of the convex hull on the bed), `cut_object` (horizontal cut,
  top piece flipped onto the cut face).
- `add_modifier` / `remove_part`: box modifiers with settings, negative parts, support blockers/enforcers.
- `make_max_flow_test` (single-wall cylinders at increasing volumetric speed) and `make_retraction_test` (one small
  stringing test per retraction length), as separate project files.
- Sync with Bambu Studio: the project file is re-read when it was saved in the app and there are no unsaved changes;
  conflicts are reported; `sync_with_bambu_studio` to force it.

## 0.1.0 (unreleased)

First version, tested on macOS with Bambu Studio 2.8 and a P1S / A1 mini setup.

- Projects: new, open any Bambu Studio / MakerWorld .3mf (painted colors, modifiers, per-object settings and
  instances kept), save without overwriting.
- Plates and objects: add, rename, remove, import STL/OBJ/3MF, primitives and text, move, rotate, scale,
  duplicate, arrange, filament per object or part, per-object settings, solid check.
- Presets resolved like Bambu Studio (inherits, include, user presets); filaments matched to the printer.
- Printer switch with automatic re-layout (e.g. P1S -> A1 mini).
- Slicing through the Bambu Studio CLI: time, grams per filament, filament changes, layers, warnings.
- Previews: plate (iso/top, zoom) and sliced layers.
- First-layer test plate generator.
- Experimental: `send_to_printer` (plate exported as .gcode.3mf and opened in Bambu Connect or Bambu Studio),
  `printer_status` and `use_ams_filaments` (read-only status over the local network).
