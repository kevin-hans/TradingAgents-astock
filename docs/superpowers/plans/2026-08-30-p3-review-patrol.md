# P3 Review 巡检 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 `tradingagents review` 决策纪律巡检——扫记忆日志 pending 决策，拉现价检查止损/目标/期限/证伪/新鲜度，替换现有 CLI stub 为真实现（零 LLM）。

**Architecture:** 纯函数检查核心住 `tradingagents/advisor/review.py`（可注入行情 provider，测试零网络）；CLI 层组装（memory log + tencent 批量行情 + fetch_p0 + scenario_io）；MCP 层零改动（薄壳，review_tool 已就位只等 CLI）。exit code 新增 6=部分行情失败，`mcp/errors.py` 映射表同步。

**Tech Stack:** Python 3.10+ / pydantic v2 / typer / pytest。零新增依赖。

**前置状态**：main 分支（P2+P3+ 已合入），baseline 574 passed / 1 skipped / 0 failed。

**已就位接口（调研确认，直接用）**：
- `TradingMemoryLog(config).get_pending_entries() -> list[dict]`（字段 `date/ticker/rating/pending/raw/alpha/holding/decision/reflection`）；路径经 `config["memory_log_path"]`，env `TRADINGAGENTS_MEMORY_LOG_PATH` 可隔离
- `_tencent_quote(codes: list[str]) -> dict[code, {price, last_close, name, ...}]`（`tradingagents/dataflows/a_stock.py`，批量秒级）
- `fetch_p0(ticker, trade_date) -> float | None`（`tradingagents/agents/utils/scenario_check.py`，新浪 K 线取分析日收盘，失败返 None 降级）
- `advisor.scenario_io.load_scenario(ticker, date)`（缺文件抛 `ScenarioNotFoundError`）
- `advisor.engine.advise(bucket, vector, config, ...)`（w* 计算，止损触发的减仓提示用）
- `advisor.calibrate.from_kyc` / `advisor.profile_io.read_profile`（KYC 链路与 advise 完全同构）

**Spec 验收标准**（scenario-vector-advisor spec §7 review 表）：

| 检查项 | 判据 | 动作 |
|---|---|---|
| 止损触发 | 现价 ≤ stop | 高亮 + 按 w* 提示减仓幅度 |
| 目标达成 | 现价 ≥ target | 提示兑现/移动止损 |
| 期限到期 | 今天 > 分析日+桶期限 | 提示重新分析 |
| 证伪条件 | v1 不自动判定 | 列为人工核查清单 |
| 新鲜度 | \|现价−p₀\|/p₀ > 5% | 告警（p₀ 不可得则跳过，标 unknown） |

行情拉取失败：跳过该条目并汇总说明；exit code 区分全部成功（0）/部分失败（6）。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `tradingagents/advisor/review.py`（新建） | 类型 + `check_bucket` 纯函数 + `build_review_item` + `run_review`（provider 注入） |
| `cli/main.py`（修改） | 替换 `review` stub 为真实现 |
| `tradingagents/mcp/errors.py`（修改） | `_CODE_MAP` 加 `6: MCP_ERROR_PARTIAL_DATA` |
| `tests/test_advisor_review.py`（新建） | 纯函数矩阵 + run_review（fake provider） |
| `tests/test_cli_review.py`（新建） | CLI 真实现（env 隔离；网络路径不进 CI） |
| `tests/test_mcp_errors.py`（修改） | 补 exit 6 映射测试 |
| `CLAUDE.md` / `docs/mcp-deployment.md`（修改） | baseline + review 状态更新 |

**类型定义**（Task 1 建立，后续 task 复用）：

```python
class BucketCheck(BaseModel):
    horizon_months: int
    stop_triggered: bool          # 现价 ≤ stop
    target_hit: bool              # 现价 ≥ target
    horizon_expired: bool         # today > 分析日 + horizon_months 自然月
    fresh_warning: bool | None    # |price−p0|/p0 > 0.05；None = p0 不可得
    w_star_hint: float | None     # 止损触发且有向量时的减仓目标（0=清仓）

class ReviewItem(BaseModel):
    ticker: str
    date: str
    rating: str
    price: float
    p0: float | None
    checks: list[BucketCheck]
    falsification: list[str]      # 人工核查清单（原样列出）

class SkippedItem(BaseModel):
    ticker: str
    date: str
    reason: Literal["quote_failed", "no_scenario"]

class ReviewReport(BaseModel):
    generated_at: str             # YYYY-MM-DD
    items: list[ReviewItem]
    skipped: list[SkippedItem]
    manual_checklist: list[str]   # 所有 items 的 falsification 聚合
```

---

## Task 1: `review.py` 类型 + `check_bucket` 纯函数

