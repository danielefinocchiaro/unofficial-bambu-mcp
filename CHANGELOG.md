# Changelog

## 0.2.0 (unreleased)

- Calibration plates for any filament: temperature tower (M104 per block, temperatures engraved), flow rate test
  (per-object `print_flow_ratio`, modifier engraved), pressure advance tower (M900 K every millimeter).
- Layer actions: pause, AMS filament change and custom G-code at a height, read from and written to
  `Metadata/custom_gcode_per_layer.xml` in Bambu Studio's format.
- `save_filament_preset`: save a slot's tuned settings as a Bambu Studio user preset (never overwrites).

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
