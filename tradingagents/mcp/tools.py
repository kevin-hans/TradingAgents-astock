"""6 个 MCP 工具，全部 subprocess 调 CLI + 解析 JSON + 错误映射。

CLAUDE.md 薄壳方针：本文件只 import stdlib + 本包内 cli_runner/errors/schemas。
禁 advisor/graph/dataflows/agents/performance 等业务模块。
"""
import json
from typing import Any

from tradingagents.mcp.cli_runner import run_cli
from tradingagents.mcp.errors import CLIError
from tradingagents.mcp.schemas import (
    AdviseArgs,
    AnalyzeArgs,
    ReportsArgs,
    ReviewArgs,
    ScenarioArgs,
)


class ToolError(Exception):
    """工具层错误：携带结构化 code + message + payload。"""

    def __init__(self, code: str, message: str, payload: dict[str, Any]) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.payload = payload


def _raise_from_cli(err: CLIError) -> None:
    raise ToolError(code=err.code, message=err.message, payload=err.payload)


async def reports_tool(args: ReportsArgs) -> dict[str, Any]:
    """列出已生成的分析报告。"""
    argv = ["reports"]
    if args.ticker is not None:
        argv += ["--ticker", args.ticker]
    argv += ["--json"]
    result = await run_cli(argv)
    if not result.ok:
        _raise_from_cli(result.error)
    return result.data


async def kyc_questionnaire_tool() -> dict[str, Any]:
    """返回 KYC 问卷 schema（问题列表 + 说明）。"""
    result = await run_cli(["kyc-questionnaire", "--json"])
    if not result.ok:
        _raise_from_cli(result.error)
    return result.data


async def scenario_tool(args: ScenarioArgs) -> dict[str, Any]:
    """获取指定股票的情景向量树。"""
    argv = ["scenario", args.ticker]
    if args.date is not None:
        argv += ["--date", args.date]
    argv += ["--json"]
    result = await run_cli(argv)
    if not result.ok:
        _raise_from_cli(result.error)
    return result.data


async def advise_tool(args: AdviseArgs) -> dict[str, Any]:
    """结合情景树 + KYC 答案给出个性化投资建议。"""
    argv = [
        "advise", args.ticker,
        "--json",
        "--kyc-json", json.dumps(args.kyc_answers.model_dump()),
    ]
    if args.date is not None:
        argv += ["--date", args.date]
    result = await run_cli(argv)
    if not result.ok:
        _raise_from_cli(result.error)
    return result.data


async def review_tool(args: ReviewArgs) -> dict[str, Any]:
    """决策纪律巡检（P3 CLI 到位前返 not_implemented，透传即可）。"""
    argv = [
        "review",
        "--json",
        "--kyc-json", json.dumps(args.kyc_answers.model_dump()),
    ]
    result = await run_cli(argv)
    if not result.ok:
        _raise_from_cli(result.error)
    return result.data


async def analyze_tool(args: AnalyzeArgs) -> dict[str, Any]:
    """触发多 Agent 分析（estimate 或 confirm 两相）。"""
    argv = ["analyze", "--json", "--depth", args.depth]
    if args.confirm:
        argv += ["--confirm"]
    if args.force:
        argv += ["--force"]
    if args.single_analyst is not None:
        argv += ["--single-analyst", args.single_analyst]
    result = await run_cli(argv)
    if not result.ok:
        _raise_from_cli(result.error)
    return result.data
