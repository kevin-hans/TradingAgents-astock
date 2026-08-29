# Scenario Tree P1 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** PM 结构化输出扩展情景树（bull/base/bear × 6/12 月桶 + 关键价位 + 证伪条件），经确定性校验后落盘为可复用制品 `scenario_<ticker>_<date>.json`，并加生成端同日守卫与 `--force` 归档。

**Architecture:** 情景树挂在 PM 现有的 `with_structured_output(PortfolioDecision)` 上（同源原则，零新增节点）；算术/锚定/方向校验在独立纯函数模块 `scenario_check.py`，违例重问一次、再败降级（主流程永不阻塞）；落盘与归档在 `finalize_graph_run`/`_log_state`；CLI 补上同日守卫并对其持久化行为（对齐 web 的 `finalize_graph_run` 调用）。

**Tech Stack:** Python 3.10+ / pydantic v2 / LangChain structured output / pytest。规格：`docs/superpowers/specs/2026-08-29-scenario-vector-advisor-design.md`（§4 P1、§7 同日守卫）。

**已确认的边界推翻:** `schemas.py` 中 TraderProposal/PortfolioDecision "不输出可执行价位" 的成文边界，由 fork 维护者（kevin-hans）于 2026-08-29 显式决定推翻（上游注释本身预留了下游 fork 自担责任添加的口子）。本计划只放开 **PM** 的结构化字段；Trader 保持原样。所有制品须带研究工具免责语义（spec §13）。

**命名约定（与 spec 的小差异，以本计划为准）:**
- 情景收益字段名 `expected_return`（spec 写作 return_pct），**小数形式**（0.25 = +25%），避免百分号单位歧义。
- state 新键名 `scenario_tree`（与 spec 一致），载荷 `{"decision": <PortfolioDecision.model_dump(mode="json")>, "scenario_meta": {...}}`。

---

### Task 1: schemas.py — 情景树模型 + PortfolioDecision 扩展 + 渲染

**Files:**
- Modify: `tradingagents/agents/schemas.py`（PortfolioDecision 类之后追加模型；修改 PortfolioDecision 与 render_pm_decision；更新 docstring）
- Test: `tests/test_scenario_schemas.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_scenario_schemas.py
"""Scenario tree schema models and rendering (spec §4.1)."""
import pytest

from tradingagents.agents.schemas import (
    Falsification,
    KeyLevels,
    PortfolioDecision,
    PortfolioRating,
    Scenario,
    ScenarioBucket,
    render_pm_decision,
)


def _bucket(horizon=6, *, bull=0.25, base=0.05, bear=-0.18,
            p_bull=0.30, p_base=0.45, p_bear=0.25,
            stop=1450.0, entry_low=1480.0, entry_high=1520.0, target=1750.0):
    return ScenarioBucket(
        horizon_months=horizon,
        scenarios=[
            Scenario(name="bull", thesis="多空辩论多方: 估值锚+资金回流", expected_return=bull, prob=p_bull),
            Scenario(name="base", thesis="综合裁决: 区间震荡", expected_return=base, prob=p_base),
            Scenario(name="bear", thesis="空方: 中报负增长+主力流出", expected_return=bear, prob=p_bear),
        ],
        key_levels=KeyLevels(stop=stop, entry_low=entry_low, entry_high=entry_high, target=target),
    )


def _decision(with_tree=True):
    return PortfolioDecision(
        rating=PortfolioRating.UNDERWEIGHT,
        executive_summary="证据偏空但非结构性利空。",
        investment_thesis="空方新增证据可信度高，牛方论据陈旧。",
        time_horizon="3-6 months",
        scenario_buckets=[_bucket(6), _bucket(12)] if with_tree else [],
        falsification=Falsification(conditions=["跌破 1450 且放量", "应收账款周转天数 > 90"]) if with_tree else None,
    )


@pytest.mark.unit
class TestScenarioModels:
    def test_scenario_name_literal_rejects_other(self):
        with pytest.raises(Exception):
            Scenario(name="moon", thesis="x", expected_return=0.1, prob=0.5)

    def test_decision_without_tree_renders_identical(self):
        md = render_pm_decision(_decision(with_tree=False))
        assert "**Rating**: Underweight" in md
        assert "Scenario Tree" not in md
        assert "Falsification" not in md

    def test_decision_with_tree_renders_sections(self):
        md = render_pm_decision(_decision())
        assert "**Scenario Tree**:" in md
        assert "6M:" in md and "12M:" in md
        assert "bull +25%" in md          # 0.25 → +25%
        assert "stop 1450" in md
        assert "**Falsification**:" in md
        assert "跌破 1450 且放量" in md

    def test_model_dump_json_mode_gives_plain_types(self):
        dumped = _decision().model_dump(mode="json")
        import json
        json.dumps(dumped)  # must not raise on enum/date
        assert dumped["rating"] == "Underweight"
        assert dumped["scenario_buckets"][0]["horizon_months"] == 6
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_scenario_schemas.py -v`
Expected: FAIL，`ImportError: cannot import name 'Falsification'`

- [ ] **Step 3: 实现模型与渲染**

在 `tradingagents/agents/schemas.py` 的 `PortfolioDecision` 类**定义之前**插入：

