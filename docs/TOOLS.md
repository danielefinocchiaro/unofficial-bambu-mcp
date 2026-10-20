# Tools

31 tools, generated from the server code by `scripts/gen_tools_doc.py`.

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
A filament name without '@...' is matched to the printer automatically.

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
setting overrides and warnings.

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
of the letters; base > 0 puts the text on a plate that thick; font = path to a .ttf/.otf).

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

Open a .3mf in the Bambu Studio window: by default the last sliced file (to see the preview there),
otherwise the last saved one. Bambu Studio may ask what to do with the project already open.

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

| Parameter | Type | Default |
|---|---|---|
| `plate` | integer | `1` |
| `view` | string | `'iso'` |
| `zoom` | boolean | `False` |

## `preview_layer`

Image of one sliced layer seen from the top (needs slice_project first). Choose by layer number (1 = first)
or by height z in mm. Extrusions are drawn in the filament colors.

| Parameter | Type | Default |
|---|---|---|
| `plate` | integer | `1` |
| `layer` | integer | `0` |
| `z` | number | `0` |

## `make_first_layer_test`

Add a plate with the first `height` mm of the objects of a plate (or of the listed objects):
a short print to check bed adhesion and the first layers before a long print. Slice it with
slice_project(plate=<new plate>).

| Parameter | Type | Default |
|---|---|---|
| `plate` | integer | `1` |
| `height` | number | `0.8` |
| `objects` | array / null | `None` |
