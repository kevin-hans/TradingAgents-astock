import pytest

pytest.importorskip("pytest_asyncio")

import asyncio  # noqa: E402
from unittest.mock import AsyncMock, patch  # noqa: E402

from tradingagents.mcp.cli_runner import CLIResult, run_cli  # noqa: E402
from tradingagents.mcp.errors import MCP_ERROR_NOT_FOUND, MCP_ERROR_INTERNAL  # noqa: E402


@pytest.mark.asyncio
async def test_success():
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b'{"ticker": "000001"}', b""))
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
        result = await run_cli(["advise", "000001", "--json"])
    assert isinstance(result, CLIResult)
    assert result.ok is True
    assert result.data == {"ticker": "000001"}


@pytest.mark.asyncio
async def test_error_exit_code_mapping():
    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(
        b'{"error": "not_found", "message": "no scenario"}', b""
    ))
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
        result = await run_cli(["advise", "999999", "--json"])
    assert result.ok is False
    assert result.error.code == MCP_ERROR_NOT_FOUND
    assert "no scenario" in result.error.message


@pytest.mark.asyncio
async def test_malformed_stdout_when_ok():
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"not json", b""))
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
        result = await run_cli(["reports", "--json"])
    assert result.ok is False
    assert result.error.code == MCP_ERROR_INTERNAL


@pytest.mark.asyncio
async def test_stderr_fallback_when_stdout_empty():
    """CLI 用 print_json 走 stdout；如果 stdout 空则看 stderr。"""
    mock_proc = AsyncMock()
    mock_proc.returncode = 1
    mock_proc.communicate = AsyncMock(return_value=(
        b"", b'{"error": "not_found", "message": "empty stdout"}'
    ))
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
        result = await run_cli(["advise", "999", "--json"])
    assert result.ok is False
    assert result.error.code == MCP_ERROR_NOT_FOUND


@pytest.mark.asyncio
async def test_timeout():
    """超时应 kill 进程并返 internal 错误。"""
    async def _hang():
        await asyncio.sleep(100)
        return (b"", b"")
    mock_proc = AsyncMock()
    mock_proc.returncode = None
    mock_proc.communicate = _hang
    mock_proc.kill = AsyncMock()  # kill 是同步的，但 AsyncMock 兼容
    mock_proc.wait = AsyncMock(return_value=None)
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
        result = await run_cli(["reports", "--json"], timeout=0.1)
    assert result.ok is False
    assert result.error.code == MCP_ERROR_INTERNAL
    assert "超时" in result.error.message or "timeout" in result.error.message.lower()
