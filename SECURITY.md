# Security

This server runs on your computer, next to Bambu Studio, with the permissions of the MCP client that starts it.
Here is everything it touches.

## Your printer

- **Read only in cloud mode.** `printer_status` opens one MQTT connection over TLS (port 8883) on your local
  network, sends a single `pushall` request and closes. `printer_camera` reads one picture (port 6000) and
  `printer_files` / `download_printer_file` read the SD card over FTPS (port 990), all with the LAN access code.
- **Changes only after a confirmation code.** `delete_printer_files` deletes files on the SD card, and, on printers in
  LAN-only + Developer Mode, `send_to_printer(via='lan')` starts a print, `skip_objects` skips objects and
  `ams_load` / `ams_unload` move filament. Each first answers what it would do and a code tied to exactly that; it
  acts only when called again with the code. A printer in cloud mode refuses the Developer Mode commands.
- **The LAN access code** is read from Bambu Studio's `BambuStudio.conf` (or `BAMBU_PRINTER_ACCESS_CODE`) at the
  moment of the connection. It is never returned to the assistant, logged or written anywhere.
- **The only cache** is `~/.config/unofficial-bambu-mcp/printers.json`: serial number → IP address, so the printer
  is found faster next time.

## Your files

- Projects, sliced files and print files go to `UBMCP_DIR` (default `~/Documents/unofficial-bambu-mcp`). Files that
  exist are never overwritten: a new name is picked. Opened projects are read as a copy.
- `save_filament_preset` writes a filament preset in Bambu Studio's user folder, as Bambu Studio itself does.
  Updating an existing preset copies the old file to `~/.config/unofficial-bambu-mcp/preset-backups` first.
- Slicing works in a temporary folder.

## The network

Nothing leaves your local network. The server has no telemetry and makes no request to Bambu Lab's cloud or to
any other service.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's **Report a vulnerability** button (Security tab of this
repository), or write through [danielefinocchiaro.com](https://danielefinocchiaro.com). You will get an answer
within a week.
