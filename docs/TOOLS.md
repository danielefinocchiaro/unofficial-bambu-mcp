# Tools

49 tools, generated from the server code by `scripts/gen_tools_doc.py`.

## `bambu_status`

Where Bambu Studio is installed, its version, whether it is running, and the current project.

## `list_printers`

Printer short names that can be used anywhere a printer is asked (a full machine preset name works too).

## `search_presets`

Find presets. kind: filament | process | machine. query: words to match (e.g. 'eSUN PLA+', '0.16mm').
With printer, only presets compatible with it. User presets come first.

| Parameter | Type | Default |
|---|---|---|
| `kind` | string | required |
| `query` | string | `''` |
| `printer` | string | `''` |
| `limit` | integer | `30` |

## `filament_colors`

Official colors (name, hex) of a Bambu filament line, e.g. 'Bambu PLA Basic @BBL X1C'.

| Parameter | Type | Default |
|---|---|---|
| `preset` | string | required |

## `new_project`

Start an empty project. filaments: AMS slots in order, e.g.
[{"preset": "Bambu PLA Basic", "color": "#000000"}, {"preset": "eSUN PLA+", "color": "#FFFFFF"}].
A filament name without '@...' is matched to the printer automatically. The build plate type is the one
picked in Bambu Studio for this printer (change it with set_setting('curr_bed_type', ...)).

| Parameter | Type | Default |
|---|---|---|
| `name` | string | required |
| `printer` | string | `'P1S'` |
| `process` | string | `''` |
| `filaments` | array / null | `None` |

## `open_project`

Open a .3mf saved by Bambu Studio (or downloaded from MakerWorld). The file is never modified:
save_project writes a new file. Returns the project summary and what could not be carried over.

| Parameter | Type | Default |
|---|---|---|
| `path` | string | required |

## `get_project`

Current project: printer, process, filament slots, plates, objects (id, name, center, size, filaments),
setting overrides and warnings. If the project was saved in Bambu Studio in the meantime it is re-read first.

## `set_printer`

Switch printer (e.g. P1S -> A1M). Filament presets are swapped for the same filaments on the new printer.
With rearrange, objects are re-placed to fit the new bed (extra plates are added if needed).

| Parameter | Type | Default |
|---|---|---|
| `printer` | string | required |
| `process` | string | `''` |
| `rearrange` | boolean | `True` |

## `set_filament`

Change one filament slot (1-based); a new slot number = add a slot. Leave a field empty to keep it.

| Parameter | Type | Default |
|---|---|---|
| `slot` | integer | required |
| `preset` | string | `''` |
| `color` | string | `''` |

## `add_plate`

Add an empty plate at the end.

| Parameter | Type | Default |
|---|---|---|
| `name` | string | `''` |

## `rename_plate`

Give a plate a name (shown in Bambu Studio).

| Parameter | Type | Default |
|---|---|---|
| `plate` | integer | required |
| `name` | string | required |

## `remove_plate`

Delete a plate. Its objects are moved to plate `move_objects_to` (0 = delete them too).

| Parameter | Type | Default |
|---|---|---|
| `plate` | integer | required |
| `move_objects_to` | integer | `0` |

## `import_model`

Put an STL, OBJ or 3MF on a plate. Without x/y it goes to the free spot closest to the center.
From a 3MF every object is imported (with its parts and filament assignments).

| Parameter | Type | Default |
|---|---|---|
| `path` | string | required |
| `plate` | integer | `1` |
| `x` | number / null | `None` |
| `y` | number / null | `None` |
| `rotate_z` | number | `0` |
| `scale` | number | `1.0` |
| `filament` | integer | `1` |
| `name` | string | `''` |

## `add_shape`

Create a simple solid: box (width, depth, height), cylinder (diameter, height), cone (diameter,
diameter_top, height), sphere (diameter), text (text, text_height = capital letters in mm, height = depth
of the letters; base > 0 puts the text on a plate that thick, as a separate part 'Base' with filament
base_filament (0 = same as the text), e.g. white letters on a black tag; font = path to a .ttf/.otf).

| Parameter | Type | Default |
|---|---|---|
| `shape` | string | required |
| `plate` | integer | `1` |
| `x` | number / null | `None` |
| `y` | number / null | `None` |
| `filament` | integer | `1` |
| `name` | string | `''` |
| `width` | number | `20` |
| `depth` | number | `20` |
| `height` | number | `20` |
| `diameter` | number | `20` |
| `diameter_top` | number | `0` |
| `text` | string | `''` |
| `text_height` | number | `10` |
| `font` | string | `''` |
| `base` | number | `0` |
| `base_filament` | integer | `0` |