```python
# ---------------------------------------------------------------------------
# Scenario tree (P1 of the scenario-vector advisor; spec §4.1)
# ---------------------------------------------------------------------------


class Scenario(BaseModel):
    """One outcome of a horizon bucket, anchored to the debate evidence."""

    name: Literal["bull", "base", "bear"] = Field(
        description="Exactly one of bull / base / bear.",
    )
    thesis: str = Field(
        description=(
            "One sentence citing the SPECIFIC bull/bear debate argument this "
            "scenario rests on. Generic filler like 'market sentiment improves' "
            "is not acceptable."
        ),
    )
    expected_return: float = Field(
        description=(
            "Expected TOTAL return from the analysis-date close to the end of "
            "the bucket horizon, as a decimal fraction (0.25 = +25%, -0.18 = -18%). "
            "Anchor to the key levels of the same bucket: bear ≈ stop/close − 1, "
            "bull ≈ target/close − 1."
        ),
    )
    prob: float = Field(
        description=(
            "Probability as a decimal fraction. The three probabilities of a "
            "bucket must sum to 1.0. Base sits in [0.35, 0.55]. When the final "
            "rating is Hold or below, P(bear) ≥ P(bull); when Overweight or "
            "above, P(bull) ≥ P(bear)."
        ),
    )


class KeyLevels(BaseModel):
    """Reference price levels for one horizon bucket (fork decision: shipped)."""

    stop: float = Field(description="Invalidation/stop level, below analysis-date context.")
    entry_low: float = Field(description="Lower bound of the suggested entry zone.")
    entry_high: float = Field(description="Upper bound of the suggested entry zone.")
    target: float = Field(description="Price target for the bucket horizon.")


class ScenarioBucket(BaseModel):
    """Scenario tree for one horizon (v1 ships the 6- and 12-month buckets)."""

    horizon_months: int = Field(description="Bucket horizon in months; v1 uses 6 or 12.")
    scenarios: list[Scenario] = Field(
        description="Exactly three scenarios: bull, base, bear.",
    )
    key_levels: KeyLevels = Field(
        description="Price levels for this bucket; must satisfy stop < entry_low ≤ entry_high < target.",
    )


class Falsification(BaseModel):
    """Concrete, checkable conditions that would falsify the decision (spec §4)."""

    conditions: list[str] = Field(
        description=(
            "1-3 conditions, each checkable against later data: price levels "
            "(e.g. 'daily close below 1450 on volume'), fundamental thresholds "
            "(e.g. 'receivables turnover days > 90'), or events."
        ),
    )
```

文件顶部 import 区把 `from typing import Optional` 改为 `from typing import Literal, Optional`。

修改 `PortfolioDecision`：docstring 中 "Like :class:`TraderProposal`, this carries no price target and no other executable level — see that class for why." 一段替换为：

```python
    Like :class:`TraderProposal` this stays level-free in its prose fields, but
    this fork (kevin-hans, 2026-08-29) DOES ship executable levels inside the
    structured ``scenario_buckets`` — the upstream docstring explicitly left
    that to a downstream fork's responsibility. Every artifact and consumer
    built on it carries the research-tool disclaimer (spec §13).
```

`PortfolioDecision` 字段区（`time_horizon` 之后）追加：

```python
    scenario_buckets: list[ScenarioBucket] = Field(
        default_factory=list,
        description=(
            "Scenario tree for the reusable advisory artifact. Provide exactly "
            "two buckets (horizon_months 6 and 12). Follow the anchoring and "
            "probability rules of each nested field exactly."
        ),
    )
    falsification: Optional[Falsification] = Field(
        default=None,
        description="1-3 concrete conditions that, if met, falsify this decision.",
    )
```

`render_pm_decision` 末尾（`time_horizon` 块之后、`return` 之前）追加：

```python
    if decision.scenario_buckets:
        parts.append("")
        parts.append("**Scenario Tree**:")
        for b in decision.scenario_buckets:
            summary = " / ".join(
                f"{s.name} {s.expected_return:+.0%}@{s.prob:.0%}"
                for s in b.scenarios
            )
            parts.append(f"- {b.horizon_months}M: {summary}")
            kl = b.key_levels
            parts.append(
                f"  levels: stop {kl.stop}, entry {kl.entry_low}-{kl.entry_high}, target {kl.target}"
            )
    if decision.falsification:
        parts.append("")
        parts.append("**Falsification**:")
        for cond in decision.falsification.conditions:
            parts.append(f"- {cond}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_scenario_schemas.py -v`
Expected: 4 passed

- [ ] **Step 5: 跑存量渲染测试防回归**

Run: `pytest tests/test_structured_agents.py tests/test_memory_log.py -v`
Expected: 全部 passed（render 对无树的决策输出逐字节不变）

- [ ] **Step 6: 提交**

```bash
git add tradingagents/agents/schemas.py tests/test_scenario_schemas.py
git commit -m "feat: scenario tree models on PortfolioDecision (spec P1 §4.1)"
```

---

### Task 2: scenario_check.py — 确定性校验器（全矩阵）

**Files:**
- Create: `tradingagents/agents/utils/scenario_check.py`
- Test: `tests/test_scenario_check.py`（新建）

- [ ] **Step 1: 写失败测试（全违例矩阵）**

