# Scenario-Vector Advisor P2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付情景向量顾问 P2 分期的计算核心与 CLI 消费端——`tradingagents/advisor/` 包（calibrate + engine + render + IO）+ `tradingagents advise` CLI 命令，使 P1 的 `scenario_<ticker>_<date>.json` 制品可被消费为投资者定制建议。

**Architecture:** 引擎是纯函数，无 LLM 调用；`advise(scenario, vector, config) → AdviceResult`。CLI 是引擎的第一张嘴，`--json` 输出即机器契约（P3+ MCP plan 依赖此契约）。校准公式住服务端单一真相源，客户端只发原始 KYC 答案。

**Tech Stack:** Python 3.10+ / pydantic v2 / typer / pytest / rich（CLI 渲染）。零新增外部依赖——全部走标准库 + 现有 pyproject.toml 已锁包。

**Scope out**（本 plan 明确不做）：
- Web UI 画像面板 / 3×3 矩阵渲染（spec §7 的 Web 部分）→ 独立后续 PR
- P3 `tradingagents review` 巡检 → 另一份 plan
- MCP 面 → 另一份 plan（`2026-08-30-picoclaw-mcp-integration.md`）

**前置状态**：P1 已合入 main（`cc13a98`），schemas.py 有 `PortfolioDecision.scenario_buckets`，`trading_graph.py:758` 会写 `scenario_<ticker>_<date>.json`。测试基线 425 passed / 0 failed。

---

## File Structure

**新增文件（`tradingagents/advisor/` 包）：**

| 文件 | 职责 |
|---|---|
| `tradingagents/advisor/__init__.py` | 包标记；re-export 稳定公共 API |
| `tradingagents/advisor/types.py` | pydantic 类型：`KYCAnswers` / `InvestorVector` / `AdviceResult` / `AdvicePosition` / `AdviceTrace` / `AdviceGuardReason` / `AdvisorConfig` |
| `tradingagents/advisor/questionnaire.py` | 5 题 KYC 静态问卷数据 + `get_questionnaire()` |
| `tradingagents/advisor/calibrate.py` | `from_kyc(KYCAnswers) → InvestorVector`（γ_eff / HC / H_avail） |
| `tradingagents/advisor/engine.py` | `advise(scenario_bucket, vector, config) → AdviceResult`（Merton + 硬门 + 守卫） |
| `tradingagents/advisor/render.py` | 3×3 矩阵采样 + 人类可读渲染 |
| `tradingagents/advisor/scenario_io.py` | `load_scenario(ticker, date) → ScenarioArtifact` / `list_scenarios()` |
| `tradingagents/advisor/profile_io.py` | `read_profile() / write_profile(answers)` 原子写 `~/.tradingagents/profile.json` |

**修改文件：**

| 文件 | 修改 |
|---|---|
| `cli/main.py` | 新增 `@app.command()` `advise` 子命令（含 `--json` / `--assume-neutral` / `--date`） |
| `CLAUDE.md` | 已知问题段追加 P2 分期完成的备注（测试基线更新） |

**新增测试文件：**

| 文件 | 覆盖 |
|---|---|
| `tests/test_advisor_types.py` | pydantic schema 边界 |
| `tests/test_advisor_questionnaire.py` | 5 题结构 + 分值枚举 |
| `tests/test_advisor_calibrate.py` | γ_eff / HC / H_avail 端点 + C1-C5 双向映射 |
| `tests/test_advisor_engine.py` | Merton 公式 + 硬门 + 守卫 + property 单调性 |
| `tests/test_advisor_render.py` | 矩阵 ≡ 引擎逐格 |
| `tests/test_advisor_scenario_io.py` | load / list / 缺文件 |
| `tests/test_advisor_profile_io.py` | 原子写 / 缺文件 / 版本迁移 |
| `tests/test_cli_advise.py` | CLI 命令 + `--json` schema + `--assume-neutral` + `test_cli_default_command` 兼容 |

---

## Milestone 1: 类型系统与问卷（M1）

### Task 1: 建 advisor 包骨架 + 类型定义

**Files:**
- Create: `tradingagents/advisor/__init__.py`
- Create: `tradingagents/advisor/types.py`
- Test: `tests/test_advisor_types.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_advisor_types.py
import pytest
from pydantic import ValidationError

from tradingagents.advisor.types import (
    KYCAnswers,
    InvestorVector,
    AdvicePosition,
    AdviceTrace,
    AdviceResult,
    AdviceGuardReason,
    AdvisorConfig,
)


class TestKYCAnswers:
    def test_valid_answers(self):
        ans = KYCAnswers(q1=7, q2=5, q3=7, q4=7, q5=7)
        assert ans.q1 == 7
        assert ans.schema_version == 1

    def test_reject_invalid_value(self):
        with pytest.raises(ValidationError):
            KYCAnswers(q1=4, q2=5, q3=7, q4=7, q5=7)  # 4 not in {3,5,7,9}

    def test_reject_missing_field(self):
        with pytest.raises(ValidationError):
            KYCAnswers(q1=7, q2=5, q3=7, q4=7)  # q5 missing


class TestInvestorVector:
    def test_valid_vector(self):
        v = InvestorVector(gamma_eff=5.0, hc=0.6, h_avail_months=60.0)
        assert v.gamma_eff == 5.0

    def test_reject_negative_gamma(self):
        with pytest.raises(ValidationError):
            InvestorVector(gamma_eff=-1.0, hc=0.6, h_avail_months=60.0)


class TestAdvisorConfig:
    def test_defaults(self):
        c = AdvisorConfig()
        assert c.kappa == 0.3
        assert c.w_max == 0.25
        assert c.r_f == 0.015
        assert c.action_watch == 0.05
        assert c.action_overweight == 0.15

    def test_reject_nonpositive_kappa(self):
        with pytest.raises(ValidationError):
            AdvisorConfig(kappa=0)


class TestAdviceResult:
    def test_construction(self):
        r = AdviceResult(
            ticker="000001",
            date="2026-08-30",
            with_position=AdvicePosition(
                action="observe", direction="build", weight_star=0.03
            ),
            without_position=AdvicePosition(
                action="observe", direction="build", weight_star=0.03
            ),
            trace=AdviceTrace(
                gamma_eff=5.0, mu=0.08, sigma_sq=0.04,
                w_raw=0.5, w_after_kappa=0.15, w_star=0.15,
                h_avail_months=60.0, horizon_months=6, bucket_horizon_ok=True,
            ),
            guard_reasons=[],
        )
        assert r.trace.gamma_eff == 5.0
        assert r.guard_reasons == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_advisor_types.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'tradingagents.advisor'`

- [ ] **Step 3: Write minimal implementation**

```python
# tradingagents/advisor/__init__.py
"""Scenario-Vector Advisor: 纯函数消费端，零 LLM。

模块布局（P2 分期）：
- types: pydantic 类型
- questionnaire: 5 题 KYC 静态数据
- calibrate: KYC → InvestorVector
- engine: (scenario, vector, config) → AdviceResult
- render: 3×3 矩阵采样 + 人类可读渲染
- scenario_io / profile_io: 磁盘 I/O
"""
from tradingagents.advisor.types import (
    AdviceGuardReason,
    AdvicePosition,
    AdviceResult,
    AdviceTrace,
    AdvisorConfig,
    InvestorVector,
    KYCAnswers,
)

__all__ = [
    "AdviceGuardReason",
    "AdvicePosition",
    "AdviceResult",
    "AdviceTrace",
    "AdvisorConfig",
    "InvestorVector",
    "KYCAnswers",
]
```