## `move_object`

Move an object (by name or id): absolute x/y, relative dx/dy, rotate around Z by rotate_z degrees,
or move it to another plate (it keeps x/y if given, otherwise it goes to a free spot).

| Parameter | Type | Default |
|---|---|---|
| `object` | string | required |
| `x` | number / null | `None` |
| `y` | number / null | `None` |
| `dx` | number | `0` |
| `dy` | number | `0` |
| `rotate_z` | number | `0` |
| `plate` | integer | `0` |

## `transform_object`

Scale (uniform or per axis) and rotate an object around its center. It stays on the bed.

| Parameter | Type | Default |
|---|---|---|
| `object` | string | required |
| `scale` | number | `1.0` |
| `scale_xyz` | array / null | `None` |
| `rotate_x` | number | `0` |
| `rotate_y` | number | `0` |
| `rotate_z` | number | `0` |

## `duplicate_object`

Copy an object `copies` times onto free spots (same plate unless `plate` is given).

| Parameter | Type | Default |
|---|---|---|
| `object` | string | required |
| `copies` | integer | `1` |
| `plate` | integer | `0` |

## `delete_object`

Remove an object from the project.

| Parameter | Type | Default |
|---|---|---|
| `object` | string | required |

## `set_object_filament`

Assign a filament slot to a whole object, or to one of its parts (by part name).

| Parameter | Type | Default |
|---|---|---|
| `object` | string | required |
| `filament` | integer | required |
| `part` | string | `''` |

## `set_object_setting`

Per-object print setting (e.g. sparse_infill_density '40%', wall_loops '4', layer_height '0.12').
An empty value removes the override.

| Parameter | Type | Default |
|---|---|---|
| `object` | string | required |
| `key` | string | required |
| `value` | string | required |

## `check_object`

Is the mesh a closed, printable solid? Size, volume, number of separate pieces.

| Parameter | Type | Default |
|---|---|---|
| `object` | string | required |

## `arrange`

Re-place the objects of a plate (0 = all plates) close to the center without overlaps.
Objects that do not fit are moved to a new plate.

| Parameter | Type | Default |
|---|---|---|
| `plate` | integer | `0` |
| `gap` | number | `6.0` |

## `get_setting`

Current value of a print/filament/printer setting, where it comes from, and the preset value.

| Parameter | Type | Default |
|---|---|---|
| `key` | string | required |

## `set_setting`

Override a project setting. For filament settings (temperatures, plate temperatures...) slot = filament
slot (0 = all slots). Values are Bambu Studio strings, e.g. '0.16', '15%', '65'. Useful keys:
layer_height, wall_loops, sparse_infill_density, top_shell_layers, enable_support, brim_type,
initial_layer_speed, ironing_type, textured_plate_temp(_initial_layer) for Textured PEI,
hot_plate_temp(_initial_layer) for the smooth/High Temp plate, nozzle_temperature(_initial_layer),
close_fan_the_first_x_layers, print_sequence ('by object'), curr_bed_type ('Textured PEI Plate').

| Parameter | Type | Default |
|---|---|---|
| `key` | string | required |
| `value` | string | required |
| `slot` | integer | `0` |

## `reset_setting`

Drop an override: the setting goes back to the preset value.

| Parameter | Type | Default |
|---|---|---|
| `key` | string | required |

## `save_project`

Write the project as a Bambu Studio .3mf (default folder: the output dir, name from the project).
Never overwrites: if the file exists a -2, -3... suffix is added. Optionally open it in Bambu Studio.

| Parameter | Type | Default |
|---|---|---|
| `path` | string | `''` |
| `open_in_bambu` | boolean | `False` |

## `open_in_bambu_studio`

Open a .3mf in the Bambu Studio window: by default the last saved project (else the last sliced one).
Bambu Studio re-slices a project when asked (Slice plate), it does not reuse the slicing done here; to open
a plate sliced and ready to print, use send_to_printer(via='bambu_studio').

| Parameter | Type | Default |
|---|---|---|
| `path` | string | `''` |

## `slice_project`

Slice with Bambu Studio (plate 0 = all). Returns per plate: minutes, grams (total and per filament slot),
filament changes, layers and warnings. The sliced project is saved next to the project file.

| Parameter | Type | Default |
|---|---|---|
| `plate` | integer | `0` |

## `preview_plate`