```python
# tests/test_scenario_check.py
"""Full violation matrix for the scenario validator (spec §4.3).

照 CLAUDE.md 评级边界三轮返工的教训：枚举所有违例形状跑整张矩阵，
不是只测自己想到的一两个用例。
"""
import pytest

from tradingagents.agents.schemas import PortfolioDecision, PortfolioRating
from tradingagents.agents.utils.scenario_check import (
    fetch_p0,
    parse_horizon_months,
    validate_scenario_tree,
)
from tests.test_scenario_schemas import _bucket, _decision

P0 = 1500.0


def _anchored_bucket(horizon, rating_sign=-1):
    # stop=1365 → -9%; entry 1440-1500; target=1785 → +19%
    return _bucket(
        horizon,
        bull=1785 / P0 - 1, base=0.04, bear=1365 / P0 - 1,
        p_bull=0.25 if rating_sign < 0 else 0.35,
        p_base=0.50, p_bear=0.25 if rating_sign < 0 else 0.35,
        stop=1365.0, entry_low=1440.0, entry_high=1500.0, target=1785.0,
    )


@pytest.mark.unit
class TestParseHorizonMonths:
    @pytest.mark.parametrize("text,expected", [
        ("3-6 months", 6), ("6-12个月", 9), ("1-2 years", 18),
        ("3-6 Months", 6), ("", 6), (None, 6), ("garbage", 6),
    ])
    def test_parse(self, text, expected):
        assert parse_horizon_months(text) == expected


@pytest.mark.unit
class TestValidateScenarioTree:
    def _valid(self, rating=PortfolioRating.UNDERWEIGHT):
        d = _decision()
        d.rating = rating
        d.scenario_buckets = [_anchored_bucket(6), _anchored_bucket(12)]
        return d

    def test_valid_bearish(self):
        assert validate_scenario_tree(self._valid(), P0) == []

    def test_valid_bullish(self):
        d = self._valid(rating=PortfolioRating.OVERWEIGHT)
        d.scenario_buckets = [_anchored_bucket(6, 1), _anchored_bucket(12, 1)]
        assert validate_scenario_tree(d, P0) == []

    def test_empty_tree_reports_missing(self):
        assert validate_scenario_tree(_decision(with_tree=False), P0) == ["scenario tree missing"]

    def test_wrong_horizons(self):
        d = self._valid()
        d.scenario_buckets[1].horizon_months = 24
        assert any("horizons" in v for v in validate_scenario_tree(d, P0))

    def test_prob_sum_off(self):
        d = self._valid()
        d.scenario_buckets[0].scenarios[0].prob = 0.40  # sum 1.10
        assert any("sum" in v for v in validate_scenario_tree(d, P0))

    def test_base_prob_out_of_range(self):
        d = self._valid()
        s = d.scenario_buckets[0].scenarios
        s[0].prob, s[1].prob, s[2].prob = 0.30, 0.60, 0.10
        assert any("base prob" in v for v in validate_scenario_tree(d, P0))

    def test_not_monotonic(self):
        d = self._valid()
        d.scenario_buckets[0].scenarios[1].expected_return = -0.20  # base < bear
        assert any("bull > base > bear" in v for v in validate_scenario_tree(d, P0))

    def test_levels_order_violated(self):
        d = self._valid()
        d.scenario_buckets[0].key_levels.stop = 1600.0
        assert any("stop < entry" in v for v in validate_scenario_tree(d, P0))

    def test_bear_anchor_drift(self):
        d = self._valid()
        d.scenario_buckets[0].scenarios[2].expected_return = -0.30  # vs stop anchor -9%
        assert any("not anchored to stop" in v for v in validate_scenario_tree(d, P0))

    def test_bull_anchor_drift(self):
        d = self._valid()
        d.scenario_buckets[0].scenarios[0].expected_return = 0.50  # vs target anchor +19%
        assert any("not anchored to target" in v for v in validate_scenario_tree(d, P0))

    def test_anchor_skipped_when_p0_none(self):
        d = self._valid()
        d.scenario_buckets[0].scenarios[2].expected_return = -0.30
        vs = validate_scenario_tree(d, None)
        assert not any("anchored" in v for v in vs)

    def test_direction_contradiction_bearish_rating_positive_mu(self):
        d = self._valid()  # Underweight
        d.scenario_buckets[0].scenarios[0].expected_return = 0.60
        d.scenario_buckets[0].scenarios[0].prob = 0.40
        d.scenario_buckets[0].scenarios[2].prob = 0.10  # mu = .6*.4+.04*.5-.09*.1 = +27.1%
        assert any("contradicts rating" in v for v in validate_scenario_tree(d, None))

    def test_direction_contradiction_bullish_rating_negative_mu(self):
        d = self._valid(rating=PortfolioRating.OVERWEIGHT)
        for b in d.scenario_buckets:
            b.scenarios[0].expected_return = 0.02
            b.scenarios[1].expected_return = 0.01
            b.scenarios[2].expected_return = -0.30
        assert any("contradicts rating" in v for v in validate_scenario_tree(d, None))

    def test_probability_direction_rule(self):
        d = self._valid()  # Underweight, but anchored bucket gives bear==bull
        d.scenario_buckets[0].scenarios[0].prob = 0.45
        d.scenario_buckets[0].scenarios[2].prob = 0.05
        d.scenario_buckets[0].scenarios[1].prob = 0.50
        assert any("P(bear)" in v for v in validate_scenario_tree(d, None))


@pytest.mark.unit
class TestFetchP0:
    def test_returns_none_on_any_failure(self, monkeypatch):
        import tradingagents.agents.utils.scenario_check as sc
        monkeypatch.setattr(sc, "_sina_kline_fallback", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("net")))
        assert fetch_p0("600519", "2026-08-25") is None

    def test_picks_last_close_on_or_before_date(self, monkeypatch):
        import pandas as pd
        import tradingagents.agents.utils.scenario_check as sc
        df = pd.DataFrame({
            "Date": pd.to_datetime(["2026-08-24", "2026-08-25", "2026-08-26"]),
            "Close": [10.0, 11.0, 12.0],
        })
        monkeypatch.setattr(sc, "_sina_kline_fallback", lambda *a, **k: df)
        assert fetch_p0("600519", "2026-08-25") == 11.0
```

注意：`from tests.test_scenario_schemas import _bucket, _decision` 要求测试目录是包或 rootdir 可导入；若 pytest 报导入错误，把两个工厂函数复制到本文件顶部（保持两边一致），并在提交信息里注明。

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_scenario_check.py -v`
Expected: FAIL，ModuleNotFoundError: scenario_check

- [ ] **Step 3: 实现校验器**

```python
# tradingagents/agents/utils/scenario_check.py
"""Deterministic validation for the PM scenario tree (spec §4.2-4.3).

All arithmetic/anchoring/direction rules live here so the retry message can
name the exact violation. Structural typing is enforced by pydantic; anything
this module returns is a semantic violation list (empty == valid).
"""
from __future__ import annotations

