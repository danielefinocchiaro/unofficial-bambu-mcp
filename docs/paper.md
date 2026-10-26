# Driving a closed slicer from an AI assistant: notes from unofficial-bambu-mcp

Daniele Finocchiaro — October 2026

## Abstract

unofficial-bambu-mcp is an MCP server that lets an AI assistant build, edit, slice, check and calibrate Bambu Studio
projects, and read the status of a Bambu Lab printer on the local network. Bambu Studio has no plugin or scripting
API, so the server works on the project file and on the slicer's command line instead of on the running app. This
note describes how it is built, the parts of the Bambu 3MF format that mattered, why printing is handed over to an
official app instead of started by the server, and what happened when the whole thing was used to calibrate two
third-party filaments on a real printer. It ends with the limits we know about.

## 1. The problem

An assistant that helps with 3D printing needs to do more than talk about settings. It has to:

- make or change a project: import a model, add a shape or some text, place and rotate objects, give each one a
  filament, add a modifier or a hole for a magnet;
- change settings, per object or per filament, and know when a value cannot apply;
- slice, read back the time, the grams and the warnings, and look at the layers;
- check its own work, because it cannot see the screen;
- leave the user with a file that opens in the slicer they already use, ready to print.

Bambu Studio [3] is the slicer most Bambu Lab owners use. It is open source (a fork of PrusaSlicer), but it has no
plugin system and no scripting interface. Its command line can slice a project and export the result; it cannot
edit one. There is no way to ask the running app to add a cube to plate 2.

The Model Context Protocol [1] gives an assistant a set of tools with typed parameters. So the question was what
tools to offer, and how to implement them without an API on the other side.

## 2. Design

### 2.1 The project lives in the server

The server keeps the current project in memory: printer, filament slots, plates, objects, parts, per-object
settings, layer actions (pauses, filament changes, custom G-code at a height). Tools change that model. When a file
is needed, for saving, slicing or opening in the app, the model is written out as a native Bambu Studio `.3mf`.

Coordinates follow one rule that is repeated in the server instructions: millimeters on the plate, origin at the
front-left corner, objects placed by the center of their footprint, always sitting on the bed. Plates and filament
slots are numbered from 1, as in the app. Objects keep the same id while they move between plates, so the assistant
can refer to "object 7" across many calls.

Geometry is handled with numpy, shapely and manifold3d, and text is built from font outlines with fonttools. The
dependencies are pure Python wheels: no GPU, no OpenGL, no copy of Bambu Studio's code.

### 2.2 Reading and writing 3MF

A Bambu project is a zip in the 3MF format [5], with the Production extension [6] and Bambu's own metadata. Reading
keeps what Bambu Studio keeps: parts and their types (normal, modifier, negative part, support blocker or enforcer),
painted colors and painted supports and seams (per-triangle attributes), instances, plate names and plate settings,
layer actions, the author's changes to the presets and the build plate type. Writing produces a file that both the
app and its command line open as a native project. Section 3 lists the details that took time.

### 2.3 Presets, flattened

Bambu presets are JSON files that inherit from each other (`inherits`) and include shared fragments (`include`). The
app resolves the chain when it loads a preset. The command line does not do it for a project: a project has to carry
the full, resolved settings. So the server reads the presets from the user's installation (the system profiles, the
app's own profiles and the user folder), flattens them the way the app does, and writes the result into the project.
Filament names without the `@printer` suffix are matched to the current printer. No Bambu profile is shipped with
the repository.

### 2.4 Slicing with the command line

`slice_project` writes a temporary project and runs `bambu-studio --slice N --export-3mf`. Time, weight per
filament, filament changes, layers, pauses and warnings are read from `slice_info.config` and from the G-code in the
result. Two details:

- The command line refuses to slice "all plates" when one plate is empty. The server slices a copy without the empty
  plates and says so (`skipped_empty_plates`), because the plate numbers in the sliced file then differ.
- For a print file, `send_to_printer` runs `--slice N --min-save --export-3mf` for one plate. The command line leaves
  the printer model id empty in that file; the server fills it in.

### 2.5 Previews, so the assistant can see

An assistant that moves objects blind will put them on top of each other. Every layout change can be followed by
`preview_plate`, which returns an image: an iso or top view of the plate, with the filament colors, the painted
colors and, on request, a label with each object's id and name. `preview_layer` draws one sliced layer from the
G-code moves, framed on the extrusions.

