# Tools

74 tools, generated from the server code by `scripts/gen_tools_doc.py`.

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

## `set_plate_settings`

Settings of one plate, like Bambu Studio's plate settings; they win over the project's on that plate.
bed_type: Cool Plate, Engineering Plate, High Temp Plate, Textured PEI Plate or Supertack Plate.
print_sequence: 'by layer', or 'by object' (each object printed to the end before the next).
first_layer_filaments: order of the filament slots on the first layer, e.g. [2, 1].
spiral_vase: 'on' or 'off'. prime_tower: [x, y] in mm, where its corner goes (e.g. between objects).
'global' (or [] for the lists) goes back to the project's choice; empty leaves it as it is.

| Parameter | Type | Default |
|---|---|---|
| `plate` | integer | required |
| `bed_type` | string | `''` |
| `print_sequence` | string | `''` |
| `first_layer_filaments` | array / null | `None` |
| `spiral_vase` | string | `''` |
| `prime_tower` | array / null | `None` |

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

## `fill_plate`

Fill the free area of an object's plate with copies of it, like Bambu Studio's Fill bed with copies.
copies: 0 = as many as fit, N = at most N. Shapes nest by their real outline (brim and brim ears counted), and
rotate=True also tries turning them by rotation_step degrees. The original is placed again together with the
copies (more fit), unless keep_original=True; the other objects on the plate stay where they are.

| Parameter | Type | Default |
|---|---|---|
| `object` | string | required |
| `copies` | integer | `0` |
| `gap` | number | `6.0` |
| `rotate` | boolean | `False` |
| `rotation_step` | number | `90.0` |
| `keep_original` | boolean | `False` |

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

Arrange objects by their real outline seen from above, brim and brim ears included, so shapes can nest
(like Bambu Studio's Arrange, which only uses convex hulls). gap: mm between those outlines (and from the
plate's edge half of it). Which objects: plate N, the named `objects` (ids or names), or all (plate=0).
plates: 0 = each object stays on its plate; N = spread them over plates 1..N, evenly; -1 = as few plates as
possible. rotate: allow turning them by multiples of rotation_step degrees (e.g. 60 for snowflakes);
multi_material false = one material (set of filaments) per plate; avoid_calibration_area: keep off the
printer's flow calibration corner (P1S/X1: front left); align_to_y: long side along Y first.
Plates with more than one material keep the back right corner free for the prime tower.
If something does not fit, nothing is moved: the answer says what is left over and how many plates it needs.
Objects not being arranged stay where they are. Look at preview_plate(view='top') afterwards.

| Parameter | Type | Default |
|---|---|---|
| `plate` | integer | `0` |
| `objects` | array / null | `None` |
| `plates` | integer | `0` |
| `gap` | number | `6.0` |
| `rotate` | boolean | `False` |
| `rotation_step` | number | `90.0` |
| `multi_material` | boolean | `True` |
| `avoid_calibration_area` | boolean | `True` |
| `align_to_y` | boolean | `False` |

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

## `get_purge_volumes`

Purge (flush) volumes between filament slots, in mm³, and the multiplier: the filament wasted at each
change on the prime tower (or into infill/objects, see set_purge_volumes).

## `set_purge_volumes`

Change the purge (flush) volumes, as in Bambu Studio's Purging volumes dialog.
volumes: [{"from": 1, "to": 2, "volume": 350}, ...] mm³ for single changes; matrix: every value at once,
rows = from, columns = to (the diagonal is ignored); multiplier: scales all of them (0..3, 1 = as written);
reset: back to the values estimated from the colors and multiplier 1. A value set by hand stays while both
slots keep their color. Values are 0..900 mm³. Less purge saves filament but the new color can come out mixed
at first; to waste less without that, purge into the infill or into an object with
set_setting('flush_into_infill', '1') or set_object_setting(object, 'flush_into_objects', '1').

| Parameter | Type | Default |
|---|---|---|
| `volumes` | array / null | `None` |
| `matrix` | array / null | `None` |
| `multiplier` | number | `0` |
| `reset` | boolean | `False` |

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
cost (from the presets' price per kg), filament changes, layers and warnings. The sliced project is saved next to the project file.

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

## `check_print_risks`

Before a long print: parts likely to come off or topple, and settings that do not fit. Per plate (0 = all):
tall and narrow parts (height against the smaller side of the footprint), parts standing on a narrow or tiny
footing without a brim (e.g. pins lying on their side), filaments whose temperature for this build plate is 0
(not meant for it), and plates where tall parts share a long print with many others (a part that fails late can
knock the others: print them apart).

| Parameter | Type | Default |
|---|---|---|
| `plate` | integer | `0` |

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
the AMS has not been told about), AMS humidity and temperature, active slot, errors, objects skipped during the
print, and warnings (the spool being fed is unknown or not the project's filament, sport speed on a long print,
a report that looks old). read_at = when the printer sent it; age_s = seconds since, when a reading of a few
seconds ago is given again (the printer is asked at most every 20 s).
Works with the printer in normal cloud mode (Bambu Handy keeps working). Nothing is sent to the printer except a
status request.

## `printer_camera`

A picture from the printer's camera right now (P1 and A1 series), to see the plate: how a print is going,
whether something came off or made spaghetti, what is left on the bed. Read-only; works with the printer in
cloud mode. With the chamber light off the picture is dark. max_size: longest side in pixels.

| Parameter | Type | Default |
|---|---|---|
| `max_size` | integer | `1280` |

## `printer_files`

Files on the printer's SD card, newest first, with name, size and date and the total per folder:
timelapse (videos of past prints), prints (files of past prints the printer keeps), thumbnails (timelapse
thumbnails whose video was deleted). Read-only; works with the printer in cloud mode.

| Parameter | Type | Default |
|---|---|---|
| `kind` | string | `'all'` |
| `limit` | integer | `30` |

## `download_printer_file`

Copy a file from the printer's SD card into the projects folder: a timelapse video (name from printer_files,
or 'latest') or the file of a past print (kind='prints'). For a timelapse its last frame is shown too: the
finished print. Read-only on the printer.

