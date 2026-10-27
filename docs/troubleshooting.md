# Troubleshooting

**The assistant only says "Error executing tool …".**
Old versions of this server let the MCP SDK hide the reason. Update: every expected error now reaches the assistant
with its message (wrong slot, preset not found, printer refused, broken file…).

**A preset made by the server is not in the AMS slot menu.**
The AMS menu lists system presets and user filaments that have their own filament id (what *Create Filament* makes).
Presets saved by this server for a new filament are made that way; restart Bambu Studio to see them. A preset that
inherits from another (a tweak of a Bambu filament) is not listed there: pick the original filament for the slot.

**Bambu Studio opens the print file but Print is greyed out and the plate is empty.**
Fixed: the print file now carries the plate's build plate type. It happened when the plate chosen in Bambu Studio for
your printer differed from the project's.

**Bambu Studio starts but shows no window.**
Seen on macOS when the app was started by `open -a … file` while closed. The server now starts the program with the
file instead. If a window is still missing, quit Bambu Studio (Cmd+Q) and try again.

**`send_to_printer(via='lan')`, `skip_objects` or `ams_load` is refused with code 84033543.**
The printer is in cloud mode: these need LAN-only mode with Developer Mode; see [printing.md](printing.md).

**`printer_status`: "printer not found on the local network".**
The printer must be on and on the same network as the computer. Set `BAMBU_PRINTER_IP` if your network blocks
discovery. The access code comes from Bambu Studio: connect to the printer once in Bambu Studio, or set
`BAMBU_PRINTER_SERIAL` and `BAMBU_PRINTER_ACCESS_CODE`.

**An old .3mf opens empty, fails to parse, or carries another printer's start G-code.**
Fixed for Bambu Studio 1.6 and 1.7 files (objects in separate model files, undeclared XML prefixes). When a file was
made for a printer you do not have, the author's printer-specific settings (start G-code and the like) are dropped,
with a warning that lists them.

**Slicing "all plates" fails because a plate is empty.**
Empty plates are now skipped (`skipped_empty_plates`); the sliced file then numbers its plates without them.

**The temperature or flow numbers on a test print cannot be read.**
Light from the side; on dark filament the engraving is shallow to the eye. Recent versions use larger, deeper digits.