The renderer is a small z-buffer rasterizer in numpy, with flat shading and 2× supersampling, saved with Pillow.
The first version sorted faces back to front (a painter's algorithm); a large face under small ones was then drawn
on top of them. The z-buffer fixed that. With flat shading the floor of an engraved digit has the same color as the
face around it, so the depth buffer is used once more: a pixel gets darker when surfaces a few tenths of a
millimeter to a few millimeters nearer surround it. Engraved numbers on the calibration prints became readable in
the previews. Rendering on the CPU keeps the server usable on any machine and in any MCP client that shows images.

### 2.6 Errors the model can read

With the MCP Python SDK [2] version used here (2.3), an exception raised inside a tool reaches the model as a
generic "Error executing tool" unless it is a `ToolError`. Our errors say what to do next: wrong slot number, preset
not found, printer refused, broken file. A small decorator turns `ValueError`, `LookupError`, `OSError`,
`RuntimeError`, `SyntaxError` and `BadZipFile` into `ToolError` with the original message. It was a one-line cause
for a lot of confused retries.

### 2.7 In sync with the app

`open_in_bambu_studio` opens the project in the app. If the user changes it there and saves, the server notices the
new modification time and re-reads the file on the next command, as long as there are no unsaved changes on the
server side; if both sides changed, it says so instead of choosing. Files are never overwritten: saving picks
`name-2.3mf`, `name-3.3mf` and so on, and an opened file is read as a copy.

## 3. The 3MF details that mattered

Most projects people print are not made from scratch: they come from MakerWorld or Printables, saved by many
versions of Bambu Studio. Opening those correctly took more work than writing new ones.

**Objects in separate model files.** Recent files put each object in `3D/Objects/object_N.model` and reference it
from the main `3D/3dmodel.model` through components with the Production extension's `path` attribute. Some older
files, which we met from Bambu Studio 1.6 and 1.7, also put `path` on the build items. Object ids repeat from file
to file, so a component without a path has to be resolved in the file of its parent, not in the main one. Getting
this wrong gave empty projects or the wrong mesh.

**Undeclared XML prefixes.** The same old files use attributes such as `p:UUID` without declaring the `p` prefix.
No conforming XML parser accepts that. Before parsing, the server declares any missing prefix on the `<model>`
element (`p` with the Production namespace, others with a placeholder).

**The author's changes to the presets.** `project_settings.config` carries the full flattened settings and, in
`different_settings_to_system`, the keys the author changed from the presets: a list of the form
`[process, filament 1, …, filament n, printer]`. Taking every listed key as an override is wrong. Printer keys (for
example a custom start G-code) only make sense on that printer: they are kept only when the printer stays the same,
and dropped with a warning that lists them otherwise. Filament keys are kept only for slots whose filament was not
replaced. Process keys are kept.

**The build plate type.** `curr_bed_type` is a project choice, not a preset setting, so it never appears in the
list above. It has to be read on its own, or a project made for a smooth plate comes back as textured.

**The plate grid.** Bambu Studio lays plates out on a grid in a single coordinate space, with a pitch of 1.2 times
the bed width. Reading positions needs the bed width of the printer the file was made for, taken from its
`printable_area`, not of the current printer.

A related problem appeared in the app, not in the file. When the build plate chosen in Bambu Studio for a printer
differs from the plate of a sliced file, the app discards the slicing when it opens the file: the plate shows empty
and Print is greyed out. Print files made by the server now pin the build plate type on the plate. New projects
start with the plate the user picked in Bambu Studio for that printer.

## 4. Printing, and the firmware authorization

### 4.1 What the printer accepts

In January 2025 Bambu Lab announced an authorization system for printer control [4]: starting a print, moving the
axes, changing temperatures, fans and AMS settings and running calibrations need authorization, while status
messages and printing from the SD card do not. Bambu's wiki describes the way out for third-party software: a
Developer Mode that runs in LAN-only mode, without the cloud, and "does not require authorization verification"
[7][8].

We checked what this means on a P1S in normal cloud mode, with Bambu Handy working:

- Reading the status works. One MQTT connection over TLS on port 8883, user `bblp` and the LAN access code that
  Bambu Studio saved, one `pushall` request, then close.
- Uploading a file over FTPS (port 990) works.
- Starting the uploaded file (`project_file`) is refused. The reply carries `err_code 84033543` and the printer
  shows HMS `0500-0500-0001-0007`, "MQTT command verification failed".
- Setting an AMS slot (`ams_filament_setting`) is refused the same way.

A detail worth knowing for anyone building on this: a refusal can come back as a reply without a `result` field,
and the HMS list repeats old entries. An early version of the direct printing code took that reply as "accepted".
It now looks at `err_code` and at HMS entries newer than the request.

### 4.2 The hand-off

Most users will not turn off the cloud to let a program print. So the released server never starts a print.
`send_to_printer` makes the print file of one plate (`.gcode.3mf`: G-code, thumbnails, slice info, printer model)
and opens it in Bambu Studio, or in Bambu Connect if installed. The user checks the printer and the AMS mapping in
the print dialog and presses Print. Direct printing for printers in LAN-only + Developer Mode is written (FTPS
upload and `project_file`) and kept on a separate branch, together with skipping objects of a running print, which
asks the assistant for a confirmation code before it sends anything. That branch is not part of releases.

### 4.3 Reading the status

`printer_status` returns the state (with the last job's result when idle), job, progress, remaining time, layer,
temperatures, speed mode, AMS trays with humidity and temperature of each unit, the active slot, errors and skipped
objects. The MQTT client is a small piece of standard library code (socket and ssl), not a dependency. The
printer is found by SSDP and, failing that, by a scan of port 8883 on the local network; only serial number → IP is
cached.

Two things learned from real prints:

- A spool without RFID that was never set in the AMS reports an empty type. The tray exists (`tray_exist_bits`), so
  it is reported as `unknown`, not as an empty slot. When the printer feeds from such a tray there is no auto-refill
  and no grams left, and the status says so.
- Objects skipped during a print are reported by the ids Bambu Studio assigns when slicing (`s_obj`). They can be
  matched to names only when the print file was made by the server.

Status now carries warnings: an unknown spool being fed, a spool that is not the filament of the project being
printed, sport or ludicrous speed with more than two hours to go.

### 4.4 Before and after a long print

Two tools came out of one 20-hour plate of a multi-part assembly, where a pin came off at layer 4.
`check_print_risks` looks at each plate before printing. It measures the faces of each part that lie on the bed
(the union of those faces, with shapely) and flags tall and narrow parts (at least 40 mm high and 4 times the
smaller side of the footprint); parts without a brim standing on a narrow footing (height over 4 times the footing
width, or a footing under 15 mm wide and height over 1.5 times it) or on a piece smaller than 250 mm²; filaments
whose temperature for the project's plate type is 0; and parts over 120 mm sharing a long plate with many others.
These thresholds are rules of thumb, not measured failure rates. On that plate they flag the pins, the crossbars,
the spindles and the cradles, and not the parts standing on a large gear or already on a brim.
`reprint_objects` then makes a new project with only the parts that failed, the same settings and a brim.

## 5. Calibrating two filaments on real hardware

The test that used most of the server at once was calibrating two spools of eSUN PLA Basic, black and white, without
RFID, on a P1S with two AMS units. Bambu Studio has no preset for them.

**Presets.** The assistant started from Generic PLA, set the maker's published values and saved one preset per
color with `save_filament_preset`. The first attempt saved presets that inherit from Generic PLA. They worked in
projects but did not appear in the AMS slot menu. Reading the Bambu Studio source showed why: the AMS dialog lists
system presets and user presets without a parent. Bambu Studio's own *Create Filament* makes the second kind: full
settings, no `inherits`, and a filament id of its own. The server now does the same for a new filament, with an id
of the form "P" + 7 hex digits that does not collide with the existing ones. After a restart of Bambu Studio both
presets were in the menu. The slot assignment itself was done by the user in Bambu Studio, because the firmware
refuses `ams_filament_setting` in cloud mode (4.1).

**Temperature tower.** One block per temperature, 8 mm each, hottest at the bottom, each block made in a separate
`M104` step. The black tower had good bridges at every temperature and small defects only at 225–230 °C; the
coldest block, 200 °C, was very hard to break. The white tower led to the same choice. Both were set to 215 °C.

**Flow rate.** One square per flow ratio, pass 1 from −20 % to +20 % by 5 %, each square printed with its own
`print_flow_ratio`. On the black spool −5 % was the smoothest: 0.98 × 0.95 = 0.931. On the white spool −5 % and 0 %
looked the same, so the value went in between: 0.955.

**A first-layer corner.** On the first prints a corner of the tower lifted and was melted again by the nozzle. With
the part fan off for the first three layers (`close_fan_the_first_x_layers = 3`) it did not happen again.

**Saving the results.** `save_filament_preset(..., replace=True)` updates the preset in place, keeping its filament
id, so the AMS slots set to it stay valid. The old file is copied to a backup folder first.

**What was read and how.** The user printed each test, looked at it and described it, with photos. The assistant
read the description, asked about anything unclear and set the values. It also got one thing wrong: it read a
flipped photo of the tower upside down and had to be corrected. The engraved numbers were hard to read on black
filament, so the tests now use larger and deeper digits.

**Not printed yet.** The pressure advance tower, the max volumetric speed test and the retraction test are checked
by slicing (the G-code is inspected for the K steps and the retraction lengths) but have not been printed. The
printer was busy with a long job when this was written.

## 6. Principles

**Everything through MCP.** Users give permissions to an MCP server and to their assistant, not to a program
that clicks around their desktop. Every action and every test goes through the protocol: no simulated clicks, no
AppleScript, no screen reading to finish a task. When something could only be done by hand in the app (setting an
AMS slot, pressing Print), the tool says so and stops there.

**Never overwrite.** Projects, sliced files and print files get a new name if one exists. Opened files are read as
a copy. Updating a user's filament preset copies the old one first.

**The printer is read only.** Releases send one kind of request to the printer: `pushall`, to read the status.

**The access code stays where it is.** The LAN access code is read from Bambu Studio's configuration (or an
environment variable) at the moment of the connection. It is never returned to the assistant, logged or written
anywhere. Nothing is sent outside the local network.

## 7. Testing

- 59 unit tests run in CI on Linux, without Bambu Studio (the tests that need it are skipped there).
- Smoke tests run on a machine with Bambu Studio: they build projects, open real files, slice, render previews and
  build the calibration plates, and write everything to a folder so it can be looked at.
- Three scripts go through a real MCP client over stdio, as an assistant does: a quick check, one against a live
  printer (nothing is printed) and the one that makes the demo in the README.
- A list of 21 scenarios was run by an assistant through the MCP tools alone, on macOS with Bambu Studio 2.8.2 and
  the P1S. The projects included files downloaded from MakerWorld and Printables: painted 6-color models,
  multi-part assemblies, 3-plate projects, files from Bambu Studio 1.6 and 1.7. Many of the fixes described above
  (the empty-plate slicing, the build plate type, the unknown spools, the hidden error messages, the unstable
  object ids, an app started from the command line that stayed without a window) were found this way, not by unit
  tests.
- The calibration prints of section 5 and live status during prints.

Windows and Linux paths exist in the code but have not been tested with Bambu Studio.

## 8. Limitations

- Single-nozzle printers only. Dual-nozzle machines need settings that are not handled.
- Variable layer height and height-range modifiers in opened projects are not carried over; the user gets a
  warning.
- First-layer tests and cuts do not keep painted colors.
- Bambu Studio re-slices a project when it opens it. To see a plate sliced and ready to print in the app, the print
  file from `send_to_printer` has to be used.
- The Bambu Connect hand-off is written from Bambu's documentation and has not been tested.
- The work relies on undocumented formats and behaviors of Bambu Studio and of the firmware, which can change with
  any update.

## 9. Future work

- Direct printing and object skipping for printers in LAN-only + Developer Mode, behind explicit confirmation.
- Testing on Windows and Linux, and a package that installs with one command.
- A live bridge inside the slicer, so an assistant can work on the open project instead of on a file. This needs
  the slicer's maintainers, and would be proposed to OrcaSlicer and Bambu Studio.

## References

1. Model Context Protocol, specification. https://modelcontextprotocol.io/specification
2. Model Context Protocol, Python SDK. https://github.com/modelcontextprotocol/python-sdk
3. Bambu Lab, Bambu Studio (source code). https://github.com/bambulab/BambuStudio
4. Bambu Lab, "Firmware Update Introducing New Authorization Control System", 16 January 2025.
   https://blog.bambulab.com/firmware-update-introducing-new-authorization-control-system-2
5. 3MF Consortium, 3MF specifications. https://3mf.io/specification/
6. 3MF Consortium, 3MF Production Extension. https://github.com/3MFConsortium/spec_production
7. Bambu Lab Wiki, "Third-party Integration with Bambu Lab Products".
   https://wiki.bambulab.com/en/software/third-party-integration
8. Bambu Lab Wiki, "How to enable Developer Mode on Bambu Lab printers".
   https://wiki.bambulab.com/en/knowledge-sharing/enable-developer-mode

Bambu Lab, Bambu Studio, Bambu Connect and Bambu Handy are trademarks of their respective owners. This project is
not affiliated with or endorsed by Bambu Lab.
