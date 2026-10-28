# Contributing

Bug reports, test results on other printers and systems, and pull requests are welcome.

## Reporting a bug

Open an issue with the **Bug report** form: OS, Bambu Studio version, printer, the tool that failed and its
message. A .3mf that reproduces the problem helps more than anything (only share files you are allowed to share).

Results on hardware we do not have are just as useful: Windows, Linux, A1, X1C, H2S, a printer in Developer Mode.

## Development

```bash
uv sync
uv run ruff check .
uv run pytest -q                                         # unit tests (the ones that need Bambu Studio skip without it)
UBMCP_DIR=tests/out uv run python tests/smoke.py          # end-to-end, needs Bambu Studio
UBMCP_DIR=tests/out uv run python tests/features_smoke.py
UBMCP_DIR=tests/out uv run python tests/calib_smoke.py
UBMCP_DIR=tests/out uv run python tests/open_real.py some.3mf
uv run python tests/stdio_client.py                       # the server over stdio, as an MCP client sees it
uv run python tests/live_printer.py                       # with a printer on the network; nothing is printed
uv run python scripts/gen_tools_doc.py                    # refresh docs/TOOLS.md after changing a tool
```

`tests/out/` is ignored by git: the smoke tests write their projects and images there, to be looked at. They call
the tool functions directly; `stdio_client.py` and `live_printer.py` go through a real MCP client, the way an
assistant does.

## Ground rules

- **Through MCP.** Every feature must work for someone who only gave permissions to the MCP server and their
  assistant: no clicks in the app, no AppleScript, no screen reading.
- **Never overwrite user files.** Save with a new name; copy before changing a user preset.
- **The printer is the user's.** Nothing that moves, heats, prints or deletes without the user pressing a button
  in an official app, or confirming with the code the tool gives (two steps: the first call does nothing).
- **No Bambu profiles in the repository.** Read them from the user's installation.
- **Light dependencies.** Pure Python wheels; no GPU, no OpenGL.
- Errors the assistant can act on are `ValueError`, `LookupError` or `OSError` with a clear message: the server
  turns them into tool errors the assistant can read.

## Pull requests

One topic per pull request, with tests when you change behavior, `ruff` and `pytest` green, and an entry in
`CHANGELOG.md`. Say on what you tested it (OS, Bambu Studio version, printer).

## Releases

See [docs/releasing.md](docs/releasing.md).