Image of a plate with its objects in their filament colors (painted colors too).
view: iso | top. zoom: frame the objects instead of the whole bed, to see details.
labels: write each object's id and name on it, e.g. view='top', labels=True to tell which part is which
(a part that came off the plate, the list in Bambu Handy's skip objects).

| Parameter | Type | Default |
|---|---|---|
| `plate` | integer | `1` |
| `view` | string | `'iso'` |
| `zoom` | boolean | `False` |
| `labels` | boolean | `False` |

## `reprint_objects`

A new project with only some objects of the open one, e.g. a part that came off the plate and was skipped:
same printer, process, filaments and settings, laid out again (more plates if needed); brim=True gives each
an outer brim. Saved as a new file (never overwrites) and sliced; the open project is not changed:
open_project(file) then send_to_printer to print it. objects: names or ids (see get_project).

| Parameter | Type | Default |
|---|---|---|
| `objects` | array | required |
| `brim` | boolean | `True` |
| `name` | string | `''` |
| `slice` | boolean | `True` |

## `preview_layer`

Image of one sliced layer seen from the top (needs slice_project first). Choose by layer number (1 = first)
or by height z in mm. Extrusions are drawn in the filament colors. zoom: frame the extrusions (default),
or False for the whole bed.

| Parameter | Type | Default |
|---|---|---|
| `plate` | integer | `1` |
| `layer` | integer | `0` |
| `z` | number | `0` |
| `zoom` | boolean | `True` |

## `make_first_layer_test`

Add a plate with the first `height` mm of the objects of a plate (or of the listed objects):
a short print to check bed adhesion and the first layers before a long print. Slice it with
slice_project(plate=<new plate>).

| Parameter | Type | Default |
|---|---|---|
| `plate` | integer | `1` |
| `height` | number | `0.8` |
| `objects` | array / null | `None` |

## `send_to_printer`

Prepare the print file of one plate (.gcode.3mf) and hand it to an official Bambu app, where the user
checks printer and AMS mapping and presses Print/Send. Nothing starts printing by itself.
via: auto (Bambu Connect if installed, otherwise Bambu Studio) | bambu_connect | bambu_studio | file (only export).
Tell the user what to press, and the time, weight and filaments of the plate.

| Parameter | Type | Default |
|---|---|---|
| `plate` | integer | `1` |
| `via` | string | `'auto'` |

## `printer_status`

Read-only status of the printer on the local network: state, job, progress, remaining time, layer
(or the last job's result when idle), temperatures, AMS trays (type, color, remaining %; 'unknown' = a spool
the AMS has not been told about), AMS humidity and temperature, active slot, errors. Works with the printer in normal
cloud mode (Bambu Handy keeps working). Nothing is sent to the printer except a status request.

## `use_ams_filaments`

Set the project's filament slots from what is loaded in the AMS right now (preset and color), like
Bambu Studio's 'sync AMS'. Default: every loaded tray in order (project slot 1 = first loaded tray).
ams_slots: pick trays explicitly, e.g. [1, 3] -> project slot 1 = AMS slot 1, project slot 2 = AMS slot 3.

| Parameter | Type | Default |
|---|---|---|
| `ams_slots` | array / null | `None` |

## `add_layer_action`

Do something when the print reaches height z (mm), before that layer is printed:
action = pause (e.g. to insert magnets or nuts; message is shown in Bambu Studio),
filament_change (switch to filament slot `filament` from that height on, with the AMS),
gcode (any G-code line(s), e.g. 'M104 S210'). z is snapped to the nearest real layer at or above it.

| Parameter | Type | Default |
|---|---|---|
| `plate` | integer | required |
| `z` | number | required |
| `action` | string | required |
| `filament` | integer | `0` |
| `gcode` | string | `''` |
| `message` | string | `''` |

## `remove_layer_action`

Remove a layer action (1-based index as listed by get_project), or all of them with index 0.

| Parameter | Type | Default |
|---|---|---|
| `plate` | integer | required |
| `index` | integer | `0` |

## `make_temperature_tower`

Add a plate with a temperature tower for a filament slot: one 8 mm block per temperature (hottest at the
bottom), each with a bridge and its temperature engraved on the front. Defaults: the filament's
temperature +15 down to -25 °C, within its allowed range. Pick the block with the best bridge, surface and
least stringing.

| Parameter | Type | Default |
|---|---|---|
| `filament` | integer | `1` |
| `start` | number | `0` |
| `end` | number | `0` |
| `step` | number | `5` |

## `make_flow_test`

Add a plate of flow-rate squares for a filament slot, each printed with a different flow modifier (percent)
engraved on top. Pass 1: -20..+20 step 5. Pass 2: around the best one, e.g. low=-4 high=4 step=1.
Pick the square with the smoothest top surface (no gaps, no ridges).

| Parameter | Type | Default |
|---|---|---|
| `filament` | integer | `1` |
| `low` | number | `-20` |
| `high` | number | `20` |
| `step` | number | `5` |

## `make_pa_tower`

Add a plate with a pressure advance (flow dynamics) tower: a thin square tube printed fast, the K value grows
by `step` every millimeter. Find the height with the sharpest corners and no gaps: K = start + floor(height) * step.
When sending it, turn off the printer's automatic flow dynamics calibration.

| Parameter | Type | Default |
|---|---|---|
| `filament` | integer | `1` |
| `start` | number | `0.0` |
| `end` | number | `0.06` |
| `step` | number | `0.004` |

## `save_filament_preset`

Save the filament of a slot, with this project's changes for that slot (temperatures, flow ratio, plate
temperatures...), as a Bambu Studio user preset; it appears after Bambu Studio restarts.
A new filament (made from a Generic preset, or with another filament_vendor) is saved like Bambu Studio's
Create Filament does: its own filament id, so it can be picked for an AMS slot (Device > AMS). Changes to a
Bambu filament are saved as a variant of it, so its RFID spools still match it.
replace=True updates an existing user preset with that name (e.g. after a calibration): it keeps its
filament id, so AMS slots set to it stay valid, and a backup copy is kept. Never overwrites otherwise.