| Parameter | Type | Default |
|---|---|---|
| `name` | string | `'latest'` |
| `kind` | string | `'timelapse'` |

## `delete_printer_files`

Free space on the printer's SD card: delete timelapse videos (with their thumbnails), files of past prints
(kind='prints') or thumbnails whose video is gone (kind='thumbnails'). Pick them by names (from printer_files)
or all those older than older_than_days. Two steps: without confirm nothing is deleted, the answer lists what
would go, the space freed and a code; show the list to the user and only if they agree call again with
confirm=<code>. Deleted files cannot be recovered. Nothing is deleted while a print is running.

| Parameter | Type | Default |
|---|---|---|
| `kind` | string | required |
| `names` | array / null | `None` |
| `older_than_days` | integer | `0` |
| `confirm` | string | `''` |

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

## `make_vfa_test`

Add a plate with a VFA test (vertical fine artifacts: fine vertical ripples on walls that some speeds cause):
one block per outer wall speed from start to end mm/s, the speed engraved on top. Look at the long faces with
light from the side and pick the fastest speed without ripples for outer_wall_speed. Bambu Studio's VFA tower
changes the speed inside one object; here each block has its own speed.

| Parameter | Type | Default |
|---|---|---|
| `filament` | integer | `1` |
| `start` | number | `40` |
| `end` | number | `200` |
| `step` | number | `20` |

## `save_filament_preset`

Save the filament of a slot, with this project's changes for that slot (temperatures, flow ratio, pressure
advance, plate temperatures...), as a Bambu Studio user preset; it appears after Bambu Studio restarts.
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

## `save_process_preset`

Save this project's process changes (layer height, walls, infill, speeds, brim, supports, ironing...:
the set_setting changes that belong to the process) as a Bambu Studio user process preset, a child of the
project's process preset, like Save as in Bambu Studio. replace=True updates your user preset with that name
(a backup copy is kept). It appears after Bambu Studio restarts.

| Parameter | Type | Default |
|---|---|---|
| `name` | string | required |
| `replace` | boolean | `False` |

