"""MCP server 集成测试：6 工具挂载 + 分发 + 回调错误路径。"""
import json

import pytest

pytest.importorskip("mcp")
pytest.importorskip("pytest_asyncio")

from unittest.mock import AsyncMock, patch  # noqa: E402

from tradingagents.mcp import tools  # noqa: E402
from tradingagents.mcp.cli_runner import CLIResult  # noqa: E402
from tradingagents.mcp.errors import CLIError  # noqa: E402
from tradingagents.mcp.server import (  # noqa: E402
    build_server,
    dispatch_tool,
    list_tools_spec,
    on_call_tool,
    on_list_tools,
)


class TestListTools:
    def test_six_tools_discovered(self):
        names = {t.name for t in list_tools_spec()}
        assert names == {
            "reports", "scenario", "advise", "review",
            "kyc_questionnaire", "analyze",
        }

    def test_tool_has_schema(self):
        for t in list_tools_spec():
            assert t.input_schema.get("type") == "object"
            assert t.description

    def test_advise_schema_requires_kyc(self):
        advise = next(t for t in list_tools_spec() if t.name == "advise")
        assert "kyc_answers" in advise.input_schema.get("properties", {})
        assert "kyc_answers" in advise.input_schema.get("required", [])

    def test_kyc_questionnaire_no_params(self):
        kyc = next(t for t in list_tools_spec() if t.name == "kyc_questionnaire")
        assert kyc.input_schema.get("properties") == {}


class TestDispatch:
    @pytest.mark.asyncio
    async def test_reports_dispatch(self):
        with patch.object(tools, "run_cli", AsyncMock(return_value=CLIResult(
            ok=True, data={"reports": []},
        ))):
            result = await dispatch_tool("reports", {})
        assert result == {"reports": []}

    @pytest.mark.asyncio
    async def test_unknown_tool_raises_tool_error(self):
        with pytest.raises(tools.ToolError):
            await dispatch_tool("nope", {})

    @pytest.mark.asyncio
    async def test_advise_bad_kyc_raises_validation(self):
        with pytest.raises(Exception):
            await dispatch_tool("advise", {"ticker": "000001", "kyc_answers": {"q1": 4}})

    @pytest.mark.asyncio
    async def test_scenario_missing_ticker_raises_validation(self):
        with pytest.raises(Exception):
            await dispatch_tool("scenario", {})


class TestServerCallbacks:
    @pytest.mark.asyncio
    async def test_list_tools_callback(self):
        result = await on_list_tools(None, None)
        names = {t.name for t in result.tools}
        assert "analyze" in names and len(result.tools) == 6

    @pytest.mark.asyncio
    async def test_call_tool_success(self):
        from mcp.types import CallToolRequestParams
        with patch.object(tools, "run_cli", AsyncMock(return_value=CLIResult(
            ok=True, data={"reports": [{"ticker": "000001"}]},
        ))):
            params = CallToolRequestParams(name="reports", arguments={})
            result = await on_call_tool(None, params)
        assert result.is_error is False
        assert result.structured_content == {"reports": [{"ticker": "000001"}]}
        assert json.loads(result.content[0].text)["reports"][0]["ticker"] == "000001"

    @pytest.mark.asyncio
    async def test_call_tool_error_returns_is_error(self):
        from mcp.types import CallToolRequestParams
        with patch.object(tools, "run_cli", AsyncMock(return_value=CLIResult(
            ok=False,
            error=CLIError(code="not_found", message="no scenario", payload={}),
        ))):
            params = CallToolRequestParams(name="scenario", arguments={"ticker": "999999"})
            result = await on_call_tool(None, params)
        assert result.is_error is True
        assert result.structured_content["error"] == "not_found"
        assert result.structured_content["message"] == "no scenario"

    @pytest.mark.asyncio
    async def test_call_tool_unexpected_exception_internal(self):
        from mcp.types import CallToolRequestParams
        with patch.object(tools, "run_cli", AsyncMock(side_effect=RuntimeError("boom"))):
            params = CallToolRequestParams(name="reports", arguments={})
            result = await on_call_tool(None, params)
        assert result.is_error is True
        assert result.structured_content["error"] == "internal"

    @pytest.mark.asyncio
    async def test_call_tool_validation_error_is_error(self):
        from mcp.types import CallToolRequestParams
        params = CallToolRequestParams(name="scenario", arguments={})
        result = await on_call_tool(None, params)
        assert result.is_error is True

    @pytest.mark.asyncio
    async def test_call_tool_none_arguments(self):
        from mcp.types import CallToolRequestParams
        with patch.object(tools, "run_cli", AsyncMock(return_value=CLIResult(
            ok=True, data={"reports": []},
        ))):
            params = CallToolRequestParams(name="reports")  # arguments=None
            result = await on_call_tool(None, params)
        assert result.is_error is False


class TestBuildServer:
    def test_build_server_returns_server_with_handlers(self):
        from mcp.server import Server
        server = build_server()
        assert isinstance(server, Server)
        assert server.name == "tradingagents"

    def test_run_unknown_transport_raises(self):
        import pytest as _pytest
        from tradingagents.mcp import server as srv
        with _pytest.raises(ValueError):
            srv.run(transport="carrier-pigeon")


class TestScenarioEndToEnd:
    @pytest.mark.asyncio
    async def test_scenario_tool_via_real_cli(self, tmp_path, monkeypatch):
        """scenario 工具 subprocess 调真 CLI（不再 mock run_cli），验证 argv 契约成立。"""
        import json as _json
        reports = tmp_path / "reports"
        reports.mkdir()
        (reports / "scenario_000001_2026-08-30.json").write_text(_json.dumps({
            "version": 1, "ticker": "000001", "trade_date": "2026-08-30",
            "rating": "Buy",
            "scenario_buckets": [{
                "horizon_months": 6,
                "scenarios": [
                    {"name": "bull", "thesis": "t", "expected_return": 0.25, "prob": 0.35},
                    {"name": "base", "thesis": "t", "expected_return": 0.05, "prob": 0.45},
                    {"name": "bear", "thesis": "t", "expected_return": -0.15, "prob": 0.20},
                ],
                "key_levels": {"stop": 8.5, "entry_low": 9.5, "entry_high": 10.5, "target": 12.5},
            }],
            "falsification": {"conditions": ["c"]},
        }), encoding="utf-8")
        monkeypatch.setenv("TRADINGAGENTS_REPORTS_DIR", str(reports))
        monkeypatch.setenv("HOME", str(tmp_path))
        result = await dispatch_tool("scenario", {"ticker": "000001"})
        assert result["ticker"] == "000001"
