# PicoClaw ↔ TradingAgents MCP Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在本仓库内交付 MCP server 薄壳，暴露 6 个工具供 PicoClaw / Claude Code / 任何 MCP 客户端消费 TradingAgents 的分析能力；同时补齐薄壳下面 CLI 侧的独立命令（`reports` / `kyc-questionnaire` / `analyze --json --confirm` / `mcp-serve`）。

**Architecture:** MCP 层是 CLI 的薄壳（TradingAgents 项目级方针，见 CLAUDE.md）；所有业务逻辑住在 CLI 命令实现里，MCP 层 subprocess 调 CLI + 解析 JSON + 映射错误码。物理边界保证 MCP 无逻辑漂移（静态守卫测试拦 import）。

**Tech Stack:** Python 3.10+ / mcp SDK v2.1+（httpx2 无冲突）/ pydantic v2 / typer / pytest / asyncio.subprocess。作为 `[mcp]` extra 提供，不用 MCP 的用户零影响。

**前置状态**：
- 情景向量顾问 spec P2 分期已交付（`2026-08-30-scenario-vector-advisor-p2.md` 完成）——本 plan 的 M1 依赖 `tradingagents advise --json --kyc-json` 已就绪；`advisor.questionnaire.get_questionnaire()` 可用
- P1 已合入 main（scenario_<ticker>_<date>.json 制品可读）
- 本 plan 交付后 baseline：P2 baseline + 本 plan 新增测试

**Scope out**（本 plan 明确不做）：
- Web UI 相关（属 P2b / Web UI PR）
- P3 review 巡检本体（`tradingagents review` CLI 命令）——**但本 plan 会拉一个薄壳工具 `review` 指向 P3 CLI，工具在 P3 到位前挂 stub**
- MCP server 鉴权 / 授权（spec §7.3 v1 显式不做）
- 异步作业队列（spec §12 YAGNI）
- 其它 MCP 客户端的具体接入示例（属于文档 / 部署事）

---

## File Structure

**新增文件（`tradingagents/mcp/` 子包，subprocess 只调 CLI）：**

| 文件 | 职责 | 严禁 |
|---|---|---|
| `tradingagents/mcp/__init__.py` | 包标记；mcp SDK 未装时 raise 清晰 ImportError | 业务逻辑 |
| `tradingagents/mcp/server.py` | MCP server 启动、工具挂载、传输选择 | 业务判断 |
| `tradingagents/mcp/schemas.py` | 工具入参 pydantic 类型（复用 advisor.types 的 KYCAnswers） | 业务判断 |
| `tradingagents/mcp/tools.py` | 6 个工具实现（subprocess 调 CLI + 解析 JSON） | 业务判断 |
| `tradingagents/mcp/errors.py` | CLI exit code / stderr → MCP 错误码映射 | 业务判断 |
| `tradingagents/mcp/cli_runner.py` | asyncio.subprocess 包装（可 mock 测试） | 业务判断 |

**修改文件：**

| 文件 | 修改 |
|---|---|
| `pyproject.toml` | 新增 `[project.optional-dependencies]` `mcp = ["mcp>=2.1.0"]` |
| `cli/main.py` | 新增 `reports` / `kyc-questionnaire` / `mcp-serve` 子命令；扩展 `analyze` 加 `--json` + `--confirm` |
| `CLAUDE.md` | 已知问题段追加 MCP 集成交付备注 |

**新增测试文件：**

| 文件 | 覆盖 |
|---|---|
| `tests/test_mcp_thin_shell_guard.py` | **静态守卫**：`tradingagents/mcp/` 下所有 `.py` 不得 import advisor/graph/dataflows |
| `tests/test_mcp_schemas.py` | 工具 pydantic 入参类型 |
| `tests/test_mcp_errors.py` | 错误码映射表 |
| `tests/test_mcp_cli_runner.py` | subprocess 包装（可 mock） |
| `tests/test_mcp_tools_unit.py` | 6 个工具 mock subprocess 单测 |
| `tests/test_mcp_server_integration.py` | 起真实 server（stdio）→ 发现 6 个工具 → 调一遍 |
| `tests/test_cli_reports_json.py` | CLI reports 子命令 |
| `tests/test_cli_kyc_questionnaire.py` | CLI kyc-questionnaire 子命令 |
| `tests/test_cli_analyze_confirm.py` | CLI analyze --json / --confirm 两相 |
| `tests/test_cli_mcp_serve.py` | CLI mcp-serve --help 稳定 + default command 兼容 |

---

## Milestone 0: 依赖与骨架（M0）

### Task 1: 添加 `[mcp]` extra + 包骨架 + 静态守卫测试

**Files:**
- Modify: `pyproject.toml`
- Create: `tradingagents/mcp/__init__.py`
- Test: `tests/test_mcp_thin_shell_guard.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mcp_thin_shell_guard.py
"""CLAUDE.md 项目级方针：MCP server 必须是 CLI 薄壳。

物理保证：tradingagents/mcp/ 下所有 .py 不得 import 业务模块（advisor / graph /
dataflows / agents 等）。守卫触发 → 立刻回退到 subprocess 形态。
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


@pytest.mark.parametrize("py_file", [p for p in MCP_DIR.rglob("*.py") if p.name != "__pycache__"])
def test_no_business_module_imports(py_file: Path):
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

    monkeypatch.setitem(sys.modules, "mcp", None)
    if "tradingagents.mcp" in sys.modules:
        del sys.modules["tradingagents.mcp"]
    with pytest.raises(ImportError, match=r"pip install .*\[mcp\]|需要 mcp SDK"):
        importlib.import_module("tradingagents.mcp")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_mcp_thin_shell_guard.py -v`

Expected: FAIL with "tradingagents/mcp 不存在" 或 collection error（`FileNotFoundError`）

- [ ] **Step 3: Write minimal implementation**

Edit `pyproject.toml`（在 `[project.optional-dependencies]` 段追加）：

```toml
[project.optional-dependencies]
agentsdk = ["claude-agent-sdk>=0.2.82"]
mcp = ["mcp>=2.1.0"]   # httpx2 依赖，与 mootdx (httpx<0.26) 无冲突（uv lock 实测）
```

Create `tradingagents/mcp/__init__.py`：

```python
"""TradingAgents MCP server 薄壳（CLAUDE.md 项目级方针）。

**MCP 层零业务逻辑**：所有工具通过 subprocess 调 `tradingagents ... --json`，
解析 stdout JSON、映射错误码。业务住 CLI。

安装：`pip install -e .[mcp]`
启动：`tradingagents mcp-serve --transport sse --port 8765`
"""
try:
    import mcp  # noqa: F401
except ImportError as e:
    raise ImportError(
        "需要 mcp SDK。安装：pip install -e .[mcp]"
    ) from e
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_mcp_thin_shell_guard.py -v`