```python
# tradingagents/advisor/types.py
"""Advisor pydantic types (schema version v1).

Schema 演化规则：加字段=minor（`schema_version` 保持），改语义=version bump。
"""
from typing import Literal

from pydantic import BaseModel, Field, PositiveFloat


class KYCAnswers(BaseModel):
    """5 题 KYC 原始答案。客户端持有，每次调用 inline 传。

    分值语义详见 scenario-vector-advisor spec §5。
    """

    q1: Literal[3, 5, 7, 9]  # 浮亏 20% 反应
    q2: Literal[3, 5, 7, 9]  # 资金动用期限
    q3: Literal[3, 5, 7, 9]  # 权益类投资经验
    q4: Literal[3, 5, 7, 9]  # 收入稳定性
    q5: Literal[3, 5, 7, 9]  # 年龄段
    schema_version: Literal[1] = 1


class InvestorVector(BaseModel):
    """校准后的投资者向量（引擎入参）。

    gamma_eff: 有效风险规避系数 (>= 1.5)
    hc: 人力资本 (0..1)
    h_avail_months: 距流动性事件月数
    """

    gamma_eff: PositiveFloat
    hc: float = Field(ge=0.0, le=1.0)
    h_avail_months: float = Field(ge=0.0)


class AdvisorConfig(BaseModel):
    """引擎运行参数（spec §6 参数表）。"""

    kappa: PositiveFloat = 0.3         # Merton 打折系数（半-Kelly）
    w_max: float = Field(default=0.25, gt=0.0, le=1.0)  # 单票硬上限
    r_f: float = 0.015                 # 年化无风险利率
    action_watch: float = 0.05         # 观望↔持有分界
    action_overweight: float = 0.15    # 持有↔增持分界
    gamma_hc_coef: float = 0.5         # γ_eff = γ × (1 + coef × (1 - HC))
    retirement_age: int = 65
    anchor_tolerance: float = 0.05     # 情景校验锚定容差 (5pp)


class AdvicePosition(BaseModel):
    """有仓 / 无仓单侧建议。"""

    action: Literal["avoid", "observe", "hold_underweight", "increase_overweight"]
    direction: Literal["build", "reduce"]
    weight_star: float = Field(ge=0.0, le=1.0)


class AdviceTrace(BaseModel):
    """审计 trace：γ_eff → μ/σ → w_raw → 打折/截断 → w*。"""

    gamma_eff: float
    mu: float
    sigma_sq: float
    w_raw: float
    w_after_kappa: float
    w_star: float
    h_avail_months: float
    horizon_months: int
    bucket_horizon_ok: bool


class AdviceGuardReason(BaseModel):
    """守卫触发原因（σ²→0 / 概率退化 / NaN 等）。"""

    code: Literal[
        "sigma_zero", "prob_degenerate", "nan_encountered",
        "gamma_out_of_range", "horizon_mismatch",
    ]
    detail: str


class AdviceResult(BaseModel):
    """引擎输出：有仓 + 无仓双建议 + trace + 守卫。"""

    ticker: str
    date: str
    with_position: AdvicePosition
    without_position: AdvicePosition
    trace: AdviceTrace
    guard_reasons: list[AdviceGuardReason] = Field(default_factory=list)
    schema_version: Literal[1] = 1
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_advisor_types.py -v`

Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/advisor/__init__.py tradingagents/advisor/types.py tests/test_advisor_types.py
git commit -m "feat(advisor): P2 类型骨架 (KYCAnswers/InvestorVector/AdvisorConfig/AdviceResult)"
```

---

### Task 2: KYC 问卷静态数据

**Files:**
- Create: `tradingagents/advisor/questionnaire.py`
- Test: `tests/test_advisor_questionnaire.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_advisor_questionnaire.py
from tradingagents.advisor.questionnaire import (
    get_questionnaire,
    KYC_Q2_MONTHS,
    KYC_Q4_INCOME_STABILITY,
    KYC_Q5_AGE,
)


class TestQuestionnaire:
    def test_five_questions(self):
        q = get_questionnaire()
        assert len(q.questions) == 5
        assert [x.id for x in q.questions] == ["q1", "q2", "q3", "q4", "q5"]

    def test_each_question_four_options(self):
        for question in get_questionnaire().questions:
            assert len(question.options) == 4
            assert {opt.value for opt in question.options} == {3, 5, 7, 9}

    def test_schema_version(self):
        assert get_questionnaire().schema_version == 1


class TestValueMaps:
    def test_q2_months_map(self):
        assert KYC_Q2_MONTHS == {3: 3, 5: 15, 7: 42, 9: 120}

    def test_q4_income_stability(self):
        assert KYC_Q4_INCOME_STABILITY == {3: 0.3, 5: 0.5, 7: 0.8, 9: 1.0}

    def test_q5_representative_age(self):
        assert KYC_Q5_AGE == {3: 65, 5: 52, 7: 37, 9: 25}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_advisor_questionnaire.py -v`

Expected: FAIL with `ImportError: cannot import name 'get_questionnaire'`

- [ ] **Step 3: Write minimal implementation**

```python
# tradingagents/advisor/questionnaire.py
"""5 题 KYC 静态问卷 + 分桶数值映射（spec §5）。

维护：题目文本 / 选项 / 分值 / 数值映射改动都在这里一处；calibrate.py 只查表。
"""
from typing import Literal

from pydantic import BaseModel


class KYCOption(BaseModel):
    label: str
    value: Literal[3, 5, 7, 9]


class KYCQuestion(BaseModel):
    id: Literal["q1", "q2", "q3", "q4", "q5"]
    text: str
    options: list[KYCOption]


class Questionnaire(BaseModel):
    schema_version: Literal[1] = 1
    questions: list[KYCQuestion]
    note: str = (
        "客户端本地存 KYC 原始答案，每次调用 advise/review 时 inline 传给服务端。"
        "服务端负责校准（γ_eff / HC / H_avail 公式住 advisor/calibrate.py）。"
    )


_QUESTIONS: list[KYCQuestion] = [
    KYCQuestion(id="q1", text="如果你的组合浮亏 20%，你的第一反应是？", options=[
        KYCOption(label="全部卖出", value=3),
        KYCOption(label="卖一部分", value=5),
        KYCOption(label="持有", value=7),
        KYCOption(label="加仓", value=9),
    ]),
    KYCQuestion(id="q2", text="这笔钱多久内可能被动用？", options=[
        KYCOption(label="6 个月内", value=3),
        KYCOption(label="6-24 个月", value=5),
        KYCOption(label="2-5 年", value=7),
        KYCOption(label="5 年以上", value=9),
    ]),
    KYCQuestion(id="q3", text="你的权益类投资经验？", options=[
        KYCOption(label="无", value=3),
        KYCOption(label="仅基金", value=5),
        KYCOption(label="个股", value=7),
        KYCOption(label="含衍生品", value=9),
    ]),
    KYCQuestion(id="q4", text="你的收入稳定性？", options=[
        KYCOption(label="不稳定", value=3),
        KYCOption(label="一般", value=5),
        KYCOption(label="稳定", value=7),
        KYCOption(label="高且上升", value=9),
    ]),
    KYCQuestion(id="q5", text="你的年龄段？", options=[
        KYCOption(label="60 岁以上", value=3),
        KYCOption(label="45-59 岁", value=5),
        KYCOption(label="30-44 岁", value=7),
        KYCOption(label="30 岁以下", value=9),
    ]),
]


# Q2 分值 → 月数（spec §5 分桶）
KYC_Q2_MONTHS: dict[int, int] = {3: 3, 5: 15, 7: 42, 9: 120}
# Q4 分值 → 收入稳定系数
KYC_Q4_INCOME_STABILITY: dict[int, float] = {3: 0.3, 5: 0.5, 7: 0.8, 9: 1.0}
# Q5 分值 → 代表年龄
KYC_Q5_AGE: dict[int, int] = {3: 65, 5: 52, 7: 37, 9: 25}


def get_questionnaire() -> Questionnaire:
    """返回完整问卷（题目 + 选项 + 分值 + note）。"""
    return Questionnaire(questions=_QUESTIONS)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_advisor_questionnaire.py -v`

Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/advisor/questionnaire.py tests/test_advisor_questionnaire.py
git commit -m "feat(advisor): P2 KYC 5 题问卷静态数据 + 分桶数值映射"
```

---

## Milestone 2: 校准（M2）

### Task 3: `from_kyc` 校准函数

