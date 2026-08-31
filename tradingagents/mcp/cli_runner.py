"""asyncio.subprocess 包装：唯一调 CLI 的入口，便于 mock 测试。

CLAUDE.md 薄壳方针：本文件只 import stdlib + 本包 errors。禁业务模块。
"""
import asyncio
import json
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from tradingagents.mcp.errors import CLIError, MCP_ERROR_INTERNAL, map_cli_error


@dataclass
class CLIResult:
    ok: bool
    data: Optional[dict[str, Any]] = None
    error: Optional[CLIError] = None


def _resolve_binary() -> list[str]:
    """定位 tradingagents 可执行。

    优先级：
    1. PATH 中的 tradingagents（激活 venv 或显式安装到 PATH 的情况）
    2. sys.prefix/bin/tradingagents（venv 正确激活时）
    3. 当前解释器跑 cli.main 模块 + _subprocess_env 保证 PYTHONPATH 正确
    """
    which = shutil.which("tradingagents")
    if which:
        return [which]
    venv_script = Path(sys.prefix) / "bin" / "tradingagents"
    if venv_script.exists():
        return [str(venv_script)]
    return [sys.executable, "-m", "cli.main"]


def _subprocess_env() -> dict[str, str]:
    """为 subprocess 构建携带正确 PYTHONPATH 的环境变量字典。

    问题根因：MCP server 以 systemd 服务形式运行时，venv 的 python 是指向系统
    Python 的 symlink，kernel 解析 shebang 后 sys.executable/sys.prefix 均落到
    /usr/bin，导致 subprocess 无法找到 typer 等 venv 包。
    解法：从 __file__ 向上查找 .venv/lib/pythonX.Y/site-packages，注入 PYTHONPATH，
    subprocess 即可在系统 Python 下正确 import venv 中安装的包。
    """
    env = dict(os.environ)

    # 从本文件所在目录向上最多 6 层寻找 .venv
    search = Path(__file__).resolve().parent
    for _ in range(6):
        lib_dir = search / ".venv" / "lib"
        if lib_dir.is_dir():
            site_pkgs = sorted(lib_dir.glob("python*/site-packages"))
            if site_pkgs:
                # project_root 本身也要加入（editable install 的包在源码目录）
                paths = [str(p) for p in site_pkgs] + [str(search)]
                existing = env.get("PYTHONPATH", "")
                env["PYTHONPATH"] = ":".join(paths + ([existing] if existing else []))
                env["VIRTUAL_ENV"] = str(search / ".venv")
                return env
        search = search.parent

    return env


async def run_cli(argv: list[str], timeout: float | None = None) -> CLIResult:
    """跑 tradingagents <argv>，解析 stdout JSON。

    - returncode=0 + stdout 合法 JSON → CLIResult(ok=True, data=...)
    - 非零 exit → 走 map_cli_error（优先 stdout，为空回退 stderr）
    - 超时 → kill + CLIResult(ok=False, error=timeout)

    timeout 缺省从环境变量 TRADINGAGENTS_CLI_TIMEOUT 读取（秒），未设置则 900s。
    Pi 3B 跑 --depth full 常超过 15 min，可调到 3600s+。
    """
    if timeout is None:
        timeout = float(os.getenv("TRADINGAGENTS_CLI_TIMEOUT", "900"))
    cmd = _resolve_binary() + list(argv)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=_subprocess_env(),
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
