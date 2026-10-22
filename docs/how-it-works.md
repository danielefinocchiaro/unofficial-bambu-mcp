# How it works

Bambu Studio has no plugin or scripting API, and its command line slices files but does not edit them. So the
server keeps the project in memory, writes it as a Bambu Studio `.3mf` when needed, and lets the command line slice
and export it.

## The project file

A Bambu Studio project is a zip: `3D/3dmodel.model` (meshes, or components pointing to `3D/Objects/*.model`),
`Metadata/model_settings.config` (object and part names, filaments, per-object settings, plates and the objects on
each), `Metadata/project_settings.config` (the full flattened settings and the names of the presets they came from),
and optional files such as `custom_gcode_per_layer.xml` (pauses and filament changes at a height).

Reading keeps what Bambu Studio keeps: parts and their types (normal, modifier, negative, support blocker or
enforcer), painted colors, supports and seams (per-triangle attributes), instances, plate names and settings, layer
actions, the author's changes to the presets (only those that still apply), and the build plate type. Plates are laid
out on Bambu's grid (pitch 1.2 × bed width), with the bed of the printer the file was made for.

Writing produces a file Bambu Studio and its command line open as a native project. Files are never overwritten.

## Presets

Presets are read from the Bambu Studio installation (`system/` and the app's own `profiles/`) and from the user's
folder. The command line does not resolve `inherits` and `include`, so the server flattens them the way the app does
and writes the result in the project. Filament names without `@printer` are matched to the printer. New filaments are
saved as root user presets with their own `filament_id` ("P" + 7 hex digits, like *Create Filament*).

## Slicing and print files

`slice_project` writes a temporary project and runs `bambu-studio --slice N --export-3mf`; times, weights, filament
changes and warnings come from `slice_info.config` and the G-code. "All plates" with an empty plate is refused by the
command line, so a copy without empty plates is sliced instead.

`send_to_printer` runs `--slice N --min-save --export-3mf` for one plate, writes the printer model id that the command
line leaves empty, and pins the build plate type on the plate.

## Previews

Plates are drawn with a small z-buffer rasterizer (numpy and Pillow, flat shading, 2× supersampling): no GPU and no
OpenGL. The depth buffer also darkens pixels surrounded by nearer surfaces, so engraved numbers and holes read apart
from the face around them. Sliced layers are drawn from the G-code moves.

## Printer

Status is one MQTT `pushall` request over TLS on port 8883 with user `bblp` and the LAN access code; nothing else is
sent. See [printing.md](printing.md).