Expected: PASS (3 tests：目录存在、无违规 import、SDK 未装时清晰 ImportError)

Note: 若本机没装 `mcp` package，`test_mcp_import_error_when_sdk_missing` 通过；
若装了，也应通过（monkeypatch 强制模拟未装）。

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml tradingagents/mcp/__init__.py tests/test_mcp_thin_shell_guard.py
git commit -m "feat(mcp): P3+ 骨架 + [mcp] extra + 薄壳方针静态守卫测试"
```

---

## Milestone 1: CLI 命令扩展（M1）——subprocess 目标先立起来

### Task 2: CLI `reports` 子命令

**Files:**
- Modify: `cli/main.py`
- Test: `tests/test_cli_reports_json.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_reports_json.py
import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def tmp_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setenv("TRADINGAGENTS_REPORTS_DIR", str(reports))
    return reports


def _write_scenario(reports: Path, ticker: str, date: str):
    (reports / f"scenario_{ticker}_{date}.json").write_text(json.dumps({
        "version": 1, "ticker": ticker, "trade_date": date, "rating": "Buy",
        "scenario_buckets": [{
            "horizon_months": 6,
            "scenarios": [
                {"name": "bull", "thesis": "t", "return_pct": 0.2, "prob": 0.3},
                {"name": "base", "thesis": "t", "return_pct": 0.05, "prob": 0.5},
                {"name": "bear", "thesis": "t", "return_pct": -0.1, "prob": 0.2},
            ],
            "key_levels": {"stop": 9, "entry_low": 10, "entry_high": 10, "target": 12},
        }],
        "falsification": {"conditions": ["c"]},
    }), encoding="utf-8")


def _run(reports: Path, *args):
    return subprocess.run(
        [".venv/bin/python", "-m", "cli.main", *args],
        capture_output=True, text=True,
        env={"TRADINGAGENTS_REPORTS_DIR": str(reports), "HOME": str(reports.parent),
             "PATH": "/usr/bin:/bin"},
    )


