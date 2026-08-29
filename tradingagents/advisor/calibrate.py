"""KYC → InvestorVector 校准（spec §5）。

单一真相源：所有客户端都发原始 KYC 答案；校准公式只住这里。
"""
from typing import Literal

from tradingagents.advisor.questionnaire import (
    KYC_Q2_MONTHS,
    KYC_Q4_INCOME_STABILITY,
    KYC_Q5_AGE,
)
from tradingagents.advisor.types import InvestorVector, KYCAnswers


_GAMMA_MIN = 1.5
_GAMMA_MAX = 9.5
_HC_COEF = 0.5              # γ_eff = γ × (1 + coef × (1 − HC))
_ANCHOR_AGE = 25
_HC_SPAN = 50
_RETIREMENT_AGE = 65


def from_kyc(answers: KYCAnswers) -> InvestorVector:
    """把 5 题 KYC 原始答案校准成 InvestorVector (γ_eff / HC / H_avail)."""
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


def gamma_to_C(gamma: float) -> Literal["C1", "C3", "C4", "C5"]:
    """γ → C1-C5 兼容锚点（spec §5）。

    γ≥7.5→C1/C2、5–7.5→C3、3–5→C4、<3→C5。
    C1/C2 v1 不区分，统一返回 'C1'。
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
