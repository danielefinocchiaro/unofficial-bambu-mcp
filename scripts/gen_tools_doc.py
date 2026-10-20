"""Write docs/TOOLS.md from the tools the server actually exposes (names, descriptions, parameters)."""
import asyncio
import inspect
import os

from unofficial_bambu_mcp import server

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    tools = asyncio.run(server.mcp.list_tools())
    lines = ["# Tools", "", f"{len(tools)} tools, generated from the server code by `scripts/gen_tools_doc.py`.", ""]
    for t in tools:
        lines += [f"## `{t.name}`", "", inspect.cleandoc(t.description or ""), ""]
        props = (t.input_schema or {}).get("properties", {}) if hasattr(t, "input_schema") else (t.inputSchema or {}).get("properties", {})
        req = set(((t.input_schema if hasattr(t, "input_schema") else t.inputSchema) or {}).get("required", []))
        if props:
            lines += ["| Parameter | Type | Default |", "|---|---|---|"]
            for name, p in props.items():
                typ = p.get("type") or " / ".join(x.get("type", "?") for x in p.get("anyOf", [])) or "any"
                default = "required" if name in req else f"`{p.get('default')!r}`"
                lines.append(f"| `{name}` | {typ} | {default} |")
            lines.append("")
    path = os.path.join(HERE, "..", "docs", "TOOLS.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"{len(tools)} tools -> {os.path.normpath(path)}")


if __name__ == "__main__":
    main()
