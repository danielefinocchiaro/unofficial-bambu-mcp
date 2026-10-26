# Calibrating a filament

How to tune a filament with the assistant, from the preset to the test prints. Written from a real run: two spools of
eSUN PLA Basic (black and white, no RFID) on a P1S with an AMS. The tests are printed by you (press Print in Bambu
Studio); you look at them and tell the assistant what you see; it updates the preset.

## 1. Make a preset

If Bambu Studio has a preset for your filament, start from it. If not, start from the matching *Generic* preset and
set what the maker publishes (nozzle and bed temperatures, density):

> *"I have eSUN PLA Basic, black in AMS slot 2 and white in slot 3. Look up eSUN's settings and make a preset for
> each, starting from Generic PLA."*

The assistant does `new_project` with Generic PLA, `set_setting` for each value, then `save_filament_preset`.
A new filament is saved like Bambu Studio's **Create Filament**: full settings, its own filament id, compatible with
your printer. That matters: **only presets saved this way appear in the AMS slot menu** (Device > AMS > slot >
filament), presets that inherit from another one are not listed there.

Restart Bambu Studio, then set the AMS slots yourself (Device > AMS > slot: the preset under its brand, and the
color). Bambu firmware does not let other programs change AMS slots in cloud mode.

## 2. The test prints

> *"Make the calibration prints for both."*

| Test | Tool | Time on a P1S | What changes |
|---|---|---|---|
| Temperature tower | `make_temperature_tower` | ~50 min | nozzle temperature, one 8 mm block per value |
| Flow rate | `make_flow_test` | ~25 min | flow ratio, one square per value (pass 1: ±20 % by 5) |
| Pressure advance | `make_pa_tower` | ~20 min | K, one step per millimeter |
| Max volumetric speed | `make_max_flow_test` | ~27 min | speed, one cylinder per mm³/s (separate file) |
| Retraction | `make_retraction_test` | ~20 min each | one file per length (separate files) |

The first three are plates of the open project (an empty plate 1 is reused); the last two are separate project files
(`open_project(file)`, then `send_to_printer`). Print them in this order: temperature first, because flow and
pressure advance depend on it. Ask for `send_to_printer(plate=N, via="bambu_studio")` for each: Bambu Studio opens
on the sliced plate, you press Print.

## 3. Reading them

**Temperature tower.** Numbers go from the hottest at the bottom to the coldest at the top. Look at each block:
bridges (sagging means too hot), strings between the pillars, walls (dull or rough means too cold), and try to snap
the coldest block with your fingers (layers splitting means too cold). Pick the middle of the good range. On the
eSUN black: perfect bridges everywhere, defects only at 225–230 °C, the 200 °C block very hard, so 215 °C.

**Flow rate.** Look at the top of each square with light from the side and run a finger over it: gaps between
lines mean too little, ridges or bulges around the engraved number mean too much. The smoothest wins; if two look the
same, take the middle or ask for a pass 2 (`make_flow_test(low=-5, high=0, step=1)`). The new value is the current
flow ratio times (1 + percent / 100): black eSUN −5 % → 0.931.

**Pressure advance tower.** Look at the four corners: bulging corners at the bottom (K too low), rounded corners
or gaps after the corner at the top (K too high). Measure the height of the sharpest corners: K = height in mm ×
step (0.004 by default). In the print dialog, untick *Flow Dynamics Calibration* for this test. Bambu printers take
K from the printer, not from the preset: put it in Device > AMS > slot > *PA Profile / Factor K*. A K saved in
the filament preset (`pressure_advance` with `enable_pressure_advance`) is kept in the file but not used: Bambu
Studio writes no M900 for Bambu printers, and the server says so when you set it.

**Max volumetric speed.** The last cylinder with clean walls; use about 90 % of it as
`filament_max_volumetric_speed`.

## 4. Save the results

> *"Black: 215 °C and flow −5. White: 215 °C and flow between −5 and 0."*

The assistant sets the values with `set_setting(..., slot=N)` and calls
`save_filament_preset(slot, name, replace=True)`: the preset is updated **with the same filament id**, so the AMS
slots set to it stay valid, and the previous file is copied to `~/.config/unofficial-bambu-mcp/preset-backups`
first.

## Lessons from the real run

- A first-layer corner lifting and getting melted again by the nozzle: turning the part fan off for the first 3
  layers (`close_fan_the_first_x_layers = 3`) fixed it on the next print. A degreased plate helps too.
- On black filament, engraved numbers fill up: the towers and squares now use large, deep digits, but light from
  the side still helps.
- Squares and towers taken off the plate lose their order: say which number is engraved on the one you mean.