**Files:**
- Create: `tradingagents/advisor/review.py`
- Test: `tests/test_advisor_review.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_advisor_review.py
from datetime import date

import pytest

from tradingagents.advisor.review import BucketCheck, check_bucket
from tradingagents.agents.schemas import KeyLevels, Scenario, ScenarioBucket


def _bucket(horizon=6, stop=9.0, target=12.0) -> ScenarioBucket:
    return ScenarioBucket(
        horizon_months=horizon,
        scenarios=[
            Scenario(name="bull", thesis="t", expected_return=0.25, prob=0.35),
            Scenario(name="base", thesis="t", expected_return=0.05, prob=0.45),
            Scenario(name="bear", thesis="t", expected_return=-0.15, prob=0.20),
        ],
        key_levels=KeyLevels(stop=stop, entry_low=9.5, entry_high=10.5, target=target),
    )


class TestCheckBucket:
    def test_stop_triggered(self):
        r = check_bucket(_bucket(), price=8.9, today=date(2026, 8, 30),
                         analysis_date=date(2026, 8, 1), p0=10.0)
        assert r.stop_triggered is True
        assert r.target_hit is False

    def test_stop_boundary_inclusive(self):
        """现价 == stop 也算触发（≤）。"""
        r = check_bucket(_bucket(), price=9.0, today=date(2026, 8, 30),
                         analysis_date=date(2026, 8, 1), p0=10.0)
        assert r.stop_triggered is True

    def test_target_hit(self):
        r = check_bucket(_bucket(), price=12.1, today=date(2026, 8, 30),
                         analysis_date=date(2026, 8, 1), p0=10.0)
        assert r.target_hit is True
        assert r.stop_triggered is False

    def test_target_boundary_inclusive(self):
        r = check_bucket(_bucket(), price=12.0, today=date(2026, 8, 30),
                         analysis_date=date(2026, 8, 1), p0=10.0)
        assert r.target_hit is True

    def test_neither_triggered(self):
        r = check_bucket(_bucket(), price=10.5, today=date(2026, 8, 30),
                         analysis_date=date(2026, 8, 1), p0=10.0)
        assert r.stop_triggered is False
        assert r.target_hit is False

    def test_horizon_expired(self):
        """分析日 2026-01-15 + 6 月 = 2026-07-15；今天 8-30 > 到期日。"""
        r = check_bucket(_bucket(horizon=6), price=10.0, today=date(2026, 8, 30),
                         analysis_date=date(2026, 1, 15), p0=10.0)
        assert r.horizon_expired is True

    def test_horizon_not_expired_same_day(self):
        """到期日当天不算过期（today > 到期日 才算）。"""
        r = check_bucket(_bucket(horizon=6), price=10.0, today=date(2026, 7, 15),
                         analysis_date=date(2026, 1, 15), p0=10.0)
        assert r.horizon_expired is False

    def test_horizon_month_rollover(self):
        """自然月加法：1-31 + 1 月 = 2-28（clamped）。"""
        r = check_bucket(_bucket(horizon=1), price=10.0, today=date(2026, 3, 1),
                         analysis_date=date(2026, 1, 31), p0=10.0)
        assert r.horizon_expired is True

    def test_fresh_warning_over_5pct(self):
        """p0=10, price=10.6 → 偏离 6% → 告警。"""
        r = check_bucket(_bucket(), price=10.6, today=date(2026, 8, 30),
                         analysis_date=date(2026, 8, 1), p0=10.0)
        assert r.fresh_warning is True

    def test_fresh_warning_boundary(self):
        """恰好 5% 不告警（> 0.05 严格）。"""
        r = check_bucket(_bucket(), price=10.5, today=date(2026, 8, 30),
                         analysis_date=date(2026, 8, 1), p0=10.0)
        assert r.fresh_warning is False

    def test_fresh_warning_downward(self):
        """下跌方向同样告警：p0=10, price=9.4 → -6%。"""
        r = check_bucket(_bucket(), price=9.4, today=date(2026, 8, 30),
                         analysis_date=date(2026, 8, 1), p0=10.0)
        assert r.fresh_warning is True

    def test_fresh_warning_none_p0(self):
        """p0 不可得 → None（不是 False）。"""
        r = check_bucket(_bucket(), price=10.0, today=date(2026, 8, 30),
                         analysis_date=date(2026, 8, 1), p0=None)
        assert r.fresh_warning is None

    def test_w_star_hint_default_none(self):
        r = check_bucket(_bucket(), price=10.0, today=date(2026, 8, 30),
                         analysis_date=date(2026, 8, 1), p0=10.0)
        assert r.w_star_hint is None
```

- [ ] **Step 2: 跑失败**

Run: `.venv/bin/python -m pytest tests/test_advisor_review.py -v`
Expected: FAIL — `ImportError: cannot import name 'check_bucket'`

- [ ] **Step 3: 实现**