import logging
import re
from typing import Optional

from tradingagents.agents.schemas import PortfolioDecision, PortfolioRating

logger = logging.getLogger(__name__)

REQUIRED_HORIZONS = (6, 12)
BASE_PROB_RANGE = (0.35, 0.55)
ANCHOR_TOL = 0.05
BEARISH_RATINGS = {
    PortfolioRating.HOLD, PortfolioRating.UNDERWEIGHT, PortfolioRating.SELL,
}

_HORIZON_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(month|month个?月|月|year|年)", re.IGNORECASE)


def parse_horizon_months(text: Optional[str]) -> int:
    """'3-6 months' → 6 (take the FIRST number); '1-2 years' → 12; default 6."""
    if not text:
        return 6
    m = _HORIZON_RE.search(str(text))
    if not m:
        return 6
    value = float(m.group(1))
    if m.group(2).lower().startswith(("y", "年")):
        value *= 12
    return max(1, int(value))


def _main_bucket(decision: PortfolioDecision, buckets):
    target = parse_horizon_months(decision.time_horizon)
    return min(buckets, key=lambda b: abs(b.horizon_months - target))


def validate_scenario_tree(decision: PortfolioDecision, p0: Optional[float]) -> list[str]:
    """Return a list of human-readable violations; empty list means valid.

    ``p0`` is the analysis-date close. When None, anchor checks are skipped
    (the artifact is later flagged ``unanchored``).
    """
    buckets = decision.scenario_buckets
    if not buckets:
        return ["scenario tree missing"]

    violations: list[str] = []
    horizons = sorted(b.horizon_months for b in buckets)
    if horizons != list(REQUIRED_HORIZONS):
        violations.append(
            f"expected exactly two buckets with horizons 6 and 12 months, got {horizons}"
        )

    bearish = decision.rating in BEARISH_RATINGS
    main = _main_bucket(decision, buckets)

    for b in buckets:
        tag = f"{b.horizon_months}M"
        names = sorted(s.name for s in b.scenarios)
        if names != ["base", "bear", "bull"]:
            violations.append(f"{tag}: scenarios must be exactly bull/base/bear, got {names}")
            continue
        s = {x.name: x for x in b.scenarios}

        total = sum(x.prob for x in b.scenarios)
        if not 0.99 <= total <= 1.01:
            violations.append(f"{tag}: probabilities sum to {total:.3f}, expected 1.0")
        if not BASE_PROB_RANGE[0] <= s["base"].prob <= BASE_PROB_RANGE[1]:
            violations.append(
                f"{tag}: base prob {s['base'].prob:.2f} outside [0.35, 0.55]"
            )
        if not s["bull"].expected_return > s["base"].expected_return > s["bear"].expected_return:
            violations.append(f"{tag}: returns must be strictly bull > base > bear")
        if bearish and s["bull"].prob > s["bear"].prob:
            violations.append(
                f"{tag}: rating {decision.rating.value} requires P(bear) ≥ P(bull)"
            )

        kl = b.key_levels
        if not kl.stop < kl.entry_low <= kl.entry_high < kl.target:
            violations.append(
                f"{tag}: key levels must satisfy stop < entry_low ≤ entry_high < target"
            )

        if p0 is not None:
            bear_anchor = kl.stop / p0 - 1
            bull_anchor = kl.target / p0 - 1
            if abs(s["bear"].expected_return - bear_anchor) > ANCHOR_TOL:
                violations.append(
                    f"{tag}: bear return {s['bear'].expected_return:+.1%} not anchored "
                    f"to stop ({bear_anchor:+.1%}, tol ±5pp)"
                )
            if abs(s["bull"].expected_return - bull_anchor) > ANCHOR_TOL:
                violations.append(
                    f"{tag}: bull return {s['bull'].expected_return:+.1%} not anchored "
                    f"to target ({bull_anchor:+.1%}, tol ±5pp)"
                )

        if b is main:
            mu = sum(x.prob * x.expected_return for x in b.scenarios)
            if bearish and mu > 0.02:
                violations.append(
                    f"main bucket ({tag}) mean return {mu:+.1%} contradicts rating "
                    f"{decision.rating.value} (≤ Hold expects μ ≤ +2%)"
                )
            if not bearish and mu <= 0:
                violations.append(
                    f"main bucket ({tag}) mean return {mu:+.1%} contradicts rating "
                    f"{decision.rating.value} (≥ Overweight expects μ > 0)"
                )
    return violations


def fetch_p0(ticker: str, trade_date: str) -> Optional[float]:
    """Analysis-date close for anchor checks; None on any failure → unanchored."""
    try:
        import pandas as pd

        from tradingagents.dataflows.a_stock import _sina_kline_fallback

        df = _sina_kline_fallback(ticker)
        if df is None or df.empty:
            return None
        ts = pd.to_datetime(trade_date)
        df = df[df["Date"] <= ts]
        if df.empty:
            return None
        return float(df.iloc[-1]["Close"])
    except Exception as exc:  # 数据拿不到不是错误路径：降级为 unanchored
        logger.info("fetch_p0 failed for %s@%s: %s", ticker, trade_date, exc)
        return None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_scenario_check.py -v`
Expected: 全部 passed（矩阵 ~15 例）

- [ ] **Step 5: 提交**

```bash
git add tradingagents/agents/utils/scenario_check.py tests/test_scenario_check.py
git commit -m "feat: deterministic scenario validator with full violation matrix (spec P1 §4.3)"
```

---

### Task 3: structured.py typed 变体 + PM 接线（校验→重问→降级→state）

**Files:**
- Modify: `tradingagents/agents/utils/structured.py`（追加 typed 变体）
- Modify: `tradingagents/agents/managers/portfolio_manager.py`
- Modify: `tradingagents/agents/utils/agent_states.py`（加 `scenario_tree` 键）
- Test: `tests/test_pm_scenario_wiring.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_pm_scenario_wiring.py
"""PM wiring: typed capture, validate → retry-once → degrade, state stash."""
from unittest.mock import MagicMock

