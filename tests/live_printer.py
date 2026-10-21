"""Live test with a real printer, only through the MCP protocol (what an LLM would do).

  uv run python tests/live_printer.py               # status, project, AMS, slicing, print file: nothing is printed
  uv run python tests/live_printer.py --ams 5,7     # take the two colors from these AMS slots

Needs the printer on the same network, and the LAN access code saved by Bambu Studio (or the BAMBU_PRINTER_* vars).
"""
import argparse
import asyncio
import json
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def text(res):
    return "\n".join(c.text for c in res.content if c.type == "text")


async def call(s, tool, args=None, show=1200):
    res = await s.call_tool(tool, args or {})
    out = text(res)
    print(f"\n== {tool} {json.dumps(args or {})}{'  -> ERROR' if res.is_error else ''}\n{out[:show]}")
    return res, out


async def main(a):
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    params = StdioServerParameters(command="uv", args=["run", "--directory", here, "unofficial-bambu-mcp"],
                                   env={**os.environ, "UBMCP_DIR": os.path.join(here, "tests", "out")})
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        res, _ = await call(s, "printer_status")
        if res.is_error:
            return
        await call(s, "new_project", {"name": "live-print", "printer": "P1S", "filaments": [
            {"preset": "Bambu PLA Basic", "color": "#FF6A13"}, {"preset": "Bambu PLA Basic", "color": "#5E43B7"}]})
        await call(s, "add_shape", {"shape": "box", "width": 20, "depth": 20, "height": 8, "name": "Cube"}, 300)
        await call(s, "add_shape", {"shape": "text", "text": "MCP", "text_height": 8, "height": 0.6, "base": 1,
                                    "filament": 2, "name": "Tag"}, 300)
        if a.ams:
            await call(s, "use_ams_filaments", {"ams_slots": [int(x) for x in a.ams.split(",")]})
        await call(s, "slice_project")
        await call(s, "send_to_printer", {"plate": 1, "via": "file"})


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--ams", default="", help="AMS slots for filament 1,2, e.g. 5,7 (default: the project's own filaments)")
    asyncio.run(main(ap.parse_args()))