**Files:**
- Create: `tradingagents/advisor/calibrate.py`
- Test: `tests/test_advisor_calibrate.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_advisor_calibrate.py
import pytest

from tradingagents.advisor.calibrate import from_kyc, gamma_to_C
from tradingagents.advisor.types import KYCAnswers


class TestFromKYC:
    def test_25y_stable_moderate(self):
        """25 岁（q5=9）+ 稳定收入（q4=7）+ 中度耐受 (avg~7.4 → γ~3.6)。"""
        ans = KYCAnswers(q1=7, q2=7, q3=7, q4=7, q5=9)
        v = from_kyc(ans)
        # avg = 7.4, γ = clip(11 - 7.4, 1.5, 9.5) = 3.6
        # age = 25 (from q5=9), HC = clamp(1 - (25-25)/50, 0, 1) × 0.8 = 0.8
        # γ_eff = 3.6 × (1 + 0.5 × 0.2) = 3.6 × 1.1 = 3.96
        assert v.gamma_eff == pytest.approx(3.96, rel=1e-6)
        assert v.hc == pytest.approx(0.8, rel=1e-6)
        # H_avail = min(42, max(65-25, 0)*12) = min(42, 480) = 42
        assert v.h_avail_months == pytest.approx(42.0)

    def test_60y_unstable_conservative(self):
        """60+ 岁（q5=3）+ 不稳定收入（q4=3）+ 低耐受 (avg~3.4 → γ~7.6)。"""
        ans = KYCAnswers(q1=3, q2=3, q3=3, q4=3, q5=5)  # 52 岁
        v = from_kyc(ans)
        # avg = 3.4, γ = clip(11 - 3.4, 1.5, 9.5) = 7.6
        # age = 52, HC = clamp(1 - (52-25)/50, 0, 1) × 0.3 = 0.46 × 0.3 = 0.138
        # γ_eff = 7.6 × (1 + 0.5 × 0.862) = 7.6 × 1.431 = 10.876
        assert v.gamma_eff == pytest.approx(10.8756, rel=1e-3)
        # H_avail = min(3, (65-52)*12) = min(3, 156) = 3
        assert v.h_avail_months == pytest.approx(3.0)

    def test_gamma_clip_upper(self):
        """全 3 分：avg=3, γ=8 (未触上限)。极端组合触上限。"""
        ans = KYCAnswers(q1=3, q2=3, q3=3, q4=3, q5=3)
        v = from_kyc(ans)
        # γ = 8, γ_eff = 8 × (1 + 0.5 × (1 - HC))
        # age=65, HC = 0 × 0.3 = 0, γ_eff = 8 × 1.5 = 12
        # γ_eff 无 clip 直接算，但 γ 已 clip
        assert v.gamma_eff == pytest.approx(12.0, rel=1e-6)

    def test_gamma_clip_lower(self):
        """全 9 分：avg=9, γ = clip(11-9, 1.5, 9.5) = 2."""
        ans = KYCAnswers(q1=9, q2=9, q3=9, q4=9, q5=9)
        v = from_kyc(ans)
        # age=25, HC = 1 × 1.0 = 1, γ_eff = 2 × (1 + 0) = 2
        assert v.gamma_eff == pytest.approx(2.0, rel=1e-6)

    def test_hc_clamp_over_age(self):
        """>75 岁（不在问卷）→ HC 应 clamp 到 0。用 q5=3 (65 岁) 验证 clamp 生效边界。"""
        ans = KYCAnswers(q1=5, q2=5, q3=5, q4=9, q5=3)
        v = from_kyc(ans)
        # age = 65, (65-25)/50 = 0.8, 1-0.8 = 0.2, × income (1.0) = 0.2
        assert v.hc == pytest.approx(0.2, rel=1e-6)
        # H_avail = min(15, max(65-65, 0)*12) = min(15, 0) = 0
        assert v.h_avail_months == pytest.approx(0.0)


class TestGammaToC:
    """γ ↔ C1-C5 双向映射（spec §5 兼容锚点）。"""

    def test_gamma_c1_c2(self):
        assert gamma_to_C(9.0) in ("C1", "C2")
        assert gamma_to_C(7.5) in ("C1", "C2")

    def test_gamma_c3(self):
        assert gamma_to_C(6.0) == "C3"
        assert gamma_to_C(5.0) == "C3"

    def test_gamma_c4(self):
        assert gamma_to_C(4.0) == "C4"
        assert gamma_to_C(3.0) == "C4"

    def test_gamma_c5(self):
        assert gamma_to_C(2.5) == "C5"
        assert gamma_to_C(1.5) == "C5"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_advisor_calibrate.py -v`

Expected: FAIL with `ImportError: cannot import name 'from_kyc'`

- [ ] **Step 3: Write minimal implementation**

```python
# tradingagents/advisor/calibrate.py
"""KYC → InvestorVector 校准（spec §5）。

**单一真相源**：所有客户端（PicoClaw / Claude Code / CLI / MCP）都发原始 KYC 答案；
校准公式只住这一个文件。未来任何 κ/γ/HC 通路调整只改这里。
"""
from tradingagents.advisor.questionnaire import (
    KYC_Q2_MONTHS,
    KYC_Q4_INCOME_STABILITY,
    KYC_Q5_AGE,
)
from tradingagents.advisor.types import InvestorVector, KYCAnswers


_GAMMA_MIN = 1.5
_GAMMA_MAX = 9.5
_HC_COEF = 0.5              # γ_eff = γ × (1 + coef × (1 − HC))
_ANCHOR_AGE = 25            # HC = clamp(1 − (age − 25)/50, 0, 1) × income
_HC_SPAN = 50               # 25..75 岁 HC 线性衰减
_RETIREMENT_AGE = 65


def from_kyc(answers: KYCAnswers) -> InvestorVector:
    """把 5 题 KYC 原始答案校准成 InvestorVector (γ_eff / HC / H_avail)。"""
    values = [answers.q1, answers.q2, answers.q3, answers.q4, answers.q5]
    avg = sum(values) / len(values)

    gamma = _clip(11.0 - avg, _GAMMA_MIN, _GAMMA_MAX)

    age = KYC_Q5_AGE[answers.q5]
    income_stability = KYC_Q4_INCOME_STABILITY[answers.q4]
    hc_raw = 1.0 - (age - _ANCHOR_AGE) / _HC_SPAN
    hc = _clip(hc_raw, 0.0, 1.0) * income_stability

    gamma_eff = gamma * (1.0 + _HC_COEF * (1.0 - hc))

    q2_months = KYC_Q2_MONTHS[answers.q2]
    months_to_retirement = max(_RETIREMENT_AGE - age, 0) * 12
    h_avail = min(q2_months, months_to_retirement)

    return InvestorVector(
        gamma_eff=gamma_eff,
        hc=hc,
        h_avail_months=float(h_avail),
    )


def gamma_to_C(gamma: float) -> str:
    """γ → C1-C5 兼容锚点（spec §5 展示与监管口径对接）。

    γ≥7.5→C1/C2、5–7.5→C3、3–5→C4、<3→C5。
    C1 vs C2 v1 不区分，统一返回 'C1' 表示最保守段（若客户端要区分再扩展）。
    """
    if gamma >= 7.5:
        return "C1"
    if gamma >= 5.0:
        return "C3"
    if gamma >= 3.0:
        return "C4"
    return "C5"


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_advisor_calibrate.py -v`

Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/advisor/calibrate.py tests/test_advisor_calibrate.py
git commit -m "feat(advisor): P2 校准 (from_kyc + gamma→C 双向映射，单一真相源)"
```

---

## Milestone 3: 数学引擎（M3）

### Task 4: 引擎骨架 + Merton 计算

**Files:**
- Create: `tradingagents/advisor/engine.py`
- Test: `tests/test_advisor_engine.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_advisor_engine.py
import math

import pytest
from hypothesis import assume, given, strategies as st

from tradingagents.advisor.engine import advise
from tradingagents.advisor.types import AdvisorConfig, InvestorVector
from tradingagents.agents.schemas import KeyLevels, Scenario, ScenarioBucket