import pytest

from tradingagents.agents.managers.portfolio_manager import create_portfolio_manager
from tradingagents.agents.schemas import PortfolioDecision, PortfolioRating
from tests.test_scenario_schemas import _decision


def _state():
    risk_state = {
        "history": "aggressive: risk priced in; conservative: ATR too high",
        "aggressive_history": "a", "conservative_history": "c", "neutral_history": "n",
        "latest_speaker": "Conservative",
        "current_aggressive_response": "", "current_conservative_response": "",
        "current_neutral_response": "", "count": 1, "judge_decision": "",
    }
    return {
        "company_of_interest": "600519",
        "trade_date": "2026-08-25",
        "investment_plan": "**Recommendation**: Hold",
        "trader_investment_plan": "**Action**: Hold",
        "risk_debate_state": risk_state,
        "past_context": "",
    }


def _llm(returning):
    llm = MagicMock()
    llm.invoke.return_value = returning
    return llm


@pytest.mark.unit
class TestPMScenarioWiring:
    def _run(self, structured_obj_sequence):
        calls = list(structured_obj_sequence)
        structured = MagicMock()
        structured.invoke.side_effect = calls
        pm = create_portfolio_manager.__wrapped__ if hasattr(create_portfolio_manager, "__wrapped__") else None
        node = None
        # bind_structured 是包内直连，直接构造 node：monkeypatch bind_structured
        import tradingagents.agents.managers.portfolio_manager as pmm
        original = pmm.bind_structured
        pmm.bind_structured = lambda llm, schema, name: structured
        try:
            node = pmm.create_portfolio_manager(_llm("free text fallback"))
        finally:
            pmm.bind_structured = original
        return node(_state()), structured

    def test_valid_tree_stashed_to_state(self, monkeypatch):
        import tradingagents.agents.utils.scenario_check as sc
        good = _decision()
        monkeypatch.setattr(sc, "validate_scenario_tree", lambda d, p0: [])
        monkeypatch.setattr(sc, "fetch_p0", lambda t, d: 1500.0)
        out, structured = self._run([good])
        assert out["scenario_tree"]["decision"]["rating"] == "Underweight"
        assert out["scenario_tree"]["scenario_meta"]["available"] is True
        assert structured.invoke.call_count == 1

    def test_violations_retry_once_then_accept(self, monkeypatch):
        import tradingagents.agents.utils.scenario_check as sc
        good = _decision()
        states = iter([[("bad")], []])
        monkeypatch.setattr(sc, "validate_scenario_tree", lambda d, p0: next(states))
        monkeypatch.setattr(sc, "fetch_p0", lambda t, d: None)
        out, structured = self._run([good, good])
        assert structured.invoke.call_count == 2  # 原始 + 重问一次
        assert out["scenario_tree"]["scenario_meta"]["available"] is True
        assert out["scenario_tree"]["scenario_meta"]["unanchored"] is True

    def test_retry_failure_degrades_tree(self, monkeypatch):
        import tradingagents.agents.utils.scenario_check as sc
        good = _decision()
        monkeypatch.setattr(sc, "validate_scenario_tree", lambda d, p0: ["always bad"])
        monkeypatch.setattr(sc, "fetch_p0", lambda t, d: 1500.0)
        out, structured = self._run([good, good])
        assert structured.invoke.call_count == 2
        assert out["scenario_tree"]["decision"]["scenario_buckets"] == []  # 树被剥离
        assert out["scenario_tree"]["scenario_meta"]["available"] is False
        assert "always bad" in out["scenario_tree"]["scenario_meta"]["degraded"][0] \
            or out["scenario_tree"]["scenario_meta"]["degraded"] == ["always bad"]

    def test_freetext_fallback_stashes_none(self, monkeypatch):
        import tradingagents.agents.managers.portfolio_manager as pmm
        original = pmm.bind_structured
        pmm.bind_structured = lambda llm, schema, name: None  # provider 不支持
        try:
            node = pmm.create_portfolio_manager(_llm("free text"))
        finally:
            pmm.bind_structured = original
        out = node(_state())
        assert out["final_trade_decision"] == "free text"
        assert out["scenario_tree"] is None
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_pm_scenario_wiring.py -v`
Expected: FAIL — PM 返回的 dict 没有 `scenario_tree` 键

- [ ] **Step 3: structured.py 追加 typed 变体**（文件末尾）

```python
def invoke_structured_or_freetext_typed(
    structured_llm: Optional[Any],
    plain_llm: Any,
    prompt: Any,
    render: Callable[[T], str],
    agent_name: str,
) -> tuple[str, Optional[T]]:
    """Like :func:`invoke_structured_or_freetext` but also returns the typed object.

    Returns ``(markdown, obj)`` when the structured call succeeded and
    ``(markdown, None)`` when it fell back to free text.
    """
    if structured_llm is not None:
        try:
            result = structured_llm.invoke(prompt)
            return render(result), result
        except Exception as exc:
            logger.warning(
                "%s: structured-output invocation failed (%s); retrying once as free text",
                agent_name, exc,
            )
    response = plain_llm.invoke(prompt)
    return response.content, None
```

- [ ] **Step 4: agent_states.py 加键**（`final_trade_decision` 之后）

```python
    scenario_tree: Annotated[
        object, "Typed PM decision (model_dump) + scenario_meta; None on free-text fallback or degraded run"
    ]