```python
# tradingagents/advisor/review.py
"""决策纪律巡检（spec §7 P3）。零 LLM，纯函数检查 + 可注入数据源。"""
import calendar
from datetime import date
from typing import Literal, Optional, Protocol

from pydantic import BaseModel

from tradingagents.agents.schemas import ScenarioBucket


FRESHNESS_THRESHOLD = 0.05


class BucketCheck(BaseModel):
    horizon_months: int
    stop_triggered: bool
    target_hit: bool
    horizon_expired: bool
    fresh_warning: Optional[bool]
    w_star_hint: Optional[float] = None


class ReviewItem(BaseModel):
    ticker: str
    date: str
    rating: str
    price: float
    p0: Optional[float]
    checks: list[BucketCheck]
    falsification: list[str]


class SkippedItem(BaseModel):
    ticker: str
    date: str
    reason: Literal["quote_failed", "no_scenario"]


class ReviewReport(BaseModel):
    generated_at: str
    items: list[ReviewItem]
    skipped: list[SkippedItem]
    manual_checklist: list[str]


def _add_months(d: date, months: int) -> date:
    """自然月加法，月末 clamp（1-31 + 1月 = 2-28）。"""
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def check_bucket(
    bucket: ScenarioBucket,
    price: float,
    today: date,
    analysis_date: date,
    p0: Optional[float],
) -> BucketCheck:
    """单桶四项检查：止损 / 目标 / 期限 / 新鲜度。w* 由上层补。"""
    kl = bucket.key_levels
    stop_triggered = price <= kl.stop
    target_hit = price >= kl.target

    expiry = _add_months(analysis_date, bucket.horizon_months)
    horizon_expired = today > expiry

    if p0 is not None and p0 > 0:
        fresh_warning = abs(price - p0) / p0 > FRESHNESS_THRESHOLD
    else:
        fresh_warning = None

    return BucketCheck(
        horizon_months=bucket.horizon_months,
        stop_triggered=stop_triggered,
        target_hit=target_hit,
        horizon_expired=horizon_expired,
        fresh_warning=fresh_warning,
    )
```

- [ ] **Step 4: 跑通过**

Run: `.venv/bin/python -m pytest tests/test_advisor_review.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/advisor/review.py tests/test_advisor_review.py
git commit -m "feat(advisor): P3 review 类型 + check_bucket 四项检查纯函数"
```

---

## Task 2: `build_review_item` 组装

**Files:**
- Modify: `tradingagents/advisor/review.py`
- Test: `tests/test_advisor_review.py`（追加）

- [ ] **Step 1: 追加失败测试**

```python
# 追加到 tests/test_advisor_review.py
import json
from pathlib import Path

from tradingagents.advisor.review import build_review_item
from tradingagents.advisor.scenario_io import ScenarioArtifact
from tradingagents.agents.schemas import Falsification


def _artifact(falsify=("cond1", "cond2")) -> ScenarioArtifact:
    return ScenarioArtifact(
        version=1, ticker="000001", trade_date="2026-08-01", rating="Buy",
        scenario_buckets=[_bucket(horizon=6, stop=9.0, target=12.0)],
        falsification=Falsification(conditions=list(falsify)) if falsify else None,
    )


class TestBuildReviewItem:
    def test_assembles_from_entry_and_artifact(self):
        entry = {"date": "2026-08-01", "ticker": "000001", "rating": "Buy"}
        item = build_review_item(
            entry, _artifact(), price=10.5, p0=10.0, today=date(2026, 8, 30),
        )
        assert item.ticker == "000001"
        assert item.date == "2026-08-01"
        assert item.price == 10.5
        assert item.p0 == 10.0
        assert len(item.checks) == 1
        assert item.falsification == ["cond1", "cond2"]

    def test_multiple_buckets(self):
        artifact = _artifact()
        artifact.scenario_buckets.append(_bucket(horizon=12, stop=8.5, target=14.0))
        entry = {"date": "2026-08-01", "ticker": "000001", "rating": "Buy"}
        item = build_review_item(entry, artifact, price=10.5, p0=10.0,
                                 today=date(2026, 8, 30))
        assert len(item.checks) == 2
        assert item.checks[0].horizon_months == 6
        assert item.checks[1].horizon_months == 12

    def test_no_falsification_empty_list(self):
        entry = {"date": "2026-08-01", "ticker": "000001", "rating": "Buy"}
        item = build_review_item(
            entry, _artifact(falsify=None), price=10.5, p0=10.0, today=date(2026, 8, 30),
        )
        assert item.falsification == []

    def test_stop_price_populates_checks(self):
        entry = {"date": "2026-08-01", "ticker": "000001", "rating": "Buy"}
        item = build_review_item(
            entry, _artifact(), price=8.9, p0=10.0, today=date(2026, 8, 30),
        )
        assert item.checks[0].stop_triggered is True
```

- [ ] **Step 2: 跑失败**

Run: `.venv/bin/python -m pytest tests/test_advisor_review.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_review_item'`

- [ ] **Step 3: 实现（追加到 review.py）**

```python
def build_review_item(
    entry: dict,
    artifact: ScenarioArtifact,
    price: float,
    p0: Optional[float],
    today: date,
) -> ReviewItem:
    """把 pending 决策 + scenario 制品 + 现价组装成 ReviewItem（每桶一查）。"""
    analysis_date = date.fromisoformat(artifact.trade_date)
    checks = [
        check_bucket(b, price=price, today=today,
                     analysis_date=analysis_date, p0=p0)
        for b in artifact.scenario_buckets
    ]
    falsification = (
        list(artifact.falsification.conditions) if artifact.falsification else []
    )
    return ReviewItem(
        ticker=entry["ticker"],
        date=entry["date"],
        rating=entry["rating"],
        price=price,
        p0=p0,
        checks=checks,
        falsification=falsification,
    )
```

顶部 import 追加：`from tradingagents.advisor.scenario_io import ScenarioArtifact`

- [ ] **Step 4: 跑通过**

