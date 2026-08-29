"""TradingAgents MCP server 薄壳（CLAUDE.md 项目级方针）。

MCP 层零业务逻辑：所有工具通过 subprocess 调 tradingagents ... --json，
解析 stdout JSON、映射错误码。业务住 CLI。

安装：pip install -e .[mcp]
启动：tradingagents mcp-serve --transport sse --port 8765
"""
try:
    import mcp  # noqa: F401
except ImportError as e:
    raise ImportError(
        "需要 mcp SDK。安装：pip install -e .[mcp]"
    ) from e
