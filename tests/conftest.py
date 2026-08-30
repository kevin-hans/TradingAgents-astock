"""Shared pytest fixtures that prevent CI hangs when API keys are absent."""

import os
import shutil
import socket
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def pytest_configure(config):
    for marker in ("unit", "integration", "smoke"):
        config.addinivalue_line("markers", f"{marker}: {marker}-level tests")


_API_KEY_ENV_VARS = (
    "OPENAI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "XAI_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "ZHIPU_API_KEY",
    "OPENROUTER_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "ALPHA_VANTAGE_API_KEY",
)


@pytest.fixture(autouse=True)
def _dummy_api_keys(monkeypatch):
    for env_var in _API_KEY_ENV_VARS:
        monkeypatch.setenv(env_var, os.environ.get(env_var, "placeholder"))


@pytest.fixture()
def mock_llm_client():
    client = MagicMock()
    client.get_llm.return_value = MagicMock()
    with patch(
        "tradingagents.llm_clients.factory.create_llm_client",
        return_value=client,
    ):
        yield client


# ── MCP e2e helpers ────────────────────────────────────────────────────────────


@pytest.fixture
def unused_tcp_port() -> int:
    """Return a free TCP port by binding and releasing it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture
def tmp_artifacts_env(tmp_path):
    """Copy real 600519/2026-08-30 artifacts to tmp_path and point TRADINGAGENTS_RESULTS_DIR there.

    Each test gets a fresh writable copy; the real log directory is never touched.
    TRADINGAGENTS_PROFILE also points to a nonexistent path so advise-without-kyc
    deterministically returns kyc_required regardless of the host machine's profile.
    """
    src = os.path.expanduser("~/.tradingagents/logs/600519")
    dst = tmp_path / "logs" / "600519"
    shutil.copytree(src, dst)
    results_dir = str(tmp_path / "logs")
    prev_results = os.environ.get("TRADINGAGENTS_RESULTS_DIR")
    os.environ["TRADINGAGENTS_RESULTS_DIR"] = results_dir
    prev_profile = os.environ.get("TRADINGAGENTS_PROFILE")
    os.environ["TRADINGAGENTS_PROFILE"] = str(tmp_path / "nonexistent_profile.json")
    yield results_dir
    if prev_results is None:
        os.environ.pop("TRADINGAGENTS_RESULTS_DIR", None)
    else:
        os.environ["TRADINGAGENTS_RESULTS_DIR"] = prev_results
    if prev_profile is None:
        os.environ.pop("TRADINGAGENTS_PROFILE", None)
    else:
        os.environ["TRADINGAGENTS_PROFILE"] = prev_profile


def _tradingagents_cli() -> str:
    """Resolve the repo venv CLI entry, falling back to PATH."""
    venv_cli = Path(__file__).parent.parent / ".venv" / "bin" / "tradingagents"
    if venv_cli.exists():
        return str(venv_cli)
    found = shutil.which("tradingagents")
    if found:
        return found
    pytest.skip("tradingagents CLI entry point not found")


@pytest.fixture
def stdio_mcp(tmp_artifacts_env):
    """Return an async context-manager factory yielding an initialised MCP
    ClientSession over stdio transport (real `tradingagents mcp-serve` subprocess).

    Tests must enter it inside their own body (`async with stdio_mcp() as s:`).
    Anyio cancel scopes are task-bound, so entering/exiting in the test's task
    is what keeps teardown clean — pytest-asyncio finalises async-generator
    fixtures in a different task and would otherwise blow up on exit.

    Requires [dev] extra (mcp, pytest-asyncio).
    """
    pytest.importorskip("mcp")
    pytest.importorskip("pytest_asyncio")
    import contextlib
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    @contextlib.asynccontextmanager
    async def _factory():
        params = StdioServerParameters(
            command=_tradingagents_cli(),
            args=["mcp-serve", "--transport", "stdio"],
            env={**os.environ},
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    return _factory


@pytest.fixture
def sse_mcp(tmp_artifacts_env, unused_tcp_port):
    """Return an async context-manager factory yielding an initialised MCP
    ClientSession over SSE transport.

    Starts `tradingagents mcp-serve --transport sse --port N` as a subprocess,
    waits up to 5 s for the /sse endpoint to respond, then connects.
    Skips (not fails) if the server does not start in time. Same task-bound
    enter/exit rule as stdio_mcp above.
    """
    pytest.importorskip("mcp")
    pytest.importorskip("pytest_asyncio")
    import asyncio
    import contextlib
    import httpx
    from mcp.client.session import ClientSession
    from mcp.client.sse import sse_client

    port = unused_tcp_port
    sse_url = f"http://127.0.0.1:{port}/sse"

    @contextlib.asynccontextmanager
    async def _factory():
        proc = await asyncio.create_subprocess_exec(
            _tradingagents_cli(),
            "mcp-serve", "--transport", "sse", "--port", str(port),
            env={**os.environ},
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            started = False
            async with httpx.AsyncClient() as http:
                for _ in range(25):  # 25 × 0.2 s = 5 s max
                    try:
                        async with http.stream("GET", sse_url, timeout=0.5) as r:
                            if r.status_code == 200:
                                started = True
                                break
                    except Exception:
                        pass
                    await asyncio.sleep(0.2)
            if not started:
                pytest.skip("SSE server did not start in time")
            async with sse_client(sse_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
        finally:
            proc.terminate()
            await proc.wait()

    return _factory


@pytest.fixture
def http_mcp(tmp_artifacts_env, unused_tcp_port):
    """Return an async context-manager factory yielding an initialised MCP
    ClientSession over Streamable HTTP transport (/mcp endpoint, JSON responses).

    Same subprocess shape as sse_mcp — one server process serves both
    /sse (legacy) and /mcp (streamable). Same task-bound enter/exit rule.
    """
    pytest.importorskip("mcp")
    pytest.importorskip("pytest_asyncio")
    import asyncio
    import contextlib
    import httpx
    from mcp.client.session import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    port = unused_tcp_port
    base_url = f"http://127.0.0.1:{port}"
    mcp_url = f"{base_url}/mcp"

    @contextlib.asynccontextmanager
    async def _factory():
        proc = await asyncio.create_subprocess_exec(
            _tradingagents_cli(),
            "mcp-serve", "--transport", "sse", "--port", str(port),
            env={**os.environ},
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            started = False
            async with httpx.AsyncClient() as http:
                for _ in range(25):  # 25 × 0.2 s = 5 s max
                    try:
                        # GET /mcp 无会话头会被 streamable 层秒拒 400（完整响应），
                        # 400 恰好证明 uvicorn 在服务——别探 /sse（流式响应永不完成）
                        r = await http.get(f"{base_url}/mcp", timeout=0.5)
                        if r.status_code < 500:
                            started = True
                            break
                    except Exception:
                        pass
                    await asyncio.sleep(0.2)
            if not started:
                pytest.skip("HTTP server did not start in time")
            async with streamable_http_client(mcp_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    yield session
        finally:
            proc.terminate()
            await proc.wait()

    return _factory