Run: `.venv/bin/python -m pytest tests/test_advisor_review.py -v`
Expected: PASS (17 tests)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/advisor/review.py tests/test_advisor_review.py
git commit -m "feat(advisor): P3 build_review_item 组装 (多桶 + 证伪清单)"
```

---

## Task 3: `run_review` IO 组装（provider 注入 + w\* hint + skipped）

**Files:**
- Modify: `tradingagents/advisor/review.py`
- Test: `tests/test_advisor_review.py`（追加）

**设计**：数据源全部经参数注入（`quotes_provider` / `p0_provider` / `entries_provider` / `scenario_loader`，默认值为真实现），测试传 fake 零网络。止损触发的桶补 `w_star_hint`（`engine.advise` 的 w*，含 horizon 硬门：期限不匹配时引擎自然给 0）。

- [ ] **Step 1: 追加失败测试**

```python
# 追加到 tests/test_advisor_review.py
from tradingagents.advisor.review import run_review
from tradingagents.advisor.types import InvestorVector, AdvisorConfig


def _write_memory_log(tmp_path: Path, entries_md: str) -> Path:
    log = tmp_path / "memory" / "trading_memory.md"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(entries_md, encoding="utf-8")
    return log


_PENDING_MD = """[2026-08-01 | 000001 | Buy | pending]

DECISION:
buy some

<!-- ENTRY_END -->

[2026-08-01 | 600000 | Sell | pending]

DECISION:
sell some

<!-- ENTRY_END -->
"""


class TestRunReview:
    def _env(self, tmp_path: Path, monkeypatch, md: str = _PENDING_MD):
        log = _write_memory_log(tmp_path, md)
        reports = tmp_path / "reports"
        reports.mkdir(exist_ok=True)
        monkeypatch.setenv("TRADINGAGENTS_MEMORY_LOG_PATH", str(log))
        monkeypatch.setenv("TRADINGAGENTS_REPORTS_DIR", str(reports))
        return reports

    def _write_artifact(self, reports: Path, ticker="000001",
                        date_str="2026-08-01", stop=9.0, target=12.0):
        (reports / f"scenario_{ticker}_{date_str}.json").write_text(json.dumps({
            "version": 1, "ticker": ticker, "trade_date": date_str, "rating": "Buy",
            "scenario_buckets": [{
                "horizon_months": 6,
                "scenarios": [
                    {"name": "bull", "thesis": "t", "expected_return": 0.25, "prob": 0.35},
                    {"name": "base", "thesis": "t", "expected_return": 0.05, "prob": 0.45},
                    {"name": "bear", "thesis": "t", "expected_return": -0.15, "prob": 0.20},
                ],
                "key_levels": {"stop": stop, "entry_low": 9.5, "entry_high": 10.5,
                               "target": target},
            }],
            "falsification": {"conditions": ["watch X"]},
        }), encoding="utf-8")

    def test_full_flow_with_fakes(self, tmp_path, monkeypatch):
        reports = self._env(tmp_path, monkeypatch)
        self._write_artifact(reports)
        vector = InvestorVector(gamma_eff=5.0, hc=0.7, h_avail_months=60.0)
        report = run_review(
            quotes_provider=lambda codes: {"000001": {"price": 8.9}},
            p0_provider=lambda t, d: 10.0,
            vector=vector,
            today=date(2026, 8, 30),
        )
        assert len(report.items) == 1
        item = report.items[0]
        assert item.ticker == "000001"
        assert item.checks[0].stop_triggered is True
        assert item.checks[0].w_star_hint is not None  # 止损触发 + 有向量 → hint
        assert report.skipped == [{"ticker": "600000", "date": "2026-08-01",
                                   "reason": "no_scenario"}] or \
               len(report.skipped) == 1
        assert report.manual_checklist == ["watch X"]

    def test_quote_failed_skips_item(self, tmp_path, monkeypatch):
        reports = self._env(tmp_path, monkeypatch)
        self._write_artifact(reports)
        report = run_review(
            quotes_provider=lambda codes: {},  # 行情全挂
            p0_provider=lambda t, d: None,
            vector=None,
            today=date(2026, 8, 30),
        )
        assert report.items == []
        assert {s.reason for s in report.skipped} == {"quote_failed", "no_scenario"}

    def test_no_vector_no_w_hint(self, tmp_path, monkeypatch):
        reports = self._env(tmp_path, monkeypatch)
        self._write_artifact(reports)
        report = run_review(
            quotes_provider=lambda codes: {"000001": {"price": 8.9}},
            p0_provider=lambda t, d: 10.0,
            vector=None,
            today=date(2026, 8, 30),
        )
        assert report.items[0].checks[0].stop_triggered is True
        assert report.items[0].checks[0].w_star_hint is None

    def test_no_pending_empty_report(self, tmp_path, monkeypatch):
        self._env(tmp_path, monkeypatch, md="(empty log)\n")
        report = run_review(
            quotes_provider=lambda codes: {},
            p0_provider=lambda t, d: None,
            vector=None,
            today=date(2026, 8, 30),
        )
        assert report.items == []
        assert report.skipped == []
        assert report.manual_checklist == []

    def test_w_hint_zero_when_horizon_mismatch(self, tmp_path, monkeypatch):
        """止损触发但桶期限 > H_avail（3 月）→ 引擎硬门 → hint=0（清仓方向）。"""
        reports = self._env(tmp_path, monkeypatch)
        self._write_artifact(reports)
        vector = InvestorVector(gamma_eff=5.0, hc=0.7, h_avail_months=3.0)
        report = run_review(
            quotes_provider=lambda codes: {"000001": {"price": 8.9}},
            p0_provider=lambda t, d: 10.0,
            vector=vector,
            today=date(2026, 8, 30),
        )
        assert report.items[0].checks[0].w_star_hint == 0.0
