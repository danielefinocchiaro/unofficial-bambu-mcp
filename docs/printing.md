# Printing and printer status

## Printing: the hand-off

`send_to_printer(plate, via)` makes the print file of one plate (`.gcode.3mf`: G-code, thumbnails, slice info, the
printer model) and hands it to an official Bambu app:

- `via="bambu_studio"`: Bambu Studio opens on the sliced plate, ready to print. Check the printer and the AMS
  mapping in the print dialog and press **Print plate**.
- `via="bambu_connect"`: the same with Bambu Connect, if installed (written from Bambu's documentation, not tested).
- `via="file"`: only make the file.

Nothing starts printing by itself. If Bambu Studio is closed, it is started with the file; if it is open with
another project, Bambu Studio opens the file in a new window.

The print file carries the plate's build plate type, so Bambu Studio keeps the slicing even when your own plate
choice in the app is different (otherwise it would discard it and grey out Print).

## Why the server does not press Print for you

Since 2025 Bambu firmware checks who sends a command. In **normal cloud mode** (Bambu Handy working) a printer
refuses commands from other programs: a print request comes back with `err_code 84033543` and the printer shows
HMS `0500-0500-0001-0007` ("MQTT command verification failed"). The same happens for setting an AMS slot and for
skipping objects. Reading the status is allowed.

Commands from other programs are accepted only in **LAN-only mode with Developer Mode** on (printer screen:
Settings > Network), which turns off the cloud and Bambu Handy. Direct printing and object skipping for that mode are
on the `lan-print` branch (upload over FTPS, `project_file` and `skip_objects` requests), not in releases.

## Printer status

`printer_status` connects to the printer on your local network (MQTT over TLS, port 8883) with the serial number and
LAN access code that Bambu Studio saved when you added the printer, asks for one full report and closes.

It returns: state (idle with the last job's result, printing, paused), job, progress, remaining time, layer,
temperatures, speed mode, AMS trays (type, name, color, remaining % when known) with humidity and temperature of each
AMS unit, the active slot, errors, skipped objects, and **warnings**:

- the printer is feeding a spool the AMS does not know (no RFID, type not set): no auto-refill, grams left unknown,
  and where the project's filament is;
- the spool being fed is not the filament of the project being printed (when the job is the open project);
- sport or ludicrous speed with more than two hours to go.

Skipped objects are listed by the ids Bambu Studio gives them when slicing; their names are shown when the job was
sent with `send_to_printer`.

The printer is found by SSDP and, if needed, by a scan of port 8883 on your network; its IP is cached in
`~/.config/unofficial-bambu-mcp/printers.json` (serial → IP only). Set `BAMBU_PRINTER_IP` to skip the search.

## AMS

`use_ams_filaments` sets the project's filament slots from what is loaded now (preset and color, user filaments
included). Spools without RFID that were never set in the AMS are reported as `unknown` and left out.
