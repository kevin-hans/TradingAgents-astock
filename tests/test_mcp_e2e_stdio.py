"""MCP e2e — stdio transport.

Launches a real `tradingagents mcp-serve --transport stdio` subprocess,
connects via mcp.client.stdio, and exercises all 6 tools.

Requires [dev] extra (mcp, pytest-asyncio). Skips cleanly without it.
LLM calls: zero — all tools run against existing 600519/2026-08-30 artifacts.
"""
import json

import pytest

pytest.importorskip("mcp")
pytest.importorskip("pytest_asyncio")

TICKER = "600519"
DATE = "2026-08-30"
KYC = {"q1": 5, "q2": 5, "q3": 5, "q4": 5, "q5": 5}


@pytest.mark.asyncio
async def test_list_tools_returns_six(stdio_mcp):
    async with stdio_mcp() as session:
        result = await session.list_tools()
        names = {t.name for t in result.tools}
        assert names == {
            "reports", "kyc_questionnaire", "scenario",
            "advise", "review", "analyze",
        }
