"""Talk to the server over stdio like an MCP client would."""
import asyncio
import os

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main():
    params = StdioServerParameters(command="uv", args=["run", "--directory", os.getcwd(), "unofficial-bambu-mcp"],
                                   env={**os.environ, "UBMCP_DIR": os.path.join(os.getcwd(), "tests", "out")})
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            init = await s.initialize()
            print("server:", init.server_info.name, init.server_info.version)
            tools = await s.list_tools()
            print("tools:", len(tools.tools))
            res = await s.call_tool("new_project", {"name": "stdio", "printer": "A1M"})
            print("new_project ok:", not res.is_error)
            res = await s.call_tool("add_shape", {"shape": "text", "text": "OK", "height": 2, "base": 1.5})
            print("add_shape:", res.content[0].text[:120])
            res = await s.call_tool("preview_plate", {"plate": 1, "zoom": True})
            print("preview:", [c.type for c in res.content], len(res.content[0].data) if res.content[0].type == "image" else "")
            res = await s.call_tool("move_object", {"object": "nope"})
            print("error case:", res.is_error, res.content[0].text[:100])

asyncio.run(main())