```

- [ ] **Step 5: PM 接线**。`portfolio_manager.py`：

import 区加：

```python
from tradingagents.agents.utils.scenario_check import (
    fetch_p0,
    validate_scenario_tree,
)
from tradingagents.agents.utils.structured import (
    bind_structured,
    invoke_structured_or_freetext_typed,
)
```

`_NO_LEVELS_RULE`（26-29 行）整体替换为：

```python
# Fork decision (2026-08-29): executable levels ARE shipped, but only inside
# the structured scenario fields — prose sections stay level-free so the
# memory log and report readers keep their current shape.
_LEVELS_RULE = (
    "\n- State entry/stop/target levels ONLY inside the structured scenario "
    "fields; keep the prose summary and thesis free of specific levels."
)
```

prompt 末尾 `{_NO_LEVELS_RULE}` 改为 `{_LEVELS_RULE}`。

`final_trade_decision = invoke_structured_or_freetext(...)` 一段替换为：

```python
        markdown, decision = invoke_structured_or_freetext_typed(
            structured_llm,
            llm,
            prompt,
            render_pm_decision,
            "Portfolio Manager",
        )

        scenario_meta = {"available": False}
        if decision is not None and decision.scenario_buckets:
            p0 = fetch_p0(state["company_of_interest"], state["trade_date"])
            violations = validate_scenario_tree(decision, p0)
            if violations:
                retry_prompt = (
                    prompt
                    + "\n\n---\nYour structured scenario tree violated these rules; "
                    "fix them and answer again:\n"
                    + "\n".join(f"- {v}" for v in violations)
                )
                try:
                    decision = structured_llm.invoke(retry_prompt)
                    markdown = render_pm_decision(decision)
                    violations = validate_scenario_tree(decision, p0)
                except Exception:
                    violations = ["structured retry invocation failed"]
            if violations:
                logger.warning(
                    "Portfolio Manager: scenario tree degraded after retry: %s",
                    violations,
                )
                decision.scenario_buckets = []
                decision.falsification = None
                markdown = render_pm_decision(decision)
                scenario_meta["degraded"] = violations
            else:
                scenario_meta["available"] = True
                if p0 is None:
                    scenario_meta["unanchored"] = True

        scenario_tree = None
        if decision is not None:
            scenario_tree = {
                "decision": decision.model_dump(mode="json"),
                "scenario_meta": scenario_meta,
            }
```

（文件顶部需加 `import logging` + `logger = logging.getLogger(__name__)`，若尚无。）

返回 dict 改为：

```python
        return {
            "risk_debate_state": new_risk_debate_state,
            "final_trade_decision": markdown,
            "scenario_tree": scenario_tree,
        }
```

- [ ] **Step 6: 跑测试确认通过**

Run: `pytest tests/test_pm_scenario_wiring.py tests/test_structured_agents.py tests/test_memory_log.py -v`
Expected: 全部 passed。若 test_memory_log 对 PM 输出形状有断言（grep "Do NOT state entry" tests/），同步更新断言。

- [ ] **Step 7: 提交**

```bash
git add tradingagents/agents/utils/structured.py tradingagents/agents/managers/portfolio_manager.py tradingagents/agents/utils/agent_states.py tests/test_pm_scenario_wiring.py
git commit -m "feat: PM emits validated scenario tree with retry-once degrade path (spec P1)"
```

---

### Task 4: 落盘与归档（_log_state + finalize_graph_run）

**Files:**
- Modify: `tradingagents/graph/trading_graph.py`（`_log_state` 归档 + `finalize_graph_run` 写制品 + `_write_scenario_artifact` 新方法 + curated dict 加 `scenario_tree`）
- Test: `tests/test_finalize_scenario.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_finalize_scenario.py
"""Artifact persistence: scenario.json write + archive-on-rerun (spec §4.4/§7)."""
import json
from pathlib import Path

import pytest

from tests.test_scenario_schemas import _decision


def _graph(tmp_path):
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    config = dict(TradingAgentsGraph.DEFAULT_CONFIG) if hasattr(TradingAgentsGraph, "DEFAULT_CONFIG") else None
    # 直接构造轻量实例：绕过 LLM 初始化，只测持久化方法
    g = object.__new__(TradingAgentsGraph)
    g.config = {"results_dir": str(tmp_path), "data_cache_dir": str(tmp_path / "cache")}
    g.ticker = "600519"
    g.memory_log = None  # 由测试里 stub
    return g


def _final_state(with_tree=True):
    decision = _decision()
    st = {
        "trade_date": "2026-08-25",
        "final_trade_decision": "ignored",
        "scenario_tree": ({
            "decision": decision.model_dump(mode="json"),
            "scenario_meta": {"available": True},
        } if with_tree else None),
    }
    return st


class _MemoryStub:
    def __init__(self):
        self.calls = []
    def store_decision(self, **kw):
        self.calls.append(kw)