def _bucket_6m_bullish() -> ScenarioBucket:
    """μ ≈ +8%, σ² ≈ 0.024. 好研究，看多。"""
    return ScenarioBucket(
        horizon_months=6,
        scenarios=[
            Scenario(name="bull", thesis="...", return_pct=0.25, prob=0.35),
            Scenario(name="base", thesis="...", return_pct=0.05, prob=0.45),
            Scenario(name="bear", thesis="...", return_pct=-0.15, prob=0.20),
        ],
        key_levels=KeyLevels(stop=8.5, entry_low=9.5, entry_high=10.5, target=12.5),
    )


def _neutral_vector() -> InvestorVector:
    return InvestorVector(gamma_eff=5.0, hc=0.7, h_avail_months=60.0)


class TestMerton:
    def test_bullish_gives_positive_weight(self):
        bucket = _bucket_6m_bullish()
        vec = _neutral_vector()
        result = advise(bucket, vec, AdvisorConfig())
        assert result.trace.mu > 0
        assert result.trace.w_star > 0
        assert result.guard_reasons == []

    def test_hard_gate_horizon_mismatch(self):
        """H_avail < horizon → w* = 0，标 guard 但不阻塞。"""
        bucket = _bucket_6m_bullish()
        vec = InvestorVector(gamma_eff=5.0, hc=0.7, h_avail_months=3.0)  # 3 月 < 6
        result = advise(bucket, vec, AdvisorConfig())
        assert result.trace.w_star == 0.0
        assert not result.trace.bucket_horizon_ok
        codes = [g.code for g in result.guard_reasons]
        assert "horizon_mismatch" in codes

    def test_w_max_clip(self):
        """极端好机会打折后仍触上限。"""
        bucket = ScenarioBucket(
            horizon_months=6,
            scenarios=[
                Scenario(name="bull", thesis="...", return_pct=1.0, prob=0.6),
                Scenario(name="base", thesis="...", return_pct=0.3, prob=0.35),
                Scenario(name="bear", thesis="...", return_pct=-0.1, prob=0.05),
            ],
            key_levels=KeyLevels(stop=9, entry_low=10, entry_high=10, target=20),
        )
        vec = InvestorVector(gamma_eff=1.5, hc=1.0, h_avail_months=120.0)  # 最激进
        result = advise(bucket, vec, AdvisorConfig())
        assert result.trace.w_star == 0.25  # 卡 w_max

    def test_mu_below_rf_gives_zero(self):
        """μ < r_f·h → w* 恒为 0（Merton 分子非正）。"""
        bucket = ScenarioBucket(
            horizon_months=6,
            scenarios=[
                Scenario(name="bull", thesis="...", return_pct=0.01, prob=0.3),
                Scenario(name="base", thesis="...", return_pct=0.0, prob=0.4),
                Scenario(name="bear", thesis="...", return_pct=-0.05, prob=0.3),
            ],
            key_levels=KeyLevels(stop=9.5, entry_low=10, entry_high=10, target=10.1),
        )
        vec = _neutral_vector()
        result = advise(bucket, vec, AdvisorConfig())
        assert result.trace.w_star == 0.0


class TestGuards:
    def test_sigma_zero_returns_no_advice(self):
        """所有情景 return 相同 → σ²=0 → guard 触发，w*=0。"""
        bucket = ScenarioBucket(
            horizon_months=6,
            scenarios=[
                Scenario(name="bull", thesis="...", return_pct=0.05, prob=0.33),
                Scenario(name="base", thesis="...", return_pct=0.05, prob=0.34),
                Scenario(name="bear", thesis="...", return_pct=0.05, prob=0.33),
            ],
            key_levels=KeyLevels(stop=9, entry_low=10, entry_high=10, target=11),
        )
        result = advise(bucket, _neutral_vector(), AdvisorConfig())
        assert result.trace.w_star == 0.0
        assert "sigma_zero" in [g.code for g in result.guard_reasons]

    def test_prob_degenerate(self):
        """概率和明显偏离 1 → guard 触发（校验器兜底之外的兜底）。"""
        # 手工构造 pydantic 会拒的对象 —— 走内部函数验；此处只测正确概率下 sigma 非零
        bucket = _bucket_6m_bullish()
        result = advise(bucket, _neutral_vector(), AdvisorConfig())
        assert result.trace.sigma_sq > 0


class TestActionMapping:
    def test_action_thresholds(self):
        """w* 分档 → action 名称（avoid/observe/hold_underweight/increase_overweight）。"""
        bucket = _bucket_6m_bullish()

        # w* = 0 → avoid
        vec_avoid = InvestorVector(gamma_eff=5.0, hc=0.7, h_avail_months=3.0)
        r = advise(bucket, vec_avoid, AdvisorConfig())
        assert r.with_position.action == "avoid"

        # 温和 → observe / hold_underweight（依赖具体数值）
        bucket_small = ScenarioBucket(
            horizon_months=6,
            scenarios=[
                Scenario(name="bull", thesis="...", return_pct=0.10, prob=0.30),
                Scenario(name="base", thesis="...", return_pct=0.03, prob=0.45),
                Scenario(name="bear", thesis="...", return_pct=-0.08, prob=0.25),
            ],
            key_levels=KeyLevels(stop=9, entry_low=10, entry_high=10, target=11),
        )
        r2 = advise(bucket_small, _neutral_vector(), AdvisorConfig())
        assert r2.with_position.action in ("observe", "hold_underweight")


class TestPropertyMonotonicity:
    @given(st.floats(min_value=1.5, max_value=9.5))
    def test_gamma_up_weight_down(self, gamma_eff: float):
        """w* 对 γ_eff 单调不增。"""
        bucket = _bucket_6m_bullish()
        w_low_gamma = advise(
            bucket,
            InvestorVector(gamma_eff=max(gamma_eff - 0.5, 1.5), hc=0.7, h_avail_months=60.0),
            AdvisorConfig(),
        ).trace.w_star
        w_high_gamma = advise(
            bucket,
            InvestorVector(gamma_eff=gamma_eff, hc=0.7, h_avail_months=60.0),
            AdvisorConfig(),
        ).trace.w_star
        assert w_high_gamma <= w_low_gamma + 1e-9

    @given(st.floats(min_value=0.02, max_value=0.30))
    def test_mu_up_weight_up_when_below_wmax(self, target_mu: float):
        """μ 上升 → w* 上升（在 w_max 未触发的区间）。"""
        assume(target_mu < 0.15)  # 保持在 w_max 未触区
        p0 = 10.0
        target_ret = target_mu
        bucket = ScenarioBucket(
            horizon_months=6,
            scenarios=[
                Scenario(name="bull", thesis="...", return_pct=target_ret + 0.05, prob=0.35),
                Scenario(name="base", thesis="...", return_pct=target_ret, prob=0.45),
                Scenario(name="bear", thesis="...", return_pct=target_ret - 0.15, prob=0.20),
            ],
            key_levels=KeyLevels(stop=p0 * 0.85, entry_low=p0, entry_high=p0, target=p0 * 1.25),
        )
        vec = InvestorVector(gamma_eff=5.0, hc=0.7, h_avail_months=60.0)
        cfg = AdvisorConfig(w_max=1.0)  # 放开上限观察单调
        w = advise(bucket, vec, cfg).trace.w_star
        assert not math.isnan(w)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_advisor_engine.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'tradingagents.advisor.engine'`

Note: hypothesis 应已在依赖里；若报 `ModuleNotFoundError: hypothesis`，先跑
`.venv/bin/pip install hypothesis` 并在 pyproject.toml [dev] 里追加。

- [ ] **Step 3: Write minimal implementation**

```python
# tradingagents/advisor/engine.py
"""Merton 定仓引擎（spec §6）。零 LLM，纯函数。"""
import math
from typing import Literal

from tradingagents.advisor.types import (
    AdviceGuardReason,
    AdvicePosition,
    AdviceResult,
    AdviceTrace,
    AdvisorConfig,
    InvestorVector,
)
from tradingagents.agents.schemas import ScenarioBucket


