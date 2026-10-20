# unofficial-bambu-mcp

> **Unofficial community project.** Not affiliated with, endorsed by or supported by Bambu Lab.
> "Bambu Lab" and "Bambu Studio" are trademarks of their respective owners.

An [MCP](https://modelcontextprotocol.io) server that lets an AI assistant (Claude Code, Claude Desktop or any
MCP client) **build, edit, slice and preview Bambu Studio projects**: plates, objects, multi-color AMS
assignments, presets and settings, using the official Bambu Studio you already have installed.

You talk, it does the slicer work:

- *"New P1S project: a 20 mm calibration cube and the text 'DANI' on a 2 mm plate, black and white."*
- *"Open `~/Downloads/Gnome 3 Color.3mf`, add a second plate with two more gnomes, then convert it for the A1 mini."*
- *"Put eSUN PLA+ in slot 2 with the Textured PEI plate at 65 °C on the first layer, slice and tell me time and grams."*
- *"Show me layer 1 of plate 2."* / *"Make a 0.8 mm first-layer test of plate 1."*

## Features

| Area | What you can do |
|---|---|
| Projects | Create a project, or **open any .3mf** saved by Bambu Studio or downloaded from MakerWorld: painted colors, modifiers, per-object settings and multiple instances are kept. Save without ever overwriting. |
| Printers | P1S, P1P, P2S, X1C, X1, X1E, A1, A1 mini, H2S (single nozzle, 0.4) or any machine preset. **Switch printer** and objects are re-arranged for the new bed (e.g. P1S → A1 mini). |
| Filaments | AMS slots with preset and color. Filament names are matched to the printer ("eSUN PLA+" → the P1S or A1 mini preset). Your own user presets work too. |
| Plates & objects | Add, rename, remove plates. Import STL, OBJ, 3MF. Boxes, cylinders, cones, spheres and **text**. Move, rotate, scale, duplicate, **auto-arrange**, filament per object or per part, per-object settings, closed-solid check. |
| Settings | Read or change any Bambu Studio setting, per filament slot when it applies (e.g. plate temperatures). Presets are resolved like Bambu Studio does (`inherits`, `include`). |
| Slicing | Uses the Bambu Studio command line: time, grams per filament, filament changes, layers and warnings for every plate. |
| Previews | Images of a plate (iso or top, zoom on the objects, painted colors shown) and of any **sliced layer**, so the assistant can check its own work. |
| Test prints | Generate a plate with the first N mm of a model to check bed adhesion before a long print. |
| Printing *(experimental)* | `send_to_printer` exports a plate as `.gcode.3mf` and opens it in **Bambu Connect** (official URL scheme) or **Bambu Studio**, where you check the AMS mapping and press Print. Nothing starts by itself, and the printer stays in cloud mode, so Bambu Handy keeps working. |
| Printer status *(experimental)* | `printer_status` reads state, progress, remaining time, temperatures, AMS trays and errors on the local network, read-only. `use_ams_filaments` sets the project slots from what is loaded in the AMS. It uses the LAN access code Bambu Studio already saved, and finds the printer by itself. |

The full list of tools with their parameters is in [docs/TOOLS.md](docs/TOOLS.md).

## Quick start

Requirements: macOS (tested), Python 3.10+, [uv](https://docs.astral.sh/uv/) and Bambu Studio.

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
| `UBMCP_DIR` | `~/Documents/unofficial-bambu-mcp` | Where projects, sliced files and exports are saved |
| `BAMBU_STUDIO_EXE` | auto-detected | Path of the Bambu Studio executable |
| `BAMBU_STUDIO_DATA` | auto-detected | Bambu Studio data folder (with `system/` and `user/`) |

## How it works

Bambu Studio has no plugin or scripting API. This server works on the **project file** (.3mf, the same format
Bambu Studio saves) and calls the **Bambu Studio command line** to slice. Presets are read from your Bambu Studio
installation and flattened the way the app does, because the command line does not resolve them.

- **Not live.** Changes are written to a file. `open_in_bambu_studio` shows the result in the app window,
  which reloads the project instead of moving objects in real time.
- **Safe with your files.** Nothing is ever overwritten: saving adds `-2`, `-3`... if a file exists, and opened
  projects are read as a copy.
- **Light.** numpy, shapely, manifold3d, fonttools and Pillow. No Bambu profile is shipped with this repository.
- **Your printer, your call.** No print, motion or setting command is ever sent to the printer. Status is read with
  the access code Bambu Studio stores locally; the code is read when needed and never copied anywhere.

## Status and limitations

- **Experimental on this branch:** printing hand-off and printer status are written against Bambu's documented
  behavior but not yet tested on a real printer.

- Tested on macOS with Bambu Studio 2.8, on projects made from scratch and on real MakerWorld downloads
  (multi-plate, painted 6-color models, A1 mini projects).
- Windows and Linux paths are implemented but **not tested yet**.
- Single-nozzle printers. Dual-nozzle machines (H2D) need extra settings that are not handled.
- Variable layer height and height-range modifiers in opened projects are not carried over (you get a warning).
- The first-layer test copy does not keep painted colors.
- Text uses a system font (Arial on macOS/Windows, DejaVu on Linux) unless you pass a font file.

## Roadmap

- Calibration prints (temperature tower, flow rate) and custom G-code at a height (pause, color change)
- A live bridge inside the slicer, to be proposed to OrcaSlicer and Bambu Studio

## Contributing and support

Bug reports, ideas and pull requests: please use [GitHub Issues](../../issues). Include your OS, Bambu Studio
version, printer and, if you can, the .3mf that fails. See [CONTRIBUTING.md](CONTRIBUTING.md).

Author: Daniele Finocchiaro — [danielefinocchiaro.com](https://danielefinocchiaro.com)

## License

[MIT](LICENSE) for this code. Bambu Studio profiles are read from your installation and are not redistributed.
