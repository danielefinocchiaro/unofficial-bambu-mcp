## What and why

<!-- One topic per pull request. Link the issue if there is one. -->

## Tested on

<!-- OS, Bambu Studio version, printer. Which tests or real prints. -->

## Checklist

- [ ] `uv run ruff check .` and `uv run pytest -q` pass
- [ ] Works through the MCP tools alone (no clicks in the app, no screen reading)
- [ ] User files are never overwritten; nothing is sent to the printer without the user
- [ ] `docs/TOOLS.md` regenerated if a tool changed (`uv run python scripts/gen_tools_doc.py`)
- [ ] `CHANGELOG.md` updated