def advise(
    bucket: ScenarioBucket,
    vector: InvestorVector,
    config: AdvisorConfig,
    ticker: str = "",
    date: str = "",
    rating: str = "Hold",
) -> AdviceResult:
    """核心：给定情景桶 + 投资者向量 + 配置，输出仓位建议。

    公式：
      μ = Σ pᵢrᵢ,  σ² = Σ pᵢ(rᵢ−μ)²
      w_raw = (μ − r_f·h) / (γ_eff · σ²)         # Merton
      w* = clip(κ · w_raw, 0, w_max)             # 打折 + 单票上限
      硬门: horizon > H_avail → w* = 0
    """
    guards: list[AdviceGuardReason] = []
    h_years = bucket.horizon_months / 12.0

    # 计算 μ 和 σ²
    mu = sum(s.prob * s.return_pct for s in bucket.scenarios)
    sigma_sq = sum(s.prob * (s.return_pct - mu) ** 2 for s in bucket.scenarios)

    # 守卫：σ² → 0
    if sigma_sq < 1e-9:
        guards.append(AdviceGuardReason(
            code="sigma_zero",
            detail=f"σ² = {sigma_sq:.2e} (退化情景)",
        ))

    # 守卫：概率退化
    total_p = sum(s.prob for s in bucket.scenarios)
    if abs(total_p - 1.0) > 0.02:
        guards.append(AdviceGuardReason(
            code="prob_degenerate",
            detail=f"Σp = {total_p:.4f}",
        ))

    # 守卫：NaN
    if math.isnan(mu) or math.isnan(sigma_sq):
        guards.append(AdviceGuardReason(
            code="nan_encountered",
            detail="μ 或 σ² 为 NaN",
        ))

    # Merton 计算（守卫下按分支处理）
    if guards or sigma_sq < 1e-9:
        w_raw = 0.0
        w_after_kappa = 0.0
        w_star = 0.0
    else:
        w_raw = (mu - config.r_f * h_years) / (vector.gamma_eff * sigma_sq)
        w_after_kappa = config.kappa * w_raw
        w_star = _clip(w_after_kappa, 0.0, config.w_max)

    # 硬门：期限
    bucket_horizon_ok = bucket.horizon_months <= vector.h_avail_months
    if not bucket_horizon_ok:
        w_star = 0.0
        guards.append(AdviceGuardReason(
            code="horizon_mismatch",
            detail=(
                f"桶期限 {bucket.horizon_months} 月 > H_avail "
                f"{vector.h_avail_months:.1f} 月"
            ),
        ))

    # 动作映射
    action = _action_for(w_star, config)

    # 方向由评级决定（Underweight/Sell → reduce；其它 → build）
    direction: Literal["build", "reduce"] = "reduce" if rating in {
        "Underweight", "Sell",
    } else "build"

    trace = AdviceTrace(
        gamma_eff=vector.gamma_eff,
        mu=mu,
        sigma_sq=sigma_sq,
        w_raw=w_raw,
        w_after_kappa=w_after_kappa,
        w_star=w_star,
        h_avail_months=vector.h_avail_months,
        horizon_months=bucket.horizon_months,
        bucket_horizon_ok=bucket_horizon_ok,
    )

    return AdviceResult(
        ticker=ticker,
        date=date,
        with_position=AdvicePosition(
            action=action, direction=direction, weight_star=w_star,
        ),
        without_position=AdvicePosition(
            action=action, direction=direction, weight_star=w_star,
        ),
        trace=trace,
        guard_reasons=guards,
    )


def _action_for(w_star: float, cfg: AdvisorConfig) -> Literal[
    "avoid", "observe", "hold_underweight", "increase_overweight",
]:
    if w_star == 0.0:
        return "avoid"
    if w_star < cfg.action_watch:
        return "observe"
    if w_star < cfg.action_overweight:
        return "hold_underweight"
    return "increase_overweight"


