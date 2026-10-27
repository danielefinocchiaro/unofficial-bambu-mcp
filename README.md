# unofficial-bambu-mcp

<!-- mcp-name: io.github.danielefinocchiaro/unofficial-bambu-mcp -->

[![ci](https://github.com/danielefinocchiaro/unofficial-bambu-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/danielefinocchiaro/unofficial-bambu-mcp/actions/workflows/ci.yml)
![python](https://img.shields.io/badge/python-3.10%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

> **Unofficial community project.** Not affiliated with, endorsed by or supported by Bambu Lab.
> "Bambu Lab", "Bambu Studio", "Bambu Connect" and "Bambu Handy" are trademarks of their respective owners.

An [MCP](https://modelcontextprotocol.io) server that lets an AI assistant (Claude Code, Claude Desktop or any
MCP client) **build, edit, slice, check and calibrate Bambu Studio projects**, using the official Bambu Studio
you already have installed, and **read your printer's status** on the local network.

You talk, it does the slicer work:

- *"New P1S project: a 20 mm cube and the text 'DANI' in white on a black 2 mm tag."*
- *"Open `~/Downloads/Gnome 3 Color.3mf`, add a plate with two more gnomes, then convert it for the A1 mini."*
- *"I have eSUN PLA Basic in AMS slot 2: make a preset for it and the test prints to calibrate it."*
- *"Before I start this 20-hour plate: which parts are likely to come off?"*
- *"A pin came off at layer 4 and I skipped it: make me a project to reprint just that pin, with a brim."*
- *"How is the print going? Which spool is it feeding from?"*

![A session: a project from scratch, a print risk fixed, slicing, a temperature tower, the print file](https://github.com/danielefinocchiaro/unofficial-bambu-mcp/raw/main/docs/demo.gif)

<sub>A real session, sped up: every tool call, result and image comes from the server through MCP; only the requests
are written for the demo ([scripts/make_demo.py](scripts/make_demo.py)).</sub>

## What it can do

| Area | What you can do |
|---|---|
| Projects | Create a project, or **open any .3mf** saved by Bambu Studio (2.x and older 1.6/1.7 files) or downloaded from MakerWorld / Printables: painted colors, modifiers, per-object settings, instances and plates are kept. Save without ever overwriting. |
| Printers | P1S, P1P, P2S, X1C, X1, X1E, A1, A1 mini, H2S (single nozzle) or any machine preset. **Switch printer** and objects are re-arranged for the new bed. New projects use the build plate you picked in Bambu Studio for that printer. |
| Filaments | AMS slots with preset and color, your own user presets included. `use_ams_filaments` takes what is loaded in the AMS right now. |
| Plates & objects | Import STL, OBJ, 3MF; boxes, cylinders, cones, spheres and **text** (with a base in another color). Move, rotate, scale, **mirror**, **lay flat**, **auto orient** (least support, enough on the bed), duplicate, **fill the plate with copies**, **split** into objects or parts, **merge** objects into one, **mesh boolean** (holes, unions, intersections) with painted colors kept, filament per object or part, per-object settings, closed-solid check. Object ids stay the same while you work. |
| Arranging | `arrange` by the real outline seen from above, brim and brim ears included, so shapes nest (Bambu Studio's own arrange uses convex hulls). Gap, rotation steps, one material per plate, calibration corner, align to Y, prime tower corner kept free; one plate, chosen objects or all; "put them in N plates" evenly or as few as possible, and if they do not fit nothing moves and it says what is left over. |
| Cutting | `cut_object` on any plane, with **connectors** like Bambu Studio's Cut tool: a **plug** (peg and hole with clearance), **dowels** (holes in both pieces and separate pins) or a **dovetail**; round, square or hexagonal, straight or tapered, placed automatically or where you say, made shallower where a piece is thin. The pieces are laid out to print: the peg always points up. |
| Modifiers | Box or **round** parts: modifiers with their own settings ("the top 5 mm at 100 % infill"), negative parts (holes for magnets and screws), support blockers and enforcers. |
| Settings | Read or change any Bambu Studio setting, per filament slot when it applies, with a warning when a value cannot apply (e.g. a textured-plate temperature on a smooth plate). |
| Presets | Save the project's changes as Bambu Studio **user presets**: filament (`save_filament_preset`), **process** and **printer**; or change one of your presets directly (`edit_preset`), list, rename and delete them, with a backup copy each time. Values are checked and written the way Bambu Studio does (one per nozzle variant where it applies), and changes are stamped for Bambu Studio's cloud sync. Presets that are in your Bambu cloud can only be deleted from Bambu Studio: the answer says how. |
| Purge volumes | `get_purge_volumes` / `set_purge_volumes`: the purge between each pair of slots and the multiplier, as in Bambu Studio's dialog; the values in opened files are kept. |
| Slicing | Bambu Studio command line: time, grams and **cost** per filament, filament changes, pauses, layers and warnings per plate. Empty plates are skipped. |
| Previews | Images of a plate (iso or top, zoom, painted colors, **object labels**) and of any **sliced layer**, so the assistant checks its own work. |
| Print risks | `check_print_risks`: tall and narrow parts, parts standing on a tiny or narrow footing without a brim, filaments not meant for the build plate, tall parts sharing a long plate, a full brim on a print-in-place model whose joints it would weld. |
| Brim ears | `add_brim_ears`: small round brims only on the thin tips (fingers, toes) of print-in-place and articulated models, placed automatically away from joint gaps and other pieces, or where you say. Bambu Studio's *Painted* brim, checked on the sliced first layer. |
| Reprints | `reprint_objects`: a new project with only the parts that failed, same settings, with a brim. |
| Calibration | **Temperature tower**, **flow rate test** (pass 1 and 2), **pressure advance tower**, **max volumetric speed test**, **retraction test**, **VFA test** (wall speeds), **first-layer test**, for any filament. Save the result as a **Bambu Studio filament preset**: a new filament gets its own id, like Bambu Studio's *Create Filament*, so you can pick it for an AMS slot; updating it later keeps that id. |
| Layer actions | **Pause** at a height (magnets, nuts), **filament change** at a height, or any G-code at a height. |
| Printing | `send_to_printer` makes the print file of a plate and opens it in **Bambu Studio** (or **Bambu Connect**) ready to print: you check the AMS mapping and press Print. |
| Printer status | `printer_status` (read only, local network): state, progress, temperatures, AMS trays with humidity, skipped objects, and warnings (unknown spool being fed, sport speed on a long print). |

All 66 tools with their parameters: [docs/TOOLS.md](docs/TOOLS.md).

## Tested on real hardware

macOS, Bambu Studio 2.8.2, a **P1S with two AMS units**, in normal cloud mode:

- every tool through a real MCP client, on projects made from scratch and on MakerWorld / Printables downloads
  (painted 6-color models, multi-part assemblies, 3-plate projects, files from Bambu Studio 1.6 and 1.7);
- printed: temperature towers and flow tests for two third-party filaments (eSUN PLA Basic black and white), whose
  presets were made and tuned through the server; the print hand-off to Bambu Studio; live status during prints.

The pressure advance tower, the max volumetric speed test and the retraction test are checked by slicing (the G-code
is inspected) but have not been printed yet. Windows and Linux paths exist but are **not tested**.

## Printing and your printer

Bambu firmware (2025 and later) accepts commands from other programs only when the printer is in **LAN-only mode
with Developer Mode** on, which turns off the cloud and Bambu Handy. In normal cloud mode it refuses them, so this
server:

- **reads** the printer status (allowed in cloud mode), with the LAN access code Bambu Studio already saved;
- **hands the print over** to Bambu Studio or Bambu Connect, where you press Print;
- does **not** start prints, set AMS slots or skip objects on its own: you do that in Bambu Studio, Bambu Handy or on
  the printer. (Direct LAN printing for printers in Developer Mode exists on the `lan-print` branch and is not part
  of releases yet.)

More in [docs/printing.md](docs/printing.md).

## Quick start

Requirements: Python 3.10+, [uv](https://docs.astral.sh/uv/) and Bambu Studio.

```bash
git clone https://github.com/danielefinocchiaro/unofficial-bambu-mcp
cd unofficial-bambu-mcp && uv sync
```

**Claude Code**

```bash
claude mcp add bambu -- uv run --directory /path/to/unofficial-bambu-mcp unofficial-bambu-mcp
```

**Claude Desktop or other MCP clients** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "bambu": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/unofficial-bambu-mcp", "unofficial-bambu-mcp"]
    }
  }
}
```

Then ask: *"What version of Bambu Studio do I have, and which printers can you use?"*

### Configuration (optional)

| Variable | Default | Meaning |
|---|---|---|
| `UBMCP_DIR` | `~/Documents/unofficial-bambu-mcp` | Where projects, sliced files and print files are saved |
| `BAMBU_STUDIO_EXE` | auto-detected | Path of the Bambu Studio executable |
| `BAMBU_STUDIO_DATA` | auto-detected | Bambu Studio data folder (with `system/` and `user/`) |
| `UBMCP_PRESET_BACKUPS` | `~/.config/unofficial-bambu-mcp/preset-backups` | Where a copy of a user preset goes before it is changed, renamed or deleted |
| `BAMBU_PRINTER_SERIAL`, `BAMBU_PRINTER_ACCESS_CODE`, `BAMBU_PRINTER_IP` | from Bambu Studio | Printer for `printer_status`, if you do not want it read from Bambu Studio |

## How it works

Bambu Studio has no plugin or scripting API. This server works on the **project file** (.3mf, the format Bambu
Studio saves) and calls the **Bambu Studio command line** to slice. Presets are read from your installation and
flattened the way the app does. Details in [docs/how-it-works.md](docs/how-it-works.md).

- **In sync with the app.** `open_in_bambu_studio` shows a project in the app; if you change it there and save,
  the server re-reads it on the next command (and tells you if both sides changed).
- **Safe with your files.** Nothing is ever overwritten: saving adds `-2`, `-3`... and opened files are read as a
  copy. Changing, renaming or deleting one of your presets keeps a backup copy first.
- **Light.** numpy, shapely, manifold3d, fonttools and Pillow. No Bambu profile is shipped with this repository:
  presets come from your installation (the server only carries default values for settings that presets leave out).
- **Your printer, your call.** The LAN access code is read from Bambu Studio when needed and never copied
  anywhere. See [SECURITY.md](SECURITY.md).

## Guides

- [Calibrating a filament](docs/calibration.md), step by step, with what to look at on each test print
- [Printing and printer status](docs/printing.md)
- [Troubleshooting](docs/troubleshooting.md)
- [How it works](docs/how-it-works.md)
- [Driving a closed slicer from an AI assistant](docs/paper.md): a technical write-up of the design and the tests

## Limitations

- Single-nozzle printers; dual-nozzle machines (H2D) need settings that are not handled.
- Variable layer height and height-range modifiers in opened projects are not carried over (you get a warning).
- First-layer tests do not keep painted colors.
- Bambu Studio re-slices a project when it opens it; to see a plate sliced and ready to print in the app, use
  `send_to_printer`.

## Roadmap

- Direct printing for printers in LAN-only + Developer Mode (`lan-print` branch)
- Windows and Linux testing; a package on PyPI (`uvx unofficial-bambu-mcp`)
- A live bridge inside the slicer, to be proposed to OrcaSlicer and Bambu Studio

## Contributing and support

Bug reports, ideas and pull requests: [GitHub Issues](../../issues). Include your OS, Bambu Studio version,
printer and, if you can, the .3mf that fails. See [CONTRIBUTING.md](CONTRIBUTING.md).

Author: Daniele Finocchiaro — [danielefinocchiaro.com](https://danielefinocchiaro.com). If it saves you prints
and time: [buy me a coffee](https://buymeacoffee.com/danifinocchiaro).

## License

[MIT](LICENSE) for this code. Bambu Studio profiles are read from your installation and are not redistributed.