## `save_printer_preset`

Save this project's printer changes (start/end G-code, retraction, printable area...: the set_setting
changes that belong to the printer) as a Bambu Studio user printer preset, a child of the project's printer
preset. replace=True updates your user preset with that name (a backup copy is kept). It appears after
Bambu Studio restarts.

| Parameter | Type | Default |
|---|---|---|
| `name` | string | required |
| `replace` | boolean | `False` |

## `list_user_presets`

Your own Bambu Studio presets (kind: filament | process | printer; empty = all): the preset each one
inherits and what it changes, whether it is in your Bambu cloud (then only Bambu Studio can delete or
rename it), and which presets inherit it. To find system presets too, use search_presets.

| Parameter | Type | Default |
|---|---|---|
| `kind` | string | `''` |

## `edit_preset`

Change settings of one of your user presets directly, without a project (a backup copy is kept).
kind: filament | process | printer. values: {"key": "value"}, e.g. {"pressure_advance": "0.025",
"enable_pressure_advance": "1"} or {"nozzle_temperature": "215"}; a list gives one value per extruder variant
(Standard / High Flow nozzle); null removes the key, so the value comes from the parent preset again.
Bambu system presets are read-only: save a user preset from them first. Bambu Studio sees the change after it
restarts, and uploads it to your Bambu cloud if the preset is there.

| Parameter | Type | Default |
|---|---|---|
| `kind` | string | required |
| `name` | string | required |
| `values` | object | required |

## `rename_preset`

Rename one of your user presets (a backup copy is kept). A preset in your Bambu cloud cannot be renamed
from here, because Bambu Studio would download the old one again: the answer says how to do it in Bambu
Studio.

| Parameter | Type | Default |
|---|---|---|
| `kind` | string | required |
| `name` | string | required |
| `new_name` | string | required |

## `delete_preset`

Delete one of your user presets (a backup copy is kept, see the answer). A preset in your Bambu cloud
cannot be deleted from here, because Bambu Studio would download it again at its next start: only its own
Delete removes the cloud copy, and the answer says where it is.

| Parameter | Type | Default |
|---|---|---|
| `kind` | string | required |
| `name` | string | required |

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

## `orient_object`

Turn an object the way up it prints best, like Bambu Studio's Auto orientation: least area that needs support
(faces leaning more than overhang_angle degrees from vertical, not on the bed), enough area on the bed, low
height. Returns the 3 best options with those numbers and the current ones; choice=2 or 3 applies another
option, apply=False only compares. Look at preview_plate afterwards.

| Parameter | Type | Default |
|---|---|---|
| `object` | string | required |
| `choice` | integer | `1` |
| `overhang_angle` | number | `45.0` |
| `apply` | boolean | `True` |

## `split_object`

Split an object into its separate pieces, like Bambu Studio's Split: into='objects' makes one object per
piece (each part of a multi-part object becomes an object too), into='parts' keeps one object whose parts are
the pieces, so each can get its own filament. Pieces stay where they are; painted colors are kept, modifiers
and negative parts go with the piece they overlap.

| Parameter | Type | Default |
|---|---|---|
| `object` | string | required |
| `into` | string | `'objects'` |

## `merge_objects`

Join objects of the same plate into one object with several parts, where they are now, like Bambu Studio's
Assemble: they move and print as one (e.g. a model and its base in another color). Each part keeps its filament
and painting; the merged object takes the first object's settings (the others' are listed if they differ).

| Parameter | Type | Default |
|---|---|---|
| `objects` | array | required |
| `name` | string | `''` |

## `boolean_objects`

Mesh boolean between two objects where they are on the plate, like Bambu Studio's Mesh boolean.
difference: cut tool_object's shape out of object (a hole, a slot, a lettering); intersection: keep only what
they share; union: weld tool_object onto object (onto its part `part`, default the biggest). The result keeps
object's name, settings and filaments; painted colors stay, new faces take the part's filament. The tool object
is removed unless keep_tool=True. Both must be closed solids (check_object).