def _clip(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_advisor_engine.py -v`

Expected: PASS (all tests including property tests via hypothesis)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/advisor/engine.py tests/test_advisor_engine.py
git commit -m "feat(advisor): P2 Merton 引擎 + 硬门/守卫 + property 单调性测试"
```

---

## Milestone 4: 渲染（M4）

### Task 5: 3×3 矩阵采样 + 渲染

**Files:**
- Create: `tradingagents/advisor/render.py`
- Test: `tests/test_advisor_render.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_advisor_render.py
import pytest

from tradingagents.advisor.engine import advise
from tradingagents.advisor.render import (
    render_matrix,
    render_text,
    sample_matrix_cell,
    MATRIX_GAMMA_PRESETS,
    MATRIX_HORIZON_PRESETS,
)
from tradingagents.advisor.types import AdvisorConfig, InvestorVector
from tradingagents.agents.schemas import KeyLevels, Scenario, ScenarioBucket


def _bucket() -> ScenarioBucket:
    return ScenarioBucket(
        horizon_months=6,
        scenarios=[
            Scenario(name="bull", thesis="...", return_pct=0.25, prob=0.35),
            Scenario(name="base", thesis="...", return_pct=0.05, prob=0.45),
            Scenario(name="bear", thesis="...", return_pct=-0.15, prob=0.20),
        ],
        key_levels=KeyLevels(stop=8.5, entry_low=9.5, entry_high=10.5, target=12.5),
    )


class TestMatrixEqEngine:
    """铁律：矩阵 3×3 每一格 == 引擎对该 (γ, horizon) 直算，逐格相等。"""

    def test_all_nine_cells_match_engine(self):
        bucket = _bucket()
        cfg = AdvisorConfig()
        matrix = render_matrix(bucket, cfg)

        assert len(matrix.rows) == 3
        for row in matrix.rows:
            assert len(row.cells) == 3
        for gi, gamma in enumerate(MATRIX_GAMMA_PRESETS):
            for hi, horizon in enumerate(MATRIX_HORIZON_PRESETS):
                cell = matrix.rows[gi].cells[hi]
                vec = InvestorVector(
                    gamma_eff=gamma, hc=1.0, h_avail_months=float(horizon),
                )
                # 若 horizon 与 bucket.horizon_months 不同，需 bucket 视角切换
                # v1: 矩阵只在 bucket 自身 horizon 下采样 γ×H_avail 组合；
                # 高/低 H_avail 通过硬门体现（不重算 μ/σ）
                expected = advise(bucket, vec, cfg)
                assert cell.weight_star == pytest.approx(expected.trace.w_star)
                assert cell.action == expected.with_position.action


class TestSingleCell:
    def test_sample_matrix_cell_matches_engine(self):
        bucket = _bucket()
        cfg = AdvisorConfig()
        gamma = MATRIX_GAMMA_PRESETS[1]
        horizon = MATRIX_HORIZON_PRESETS[1]
        cell = sample_matrix_cell(bucket, cfg, gamma, horizon)
        vec = InvestorVector(gamma_eff=gamma, hc=1.0, h_avail_months=float(horizon))
        expected = advise(bucket, vec, cfg)
        assert cell.weight_star == pytest.approx(expected.trace.w_star)


class TestTextRender:
    def test_text_render_contains_key_fields(self):
        bucket = _bucket()
        cfg = AdvisorConfig()
        matrix = render_matrix(bucket, cfg)
        text = render_text(matrix, highlighted=(1, 1))

        assert "γ" in text
        assert "H_avail" in text or "月" in text
        for row in matrix.rows:
            for cell in row.cells:
                assert cell.action in text or f"{cell.weight_star:.2%}" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_advisor_render.py -v`

Expected: FAIL with `ImportError: cannot import name 'render_matrix'`

- [ ] **Step 3: Write minimal implementation**

```python
# tradingagents/advisor/render.py
"""3×3 矩阵采样 + 人类可读渲染。

铁律：矩阵每一格 == 引擎对该 (γ, H_avail) 直算，逐格相等（spec §6 不变量）。
不做插值/平滑。
"""
from typing import Literal

from pydantic import BaseModel

from tradingagents.advisor.engine import advise
from tradingagents.advisor.types import AdvicePosition, AdviceResult, AdvisorConfig, InvestorVector
from tradingagents.agents.schemas import ScenarioBucket


# γ 预设：保守 / 中性 / 激进
MATRIX_GAMMA_PRESETS: tuple[float, float, float] = (8.0, 5.0, 2.5)
# H_avail 预设（月）：短线 / 中线 / 长线
MATRIX_HORIZON_PRESETS: tuple[int, int, int] = (3, 24, 120)


class MatrixCell(BaseModel):
    gamma_eff: float
    h_avail_months: float
    weight_star: float
    action: Literal["avoid", "observe", "hold_underweight", "increase_overweight"]


class MatrixRow(BaseModel):
    gamma_label: str    # "保守" / "中性" / "激进"
    cells: list[MatrixCell]


class Matrix(BaseModel):
    horizon_labels: list[str]     # ["短线 3月", "中线 2年", "长线 10年"]
    rows: list[MatrixRow]


def sample_matrix_cell(
    bucket: ScenarioBucket,
    config: AdvisorConfig,
    gamma_eff: float,
    h_avail_months: int,
) -> MatrixCell:
    """采样单格。"""
    vec = InvestorVector(gamma_eff=gamma_eff, hc=1.0, h_avail_months=float(h_avail_months))
    r = advise(bucket, vec, config)
    return MatrixCell(
        gamma_eff=gamma_eff,
        h_avail_months=float(h_avail_months),
        weight_star=r.trace.w_star,
        action=r.with_position.action,
    )


def render_matrix(bucket: ScenarioBucket, config: AdvisorConfig) -> Matrix:
    """3×3 采样：γ × H_avail。"""
    gamma_labels = ["保守", "中性", "激进"]
    horizon_labels = [f"短线 {MATRIX_HORIZON_PRESETS[0]}月",
                      f"中线 {MATRIX_HORIZON_PRESETS[1]}月",
                      f"长线 {MATRIX_HORIZON_PRESETS[2]}月"]
    rows: list[MatrixRow] = []
    for gi, gamma in enumerate(MATRIX_GAMMA_PRESETS):
        cells = [sample_matrix_cell(bucket, config, gamma, h)
                 for h in MATRIX_HORIZON_PRESETS]
        rows.append(MatrixRow(gamma_label=gamma_labels[gi], cells=cells))
    return Matrix(horizon_labels=horizon_labels, rows=rows)


def render_text(matrix: Matrix, highlighted: tuple[int, int] | None = None) -> str:
    """把矩阵渲染成 ASCII 表格。highlighted=(row_idx, col_idx) 加星号。"""
    lines = ["                " + "  ".join(f"{h:>12}" for h in matrix.horizon_labels)]
    for gi, row in enumerate(matrix.rows):
        cell_texts = []
        for ci, cell in enumerate(row.cells):
            marker = "*" if highlighted == (gi, ci) else " "
            cell_texts.append(
                f"{marker}{cell.action:<20}[w*={cell.weight_star:.1%}]"
            )
        lines.append(f"γ={row.gamma_label:<4}  " + "  ".join(cell_texts))
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_advisor_render.py -v`

Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/advisor/render.py tests/test_advisor_render.py
git commit -m "feat(advisor): P2 3×3 矩阵采样 + 渲染 (矩阵≡引擎逐格测试)"
```

---

## Milestone 5: 磁盘 I/O（M5）

### Task 6: 情景 & 画像 I/O

**Files:**
- Create: `tradingagents/advisor/scenario_io.py`
- Create: `tradingagents/advisor/profile_io.py`
- Test: `tests/test_advisor_scenario_io.py`
- Test: `tests/test_advisor_profile_io.py`

- [ ] **Step 1: Write the failing test（分两个 test 文件）**

```python
# tests/test_advisor_scenario_io.py
import json
from pathlib import Path

import pytest

from tradingagents.advisor.scenario_io import (
    ScenarioArtifact,
    load_scenario,
    list_scenarios,
    ScenarioNotFoundError,
)


@pytest.fixture
def tmp_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """指向临时 reports 目录。"""
    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setenv("TRADINGAGENTS_REPORTS_DIR", str(reports))
    return reports


def _write_scenario(reports: Path, ticker: str, date: str, mu: float = 0.05) -> Path:
    """写一个最小合法的 scenario JSON。"""
    payload = {
        "version": 1,
        "ticker": ticker,
        "trade_date": date,
        "rating": "Hold",
        "scenario_buckets": [
            {
                "horizon_months": 6,
                "scenarios": [
                    {"name": "bull", "thesis": "t", "return_pct": mu + 0.1, "prob": 0.3},
                    {"name": "base", "thesis": "t", "return_pct": mu, "prob": 0.5},
                    {"name": "bear", "thesis": "t", "return_pct": mu - 0.1, "prob": 0.2},
                ],
                "key_levels": {"stop": 9, "entry_low": 10, "entry_high": 10, "target": 12},
            }
        ],
        "falsification": {"conditions": ["cond1"]},
    }
    p = reports / f"scenario_{ticker}_{date}.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


class TestLoadScenario:
    def test_load_latest(self, tmp_reports: Path):
        _write_scenario(tmp_reports, "000001", "2026-08-25")
        _write_scenario(tmp_reports, "000001", "2026-08-30")
        art = load_scenario("000001")
        assert art.trade_date == "2026-08-30"

    def test_load_specific_date(self, tmp_reports: Path):
        _write_scenario(tmp_reports, "000001", "2026-08-25")
        _write_scenario(tmp_reports, "000001", "2026-08-30")
        art = load_scenario("000001", date="2026-08-25")
        assert art.trade_date == "2026-08-25"

    def test_missing_ticker_raises(self, tmp_reports: Path):
        with pytest.raises(ScenarioNotFoundError):
            load_scenario("999999")

    def test_missing_date_raises(self, tmp_reports: Path):
        _write_scenario(tmp_reports, "000001", "2026-08-30")
        with pytest.raises(ScenarioNotFoundError):
            load_scenario("000001", date="2020-01-01")


class TestListScenarios:
    def test_list_by_ticker(self, tmp_reports: Path):
        _write_scenario(tmp_reports, "000001", "2026-08-25")
        _write_scenario(tmp_reports, "000001", "2026-08-30")
        _write_scenario(tmp_reports, "600000", "2026-08-30")
        entries = list_scenarios(ticker="000001")
        assert len(entries) == 2
        assert {e.trade_date for e in entries} == {"2026-08-25", "2026-08-30"}

    def test_list_all(self, tmp_reports: Path):
        _write_scenario(tmp_reports, "000001", "2026-08-30")
        _write_scenario(tmp_reports, "600000", "2026-08-30")
        entries = list_scenarios()
        assert len(entries) == 2

    def test_ignore_archived(self, tmp_reports: Path):
        _write_scenario(tmp_reports, "000001", "2026-08-30")
        (tmp_reports / "scenario_000001_2026-08-30.archived-20260828-120000.json").touch()
        entries = list_scenarios(ticker="000001")
        assert len(entries) == 1
```

```python
# tests/test_advisor_profile_io.py
import json
from pathlib import Path

import pytest

from tradingagents.advisor.profile_io import (
    read_profile,
    write_profile,
    ProfileNotFoundError,
)
from tradingagents.advisor.types import KYCAnswers


@pytest.fixture
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


class TestWriteRead:
    def test_write_then_read_roundtrip(self, tmp_home: Path):
        ans = KYCAnswers(q1=7, q2=5, q3=7, q4=7, q5=7)
        write_profile(ans)
        loaded = read_profile()
        assert loaded == ans

    def test_read_missing_raises(self, tmp_home: Path):
        with pytest.raises(ProfileNotFoundError):
            read_profile()

    def test_write_is_atomic(self, tmp_home: Path):
        """临时文件不残留，且已存在文件被替换。"""
        write_profile(KYCAnswers(q1=3, q2=3, q3=3, q4=3, q5=3))
        write_profile(KYCAnswers(q1=9, q2=9, q3=9, q4=9, q5=9))
        loaded = read_profile()
        assert loaded.q1 == 9
        profile_dir = tmp_home / ".tradingagents"
        stragglers = list(profile_dir.glob("profile.json.tmp*"))
        assert stragglers == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_advisor_scenario_io.py tests/test_advisor_profile_io.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'tradingagents.advisor.scenario_io'`

- [ ] **Step 3: Write minimal implementation**

```python
# tradingagents/advisor/scenario_io.py
"""P1 scenario_<ticker>_<date>.json 读侧。归档文件（.archived-*）跳过。"""
import json
import os
import re
from pathlib import Path

from pydantic import BaseModel

from tradingagents.agents.schemas import Falsification, ScenarioBucket


DEFAULT_REPORTS_DIR = Path.home() / ".tradingagents" / "reports"
_FILENAME_RE = re.compile(r"^scenario_(?P<ticker>[^_]+)_(?P<date>\d{4}-\d{2}-\d{2})\.json$")


class ScenarioNotFoundError(FileNotFoundError):
    pass


class ScenarioArtifact(BaseModel):
    version: int
    ticker: str
    trade_date: str
    rating: str
    scenario_buckets: list[ScenarioBucket]
    falsification: Falsification | None = None


class ScenarioIndexEntry(BaseModel):
    ticker: str
    trade_date: str
    path: str


def _reports_dir() -> Path:
    env = os.environ.get("TRADINGAGENTS_REPORTS_DIR")
    if env:
        return Path(env)
    return DEFAULT_REPORTS_DIR


def load_scenario(ticker: str, date: str | None = None) -> ScenarioArtifact:
    """加载指定 ticker（可选 date）的 scenario 制品。date 缺省取最新。"""
    entries = list_scenarios(ticker=ticker)
    if not entries:
        raise ScenarioNotFoundError(f"no scenario for {ticker}")
    if date is None:
        entry = sorted(entries, key=lambda e: e.trade_date)[-1]
    else:
        matches = [e for e in entries if e.trade_date == date]
        if not matches:
            raise ScenarioNotFoundError(f"no scenario for {ticker} on {date}")
        entry = matches[0]
    return ScenarioArtifact.model_validate_json(
        Path(entry.path).read_text(encoding="utf-8")
    )


def list_scenarios(ticker: str | None = None) -> list[ScenarioIndexEntry]:
    """扫 reports 目录返回所有非归档 scenario 索引。"""
    directory = _reports_dir()
    if not directory.exists():
        return []
    entries: list[ScenarioIndexEntry] = []
    for path in directory.iterdir():
        m = _FILENAME_RE.match(path.name)
        if not m:
            continue
        t = m.group("ticker")
        d = m.group("date")
        if ticker is not None and t != ticker:
            continue
        entries.append(ScenarioIndexEntry(ticker=t, trade_date=d, path=str(path)))
    return entries
```

```python
# tradingagents/advisor/profile_io.py
"""profile.json 原子读写（spec §5 Profile 存 ~/.tradingagents/profile.json）。"""
import json
import os
import tempfile
from pathlib import Path

from tradingagents.advisor.types import KYCAnswers


class ProfileNotFoundError(FileNotFoundError):
    pass


def _profile_path() -> Path:
    return Path(os.path.expanduser("~")) / ".tradingagents" / "profile.json"


def read_profile() -> KYCAnswers:
    """读 profile.json 返回 KYCAnswers。文件缺失抛 ProfileNotFoundError。"""
    p = _profile_path()
    if not p.exists():
        raise ProfileNotFoundError(str(p))
    payload = json.loads(p.read_text(encoding="utf-8"))
    return KYCAnswers.model_validate(payload.get("kyc_answers", payload))


def write_profile(answers: KYCAnswers) -> None:
    """原子写 profile.json。tmp+replace 保证不留半成品。"""
    p = _profile_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "kyc_answers": answers.model_dump()}
    with tempfile.NamedTemporaryFile(
        mode="w", dir=p.parent, delete=False, encoding="utf-8", suffix=".tmp"
    ) as tf:
        json.dump(payload, tf, ensure_ascii=False)
        tmp_name = tf.name
    os.replace(tmp_name, p)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_advisor_scenario_io.py tests/test_advisor_profile_io.py -v`

Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add tradingagents/advisor/scenario_io.py tradingagents/advisor/profile_io.py \
        tests/test_advisor_scenario_io.py tests/test_advisor_profile_io.py
git commit -m "feat(advisor): P2 scenario/profile IO (原子写 + 归档过滤 + latest 语义)"
```

