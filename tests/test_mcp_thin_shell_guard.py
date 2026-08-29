"""CLAUDE.md 项目级方针：MCP server 必须是 CLI 薄壳。

物理保证：tradingagents/mcp/ 下所有 .py 不得 import 业务模块。
守卫触发 = 违反方针 = 必须回退到 subprocess 形态。
"""
import ast
from pathlib import Path

import pytest


MCP_DIR = Path(__file__).parent.parent / "tradingagents" / "mcp"

FORBIDDEN_PREFIXES = (
    "tradingagents.advisor",
    "tradingagents.graph",
    "tradingagents.dataflows",
    "tradingagents.agents",
    "tradingagents.performance",
)


def _collect_imports(path: Path) -> list[str]:
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src, filename=str(path))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.append(node.module)
    return names


def test_mcp_dir_exists():
    assert MCP_DIR.is_dir(), f"{MCP_DIR} 不存在——先建 mcp/ 包"


def _mcp_python_files():
    return [p for p in MCP_DIR.rglob("*.py") if "__pycache__" not in p.parts]


@pytest.mark.parametrize("py_file", _mcp_python_files() or [pytest.param(None, marks=pytest.mark.skip(reason="mcp/ 无 .py"))])
def test_no_business_module_imports(py_file):
    if py_file is None:
        pytest.skip("mcp/ 无 .py")
    imports = _collect_imports(py_file)
    for imp in imports:
        for forbidden in FORBIDDEN_PREFIXES:
            assert not imp.startswith(forbidden), (
                f"{py_file.relative_to(MCP_DIR)} import 了业务模块 {imp} —— "
                f"违反 MCP 薄壳方针（CLAUDE.md）。改回 subprocess 调 CLI。"
            )


def test_mcp_import_error_when_sdk_missing(monkeypatch):
    """未装 [mcp] extra 时 import tradingagents.mcp 报清晰错误。"""
    import importlib
    import sys

    # 强制模拟 mcp SDK 不可用
    monkeypatch.setitem(sys.modules, "mcp", None)
    if "tradingagents.mcp" in sys.modules:
        monkeypatch.delitem(sys.modules, "tradingagents.mcp", raising=False)
    with pytest.raises(ImportError, match=r"pip install .*\[mcp\]|需要 mcp SDK"):
        importlib.import_module("tradingagents.mcp")
