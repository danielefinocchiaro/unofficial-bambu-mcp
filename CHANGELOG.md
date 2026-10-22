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
- New projects use the build plate picked in Bambu Studio for that printer (`build_plate` in the summary).

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