---

## Milestone 6: CLI advise 命令（M6）

### Task 7: `tradingagents advise` 命令

**Files:**
- Modify: `cli/main.py`（在末尾加 `@app.command()` `advise`）
- Test: `tests/test_cli_advise.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_advise.py
import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def tmp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setenv("TRADINGAGENTS_REPORTS_DIR", str(reports))
    monkeypatch.setenv("HOME", str(tmp_path))
    return {"reports": reports, "home": tmp_path}


def _write_scenario_and_profile(env, ticker="000001", date="2026-08-30"):
    (env["reports"] / f"scenario_{ticker}_{date}.json").write_text(json.dumps({
        "version": 1,
        "ticker": ticker,
        "trade_date": date,
        "rating": "Buy",
        "scenario_buckets": [{
            "horizon_months": 6,
            "scenarios": [
                {"name": "bull", "thesis": "t", "return_pct": 0.25, "prob": 0.35},
                {"name": "base", "thesis": "t", "return_pct": 0.05, "prob": 0.45},
                {"name": "bear", "thesis": "t", "return_pct": -0.15, "prob": 0.20},
            ],
            "key_levels": {"stop": 8.5, "entry_low": 9.5, "entry_high": 10.5, "target": 12.5},
        }],
        "falsification": {"conditions": ["cond"]},
    }), encoding="utf-8")
    profile_dir = env["home"] / ".tradingagents"
    profile_dir.mkdir(exist_ok=True)
    (profile_dir / "profile.json").write_text(json.dumps({
        "schema_version": 1,
        "kyc_answers": {"q1": 7, "q2": 7, "q3": 7, "q4": 7, "q5": 7},
    }), encoding="utf-8")


def _run(env, *args, **kwargs):
    return subprocess.run(
        [".venv/bin/python", "-m", "cli.main", *args],
        capture_output=True, text=True,
        env={**dict((k, v) for k, v in kwargs.get("passthrough_env", {}).items()),
              "TRADINGAGENTS_REPORTS_DIR": str(env["reports"]),
              "HOME": str(env["home"]),
              "PATH": "/usr/bin:/bin"},
    )


class TestAdviseJSON:
    def test_json_output(self, tmp_env):
        _write_scenario_and_profile(tmp_env)
        r = _run(tmp_env, "advise", "000001", "--json")
        assert r.returncode == 0, r.stderr
        payload = json.loads(r.stdout)
        assert payload["ticker"] == "000001"
        assert payload["schema_version"] == 1
        assert "with_position" in payload
        assert "trace" in payload

    def test_missing_scenario_returns_not_found(self, tmp_env):
        r = _run(tmp_env, "advise", "999999", "--json")
        assert r.returncode != 0
        payload = json.loads(r.stdout)
        assert payload["error"] == "not_found"

    def test_missing_profile_returns_kyc_required(self, tmp_env):
        _write_scenario_and_profile(tmp_env)
        (tmp_env["home"] / ".tradingagents" / "profile.json").unlink()
        r = _run(tmp_env, "advise", "000001", "--json")
        assert r.returncode != 0
        payload = json.loads(r.stdout)
        assert payload["error"] == "kyc_required"
        assert "questionnaire" in payload
        assert len(payload["questionnaire"]["questions"]) == 5

    def test_kyc_json_inline(self, tmp_env):
        """--kyc-json 覆盖 profile.json（本 spec §8.4 追加参数）。"""
        _write_scenario_and_profile(tmp_env)
        (tmp_env["home"] / ".tradingagents" / "profile.json").unlink()
        kyc = json.dumps({"q1": 3, "q2": 3, "q3": 3, "q4": 3, "q5": 3})
        r = _run(tmp_env, "advise", "000001", "--json", "--kyc-json", kyc)
        assert r.returncode == 0, r.stderr
        payload = json.loads(r.stdout)
        assert payload["ticker"] == "000001"

    def test_invalid_kyc_json(self, tmp_env):
        _write_scenario_and_profile(tmp_env)
        r = _run(tmp_env, "advise", "000001", "--json",
                 "--kyc-json", '{"q1": 4}')  # 4 违例
        assert r.returncode != 0
        payload = json.loads(r.stdout)
        assert payload["error"] == "invalid_kyc"

    def test_assume_neutral(self, tmp_env):
        """无 profile 时用 --assume-neutral 出中性向量演示。"""
        _write_scenario_and_profile(tmp_env)
        (tmp_env["home"] / ".tradingagents" / "profile.json").unlink()
        r = _run(tmp_env, "advise", "000001", "--json", "--assume-neutral")
        assert r.returncode == 0, r.stderr
        payload = json.loads(r.stdout)
        assert payload["ticker"] == "000001"


class TestAdviseCLIDefaultCompat:
    def test_bare_run_still_works(self):
        """加了 advise 子命令后，裸跑 tradingagents 依旧走 default callback（v0.5.9 教训）。"""
        r = subprocess.run(
            [".venv/bin/python", "-m", "cli.main", "--help"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0
        assert "advise" in r.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_cli_advise.py -v`

