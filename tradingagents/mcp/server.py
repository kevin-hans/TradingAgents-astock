"""MCP server：6 工具挂载 + stdio/sse 传输。

CLAUDE.md 薄壳方针：只 import mcp SDK + 本包 tools/schemas/errors。禁业务模块。
mcp SDK 2.1.0 回调式 API（无 FastMCP、无 @server.tool 装饰器）。
"""
import json
from typing import Any

from mcp.server import Server
from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

from tradingagents.mcp import tools
from tradingagents.mcp.errors import MCP_ERROR_INTERNAL
from tradingagents.mcp.schemas import (
    AdviseArgs,
    AnalyzeArgs,
    ReportsArgs,
    ReviewArgs,
    ScenarioArgs,
)

_NO_ARGS_SCHEMA = {"type": "object", "properties": {}}


def list_tools_spec() -> list[Tool]:
    """6 个工具的声明（schema 由 pydantic model_json_schema 生成）。"""
    return [
        Tool(
            name="reports",
            description="列出可用研报。可选 ticker 过滤。秒级只读。",
            input_schema=ReportsArgs.model_json_schema(),
        ),
        Tool(
            name="kyc_questionnaire",
            description="返回 5 题 KYC 问卷（首次建档/更新画像）。秒级只读。",
            input_schema=_NO_ARGS_SCHEMA,
        ),
        Tool(
            name="scenario",
            description="返回原始情景分布（bull/base/bear 概率+key_levels）。秒级只读。",
            input_schema=ScenarioArgs.model_json_schema(),
        ),
        Tool(
            name="advise",
            description="个性化投资建议。kyc_answers 必填（5 题答案 inline 传）。秒级只读。",
            input_schema=AdviseArgs.model_json_schema(),
        ),
        Tool(
            name="review",
            description="决策纪律巡检（止损/目标/期限）。kyc_answers 必填。",
            input_schema=ReviewArgs.model_json_schema(),
        ),
        Tool(
            name="analyze",
            description=(
                "触发新分析。confirm=false（默认）只返报价不执行；"
                "confirm=true 才真正跑（分钟级）。"
            ),
            input_schema=AnalyzeArgs.model_json_schema(),
        ),
    ]


async def dispatch_tool(name: str, arguments: dict) -> dict[str, Any]:
    """按名字分发到 tools.*；ToolError 往外抛（由 on_call_tool 统一转）。"""
    if name == "reports":
        return await tools.reports_tool(ReportsArgs.model_validate(arguments))
    if name == "kyc_questionnaire":
        return await tools.kyc_questionnaire_tool()
    if name == "scenario":
        return await tools.scenario_tool(ScenarioArgs.model_validate(arguments))
    if name == "advise":
        return await tools.advise_tool(AdviseArgs.model_validate(arguments))
    if name == "review":
        return await tools.review_tool(ReviewArgs.model_validate(arguments))
    if name == "analyze":
        return await tools.analyze_tool(AnalyzeArgs.model_validate(arguments))
    raise tools.ToolError(code="unknown_tool", message=f"unknown tool: {name}", payload={})


def _ok_result(data: dict[str, Any]) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(data, ensure_ascii=False))],
        structured_content=data,
        is_error=False,
    )


def _err_result(payload: dict[str, Any]) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, ensure_ascii=False))],
        structured_content=payload,
        is_error=True,
    )


async def on_list_tools(ctx, params) -> ListToolsResult:
    return ListToolsResult(tools=list_tools_spec())


async def on_call_tool(ctx, params) -> CallToolResult:
    try:
        data = await dispatch_tool(params.name, dict(params.arguments or {}))
        return _ok_result(data)
    except tools.ToolError as e:
        payload = {"error": e.code, "message": e.message, **(e.payload or {})}
        return _err_result(payload)
    except Exception as e:  # 未知异常兜底（含 pydantic ValidationError），不能让 server 崩
        return _err_result({"error": MCP_ERROR_INTERNAL, "message": str(e)})


def build_server() -> Server:
    return Server(
        name="tradingagents",
        on_list_tools=on_list_tools,
        on_call_tool=on_call_tool,
    )


def build_sse_app():
    """SSE 传输的 starlette app（/sse 建流 + /messages/ 回投）。"""
    from starlette.applications import Starlette
    from starlette.routing import Mount, Route

    from mcp.server.sse import SseServerTransport

    server = build_server()
    sse = SseServerTransport("/messages/")

    async def _handle_sse(scope, receive, send):
        # 纯 ASGI 形状：starlette 1.6 的 Request 没有 .send，必须直连 ASGI 三件套
        async with sse.connect_sse(scope, receive, send) as streams:
            await server.run(streams[0], streams[1], server.create_initialization_options())

    class _SSEEndpoint:
        """starlette Route 只把非函数 callable 当原生 ASGI app，包一层类。"""

        async def __call__(self, scope, receive, send):
            await _handle_sse(scope, receive, send)

    return Starlette(
        routes=[
            Route("/sse", endpoint=_SSEEndpoint()),
            Mount("/messages/", app=sse.handle_post_message),
        ],
    )


def run(transport: str = "stdio", host: str = "127.0.0.1", port: int = 8765) -> None:
    """启动 server。transport: stdio / sse。"""
    import asyncio

    server = build_server()
    if transport == "stdio":
        from mcp.server.stdio import stdio_server

        async def _main():
            async with stdio_server() as (read, write):
                await server.run(read, write, server.create_initialization_options())

        asyncio.run(_main())
    elif transport == "sse":
        import uvicorn

        uvicorn.run(build_sse_app(), host=host, port=port)
    else:
        raise ValueError(f"unknown transport: {transport}")