```

- [ ] **Step 2: 跑失败**

Run: `.venv/bin/python -m pytest tests/test_advisor_review.py -v`
Expected: FAIL — `ImportError: cannot import name 'run_review'`

- [ ] **Step 3: 实现（追加到 review.py）**

```python
from collections.abc import Callable
from typing import Any

from tradingagents.advisor.engine import advise as _engine_advise
from tradingagents.advisor.scenario_io import (
    ScenarioNotFoundError,
    list_scenarios,
    load_scenario,
)
from tradingagents.advisor.types import AdvisorConfig, InvestorVector
from tradingagents.agents.utils.memory import TradingMemoryLog
from tradingagents.default_config import DEFAULT_CONFIG


QuotesProvider = Callable[[list[str]], dict[str, dict[str, Any]]]
P0Provider = Callable[[str, str], Optional[float]]


def _default_quotes(codes: list[str]) -> dict[str, dict[str, Any]]:
    from tradingagents.dataflows.a_stock import _tencent_quote

    return _tencent_quote(codes)


def _default_p0(ticker: str, trade_date: str) -> Optional[float]:
    from tradingagents.agents.utils.scenario_check import fetch_p0

    return fetch_p0(ticker, trade_date)


def run_review(
    quotes_provider: QuotesProvider = _default_quotes,
    p0_provider: P0Provider = _default_p0,
    vector: Optional[InvestorVector] = None,
    today: Optional[date] = None,
) -> ReviewReport:
    """扫 pending 决策 → 拉现价/p0 → 逐条检查。

    skipped: quote_failed（行情拉不到）或 no_scenario（该决策无 scenario 制品）。
    """
    today = today or date.today()
    log = TradingMemoryLog(DEFAULT_CONFIG)
    pending = log.get_pending_entries()
    if not pending:
        return ReviewReport(generated_at=today.isoformat(), items=[],
                            skipped=[], manual_checklist=[])

    tickers = sorted({e["ticker"] for e in pending})
    try:
        quotes = quotes_provider(tickers)
    except Exception:
        quotes = {}

    items: list[ReviewItem] = []
    skipped: list[SkippedItem] = []
    checklist: list[str] = []

    for entry in pending:
        ticker, entry_date = entry["ticker"], entry["date"]
        q = quotes.get(ticker)
        if not q or not q.get("price"):
            skipped.append(SkippedItem(ticker=ticker, date=entry_date,
                                       reason="quote_failed"))
            continue
        try:
            artifact = load_scenario(ticker, date=entry_date)
        except ScenarioNotFoundError:
            skipped.append(SkippedItem(ticker=ticker, date=entry_date,
                                       reason="no_scenario"))
            continue
        p0 = p0_provider(ticker, entry_date)
        item = build_review_item(entry, artifact, price=q["price"], p0=p0, today=today)
        if vector is not None:
            for i, bucket in enumerate(artifact.scenario_buckets):
                if item.checks[i].stop_triggered:
                    result = _engine_advise(
                        bucket, vector, AdvisorConfig(),
                        ticker=ticker, date=entry_date, rating=artifact.rating,
                    )
                    item.checks[i].w_star_hint = result.trace.w_star
        items.append(item)
        checklist.extend(item.falsification)

    return ReviewReport(
        generated_at=today.isoformat(),
        items=items, skipped=skipped, manual_checklist=checklist,
    )
```

注意：`DEFAULT_CONFIG` 在 import 时读 env（`TRADINGAGENTS_MEMORY_LOG_PATH`），`TradingMemoryLog` 拿到的 config 字典已是测试隔离后的路径——**但** `DEFAULT_CONFIG` 是模块级常量，env 改动发生在 import 之后时不生效。测试 monkeypatch env 在 import 后设置——**因此必须在 run_review 内部现场构造 config**：

```python
    import os
    cfg = {"memory_log_path": os.environ.get(
        "TRADINGAGENTS_MEMORY_LOG_PATH",
        os.path.join(os.path.expanduser("~"), ".tradingagents", "memory", "trading_memory.md"),
    )}
    log = TradingMemoryLog(cfg)
```

用这个替代 `TradingMemoryLog(DEFAULT_CONFIG)`（并删掉对应 import）。p0_provider / scenario_io 已是 lazy（load_scenario 每次现场读 env）。

- [ ] **Step 4: 跑通过**

Run: `.venv/bin/python -m pytest tests/test_advisor_review.py -v`
Expected: PASS (22 tests)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/advisor/review.py tests/test_advisor_review.py
git commit -m "feat(advisor): P3 run_review (provider 注入 + w* hint + skipped 汇总)"
```

---

## Task 4: CLI `review` 真实现（替换 stub）