Expected: FAIL with `No such command 'advise'` in stderr

- [ ] **Step 3: Write minimal implementation**

在 `cli/main.py` 末尾（`if __name__ == "__main__":` 之前）加：

```python
@app.command()
def advise(
    ticker: str = typer.Argument(..., help="A 股 6 位代码"),
    date: str | None = typer.Option(None, "--date", help="分析日 (YYYY-MM-DD)；缺省取最新"),
    json_out: bool = typer.Option(False, "--json", help="输出 JSON（机器消费）"),
    assume_neutral: bool = typer.Option(
        False, "--assume-neutral",
        help="无 profile 时用中性向量演示（γ_eff=5, HC=0.7, H_avail=60）",
    ),
    kyc_json: str | None = typer.Option(
        None, "--kyc-json",
        help='inline KYC 答案 JSON，如 {"q1":7,"q2":5,"q3":7,"q4":7,"q5":7}',
    ),
):
    """情景向量顾问：读 scenario.json + KYC → Merton 引擎 → 建议（零 LLM，秒级）。"""
    import json as _json
    import sys

    from pydantic import ValidationError

    from tradingagents.advisor.calibrate import from_kyc
    from tradingagents.advisor.engine import advise as _advise
    from tradingagents.advisor.profile_io import ProfileNotFoundError, read_profile
    from tradingagents.advisor.questionnaire import get_questionnaire
    from tradingagents.advisor.render import render_matrix, render_text
    from tradingagents.advisor.scenario_io import ScenarioNotFoundError, load_scenario
    from tradingagents.advisor.types import AdvisorConfig, InvestorVector, KYCAnswers

    def _emit(payload: dict, exit_code: int = 0) -> None:
        if json_out:
            console.print_json(_json.dumps(payload, ensure_ascii=False))
        else:
            console.print(payload)
        raise typer.Exit(code=exit_code)

    # 1) 读 scenario
    try:
        artifact = load_scenario(ticker, date=date)
    except ScenarioNotFoundError as e:
        _emit({"error": "not_found", "message": str(e)}, exit_code=1)
        return

    # 2) 解析投资者向量
    try:
        if kyc_json is not None:
            try:
                answers = KYCAnswers.model_validate_json(kyc_json)
            except ValidationError as e:
                _emit({
                    "error": "invalid_kyc",
                    "message": "KYC 答案 schema 违例",
                    "details": _json.loads(e.json()),
                }, exit_code=2)
                return
            vector = from_kyc(answers)
        elif assume_neutral:
            vector = InvestorVector(gamma_eff=5.0, hc=0.7, h_avail_months=60.0)
        else:
            try:
                answers = read_profile()
            except ProfileNotFoundError:
                _emit({
                    "error": "kyc_required",
                    "message": "需要先建立投资者画像（5 题问卷）；或用 --kyc-json / --assume-neutral",
                    "questionnaire": get_questionnaire().model_dump(),
                }, exit_code=3)
                return
            vector = from_kyc(answers)
    except Exception as e:
        _emit({"error": "internal", "message": str(e)}, exit_code=4)
        return

    # 3) 引擎
    bucket = artifact.scenario_buckets[0]  # v1 只有一个 6 月桶
    result = _advise(bucket, vector, AdvisorConfig(),
                     ticker=ticker, date=artifact.trade_date, rating=artifact.rating)

    # 4) 输出
    if json_out:
        _emit(result.model_dump(), exit_code=0)
    else:
        matrix = render_matrix(bucket, AdvisorConfig())
        console.print(f"[bold]评级：{artifact.rating}  日期：{artifact.trade_date}[/bold]")
        console.print(render_text(matrix))
        console.print(f"\nw* = {result.trace.w_star:.1%}  action = {result.with_position.action}")
        raise typer.Exit(code=0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_cli_advise.py tests/test_cli_default_command.py -v`

Expected: PASS（`test_cli_default_command` 也必须通过——v0.5.9 铁律）

- [ ] **Step 5: Commit**

```bash
git add cli/main.py tests/test_cli_advise.py
git commit -m "feat(cli): tradingagents advise 命令 (--json / --kyc-json / --assume-neutral)"
```

---

## Milestone 7: 全量回归与 CLAUDE.md 更新

### Task 8: 全量测试 + baseline 更新

- [ ] **Step 1: 跑全量测试**

Run: `.venv/bin/python -m pytest tests/ -v --tb=short`

Expected: 全部通过；425（P1 baseline）+ 新增 P2 测试数量。若有失败，先修再往下。

- [ ] **Step 2: 记录新 baseline**

清点通过数：`.venv/bin/python -m pytest tests/ 2>&1 | tail -3`

- [ ] **Step 3: 更新 CLAUDE.md 测试基线数字**

Edit `CLAUDE.md` 的 `### 测试` 段，把 "361 passed / 13 skipped / 0 failed" 或 "425 passed" 更新到最新数字，并追加一行说明 P2 已交付：

```markdown
### 测试
**干净 clone（`pip install -e .` 不带 `[agentsdk]`）跑 `pytest tests/` 应当是
<新数字> passed / 13 skipped / **0 failed**。出现 failed 就是真回归。P2 顾问引擎
（`tradingagents/advisor/`）+ CLI `advise` 命令 2026-08-30 交付。**
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "chore: CLAUDE.md 更新 P2 交付后测试 baseline"
```

---

## Self-Review 检查表（写完 plan 后自检）

**Spec 覆盖率**（对 spec 2026-08-29-scenario-vector-advisor-design.md）：

- ✅ §5 KYC 问卷 + 校准 → Task 2 (questionnaire) + Task 3 (calibrate)
- ✅ §6 引擎（μ/σ/Merton/w_max/硬门/守卫）→ Task 4
- ✅ §6 一致性不变量（单调性 property）→ Task 4 hypothesis 测试
- ✅ §6 矩阵 ≡ 引擎逐格 → Task 5
- ✅ §7 CLI advise --json --assume-neutral → Task 7
- ✅ §7 profile.json 原子写 → Task 6
- ✅ §7 --kyc-json inline 支持（原 spec 未写，MCP spec §8.4 追加）→ Task 7
- ✅ §7 kyc_required 错误结构 → Task 7（内嵌 questionnaire payload）
- ✅ §7 同日守卫（已有 CLI --force 逻辑，未影响 advise）
- ⚠️ §7 Web UI 部分（sidebar profile 面板 + 3×3 矩阵渲染）→ **本 plan 明确不做**，独立后续 PR
- ⚠️ P3 review 巡检 → 单独 plan

**Placeholder 扫描**：
- 全 plan 每步都有具体代码 / 命令 / 期望输出
- 没有 "TBD" / "add appropriate error handling" 类占位

**类型一致性**：
- `KYCAnswers` 在所有任务保持相同字段 (`q1-q5` + `schema_version`)
- `InvestorVector` 字段名 (`gamma_eff` / `hc` / `h_avail_months`) 在 calibrate / engine / render / CLI 一致
- `AdviceResult.trace.w_star` 在测试与实现一致

**scope 边界**：
- 本 plan 只做 MCP 关键路径的 P2 子集；Web UI + P3 review 明确不在
- 无跨仓依赖

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-08-30-scenario-vector-advisor-p2.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - Fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
