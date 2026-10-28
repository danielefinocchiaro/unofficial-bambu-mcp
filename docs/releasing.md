# Releasing

For maintainers. A release publishes the package on PyPI and the server on the
[MCP Registry](https://registry.modelcontextprotocol.io), both from `.github/workflows/release.yml`, which runs only
when a GitHub release is published.

## Once

1. **PyPI**: on pypi.org, *Your projects > Publishing > Add a pending publisher*: project `unofficial-bambu-mcp`,
   owner `danielefinocchiaro`, repository `unofficial-bambu-mcp`, workflow `release.yml`, environment `pypi`.
   No token is stored anywhere: the workflow signs in with GitHub's OIDC.
2. **GitHub environment** `pypi` (Settings > Environments): add yourself as required reviewer, so a release waits
   for one click before publishing.
3. **Repository settings** when it goes public: Security > *Private vulnerability reporting* on (SECURITY.md points
   to it); General > *Social preview*: upload `docs/social-preview.png`; Discussions if wanted.

## Each release

1. Version in `pyproject.toml` and in `server.json` (twice: `version` and `packages[0].version`). A unit test fails
   if they differ, or if the README lost its `mcp-name` line, which the MCP Registry looks for on PyPI.
2. `CHANGELOG.md`: replace "unreleased" with the date.
3. `uv run ruff check . && uv run pytest -q`, and on a Mac with Bambu Studio the smoke tests and
   `uv run python scripts/make_demo.py` if the tools changed (it refreshes `docs/demo.gif`).
4. Merge into `main`, then create a release with tag `vX.Y.Z` and the changelog section as notes.
   The workflow checks the tag against both files, runs the tests, builds, publishes to PyPI, then to the MCP
   Registry (it retries for a few minutes while PyPI updates).

The README's quick start installs from PyPI with `uvx unofficial-bambu-mcp`; `uvx` keeps a cached copy, and
`unofficial-bambu-mcp@latest` in the command makes it fetch the newest release.