**Files:**
- Modify: `cli/main.py`（替换现有 review stub 函数体）
- Test: `tests/test_cli_review.py`（新建）；修改 `tests/test_cli_review_stub.py`（更名或改断言）

**KYC 链路与 `advise` 完全同构**：`--kyc-json` > `--assume-neutral` > `profile.json` > `kyc_required`(exit 3)。互斥校验同 advise（`--kyc-json` + `--assume-neutral` → exit 5）。

**exit codes**：0=全部成功（含空 pending）；2=invalid_kyc；3=kyc_required；5=flag 互斥；6=部分行情失败（`skipped` 含 `quote_failed`）。`no_scenario` 不算行情失败（是数据边界，仍 exit 0）。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_cli_review.py
import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def tmp_env(tmp_path: Path, monkeypatch):
    log = tmp_path / "memory" / "trading_memory.md"
    log.parent.mkdir(parents=True)
    monkeypatch.setenv("TRADINGAGENTS_MEMORY_LOG_PATH", str(log))
    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setenv("TRADINGAGENTS_REPORTS_DIR", str(reports))
    monkeypatch.setenv("HOME", str(tmp_path))
    return {"log": log, "reports": reports, "home": tmp_path}


def _run(*args):
    return subprocess.run(
        [".venv/bin/python", "-m", "cli.main", *args],
        capture_output=True, text=True,
    )


def _write_pending(log: Path):
    log.write_text("""[2026-08-01 | 000001 | Buy | pending]

DECISION:
buy

<!-- ENTRY_END -->
""", encoding="utf-8")


KYC = '{"q1":7,"q2":7,"q3":7,"q4":7,"q5":7}'


class TestReviewCLI:
    def test_no_pending_exit_0_empty(self, tmp_env):
        r = _run("review", "--json", "--kyc-json", KYC)
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        assert payload["items"] == []
        assert payload["skipped"] == []

    def test_kyc_required_exit_3(self, tmp_env):
        _write_pending(tmp_env["log"])
        r = _run("review", "--json")
        assert r.returncode == 3
        payload = json.loads(r.stdout)
        assert payload["error"] == "kyc_required"
        assert len(payload["questionnaire"]["questions"]) == 5

    def test_invalid_kyc_exit_2(self, tmp_env):
        r = _run("review", "--json", "--kyc-json", '{"q1":4}')
        assert r.returncode == 2
        assert json.loads(r.stdout)["error"] == "invalid_kyc"

    def test_mutex_exit_5(self, tmp_env):
        r = _run("review", "--json", "--kyc-json", KYC, "--assume-neutral")
        assert r.returncode == 5

    def test_quote_failed_exit_6(self, tmp_env):
        """pending 决策 + 无网络（行情 provider 挂）→ quote_failed → exit 6。

        真 subprocess 里无法 mock 网络，因此用 no_scenario 与 quote 的组合：
        决策存在但 reports 空 → no_scenario（exit 0 路径）；本测试验证 exit 6
        需要 quote_failed——改用环境变量注入 fake quotes（见实现）。
        """
        _write_pending(tmp_env["log"])
        r = _run("review", "--json", "--kyc-json", KYC,
                 "--fake-quotes", '{"000001": 8.9}')
        assert r.returncode == 0  # no_scenario: quote 成功但无制品
        payload = json.loads(r.stdout)
        assert payload["skipped"][0]["reason"] == "no_scenario"
```

**`--fake-quotes` 设计说明**：CLI 真 subprocess 测试无法注入 provider。给 review 加一个**测试专用** `--fake-quotes '{"code": price}'` 参数——存在时 quotes_provider 直接返回该 dict（p0 同步为 None）。这不是业务逻辑（是数据源注入 seam），生产不传即走真网络。这让 exit 6 路径可测：

```python
    def test_quote_failed_exit_6(self, tmp_env):
        """fake quotes 里不含该代码 → quote_failed → exit 6。"""
        _write_pending(tmp_env["log"])
        r = _run("review", "--json", "--kyc-json", KYC,
                 "--fake-quotes", "{}")   # 空 fake：全部拉不到
        assert r.returncode == 6
        payload = json.loads(r.stdout)
        assert payload["skipped"][0]["reason"] == "quote_failed"
