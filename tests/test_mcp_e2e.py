"""End-to-end: start the real server over stdio and call its tools through the official MCP client."""
import json
import os
import sys
from pathlib import Path

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def _run():
    params = StdioServerParameters(command=sys.executable, args=["-m", "bugtriage_mcp.server"],
                                   env={**os.environ, "PYTHONPATH": str(ROOT / "src")})
    async with stdio_client(params) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        tools = {t.name for t in (await s.list_tools()).tools}
        assert tools == {"search_logs", "triage_bug", "find_similar_bugs", "get_bug", "cluster_bugs"}

        res = await s.call_tool("triage_bug", {"title": "WiFi hotspot drops",
                                               "description": "clients lose DHCP lease, DHCP_NO_LEASE in log"})
        out = json.loads(res.content[0].text)
        assert out["component"] == "wifi" and len(out["possible_duplicates"]) == 3

        res = await s.call_tool("search_logs", {"query": "ota_sig_invalid", "level": "ERROR", "limit": 3})
        assert json.loads(res.content[0].text)["total_matches"] > 0


def test_mcp_stdio_roundtrip():
    anyio.run(_run)
