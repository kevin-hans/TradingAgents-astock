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