@pytest.mark.unit
class TestFinalizePersistence:
    def test_writes_scenario_artifact(self, tmp_path, monkeypatch):
        g = _graph(tmp_path)
        g.memory_log = _MemoryStub()
        monkeypatch.setattr(g, "process_signal", lambda s: "Sell")
        g.finalize_graph_run("600519", "2026-08-25", _final_state())
        art = tmp_path / "600519" / "TradingAgentsStrategy_logs" / "scenario_600519_2026-08-25.json"
        assert art.exists()
        payload = json.loads(art.read_text())
        assert payload["version"] == 1
        assert payload["ticker"] == "600519"
        assert payload["rating"] == "Underweight"
        assert len(payload["scenario_buckets"]) == 2

    def test_no_tree_no_artifact(self, tmp_path, monkeypatch):
        g = _graph(tmp_path)
        g.memory_log = _MemoryStub()
        monkeypatch.setattr(g, "process_signal", lambda s: "Sell")
        g.finalize_graph_run("600519", "2026-08-25", _final_state(with_tree=False))
        art_dir = tmp_path / "600519" / "TradingAgentsStrategy_logs"
        assert not list(art_dir.glob("scenario_*.json")) or not any(
            p.name.startswith("scenario_") and "archived" not in p.name for p in art_dir.glob("scenario_*.json")
        )

    def test_rerun_archives_old_log_and_artifact(self, tmp_path, monkeypatch):
        g = _graph(tmp_path)
        g.memory_log = _MemoryStub()
        monkeypatch.setattr(g, "process_signal", lambda s: "Sell")
        g.finalize_graph_run("600519", "2026-08-25", _final_state())
        g.finalize_graph_run("600519", "2026-08-25", _final_state())
        log_dir = tmp_path / "600519" / "TradingAgentsStrategy_logs"
        assert len(list(log_dir.glob("full_states_log_2026-08-25.archived-*.json"))) == 1
        assert len(list(log_dir.glob("scenario_600519_2026-08-25.archived-*.json"))) == 1
        # 当前制品仍是无后缀名
        assert (log_dir / "full_states_log_2026-08-25.json").exists()
        assert (log_dir / "scenario_600519_2026-08-25.json").exists()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_finalize_scenario.py -v`
Expected: FAIL（`scenario_...json` 不存在）

- [ ] **Step 3: 实现**。`trading_graph.py`：

`_log_state` 中 `log_path = ...` 与 `with open(log_path, "w"...)` 之间插入归档：

```python
        log_path = directory / f"full_states_log_{trade_date}.json"
        if log_path.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            log_path.rename(
                log_path.with_name(f"full_states_log_{trade_date}.archived-{stamp}.json")
            )
        with open(log_path, "w", encoding="utf-8") as f:
```

（确认文件顶部已有 `from datetime import datetime`；若无则补。）

`_log_state` 组装的 curated dict 里 `"final_trade_decision": final_state["final_trade_decision"],` 之后加一行：

```python
            "scenario_tree": final_state.get("scenario_tree"),
```

`finalize_graph_run` 中 `self._log_state(trade_date, final_state)` 之后、`self.memory_log.store_decision(...)` 之前插入：

```python
        # Reusable advisory artifact (spec §4.4).
        self._write_scenario_artifact(company_name, trade_date, final_state)
