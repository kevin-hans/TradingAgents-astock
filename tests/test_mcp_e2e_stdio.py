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


# ── helpers ───────────────────────────────────────────────────────────────────


def _parse(result) -> dict:
    """Parse JSON from the first text content block of a CallToolResult."""
    return json.loads(result.content[0].text)


# ── happy path ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_kyc_questionnaire(stdio_mcp):
    async with stdio_mcp() as session:
        result = await session.call_tool("kyc_questionnaire", {})
        text = result.content[0].text
        for q in ("q1", "q2", "q3", "q4", "q5"):
            assert q in text, f"expected {q!r} in kyc_questionnaire response"


@pytest.mark.asyncio
async def test_reports_returns_list(stdio_mcp):
    async with stdio_mcp() as session:
        result = await session.call_tool("reports", {})
        assert not result.is_error
        data = _parse(result)
        assert isinstance(data.get("reports"), list)


@pytest.mark.asyncio
async def test_scenario_600519(stdio_mcp):
    async with stdio_mcp() as session:
        result = await session.call_tool(
            "scenario", {"ticker": TICKER, "date": DATE}
        )
        assert not result.is_error
        data = _parse(result)
        assert isinstance(data.get("scenario_buckets"), list)
        assert len(data["scenario_buckets"]) == 2
        assert isinstance(data.get("rating"), str) and data["rating"]


@pytest.mark.asyncio
async def test_advise_600519(stdio_mcp):
    async with stdio_mcp() as session:
        result = await session.call_tool(
            "advise",
            {"ticker": TICKER, "date": DATE, "kyc_answers": KYC},
        )
        assert not result.is_error
        data = _parse(result)
        assert "with_position" in data
        assert "action" in data["with_position"]
        assert "trace" in data
        assert isinstance(data["trace"].get("w_star"), float)


@pytest.mark.asyncio
async def test_analyze_confirm_false(stdio_mcp):
    async with stdio_mcp() as session:
        result = await session.call_tool(
            "analyze", {"ticker": TICKER, "depth": "quick", "confirm": False}
        )
        assert not result.is_error
        data = _parse(result)
        assert data.get("mode") == "estimate"
        assert "estimated_llm_calls" in data


@pytest.mark.asyncio
async def test_analyze_same_day_guard(stdio_mcp):
    # confirm=True on an already-analysed date → same-day guard fires, no LLM
    async with stdio_mcp() as session:
        result = await session.call_tool(
            "analyze",
            {"ticker": TICKER, "date": DATE, "depth": "quick", "confirm": True},
        )
        assert result.is_error
        data = _parse(result)
        assert data.get("error") == "artifacts_exist"


# ── error path ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_unknown_tool_returns_error(stdio_mcp):
    async with stdio_mcp() as session:
        result = await session.call_tool("nonexistent_tool", {})
        assert result.is_error
        data = _parse(result)
        assert data.get("error") == "unknown_tool"


@pytest.mark.asyncio
async def test_advise_missing_kyc_raises(stdio_mcp):
    # kyc_answers is a required field in AdviseArgs — omitting it triggers
    # a pydantic ValidationError caught by on_call_tool's generic handler.
    async with stdio_mcp() as session:
        result = await session.call_tool("advise", {"ticker": TICKER})
        assert result.is_error
        data = _parse(result)
        assert "error" in data