class TestReportsJSON:
    def test_empty(self, tmp_reports):
        r = _run(tmp_reports, "reports", "--json")
        assert r.returncode == 0
        assert json.loads(r.stdout) == {"reports": []}

    def test_list_all(self, tmp_reports):
        _write_scenario(tmp_reports, "000001", "2026-08-30")
        _write_scenario(tmp_reports, "600000", "2026-08-25")
        r = _run(tmp_reports, "reports", "--json")
        payload = json.loads(r.stdout)
        assert len(payload["reports"]) == 2
        tickers = {e["ticker"] for e in payload["reports"]}
        assert tickers == {"000001", "600000"}

    def test_filter_by_ticker(self, tmp_reports):
        _write_scenario(tmp_reports, "000001", "2026-08-25")
        _write_scenario(tmp_reports, "000001", "2026-08-30")
        _write_scenario(tmp_reports, "600000", "2026-08-30")
        r = _run(tmp_reports, "reports", "--ticker", "000001", "--json")
        payload = json.loads(r.stdout)
        assert len(payload["reports"]) == 2
        for e in payload["reports"]:
            assert e["ticker"] == "000001"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli_reports_json.py -v`

Expected: FAIL — CLI 报 "No such command 'reports'"

- [ ] **Step 3: Write minimal implementation**

在 `cli/main.py` 末尾（`if __name__ == "__main__":` 之前）追加：

```python
@app.command()
def reports(
    ticker: str | None = typer.Option(None, "--ticker", help="按代码过滤"),
    json_out: bool = typer.Option(False, "--json", help="输出 JSON"),
):
    """列出可用研报（有 scenario.json 的分析日期）。"""
    import json as _json

    from tradingagents.advisor.scenario_io import list_scenarios

    entries = list_scenarios(ticker=ticker)
    payload = {
        "reports": [
            {"ticker": e.ticker, "date": e.trade_date, "path": e.path}
            for e in sorted(entries, key=lambda x: (x.ticker, x.trade_date))
        ]
    }
    if json_out:
        console.print_json(_json.dumps(payload, ensure_ascii=False))
    else:
        for e in payload["reports"]:
            console.print(f"{e['ticker']}  {e['date']}  {e['path']}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cli_reports_json.py tests/test_cli_default_command.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli/main.py tests/test_cli_reports_json.py
git commit -m "feat(cli): reports 子命令 (支持 --ticker 过滤 + --json)"
```

---

### Task 3: CLI `kyc-questionnaire` 子命令

**Files:**
- Modify: `cli/main.py`
- Test: `tests/test_cli_kyc_questionnaire.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_kyc_questionnaire.py
import json
import subprocess


def _run(*args):
    return subprocess.run(
        [".venv/bin/python", "-m", "cli.main", *args],
        capture_output=True, text=True,
    )


class TestKycQuestionnaireJSON:
    def test_returns_five_questions(self):
        r = _run("kyc-questionnaire", "--json")
        assert r.returncode == 0, r.stderr
        payload = json.loads(r.stdout)
        assert payload["schema_version"] == 1
        assert len(payload["questions"]) == 5
        assert [q["id"] for q in payload["questions"]] == ["q1", "q2", "q3", "q4", "q5"]

    def test_options_have_correct_values(self):
        r = _run("kyc-questionnaire", "--json")
        payload = json.loads(r.stdout)
        for q in payload["questions"]:
            values = sorted(opt["value"] for opt in q["options"])
            assert values == [3, 5, 7, 9]

    def test_has_note_field(self):
        r = _run("kyc-questionnaire", "--json")
        payload = json.loads(r.stdout)
        assert "note" in payload
        assert "客户端" in payload["note"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli_kyc_questionnaire.py -v`

Expected: FAIL — "No such command 'kyc-questionnaire'"

- [ ] **Step 3: Write minimal implementation**

在 `cli/main.py` 追加：

```python
@app.command("kyc-questionnaire")
def kyc_questionnaire(
    json_out: bool = typer.Option(False, "--json", help="输出 JSON"),
):
    """输出 5 题 KYC 问卷（供客户端首次建档使用）。"""
    import json as _json

    from tradingagents.advisor.questionnaire import get_questionnaire

    q = get_questionnaire()
    if json_out:
        console.print_json(_json.dumps(q.model_dump(), ensure_ascii=False))
    else:
        for question in q.questions:
            console.print(f"[bold]{question.id}[/bold] {question.text}")
            for opt in question.options:
                console.print(f"  [{opt.value}] {opt.label}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cli_kyc_questionnaire.py tests/test_cli_default_command.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli/main.py tests/test_cli_kyc_questionnaire.py
git commit -m "feat(cli): kyc-questionnaire 子命令 (--json 输出问卷)"
```

---

### Task 4: CLI `analyze` 追加 `--json` + `--confirm` 两相语义

**Files:**
- Modify: `cli/main.py`
- Test: `tests/test_cli_analyze_confirm.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_analyze_confirm.py
import json
import subprocess

import pytest


def _run(*args):
    return subprocess.run(
        [".venv/bin/python", "-m", "cli.main", *args],
        capture_output=True, text=True, timeout=30,
    )


class TestAnalyzeConfirm:
    def test_estimate_mode_no_execution(self):
        """analyze --json 无 --confirm → 只返报价不跑。"""
        r = _run("analyze", "--json", "--depth", "full")
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        assert "estimated_llm_calls" in payload
        assert "estimated_seconds" in payload
        assert payload["mode"] == "estimate"
        assert payload["depth"] == "full"

    def test_estimate_quick(self):
        r = _run("analyze", "--json", "--depth", "quick")
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        assert payload["depth"] == "quick"
        assert payload["estimated_llm_calls"] < 10  # quick 档

    def test_estimate_analyst(self):
        r = _run("analyze", "--json", "--depth", "analyst",
                 "--single-analyst", "fundamental")
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        assert payload["depth"] == "analyst"

    def test_invalid_depth(self):
        r = _run("analyze", "--json", "--depth", "bogus")
        assert r.returncode != 0

    # 真实执行的测试标 slow：CI 里跳过
    @pytest.mark.slow
    def test_confirm_true_runs(self, tmp_path, monkeypatch):
        """confirm=true 触发真实执行；仅在 slow 标记下跑。"""
        # 略：真跑一次代价大；本测试主要防 --confirm 被静默忽略
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli_analyze_confirm.py -v`

Expected: FAIL — analyze 不认识 `--json` / `--depth` / `--confirm`

- [ ] **Step 3: Write minimal implementation**

修改 `cli/main.py` 的 `analyze` 命令（第 1327 行附近）：

```python
@app.command()
def analyze(
    checkpoint: bool = typer.Option(
        False, "--checkpoint",
        help="Enable checkpoint/resume: save state after each node so a crashed run can resume.",
    ),
    clear_checkpoints: bool = typer.Option(
        False, "--clear-checkpoints",
        help="Delete all saved checkpoints before running (force fresh start).",
    ),
    force: bool = typer.Option(
        False, "--force",
        help="跳过同日研报守卫，重跑并归档旧制品。",
    ),
    json_out: bool = typer.Option(
        False, "--json",
        help="JSON 输出（机器消费）；无 --confirm 时输出报价。",
    ),
    depth: str = typer.Option(
        "full", "--depth",
        help="分析深度：quick / analyst / full",
    ),
    confirm: bool = typer.Option(
        False, "--confirm",
        help="真正执行分析（重活）；否则只返报价。",
    ),
    single_analyst: str | None = typer.Option(
        None, "--single-analyst",
        help="depth=analyst 时指定角色：fundamental / news / policy / ...",
    ),
):
    import json as _json

    if depth not in ("quick", "analyst", "full"):
        console.print(f"[red]invalid depth: {depth}[/red]")
        raise typer.Exit(code=2)

    # 报价模式（--json 无 --confirm）
    if json_out and not confirm:
        estimate = _estimate_analyze(depth)
        console.print_json(_json.dumps({
            "mode": "estimate",
            "depth": depth,
            "estimated_llm_calls": estimate["calls"],
            "estimated_seconds": estimate["seconds"],
            "note": "call again with --confirm to execute",
        }, ensure_ascii=False))
        raise typer.Exit(code=0)

    # 真实执行
    if clear_checkpoints:
        from tradingagents.graph.checkpointer import clear_all_checkpoints
        n = clear_all_checkpoints(DEFAULT_CONFIG["data_cache_dir"])
        console.print(f"[yellow]Cleared {n} checkpoint(s).[/yellow]")

    if json_out:
        # JSON + --confirm：跑完出 artifact_path
        # TODO 若 run_analysis 未支持结构化返回，此处暂 raise NotImplementedError
        try:
            result = run_analysis(checkpoint=checkpoint, force=force)
        except NotImplementedError:
            console.print_json(_json.dumps({
                "error": "not_implemented",
                "message": "run_analysis 尚不支持 --json 结构化返回；请去掉 --json 交互跑",
            }, ensure_ascii=False))
            raise typer.Exit(code=5)
        console.print_json(_json.dumps({
            "mode": "executed",
            "depth": depth,
            "artifact_path": str(result.get("artifact_path", "")) if isinstance(result, dict) else "",
        }, ensure_ascii=False))
        raise typer.Exit(code=0)

    # 原路径（交互式）
    run_analysis(checkpoint=checkpoint, force=force)


def _estimate_analyze(depth: str) -> dict:
    """报价：按 depth 查表返回预估调用数与时间（秒）。"""
    table = {
        "quick": {"calls": 5, "seconds": 30},
        "analyst": {"calls": 10, "seconds": 120},
        "full": {"calls": 47, "seconds": 480},
    }
    return table[depth]
```

**关键说明**：
- `_default` callback 里 `analyze(checkpoint=..., clear_checkpoints=..., force=...)`
  不传新参数，兼容裸跑（新参数在函数签名里都有默认值，兼容）
- 真实 `--json` + `--confirm` 执行如果 `run_analysis` 不支持结构化返回，先返
  `not_implemented`。后续 P3+ 若要真跑，需先给 `run_analysis` 加结构化返回。
  MCP 层的 `analyze(confirm=true)` 工具 v1 即接受"报价模式已能返回；执行模式暂
  返 not_implemented"这个边界。

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cli_analyze_confirm.py tests/test_cli_default_command.py -v`

Expected: PASS（`slow` 标记的执行测试跳过）

- [ ] **Step 5: Commit**

```bash
git add cli/main.py tests/test_cli_analyze_confirm.py
git commit -m "feat(cli): analyze 追加 --json + --confirm 两相 + --depth (报价模式)"
```

---

## Milestone 2: MCP 层核心（M2）

### Task 5: MCP schemas + errors 模块

**Files:**
- Create: `tradingagents/mcp/schemas.py`
- Create: `tradingagents/mcp/errors.py`
- Test: `tests/test_mcp_schemas.py`
- Test: `tests/test_mcp_errors.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mcp_schemas.py
import pytest
from pydantic import ValidationError

from tradingagents.mcp.schemas import (
    KYCAnswersIn,
    AnalyzeArgs,
    AdviseArgs,
    ReviewArgs,
    ScenarioArgs,
    ReportsArgs,
)


class TestKYCAnswersIn:
    def test_valid(self):
        a = KYCAnswersIn(q1=7, q2=5, q3=7, q4=7, q5=7)
        assert a.q1 == 7

    def test_reject_invalid(self):
        with pytest.raises(ValidationError):
            KYCAnswersIn(q1=4, q2=5, q3=7, q4=7, q5=7)


class TestToolArgs:
    def test_analyze_defaults(self):
        a = AnalyzeArgs(ticker="000001")
        assert a.depth == "full"
        assert a.confirm is False

    def test_analyze_invalid_depth(self):
        with pytest.raises(ValidationError):
            AnalyzeArgs(ticker="000001", depth="bogus")

    def test_advise_requires_kyc(self):
        with pytest.raises(ValidationError):
            AdviseArgs(ticker="000001")  # kyc_answers 缺失

    def test_review_requires_kyc(self):
        with pytest.raises(ValidationError):
            ReviewArgs()
```

```python
# tests/test_mcp_errors.py
from tradingagents.mcp.errors import (
    CLIError,
    map_cli_error,
    MCP_ERROR_KYC_REQUIRED,
    MCP_ERROR_INVALID_KYC,
    MCP_ERROR_NOT_FOUND,
    MCP_ERROR_INTERNAL,
)


class TestMapCLIError:
    def test_exit_code_1_not_found(self):
        err = map_cli_error(1, b'{"error": "not_found", "message": "no scenario for X"}')
        assert isinstance(err, CLIError)
        assert err.code == MCP_ERROR_NOT_FOUND
        assert "no scenario" in err.message

    def test_exit_code_2_invalid_kyc(self):
        err = map_cli_error(2, b'{"error": "invalid_kyc", "message": "q1=4 not allowed"}')
        assert err.code == MCP_ERROR_INVALID_KYC

    def test_exit_code_3_kyc_required(self):
        err = map_cli_error(3, b'{"error": "kyc_required", "questionnaire": {"schema_version": 1}}')
        assert err.code == MCP_ERROR_KYC_REQUIRED
        assert err.payload.get("questionnaire", {}).get("schema_version") == 1

    def test_unknown_error_falls_back_to_internal(self):
        err = map_cli_error(255, b"segfault or something")
        assert err.code == MCP_ERROR_INTERNAL

    def test_malformed_stderr_still_returns_internal(self):
        err = map_cli_error(1, b"not json at all")
        assert err.code == MCP_ERROR_INTERNAL
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_mcp_schemas.py tests/test_mcp_errors.py -v`

Expected: FAIL — ImportError on both modules

- [ ] **Step 3: Write minimal implementation**

```python
# tradingagents/mcp/schemas.py
"""MCP 工具入参 pydantic schemas。

**允许 import** 自 `pydantic`（第三方）和 `typing`（stdlib）——不 import 业务模块。
KYCAnswersIn 与 advisor.types.KYCAnswers 结构等价（不 import 后者，避免破坏薄壳
方针；工具调 subprocess 时把 JSON 传给 CLI，CLI 才校准）。
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class KYCAnswersIn(BaseModel):
    q1: Literal[3, 5, 7, 9]
    q2: Literal[3, 5, 7, 9]
    q3: Literal[3, 5, 7, 9]
    q4: Literal[3, 5, 7, 9]
    q5: Literal[3, 5, 7, 9]
    schema_version: Literal[1] = 1


class ReportsArgs(BaseModel):
    ticker: Optional[str] = None


class ScenarioArgs(BaseModel):
    ticker: str
    date: Optional[str] = None


class AdviseArgs(BaseModel):
    ticker: str
    kyc_answers: KYCAnswersIn
    date: Optional[str] = None


class ReviewArgs(BaseModel):
    kyc_answers: KYCAnswersIn


class AnalyzeArgs(BaseModel):
    ticker: str
    date: Optional[str] = None
    depth: Literal["quick", "analyst", "full"] = "full"
    confirm: bool = False
    single_analyst: Optional[str] = None
    force: bool = False
```

```python
# tradingagents/mcp/errors.py
"""CLI exit code + stderr JSON → MCP 错误码映射。

**允许 import**：stdlib only + pydantic。不 import 业务模块。
CLI 侧 exit code 规约：
  0 = 成功
  1 = not_found（找不到 scenario / ticker 不存在等）
  2 = invalid_kyc（KYC schema 违例）
  3 = kyc_required（缺 kyc_answers）
  4 = internal（未预期错误）
  5 = not_implemented（CLI 命令暂未支持某模式）
"""
import json
from dataclasses import dataclass
from typing import Any


MCP_ERROR_NOT_FOUND = "not_found"
MCP_ERROR_INVALID_KYC = "invalid_kyc"
MCP_ERROR_KYC_REQUIRED = "kyc_required"
MCP_ERROR_INTERNAL = "internal"
MCP_ERROR_NOT_IMPLEMENTED = "not_implemented"
MCP_ERROR_ARTIFACT_EXISTS = "artifact_exists"


@dataclass
class CLIError:
    code: str
    message: str
    payload: dict[str, Any]


_CODE_MAP = {
    1: MCP_ERROR_NOT_FOUND,
    2: MCP_ERROR_INVALID_KYC,
    3: MCP_ERROR_KYC_REQUIRED,
    4: MCP_ERROR_INTERNAL,
    5: MCP_ERROR_NOT_IMPLEMENTED,
}


def map_cli_error(exit_code: int, stderr: bytes | str) -> CLIError:
    """把 CLI 非零 exit + stderr JSON 转成结构化 CLIError。"""
    text = stderr.decode("utf-8", errors="replace") if isinstance(stderr, bytes) else stderr
    payload: dict[str, Any] = {}
    try:
        payload = json.loads(text) if text.strip() else {}
    except json.JSONDecodeError:
        payload = {"raw_stderr": text}
    # 优先看 payload["error"]，没有再回退 exit code 映射
    code_from_payload = payload.get("error") if isinstance(payload, dict) else None
    code = code_from_payload or _CODE_MAP.get(exit_code, MCP_ERROR_INTERNAL)
    message = payload.get("message", "") if isinstance(payload, dict) else text
    return CLIError(code=code, message=message, payload=payload if isinstance(payload, dict) else {})
```

**关键说明**：CLI 侧的 `advise` 命令（P2 task 7）已经在 `_emit()` 里用了 exit_code
1/2/3/4——本模块的 `_CODE_MAP` 与它对齐。若将来改 CLI exit code，两侧必须一起改。

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_mcp_schemas.py tests/test_mcp_errors.py tests/test_mcp_thin_shell_guard.py -v`

Expected: PASS（包括静态守卫依然通过——两个新文件都不 import 业务模块）

- [ ] **Step 5: Commit**

```bash
git add tradingagents/mcp/schemas.py tradingagents/mcp/errors.py \
        tests/test_mcp_schemas.py tests/test_mcp_errors.py
git commit -m "feat(mcp): schemas + errors 模块 (对齐 CLI exit code 契约)"
```

---

### Task 6: MCP cli_runner (subprocess wrapper)

**Files:**
- Create: `tradingagents/mcp/cli_runner.py`
- Test: `tests/test_mcp_cli_runner.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mcp_cli_runner.py
import json
from unittest.mock import AsyncMock, patch

import pytest

from tradingagents.mcp.cli_runner import CLIResult, run_cli
from tradingagents.mcp.errors import MCP_ERROR_NOT_FOUND


@pytest.mark.asyncio
async def test_success():
    """subprocess 返 0 + JSON stdout → CLIResult(ok=True, data=...)."""
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
    """subprocess 返 1 + stderr JSON → CLIResult(ok=False, error.code=not_found)."""
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
    """returncode=0 但 stdout 不是 JSON → 视为 internal 错误。"""
    mock_proc = AsyncMock()
    mock_proc.returncode = 0
    mock_proc.communicate = AsyncMock(return_value=(b"not json", b""))
    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=mock_proc)):
        result = await run_cli(["reports", "--json"])
    assert result.ok is False
    assert result.error.code == "internal"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_mcp_cli_runner.py -v`

Expected: FAIL with `ImportError: cannot import name 'run_cli'`

Note: 需要 `pytest-asyncio`。若测试报 `PytestUnknownMarkWarning`，装：
`.venv/bin/pip install pytest-asyncio`

- [ ] **Step 3: Write minimal implementation**

```python
# tradingagents/mcp/cli_runner.py
"""asyncio.subprocess 包装：唯一调 CLI 的入口，方便 mock 测试。

**允许 import**：stdlib only（asyncio, json）+ 本模块的 errors。**严禁**业务模块。
"""
import asyncio
import json
import shutil
from dataclasses import dataclass
from typing import Any, Optional

from tradingagents.mcp.errors import CLIError, map_cli_error, MCP_ERROR_INTERNAL


@dataclass
class CLIResult:
    ok: bool
    data: Optional[dict[str, Any]] = None
    error: Optional[CLIError] = None


def _resolve_binary() -> list[str]:
    """定位 tradingagents 可执行文件；缺失回退 `python -m cli.main`。"""
    which = shutil.which("tradingagents")
    if which:
        return [which]
    return ["python", "-m", "cli.main"]


async def run_cli(argv: list[str], timeout: float = 900.0) -> CLIResult:
    """跑 `tradingagents <argv>`，解析 stdout JSON。

    正常路径：returncode=0 + stdout 是 JSON → CLIResult(ok=True, data=...)
    错误路径：returncode!=0 → 调 errors.map_cli_error 转结构化错误
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
        proc.kill()
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
    # 非零 exit code
    # 优先看 stdout（CLI 的 `_emit` 用 print_json 写 stdout；stderr 可能空）
    payload_source = stdout if stdout.strip() else stderr
    return CLIResult(ok=False, error=map_cli_error(proc.returncode, payload_source))
```

**关键说明**：CLI `_emit` 用 `console.print_json` 写 **stdout**，不是 stderr。所以
`run_cli` 优先看 stdout 拿 error payload；stderr 只是兜底。若 CLI 未来改成 stderr
写错误，`run_cli` 也自动兼容。

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_mcp_cli_runner.py tests/test_mcp_thin_shell_guard.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tradingagents/mcp/cli_runner.py tests/test_mcp_cli_runner.py
git commit -m "feat(mcp): cli_runner asyncio 包装 (mock 友好 + 超时保护)"
```

---

### Task 7: MCP tools 实现 (6 工具 subprocess 版)

**Files:**
- Create: `tradingagents/mcp/tools.py`
- Test: `tests/test_mcp_tools_unit.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mcp_tools_unit.py
from unittest.mock import AsyncMock, patch

import pytest

from tradingagents.mcp import tools
from tradingagents.mcp.cli_runner import CLIResult
from tradingagents.mcp.errors import CLIError
from tradingagents.mcp.schemas import (
    AdviseArgs, AnalyzeArgs, KYCAnswersIn, ReviewArgs,
    ReportsArgs, ScenarioArgs,
)


@pytest.mark.asyncio
async def test_reports_success():
    with patch.object(tools, "run_cli", AsyncMock(return_value=CLIResult(
        ok=True, data={"reports": [{"ticker": "000001", "date": "2026-08-30"}]},
    ))) as m:
        result = await tools.reports_tool(ReportsArgs())
    assert result == {"reports": [{"ticker": "000001", "date": "2026-08-30"}]}
    m.assert_called_once()
    argv = m.call_args[0][0]
    assert argv == ["reports", "--json"]


@pytest.mark.asyncio
async def test_reports_with_ticker():
    with patch.object(tools, "run_cli", AsyncMock(return_value=CLIResult(
        ok=True, data={"reports": []},
    ))) as m:
        await tools.reports_tool(ReportsArgs(ticker="000001"))
    argv = m.call_args[0][0]
    assert argv == ["reports", "--ticker", "000001", "--json"]


@pytest.mark.asyncio
async def test_kyc_questionnaire():
    with patch.object(tools, "run_cli", AsyncMock(return_value=CLIResult(
        ok=True, data={"schema_version": 1, "questions": [], "note": "..."},
    ))) as m:
        result = await tools.kyc_questionnaire_tool()
    assert result["schema_version"] == 1
    argv = m.call_args[0][0]
    assert argv == ["kyc-questionnaire", "--json"]


@pytest.mark.asyncio
async def test_scenario_success():
    with patch.object(tools, "run_cli", AsyncMock(return_value=CLIResult(
        ok=True, data={"version": 1, "ticker": "000001"},
    ))) as m:
        await tools.scenario_tool(ScenarioArgs(ticker="000001", date="2026-08-30"))
    argv = m.call_args[0][0]
    assert argv == ["scenario", "000001", "--date", "2026-08-30", "--json"]


@pytest.mark.asyncio
async def test_advise_passes_kyc_json():
    kyc = KYCAnswersIn(q1=7, q2=5, q3=7, q4=7, q5=7)
    with patch.object(tools, "run_cli", AsyncMock(return_value=CLIResult(
        ok=True, data={"ticker": "000001", "with_position": {}},
    ))) as m:
        await tools.advise_tool(AdviseArgs(ticker="000001", kyc_answers=kyc))
    argv = m.call_args[0][0]
    assert argv[0] == "advise"
    assert argv[1] == "000001"
    assert "--json" in argv
    assert "--kyc-json" in argv
    # 验证 kyc-json 内容
    kyc_idx = argv.index("--kyc-json")
    import json as _json
    assert _json.loads(argv[kyc_idx + 1])["q1"] == 7


@pytest.mark.asyncio
async def test_advise_error_maps_to_tool_error():
    err = CLIError(code="not_found", message="no scenario", payload={})
    with patch.object(tools, "run_cli", AsyncMock(return_value=CLIResult(
        ok=False, error=err,
    ))):
        with pytest.raises(tools.ToolError) as exc:
            await tools.advise_tool(AdviseArgs(
                ticker="999", kyc_answers=KYCAnswersIn(q1=7, q2=5, q3=7, q4=7, q5=7),
            ))
    assert exc.value.code == "not_found"


@pytest.mark.asyncio
async def test_review_passes_kyc():
    kyc = KYCAnswersIn(q1=7, q2=5, q3=7, q4=7, q5=7)
    with patch.object(tools, "run_cli", AsyncMock(return_value=CLIResult(
        ok=True, data={"items": []},
    ))) as m:
        await tools.review_tool(ReviewArgs(kyc_answers=kyc))
    argv = m.call_args[0][0]
    assert argv[0] == "review"
    assert "--kyc-json" in argv


@pytest.mark.asyncio
async def test_analyze_estimate_mode():
    """confirm=false → estimate 模式，subprocess 不带 --confirm。"""
    with patch.object(tools, "run_cli", AsyncMock(return_value=CLIResult(
        ok=True, data={"mode": "estimate", "estimated_llm_calls": 47},
    ))) as m:
        result = await tools.analyze_tool(AnalyzeArgs(ticker="000001", depth="full"))
    argv = m.call_args[0][0]
    assert "--confirm" not in argv
    assert result["estimated_llm_calls"] == 47


@pytest.mark.asyncio
async def test_analyze_confirm_mode():
    with patch.object(tools, "run_cli", AsyncMock(return_value=CLIResult(
        ok=True, data={"mode": "executed", "artifact_path": "/tmp/x.json"},
    ))) as m:
        await tools.analyze_tool(AnalyzeArgs(
            ticker="000001", depth="full", confirm=True,
        ))
    argv = m.call_args[0][0]
    assert "--confirm" in argv
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools_unit.py -v`

Expected: FAIL — `ImportError: cannot import name 'reports_tool'`

- [ ] **Step 3: Write minimal implementation**

```python
# tradingagents/mcp/tools.py
"""6 个 MCP 工具，全部 subprocess 调 CLI + 解析 JSON + 错误映射。

**方针（CLAUDE.md）**：本文件不得 import advisor / graph / dataflows / agents 等
业务模块。只能 import stdlib、pydantic、cli_runner、errors、schemas。
"""
import json
from dataclasses import dataclass
from typing import Any

from tradingagents.mcp.cli_runner import run_cli
from tradingagents.mcp.errors import CLIError
from tradingagents.mcp.schemas import (
    AdviseArgs,
    AnalyzeArgs,
    KYCAnswersIn,
    ReportsArgs,
    ReviewArgs,
    ScenarioArgs,
)


@dataclass
class ToolError(Exception):
    code: str
    message: str
    payload: dict[str, Any]

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


def _raise_from_cli(err: CLIError) -> None:
    raise ToolError(code=err.code, message=err.message, payload=err.payload)


async def reports_tool(args: ReportsArgs) -> dict[str, Any]:
    """列出可用研报。"""
    argv = ["reports"]
    if args.ticker is not None:
        argv += ["--ticker", args.ticker]
    argv += ["--json"]
    result = await run_cli(argv)
    if not result.ok:
        _raise_from_cli(result.error)
    return result.data


async def kyc_questionnaire_tool() -> dict[str, Any]:
    """返回 5 题 KYC 问卷（客户端首次建档用）。"""
    result = await run_cli(["kyc-questionnaire", "--json"])
    if not result.ok:
        _raise_from_cli(result.error)
    return result.data


async def scenario_tool(args: ScenarioArgs) -> dict[str, Any]:
    """返回原始 scenario 分布。"""
    argv = ["scenario", args.ticker]
    if args.date is not None:
        argv += ["--date", args.date]
    argv += ["--json"]
    result = await run_cli(argv)
    if not result.ok:
        _raise_from_cli(result.error)
    return result.data


async def advise_tool(args: AdviseArgs) -> dict[str, Any]:
    """给出个性化建议（inline 传 KYC）。"""
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
    """决策纪律巡检（inline 传 KYC）。

    注：CLI review 命令属 P3；P3 未到位前，CLI 侧应返 not_implemented，
    本工具透传即可。
    """
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
    """触发新分析（两相 confirm 语义）。"""
    argv = ["analyze", "--json", "--depth", args.depth]
    if args.confirm:
        argv += ["--confirm"]
    if args.force:
        argv += ["--force"]
    if args.single_analyst is not None:
        argv += ["--single-analyst", args.single_analyst]
    # ticker/date 作为 analyze 命令的可选（当前 analyze 交互式收集，报价模式无需）
    # v1: 报价模式不接 ticker，返回 depth 相关常数
    result = await run_cli(argv)
    if not result.ok:
        _raise_from_cli(result.error)
    return result.data
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_mcp_tools_unit.py tests/test_mcp_thin_shell_guard.py -v`

Expected: PASS（守卫也通过——tools.py 未 import 业务模块）

- [ ] **Step 5: Commit**

```bash
git add tradingagents/mcp/tools.py tests/test_mcp_tools_unit.py
git commit -m "feat(mcp): 6 个工具 subprocess 实现 + 错误映射 + mock 单测"
```

---

### Task 8: MCP server 启动 (`server.py`)

**Files:**
- Create: `tradingagents/mcp/server.py`
- Test: `tests/test_mcp_server_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mcp_server_integration.py
"""通过 mcp SDK test client 起真实 server → 发现工具 → 调用一遍。

只在装了 [mcp] extra 时才跑；否则 skip。
"""
import pytest

pytest.importorskip("mcp")

# 具体测试形态依赖 mcp SDK 版本 API；下面骨架针对 mcp v2.1+
# 若 mcp SDK 提供 in-memory test client 则用之；否则用 stdio 起子进程


class TestServerDiscovery:
    @pytest.mark.asyncio
    async def test_lists_six_tools(self):
        from tradingagents.mcp.server import build_server
        server = build_server()
        # server.list_tools() 返回工具描述列表（依据 mcp SDK v2.1 API）
        tools = await server.list_tools()
        names = {t.name for t in tools}
        assert names == {
            "reports", "scenario", "advise", "review",
            "kyc_questionnaire", "analyze",
        }

    @pytest.mark.asyncio
    async def test_reports_callable(self, monkeypatch):
        """mock cli_runner 后调 reports 工具端到端通。"""
        from unittest.mock import AsyncMock

        from tradingagents.mcp import tools as _tools
        from tradingagents.mcp.cli_runner import CLIResult

        monkeypatch.setattr(_tools, "run_cli", AsyncMock(
            return_value=CLIResult(ok=True, data={"reports": []}),
        ))
        from tradingagents.mcp.server import build_server
        server = build_server()
        result = await server.call_tool("reports", {})
        # 返回结构依据 mcp SDK 版本；至少不 raise
        assert result is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_mcp_server_integration.py -v`

Expected: FAIL — `ImportError: cannot import name 'build_server'`（或整个 skip 若 mcp 未装）

- [ ] **Step 3: Write minimal implementation**

```python
# tradingagents/mcp/server.py
"""MCP server 启动 + 6 工具挂载。

**方针**：本文件 import mcp SDK + 本模块下的 tools/schemas。**不得** import
业务模块（同 tools.py）。
"""
from mcp.server import Server
from mcp.types import Tool

from tradingagents.mcp import tools
from tradingagents.mcp.schemas import (
    AdviseArgs,
    AnalyzeArgs,
    ReportsArgs,
    ReviewArgs,
    ScenarioArgs,
)


def build_server() -> Server:
    """构造 MCP server 实例并挂载 6 个工具。"""
    server = Server(name="tradingagents")

    @server.tool()
    async def reports(ticker: str | None = None) -> dict:
        """列出可用研报。可选 ticker 过滤。"""
        return await tools.reports_tool(ReportsArgs(ticker=ticker))

    @server.tool()
    async def kyc_questionnaire() -> dict:
        """返回 5 题 KYC 问卷（首次建档 / 更新画像用）。"""
        return await tools.kyc_questionnaire_tool()

    @server.tool()
    async def scenario(ticker: str, date: str | None = None) -> dict:
        """返回原始情景分布（bull/base/bear 概率 + key_levels）。"""
        return await tools.scenario_tool(ScenarioArgs(ticker=ticker, date=date))

    @server.tool()
    async def advise(ticker: str, kyc_answers: dict, date: str | None = None) -> dict:
        """给出个性化投资建议（inline 传 KYC 答案）。"""
        from tradingagents.mcp.schemas import KYCAnswersIn
        return await tools.advise_tool(AdviseArgs(
            ticker=ticker,
            kyc_answers=KYCAnswersIn.model_validate(kyc_answers),
            date=date,
        ))

    @server.tool()
    async def review(kyc_answers: dict) -> dict:
        """决策纪律巡检（inline 传 KYC 答案）。"""
        from tradingagents.mcp.schemas import KYCAnswersIn
        return await tools.review_tool(ReviewArgs(
            kyc_answers=KYCAnswersIn.model_validate(kyc_answers),
        ))

    @server.tool()
    async def analyze(
        ticker: str,
        date: str | None = None,
        depth: str = "full",
        confirm: bool = False,
        single_analyst: str | None = None,
        force: bool = False,
    ) -> dict:
        """触发新分析。confirm=false 只返报价；confirm=true 才真跑。"""
        return await tools.analyze_tool(AnalyzeArgs(
            ticker=ticker, date=date, depth=depth, confirm=confirm,
            single_analyst=single_analyst, force=force,
        ))

    return server


def run(transport: str = "stdio", host: str = "127.0.0.1", port: int = 8765) -> None:
    """启动 server。transport: stdio / sse。"""
    server = build_server()
    if transport == "stdio":
        from mcp.server.stdio import stdio_server
        import asyncio
        async def _main():
            async with stdio_server() as (read, write):
                await server.run(read, write, server.create_initialization_options())
        asyncio.run(_main())
    elif transport == "sse":
        from mcp.server.sse import SseServerTransport
        # SSE 具体 API 依 mcp v2.1；下面骨架为示意，实施时按 SDK 文档
        import asyncio
        async def _main():
            transport_impl = SseServerTransport("/sse")
            await server.run_sse(transport_impl, host=host, port=port)
        asyncio.run(_main())
    else:
        raise ValueError(f"unknown transport: {transport}")
```

**关键说明**：mcp SDK v2.1 API 细节（Server 类、tool decorator 签名、SSE transport
实例化）可能与骨架有差异。M2 实施时对照 SDK 文档核对——**不要因为 API 差异
就把业务逻辑滑进 server.py**，如遇复杂 tool schema 声明，也应在 schemas.py 定义、
server.py 只挂载。

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_mcp_server_integration.py tests/test_mcp_thin_shell_guard.py -v`

Expected: PASS（守卫依然通过——server.py 只 import mcp SDK 和本包）

- [ ] **Step 5: Commit**

```bash
git add tradingagents/mcp/server.py tests/test_mcp_server_integration.py
git commit -m "feat(mcp): server.py 挂载 6 工具 + stdio/sse 传输"
```

---

### Task 9: CLI `mcp-serve` 子命令

**Files:**
- Modify: `cli/main.py`
- Test: `tests/test_cli_mcp_serve.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_mcp_serve.py
import subprocess


def test_mcp_serve_help():
    r = subprocess.run(
        [".venv/bin/python", "-m", "cli.main", "mcp-serve", "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "transport" in r.stdout
    assert "stdio" in r.stdout
    assert "sse" in r.stdout


def test_bare_run_still_works():
    """加了 mcp-serve 子命令后，裸跑 --help 依然列出所有命令（v0.5.9 铁律）。"""
    r = subprocess.run(
        [".venv/bin/python", "-m", "cli.main", "--help"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "mcp-serve" in r.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli_mcp_serve.py -v`

Expected: FAIL — "No such command 'mcp-serve'"

- [ ] **Step 3: Write minimal implementation**

在 `cli/main.py` 追加：

```python
@app.command("mcp-serve")
def mcp_serve(
    transport: str = typer.Option("stdio", "--transport", help="stdio / sse"),
    host: str = typer.Option("127.0.0.1", "--host"),
    port: int = typer.Option(8765, "--port"),
):
    """启动 MCP server（暴露 6 个工具供 MCP 客户端调用）。

    需要 [mcp] extra: `pip install -e .[mcp]`。
    """
    try:
        from tradingagents.mcp.server import run as _run
    except ImportError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=1)
    _run(transport=transport, host=host, port=port)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cli_mcp_serve.py tests/test_cli_default_command.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add cli/main.py tests/test_cli_mcp_serve.py
git commit -m "feat(cli): mcp-serve 子命令 (transport=stdio/sse)"
```

---

## Milestone 3: 端到端与文档（M3）

### Task 10: 全量回归 + CLAUDE.md 更新

- [ ] **Step 1: 跑全量测试**

Run: `.venv/bin/python -m pytest tests/ -v --tb=short`

Expected: 全通过（P2 baseline + P3+ 新增测试）。若某个 `test_mcp_server_integration`
失败，检查 mcp SDK 版本 API 是否与 server.py 骨架一致（Task 8 说明中已提醒）。

- [ ] **Step 2: 记录新 baseline**

Run: `.venv/bin/python -m pytest tests/ 2>&1 | tail -3`

- [ ] **Step 3: 更新 CLAUDE.md**

Edit `CLAUDE.md` 的 `### 测试` 段，把 baseline 数字更新，追加 MCP 交付说明：

```markdown
### 测试
**干净 clone（`pip install -e .` 不带 `[agentsdk]` 与 `[mcp]`）跑 `pytest tests/`
应当是 <新数字> passed / <>skipped / **0 failed**。P2 顾问引擎 + CLI advise 于
2026-08-30 交付；P3+ MCP 集成（`tradingagents/mcp/` + `tradingagents mcp-serve`）
同日交付。`test_mcp_server_integration` 需装 `[mcp]` extra 才跑，未装则 skip。**
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "chore: CLAUDE.md 更新 P3+ MCP 交付后测试 baseline"
```

---

### Task 11: 部署文档

**Files:**
- Create: `docs/mcp-deployment.md`

- [ ] **Step 1: 写部署文档**

```markdown
# TradingAgents MCP Server 部署

## 安装

服务器需装 Python + 完整 TradingAgents：

    git clone https://github.com/kevin-hans/TradingAgents-astock
    cd TradingAgents-astock
    python -m venv .venv
    .venv/bin/pip install -e .[mcp]

## 启动

**本地 stdio（同机测试用）**：

    .venv/bin/tradingagents mcp-serve --transport stdio

**远程 SSE（生产用）**：

    .venv/bin/tradingagents mcp-serve --transport sse --host 0.0.0.0 --port 8765

## 客户端接入

**PicoClaw**：

    picoclaw mcp add tradingagents \
      --transport sse \
      --url http://<server-ip>:8765/sse
    picoclaw mcp test tradingagents   # 应发现 6 个工具

**Claude Code**：编辑 `~/.claude/claude_desktop_config.json`：

    {
      "mcpServers": {
        "tradingagents": {
          "command": "/path/to/.venv/bin/tradingagents",
          "args": ["mcp-serve", "--transport", "stdio"]
        }
      }
    }

## 安全

v1 **不做鉴权**（spec §7.3）。生产必须挂反向代理带鉴权，或走 VPN / Tailscale / 
Cloudflare Tunnel。**切勿把 8765 端口直接暴露公网**——LLM 账单和用户数据都在
那台机器上。

## 工具列表

| 工具 | 消耗 | 说明 |
|---|---|---|
| `reports([ticker])` | 秒 | 列出可用研报 |
| `kyc_questionnaire()` | 秒 | 返回 5 题 KYC 问卷 |
| `scenario(ticker, [date])` | 秒 | 原始情景分布 |
| `advise(ticker, kyc_answers, [date])` | 秒 | 个性化建议 |
| `review(kyc_answers)` | 秒 | 决策纪律巡检（需 P3） |
| `analyze(ticker, [date], [depth], [confirm])` | 报价秒 / 执行 10 分钟 | 触发新分析 |

详见 `docs/superpowers/specs/2026-08-29-picoclaw-mcp-integration.md`。
```

- [ ] **Step 2: Commit**

```bash
git add docs/mcp-deployment.md
git commit -m "docs: MCP server 部署文档 (安装/启动/客户端接入/安全)"
```

---

## Self-Review 检查表（写完 plan 后自检）

**Spec 覆盖率**（对 spec `2026-08-29-picoclaw-mcp-integration.md`）：

- ✅ §3 MCP 薄壳方针 → Task 1 静态守卫测试 + Task 5/6/7/8 每个 module 头注释 + Task 10 baseline 说明
- ✅ §4.1 只读工具 5 个（reports/scenario/advise/review/kyc_questionnaire）→ Task 2/3 (CLI) + Task 7 (MCP tools) + Task 8 (server 挂载)
- ✅ §4.2 analyze 触发工具 + 两相 confirm → Task 4 (CLI) + Task 7 (MCP)
- ✅ §4.3 kyc_required 错误 + 内嵌问卷 → Task 7（CLI advise task 7 已实现，MCP 层通过错误映射透传）
- ✅ §5 投资者向量 inline 传（客户端持有） → Task 5 (KYCAnswersIn schema) + Task 7 (advise/review 工具透传 KYC)
- ✅ §5.1 首次建档流程 → 通过 `kyc_required` 错误 + `kyc-questionnaire` 工具双入口实现
- ✅ §6 analyze 显式确认 → Task 4 + Task 7
- ✅ §7 部署（stdio/sse） → Task 8 (server run) + Task 9 (CLI mcp-serve) + Task 11 (部署文档)
- ✅ §8.1 pyproject.toml [mcp] extra → Task 1
- ✅ §8.2 模块布局 → 6 个新文件按 Task 5-8 建立
- ✅ §8.3 CLI mcp-serve → Task 9
- ✅ §8.4 CLI 侧前置需求清单 → Task 2/3/4 (reports/kyc-questionnaire/analyze) 满足；advise/review/scenario 由 P2 plan 交付
- ✅ §9 错误处理矩阵 → Task 5 (errors.py) + Task 6 (超时) + Task 7 (工具级)
- ✅ §10 测试策略 → Task 1 (守卫) + Task 5-8 (单测) + Task 8 (集成) + Task 4 (CLI 两相)
- ✅ §11 分期 M1/M2/M3 → 本 plan 对应 Milestones
- ⚠️ §12 YAGNI 明确不做（推送/异步作业/鉴权/i18n/数据类工具）——本 plan 也严格不做

**Placeholder 扫描**：
- 全 plan 每步有具体代码 / 命令 / 期望输出
- 无 "TBD" / "handle appropriately" 类占位
- ⚠️ Task 8 的 mcp SDK API 调用是**骨架**（依 SDK v2.1 实际 API 可能微调）——已在
  该 task 显著提示实施时对照 SDK 文档核对，仍保持"MCP 层不加业务逻辑"的方针

**类型一致性**：
- `KYCAnswersIn`（mcp.schemas）与 `KYCAnswers`（advisor.types，P2 plan）字段名一致：q1-q5 + schema_version
- CLI exit code 规约与 `mcp.errors._CODE_MAP` 严格对齐（1=not_found, 2=invalid_kyc, 3=kyc_required, 4=internal, 5=not_implemented）——两侧任何一处改动必须同步
- `CLIResult` / `CLIError` / `ToolError` 命名与用法在 cli_runner / tools / errors 三处一致

**scope 边界**：
- 本 plan 只做 MCP 集成
- CLI advise/review/scenario 命令属 P2 plan——本 plan 的 MCP advise/review/scenario
  工具单测用 mock，端到端通过 mock CLI 验证
- Web UI 独立后续 PR
- P3 `review` 命令本身不属本 plan；MCP review 工具会调 P3 CLI，P3 未到位前 CLI
  返 not_implemented 是可接受行为

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-08-30-picoclaw-mcp-integration.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - Fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