```

（上面 Step 1 里两个同名 `test_quote_failed_exit_6` 二选一——保留 `--fake-quotes "{}"` 这个版本，删掉另一个不完整的。最终测试类应包含：no_pending / kyc_required / invalid_kyc / mutex / no_scenario_exit_0 / quote_failed_exit_6。）

- [ ] **Step 2: 跑失败**

Run: `.venv/bin/python -m pytest tests/test_cli_review.py -v`
Expected: FAIL — stub 返 exit 5 not_implemented，新断言全挂

- [ ] **Step 3: 实现（替换 cli/main.py 的 review 函数体）**

```python
@app.command()
def review(
    json_out: bool = typer.Option(False, "--json", help="输出 JSON"),
    assume_neutral: bool = typer.Option(
        False, "--assume-neutral",
        help="无 profile 时用中性向量（γ_eff=5, HC=0.7, H_avail=60）",
    ),
    kyc_json: Optional[str] = typer.Option(
        None, "--kyc-json",
        help='inline KYC 答案 JSON，如 {"q1":7,"q2":5,"q3":7,"q4":7,"q5":7}',
    ),
    fake_quotes: Optional[str] = typer.Option(
        None, "--fake-quotes",
        help='测试注入：JSON dict {code: price}，替代真行情',
    ),
):
    """决策纪律巡检：扫 pending 决策，检查止损/目标/期限/证伪/新鲜度（零 LLM）。"""
    import json as _json
    from datetime import date as _date

    from pydantic import ValidationError

    from tradingagents.advisor.calibrate import from_kyc
    from tradingagents.advisor.profile_io import ProfileNotFoundError, read_profile
    from tradingagents.advisor.questionnaire import get_questionnaire
    from tradingagents.advisor.review import run_review
    from tradingagents.advisor.types import InvestorVector, KYCAnswers

    def _emit(payload: dict, exit_code: int) -> NoReturn:
        if json_out:
            console.print_json(_json.dumps(payload, ensure_ascii=False))
        else:
            console.print(payload)
        raise typer.Exit(code=exit_code)

    if kyc_json is not None and assume_neutral:
        console.print("[red]--kyc-json 与 --assume-neutral 互斥[/red]")
        raise typer.Exit(code=5)

    try:
        if kyc_json is not None:
            try:
                vector = from_kyc(KYCAnswers.model_validate_json(kyc_json))
            except ValidationError as e:
                _emit({
                    "error": "invalid_kyc",
                    "message": "KYC 答案 schema 违例",
                    "details": _json.loads(e.json()),
                }, exit_code=2)
        elif assume_neutral:
            vector = InvestorVector(gamma_eff=5.0, hc=0.7, h_avail_months=60.0)
        else:
            try:
                vector = from_kyc(read_profile())
            except ProfileNotFoundError:
                _emit({
                    "error": "kyc_required",
                    "message": "需要先建立投资者画像（5 题问卷）；或用 --kyc-json / --assume-neutral",
                    "questionnaire": get_questionnaire().model_dump(),
                }, exit_code=3)
    except ValidationError:
        raise  # profile.json 损坏属配置错误，如实抛出

    if fake_quotes is not None:
        fake = _json.loads(fake_quotes)
        quotes_provider = lambda codes: {
            c: {"price": float(fake[c])} for c in codes if c in fake
        }
    else:
        quotes_provider = None  # run_review 用默认真行情

    report = run_review(
        quotes_provider=quotes_provider,
        vector=vector,
    )
    payload = report.model_dump()
    exit_code = 6 if any(s.reason == "quote_failed" for s in report.skipped) else 0
    if json_out:
        _emit(payload, exit_code=exit_code)
    else:
        for item in report.items:
            flags = []
            for c in item.checks:
                if c.stop_triggered:
                    flags.append(f"[red]止损触发[/red] (≤stop, w*→{c.w_star_hint}")
                if c.target_hit:
                    flags.append("[green]目标达成[/green]")
                if c.horizon_expired:
                    flags.append("[yellow]期限到期[/yellow]")
                if c.fresh_warning:
                    flags.append("[yellow]偏离>5%[/yellow]")
            console.print(f"{item.ticker} {item.date} {item.rating} "
                          f"现价 {item.price:.2f}  {' | '.join(flags) or '正常'}")
        for s in report.skipped:
            console.print(f"[dim]跳过 {s.ticker} {s.date}: {s.reason}[/dim]")
        if report.manual_checklist:
            console.print("[bold]人工核查清单:[/bold]")
            for c in report.manual_checklist:
                console.print(f"  - {c}")
        raise typer.Exit(code=exit_code)
```

同时**更新 `tests/test_cli_review_stub.py`**：stub 已不存在——把该文件改名为断言真行为（或直接删除，其 2 个用例已被 test_cli_review.py 覆盖）：

```bash
git rm tests/test_cli_review_stub.py
```

- [ ] **Step 4: 跑通过 + v0.5.9 + 无网络路径检查**

```
.venv/bin/python -m pytest tests/test_cli_review.py tests/test_cli_default_command.py -v
```
Expected: 全 PASS。**注意**：`test_no_pending_exit_0_empty` 会走真 quotes_provider（pending 为空时 run_review 提前返回，不拉行情）——确认空 pending 路径零网络。

- [ ] **Step 5: 全量回归**

```
.venv/bin/python -m pytest tests/ --tb=no -q 2>&1 | tail -3
```

- [ ] **Step 6: Commit**

```bash
git add cli/main.py tests/test_cli_review.py
git rm tests/test_cli_review_stub.py
git commit -m "feat(cli): review 真实现 (替换 stub；exit 0/2/3/5/6 + --fake-quotes seam)"
```

---

## Task 5: MCP exit 6 映射 + review_tool 端到端契约

**Files:**
- Modify: `tradingagents/mcp/errors.py`（`_CODE_MAP` 加 6）
- Modify: `tests/test_mcp_errors.py`（补 1 测试）
- Modify: `tests/test_mcp_server_integration.py`（补 review 真契约测试）

- [ ] **Step 1: 追加失败测试**

```python
# tests/test_mcp_errors.py 追加
def test_exit_code_6_partial_data(self):
    from tradingagents.mcp.errors import MCP_ERROR_PARTIAL_DATA
    err = map_cli_error(6, b'{"items": [], "skipped": [{"reason": "quote_failed"}]}')
    # payload 无 error 字段 → fallback exit code 映射
    assert err.code == MCP_ERROR_PARTIAL_DATA
