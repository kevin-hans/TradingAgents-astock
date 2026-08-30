"""MCP 工具函数单测：全部 mock run_cli，不触碰真实 CLI。"""
import json

import pytest

pytest.importorskip("pytest_asyncio")

from unittest.mock import AsyncMock, patch  # noqa: E402

from tradingagents.mcp import tools  # noqa: E402
from tradingagents.mcp.cli_runner import CLIResult  # noqa: E402
from tradingagents.mcp.errors import CLIError  # noqa: E402
from tradingagents.mcp.schemas import (  # noqa: E402
    AdviseArgs, AnalyzeArgs, KYCAnswersIn, ReviewArgs,
    ReportsArgs, ScenarioArgs,
)


def _mock_ok(data):
    return CLIResult(ok=True, data=data)


def _mock_err(code="not_found", message="x"):
    return CLIResult(ok=False, error=CLIError(code=code, message=message, payload={}))


@pytest.mark.asyncio
async def test_reports_no_ticker():
    with patch.object(tools, "run_cli", AsyncMock(return_value=_mock_ok(
        {"reports": [{"ticker": "000001", "date": "2026-08-30"}]},
    ))) as m:
        result = await tools.reports_tool(ReportsArgs())
    assert result == {"reports": [{"ticker": "000001", "date": "2026-08-30"}]}
    argv = m.call_args[0][0]
    assert argv == ["reports", "--json"]


@pytest.mark.asyncio
async def test_reports_with_ticker():
    with patch.object(tools, "run_cli", AsyncMock(return_value=_mock_ok(
        {"reports": []},
    ))) as m:
        await tools.reports_tool(ReportsArgs(ticker="000001"))
    argv = m.call_args[0][0]
    assert argv == ["reports", "--ticker", "000001", "--json"]


@pytest.mark.asyncio
async def test_kyc_questionnaire():
    with patch.object(tools, "run_cli", AsyncMock(return_value=_mock_ok(
        {"schema_version": 1, "questions": [], "note": "..."},
    ))) as m:
        result = await tools.kyc_questionnaire_tool()
    assert result["schema_version"] == 1
    argv = m.call_args[0][0]
    assert argv == ["kyc-questionnaire", "--json"]


@pytest.mark.asyncio
async def test_scenario_success():
    with patch.object(tools, "run_cli", AsyncMock(return_value=_mock_ok(
        {"version": 1, "ticker": "000001"},
    ))) as m:
        await tools.scenario_tool(ScenarioArgs(ticker="000001", date="2026-08-30"))
    argv = m.call_args[0][0]
    assert argv == ["scenario", "000001", "--date", "2026-08-30", "--json"]


@pytest.mark.asyncio
async def test_scenario_no_date():
    with patch.object(tools, "run_cli", AsyncMock(return_value=_mock_ok(
        {"version": 1, "ticker": "000001"},
    ))) as m:
        await tools.scenario_tool(ScenarioArgs(ticker="000001"))
    argv = m.call_args[0][0]
    assert argv == ["scenario", "000001", "--json"]


@pytest.mark.asyncio
async def test_advise_passes_kyc_json():
    kyc = KYCAnswersIn(q1=7, q2=5, q3=7, q4=7, q5=7)
    with patch.object(tools, "run_cli", AsyncMock(return_value=_mock_ok(
        {"ticker": "000001", "with_position": {}},
    ))) as m:
        await tools.advise_tool(AdviseArgs(ticker="000001", kyc_answers=kyc))
    argv = m.call_args[0][0]
    assert argv[0] == "advise"
    assert argv[1] == "000001"
    assert "--json" in argv
    assert "--kyc-json" in argv
    kyc_idx = argv.index("--kyc-json")
    assert json.loads(argv[kyc_idx + 1])["q1"] == 7


@pytest.mark.asyncio
async def test_advise_error_raises_tool_error():
    with patch.object(tools, "run_cli", AsyncMock(return_value=_mock_err(
        code="not_found", message="no scenario",
    ))):
        with pytest.raises(tools.ToolError) as exc:
            await tools.advise_tool(AdviseArgs(
                ticker="999", kyc_answers=KYCAnswersIn(q1=7, q2=5, q3=7, q4=7, q5=7),
            ))
    assert exc.value.code == "not_found"
    assert "no scenario" in exc.value.message


@pytest.mark.asyncio
async def test_review_passes_kyc():
    kyc = KYCAnswersIn(q1=7, q2=5, q3=7, q4=7, q5=7)
    with patch.object(tools, "run_cli", AsyncMock(return_value=_mock_ok(
        {"items": []},
    ))) as m:
        await tools.review_tool(ReviewArgs(kyc_answers=kyc))
    argv = m.call_args[0][0]
    assert argv[0] == "review"
    assert "--kyc-json" in argv
    assert "--json" in argv


@pytest.mark.asyncio
async def test_analyze_estimate_mode():
    """confirm=false → subprocess 不带 --confirm"""
    with patch.object(tools, "run_cli", AsyncMock(return_value=_mock_ok(
        {"mode": "estimate", "estimated_llm_calls": 47},
    ))) as m:
        result = await tools.analyze_tool(AnalyzeArgs(ticker="000001", depth="full"))
    argv = m.call_args[0][0]
    assert "--confirm" not in argv
    assert "--depth" in argv
    assert "full" in argv
    assert result["estimated_llm_calls"] == 47


@pytest.mark.asyncio
async def test_analyze_confirm_mode():
    with patch.object(tools, "run_cli", AsyncMock(return_value=_mock_ok(
        {"mode": "executed", "artifact_path": "/tmp/x.json"},
    ))) as m:
        await tools.analyze_tool(AnalyzeArgs(
            ticker="000001", depth="full", confirm=True,
        ))
    argv = m.call_args[0][0]
    assert "--confirm" in argv


@pytest.mark.asyncio
async def test_analyze_with_single_analyst():
    with patch.object(tools, "run_cli", AsyncMock(return_value=_mock_ok({}))) as m:
        await tools.analyze_tool(AnalyzeArgs(
            ticker="000001", depth="analyst", single_analyst="fundamental",
        ))
    argv = m.call_args[0][0]
    assert "--single-analyst" in argv
    assert "fundamental" in argv


@pytest.mark.asyncio
async def test_analyze_with_force():
    with patch.object(tools, "run_cli", AsyncMock(return_value=_mock_ok({}))) as m:
        await tools.analyze_tool(AnalyzeArgs(
            ticker="000001", depth="full", confirm=True, force=True,
        ))
    argv = m.call_args[0][0]
    assert "--force" in argv
