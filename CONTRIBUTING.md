# Contributing

Issues and pull requests are welcome. Please include your OS, Bambu Studio version and printer model.

```bash
uv sync
uv run ruff check .
uv run pytest -q                       # unit tests (Bambu-dependent ones skip without Bambu Studio)
UBMCP_DIR=tests/out uv run python tests/smoke.py          # end-to-end on a machine with Bambu Studio
UBMCP_DIR=tests/out uv run python tests/open_real.py some.3mf
uv run python scripts/gen_tools_doc.py # refresh docs/TOOLS.md after changing tools
```

Ground rules: never overwrite user files, never start a print or move the printer without the user, and keep
dependencies light. Bambu Studio profiles must not be copied into this repository.