```

```python
# tests/test_mcp_server_integration.py 追加
class TestReviewEndToEnd:
    @pytest.mark.asyncio
    async def test_review_tool_via_real_cli(self, tmp_path, monkeypatch):
        """review 工具 subprocess 调真 CLI（kyc_required 路径零网络）。"""
        import os
        monkeypatch.setenv("TRADINGAGENTS_MEMORY_LOG_PATH",
                           str(tmp_path / "nonexistent.md"))
        monkeypatch.setenv("TRADINGAGENTS_REPORTS_DIR", str(tmp_path / "reports"))
        monkeypatch.setenv("HOME", str(tmp_path))
        result = await dispatch_tool("review", {
            "kyc_answers": {"q1": 7, "q2": 7, "q3": 7, "q4": 7, "q5": 7},
        })
        # 空 pending → exit 0 → {"items": [], "skipped": [], ...}
        assert result["items"] == []
        assert result["skipped"] == []
        assert "generated_at" in result
```

- [ ] **Step 2: 跑失败**

```
.venv/bin/python -m pytest tests/test_mcp_errors.py tests/test_mcp_server_integration.py -v
```
Expected: FAIL — `MCP_ERROR_PARTIAL_DATA` 不存在；review 端到端返 not_implemented

- [ ] **Step 3: 实现**

`tradingagents/mcp/errors.py`：

```python
MCP_ERROR_PARTIAL_DATA = "partial_data_failure"
```

`_CODE_MAP` 追加一行：

```python
_CODE_MAP = {
    1: MCP_ERROR_NOT_FOUND,
    2: MCP_ERROR_INVALID_KYC,
    3: MCP_ERROR_KYC_REQUIRED,
    4: MCP_ERROR_INTERNAL,
    5: MCP_ERROR_NOT_IMPLEMENTED,
    6: MCP_ERROR_PARTIAL_DATA,
}
```

- [ ] **Step 4: 跑通过 + 守卫**

```
.venv/bin/python -m pytest tests/test_mcp_errors.py tests/test_mcp_server_integration.py tests/test_mcp_thin_shell_guard.py -v
```
Expected: 全 PASS（守卫过——errors.py 只加常量与映射条目）

- [ ] **Step 5: Commit**

```bash
git add tradingagents/mcp/errors.py tests/test_mcp_errors.py tests/test_mcp_server_integration.py
git commit -m "feat(mcp): exit 6 partial_data_failure 映射 + review 端到端契约"
```

---

## Task 6: 全量回归 + 文档更新

- [ ] **Step 1: 全量测试**

```
.venv/bin/python -m pytest tests/ --tb=no -q 2>&1 | tail -3
```
记录新 baseline（预期 574 + ~28 = ~602）。

- [ ] **Step 2: CLAUDE.md 更新**

`### 测试` 段 baseline 数字更新；`MCP 集成规范` 段的"已知边界"改为：review 已交付（P3），scenario/review 未交付的说法删除，剩余边界只剩 `analyze --json --confirm` 真执行。

- [ ] **Step 3: docs/mcp-deployment.md 更新**

工具表 `review` 行去掉 "P3 分期" 说明，改为"决策纪律巡检（止损/目标/期限/证伪/新鲜度）；部分行情失败时返回 partial_data_failure"。

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md docs/mcp-deployment.md
git commit -m "chore: P3 review 交付后 baseline 与文档更新"
```

---

## Self-Review 检查表

**Spec 覆盖**（spec §7 review 表 + 错误处理段）：
- ✅ 止损触发（≤，含边界）+ w* 减仓提示 → Task 1/3
- ✅ 目标达成（≥，含边界）→ Task 1
- ✅ 期限到期（自然月加法，today > 到期日）→ Task 1
- ✅ 证伪条件人工清单 → Task 2/3（falsification 原样聚合）
- ✅ 新鲜度 >5% 告警，p0 不可得跳过（None）→ Task 1/3
- ✅ 行情失败跳过 + 汇总 + exit code 区分（0/6）→ Task 3/4/5
- ✅ 零 LLM → 全程无 LLM 调用
- ✅ 多桶各自检查 → Task 2
- ✅ MCP 薄壳零改动（除 errors.py 映射表一行）→ Task 5

**Placeholder 扫描**：所有步骤含完整代码/命令/期望输出；Task 4 Step 1 中两个同名测试明确保留哪个。

**类型一致性**：`BucketCheck.w_star_hint` Task 1 定义 / Task 3 填充 / Task 4 渲染一致；`SkippedItem.reason` 的 Literal 两值贯穿；`run_review(quotes_provider, p0_provider, vector, today)` 签名 Task 3 定义 / Task 4 调用一致（Task 4 不传 p0_provider 走默认）。

**风险**：
- Task 3 的 `DEFAULT_CONFIG` import 时固化 env 问题——plan 已内联解决（现场构造 cfg）
- CLI subprocess 测试零网络：空 pending 提前返回 + `--fake-quotes` seam 两条路径保证