| Parameter | Type | Default |
|---|---|---|
| `object` | string | required |
| `tool_object` | string | required |
| `operation` | string | `'difference'` |
| `keep_tool` | boolean | `False` |
| `part` | string | `''` |

## `cut_object`

Cut an object with a plane, optionally with connectors that line the pieces up for gluing (like the
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
Modifiers, negative parts and painted colors are kept on the pieces.

| Parameter | Type | Default |
|---|---|---|
| `object` | string | required |
| `z` | number | `0` |
| `keep` | string | `'both'` |
| `normal` | array / null | `None` |
| `point` | array / null | `None` |
| `place` | string | `'auto'` |
| `connector` | string | `'none'` |
| `shape` | string | `'cylinder'` |
| `style` | string | `'prism'` |
| `size` | number | `0` |
| `depth` | number | `0` |
| `count` | integer | `0` |
| `positions` | array / null | `None` |
| `clearance` | number | `0.2` |

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

## `add_brim_ears`

Brim ears: small round brims only where a part needs them, instead of a brim all around (Bambu Studio's
Painted brim). Meant for print-in-place and articulated models: a full brim fills the joint gaps on the first
layer and welds them. Without points, ears go to the tips of the thin parts of the first layer (fingers, toes,
any tip thinner than `narrow` mm), each as large as possible up to `radius` without reaching another piece, a
gap or hole, or a second thin part (those tips are listed as skipped, with the reason). small > 0 also gives
ears to first-layer pieces smaller than that (mm²), at their ends. points: [[x, y], ...] or [[x, y, radius]]
in plate mm, placed as given, with a warning when one would weld something. radius 0 = Bambu Studio's default
(16 first-layer line widths across). keep: add to the ears the object already has.
Look at them with preview_plate(view='top', zoom=True), then slice_project and preview_layer(layer=1).

| Parameter | Type | Default |
|---|---|---|
| `object` | string | required |
| `points` | array / null | `None` |
| `radius` | number | `0` |
| `narrow` | number | `3.0` |
| `small` | number | `0` |
| `clearance` | number | `0.6` |
| `keep` | boolean | `False` |

## `remove_brim_ears`

Remove an object's brim ears; its brim goes back to the project's brim type.

| Parameter | Type | Default |
|---|---|---|
| `object` | string | required |

## `set_height_range`

Settings for a height band of an object, like Bambu Studio's Height range modifier. Heights are mm from the
object's bottom. E.g. z_from=0, z_to=5, settings={"sparse_infill_density": "100%"}; {"layer_height": "0.12"}
for finer layers there (variable layer height); {"filament": 2} to print that band with another filament slot
(a color band). A band with the same z_from and z_to is updated (null removes a key); bands cannot overlap.

| Parameter | Type | Default |
|---|---|---|
| `object` | string | required |
| `z_from` | number | required |
| `z_to` | number | required |
| `settings` | object | required |

## `remove_height_range`

Remove the height band of an object that starts at z_from (mm), or all its bands (z_from=-1).

| Parameter | Type | Default |
|---|---|---|
| `object` | string | required |
| `z_from` | number | `-1` |

## `paint_object`

Paint a region of an object, like Bambu Studio's painting tools. paint: 'color' (with filament=N),
'support' (supports there), 'block_support' (none there), 'seam' (put the seam there), 'block_seam',
'fuzzy_skin'. Region: the height band z_from..z_to (mm from the object's bottom; z_to=0 = to the top) and the
faces looking 'top', 'bottom', 'sides', 'front', 'back', 'left', 'right', 'overhangs' (leaning more than `angle`
degrees from vertical, for supports) or 'all'. clear=True removes that painting there. Triangles crossing a
band's edge are split, so the edge is sharp. part: only that part. Look at preview_plate (colors) afterwards.

| Parameter | Type | Default |
|---|---|---|
| `object` | string | required |
| `paint` | string | required |
| `filament` | integer | `0` |
| `z_from` | number | `0` |
| `z_to` | number | `0` |
| `facing` | string | `'all'` |
| `angle` | number | `45.0` |
| `clear` | boolean | `False` |
| `part` | string | `''` |

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