| Parameter | Type | Default |
|---|---|---|
| `slot` | integer | required |
| `name` | string | required |
| `replace` | boolean | `False` |

## `sync_with_bambu_studio`

Re-read the project file after you changed it by hand in Bambu Studio and saved (same file).
This also happens automatically on the next command when there are no unsaved changes here;
force=True takes the app's version even if there are (they are lost).

| Parameter | Type | Default |
|---|---|---|
| `force` | boolean | `False` |

## `mirror_object`

Mirror an object across its own center (axis x, y or z).

| Parameter | Type | Default |
|---|---|---|
| `object` | string | required |
| `axis` | string | `'x'` |

## `lay_flat`

Rotate an object so one of its flat faces lies on the bed: face 1 = the biggest flat face,
2 = the second biggest, and so on.

| Parameter | Type | Default |
|---|---|---|
| `object` | string | required |
| `face` | integer | `1` |

## `cut_object`

Cut an object horizontally at height z (mm from its bottom). keep: both | bottom | top. With flip_top the top
piece is turned upside down so it prints on the flat cut face. Modifiers and painted colors are not kept.

| Parameter | Type | Default |
|---|---|---|
| `object` | string | required |
| `z` | number | required |
| `keep` | string | `'both'` |
| `flip_top` | boolean | `True` |

## `add_modifier`

Add a part to an object, covering its whole footprint between z_from and z_to (mm from the
object's bottom; z_to 0 = top), or only region [x0, y0, x1, y1] (mm from the object's center).
kind: modifier (different settings inside, e.g. {"sparse_infill_density": "100%"} for the top 5 mm),
negative (removes material), support_blocker, support_enforcer.
shape: box, or cylinder (round, as wide as the smaller side of the region: e.g. a hole for a magnet or a
screw is kind='negative', shape='cylinder', region=[-4, -4, 4, 4] for 8 mm).

| Parameter | Type | Default |
|---|---|---|
| `object` | string | required |
| `settings` | object / null | `None` |
| `kind` | string | `'modifier'` |
| `z_from` | number | `0` |
| `z_to` | number | `0` |
| `region` | array / null | `None` |
| `shape` | string | `'box'` |

## `remove_part`

Remove a part (e.g. a modifier) from an object, by part name. The last solid part cannot be removed.

| Parameter | Type | Default |
|---|---|---|
| `object` | string | required |
| `part` | string | required |

## `make_max_flow_test`

Max volumetric speed test for a filament slot, as a separate project file (the open project is not changed):
single-wall cylinders, each printed at the wall speed that gives the volumetric speed Q (mm³/s) on its tag.
Default range: around the filament's current limit. The highest Q without gaps or weak walls is the max;
use a bit less (about 90%) as filament_max_volumetric_speed.

| Parameter | Type | Default |
|---|---|---|
| `filament` | integer | `1` |
| `low` | number | `0` |
| `high` | number | `0` |
| `step` | number | `2` |

## `make_retraction_test`

Stringing test for a filament slot: one small separate project per retraction length (Bambu printers cannot
change retraction during a print). Print them one after the other and keep the shortest length without strings
between the two pillars; then set_setting('filament_retraction_length', value, slot) or save_filament_preset.

| Parameter | Type | Default |
|---|---|---|
| `filament` | integer | `1` |
| `lengths` | array / null | `None` |