```

类中新增方法（放在 `_log_state` 之后）：

```python
    def _write_scenario_artifact(self, company_name, trade_date, final_state):
        """Write the machine-readable scenario artifact; archive any prior copy."""
        tree = final_state.get("scenario_tree")
        if not tree or not tree.get("decision", {}).get("scenario_buckets"):
            return
        safe_ticker = safe_ticker_component(company_name)
        directory = (
            Path(self.config["results_dir"]) / safe_ticker / "TradingAgentsStrategy_logs"
        )
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"scenario_{safe_ticker}_{trade_date}.json"
        if path.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            path.rename(
                path.with_name(
                    f"scenario_{safe_ticker}_{trade_date}.archived-{stamp}.json"
                )
            )
        payload = {
            "version": 1,
            "ticker": safe_ticker,
            "trade_date": str(trade_date),
            "rating": tree["decision"]["rating"],
            "scenario_buckets": tree["decision"]["scenario_buckets"],
            "falsification": tree["decision"].get("falsification"),
            "scenario_meta": tree.get("scenario_meta", {}),
            "generated_at": datetime.now().isoformat(timespec="seconds"),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
```

（确认 `Path`、`json`、`safe_ticker_component` 均已在文件 imports 中——`_log_state` 已在用，直接复用。）

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_finalize_scenario.py -v`
Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add tradingagents/graph/trading_graph.py tests/test_finalize_scenario.py
git commit -m "feat: persist scenario artifact with archive-on-rerun (spec P1 §4.4)"
```

---

### Task 5: CLI — finalize 对齐 + 同日守卫 + --force

**Files:**
- Modify: `cli/main.py`（`run_analysis` 签名加 `force`；守卫块；`process_signal` 调用改 `finalize_graph_run`；`analyze` 子命令与裸跑 callback 加 `--force`）
- Test: `tests/test_cli_force_flag.py`（新建）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_cli_force_flag.py
"""--force flag plumbing and the same-day artifact detector (spec §7)."""
from pathlib import Path

from typer.testing import CliRunner

from cli.main import app, existing_artifacts

runner = CliRunner()


def test_force_flag_exposed_on_analyze():
    result = runner.invoke(app, ["analyze", "--help"])
    assert result.exit_code == 0
    assert "--force" in result.output


def test_existing_artifacts_detects_log_and_scenario(tmp_path):
    log_dir = tmp_path / "600519" / "TradingAgentsStrategy_logs"
    log_dir.mkdir(parents=True)
    (log_dir / "full_states_log_2026-08-25.json").touch()
    found = existing_artifacts(str(tmp_path), "600519", "2026-08-25")
    assert any("full_states_log" in p.name for p in found)
    (log_dir / "scenario_600519_2026-08-25.json").touch()
    found = existing_artifacts(str(tmp_path), "600519", "2026-08-25")
    assert len(found) == 2


def test_existing_artifacts_empty_when_none(tmp_path):
    assert existing_artifacts(str(tmp_path), "600519", "2026-08-25") == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_cli_force_flag.py -v`
Expected: FAIL，ImportError: existing_artifacts

- [ ] **Step 3: 实现**。`cli/main.py`：

在 `run_analysis` 附近加纯函数（供守卫与测试共用）：

```python
def existing_artifacts(results_dir: str, ticker: str, analysis_date: str) -> list[Path]:
    """Full-state log / scenario artifact already present for (ticker, date)?"""
    log_dir = Path(results_dir) / ticker / "TradingAgentsStrategy_logs"
    if not log_dir.exists():
        return []
    names = (
        f"full_states_log_{analysis_date}.json",
        f"scenario_{ticker}_{analysis_date}.json",
    )
    return [log_dir / n for n in names if (log_dir / n).exists()]
```

`run_analysis` 签名改为（保持既有参数）：

```python
def run_analysis(checkpoint: bool = False, clear_checkpoints: bool = False, force: bool = False):
```

`results_dir = ...` 创建块**之前**（selections 已就绪、config 已配置处）插入守卫：

```python
    # Same-day guard (spec §7): reuse or consciously rerun; rerun archives old artifacts.
    if not force:
        artifacts = existing_artifacts(
            config["results_dir"], selections["ticker"], selections["analysis_date"]
        )
        if artifacts:
            names = ", ".join(p.name for p in artifacts)
            rerun = typer.confirm(
                f"{selections['ticker']} 在 {selections['analysis_date']} 已有研报制品（{names}）。"
                "重跑将归档旧制品，仍要继续吗？",
                default=False,
            )
            if not rerun:
                console.print(
                    "[yellow]已取消。可直接使用现有研报，或加 --force 跳过此确认重跑。[/yellow]"
                )
                return
```

约 1206 行 `decision = graph.process_signal(final_state["final_trade_decision"])` 替换为：

```python
        # Align with web/runner.py: persist state log + memory + scenario artifact.
        decision = graph.finalize_graph_run(
            selections["ticker"], selections["analysis_date"], final_state
        )
```

裸跑 callback 与 `analyze` 子命令加参数并透传：

```python
@app.callback(invoke_without_command=True)
def main(
    checkpoint: bool = typer.Option(False, "--checkpoint", ...),  # 原有
    clear_checkpoints: bool = typer.Option(False, "--clear-checkpoints", ...),  # 原有
    force: bool = typer.Option(False, "--force", help="跳过同日研报守卫，重跑并归档旧制品。"),
):
    if ctx.invoked_subcommand is not None:
        return
    analyze(checkpoint=checkpoint, clear_checkpoints=clear_checkpoints, force=force)


@app.command()
def analyze(
    checkpoint: bool = typer.Option(False, "--checkpoint", ...),  # 原有
    clear_checkpoints: bool = typer.Option(False, "--clear-checkpoints", ...),  # 原有
    force: bool = typer.Option(False, "--force", help="跳过同日研报守卫，重跑并归档旧制品。"),
):
    if clear_checkpoints:
        ...  # 原有
    run_analysis(checkpoint=checkpoint, clear_checkpoints=clear_checkpoints, force=force)
```

⚠️ **保住裸跑**：改完立即跑 `pytest tests/test_cli_default_command.py -v`，必须 passed（v0.5.9 教训）。

- [ ] **Step 4: 跑测试确认通过**

Run: `pytest tests/test_cli_force_flag.py tests/test_cli_default_command.py -v`
Expected: 全部 passed

- [ ] **Step 5: 提交**

```bash
git add cli/main.py tests/test_cli_force_flag.py
git commit -m "feat: CLI same-day artifact guard with --force; align CLI persistence with finalize_graph_run"
```

---

### Task 6: 全量回归 + 收尾

- [ ] **Step 1: 全量测试**

Run: `pytest tests/ -q`
Expected: 之前基线 361 passed / 13 skipped / 0 failed + 本计划新增 ~30 例全部 passed，0 failed

- [ ] **Step 2: 残留引用扫描**

Run: `grep -rn "NO_LEVELS" tradingagents/ cli/ web/ tests/` 
Expected: 无输出（`_NO_LEVELS_RULE` 已全部替换为 `_LEVELS_RULE`）

- [ ] **Step 3: 人工冒烟（可选但推荐）**

```bash
.venv/bin/streamlit run web/app.py   # 或 CLI 裸跑一次 mock 之外的真实分析
```
确认：报告 markdown 出现 `**Scenario Tree**:` 与 `**Falsification**:` 段；`~/.tradingagents/logs/<ticker>/TradingAgentsStrategy_logs/` 下出现 `scenario_<ticker>_<date>.json`；再次跑同票同日触发守卫提示；`--force` 后旧制品带 `.archived-` 后缀。

- [ ] **Step 4: 提交（如有收尾改动）**

```bash
git add -A ':!diagrams'
git commit -m "chore: scenario tree P1 regression pass"
```

---

## Self-Review 记录

- **Spec 覆盖**：§4.1 schema→Task 1；§4.2 三道绳→Task 1 字段描述 + Task 2 校验；§4.3 校验/重问/降级→Task 2+3；§4.4 落盘/记忆不动→Task 4；§7 同日守卫/--force 归档→Task 4+5；截断告警接入：PM 走既有 `invoke_structured_or_freetext` 家族，Anthropic/OpenAI/Gemini/Responses 四形状已由现有 warn_if_truncated 链路覆盖（结构化失败会走 fallback，不会静默）。**P1 未含**（属 P2/P3）：advisor 引擎、问卷、advise/review 命令、MCP 面。
- **占位符**：无 TBD/TODO；`...` 仅出现在"保持原有"的既有参数示意处，任务内均给出了完整新增代码。
- **类型一致性**：`expected_return`（小数）全计划统一；state 键 `scenario_tree`（dict/None）在 Task 3 产出、Task 4 消费；`scenario_meta.available/unanchored/degraded` 三个键名两任务一致；`existing_artifacts` 定义于 Task 5 并被其测试引用。
- **已知风险**：CLI 补 `finalize_graph_run` 后，CLI 运行会开始写 full_states_log + 记忆 pending 条件（与 web 行为对齐，是修复而非破坏）；`test_memory_log.py` 若断言 PM prompt 原文需同步（Task 3 Step 6 已列检查）。
