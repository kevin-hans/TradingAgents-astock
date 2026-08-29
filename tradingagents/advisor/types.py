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

    kappa: PositiveFloat = 0.3
    w_max: float = Field(default=0.25, gt=0.0, le=1.0)
    r_f: float = 0.015
    action_watch: float = 0.05
    action_overweight: float = 0.15
    gamma_hc_coef: float = 0.5
    retirement_age: int = 65
    anchor_tolerance: float = 0.05


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
