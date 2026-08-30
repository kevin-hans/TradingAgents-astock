"""asyncio.subprocess 包装：唯一调 CLI 的入口，便于 mock 测试。

CLAUDE.md 薄壳方针：本文件只 import stdlib + 本包 errors。禁业务模块。
"""
import asyncio
import json
import shutil
from dataclasses import dataclass
from typing import Any, Optional

from tradingagents.mcp.errors import CLIError, MCP_ERROR_INTERNAL, map_cli_error


@dataclass
class CLIResult:
    ok: bool
    data: Optional[dict[str, Any]] = None
    error: Optional[CLIError] = None


def _resolve_binary() -> list[str]:
    """定位 tradingagents 可执行；缺失回退 python -m cli.main。"""
    which = shutil.which("tradingagents")
    if which:
        return [which]
    return ["python", "-m", "cli.main"]


async def run_cli(argv: list[str], timeout: float = 900.0) -> CLIResult:
    """跑 tradingagents <argv>，解析 stdout JSON。

    - returncode=0 + stdout 合法 JSON → CLIResult(ok=True, data=...)
    - 非零 exit → 走 map_cli_error（优先 stdout，为空回退 stderr）
    - 超时 → kill + CLIResult(ok=False, error=timeout)
    """
    cmd = _resolve_binary() + list(argv)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass  # プロセスが既に終了している場合は無視
        await proc.wait()
        return CLIResult(
            ok=False,
            error=CLIError(
                code=MCP_ERROR_INTERNAL,
                message=f"CLI 超时（>{timeout}s）",
                payload={},
            ),
        )
    if proc.returncode == 0:
        text = stdout.decode("utf-8", errors="replace")
        try:
            return CLIResult(ok=True, data=json.loads(text))
        except json.JSONDecodeError as e:
            return CLIResult(
                ok=False,
                error=CLIError(
                    code=MCP_ERROR_INTERNAL,
                    message=f"CLI stdout 不是合法 JSON: {e}",
                    payload={"raw": text[:500]},
                ),
            )
    # 非零 exit code：优先看 stdout（CLI _emit 用 print_json 写 stdout），空则看 stderr
    payload_source = stdout if stdout.strip() else stderr
    return CLIResult(ok=False, error=map_cli_error(proc.returncode, payload_source))
