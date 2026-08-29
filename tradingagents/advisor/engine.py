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
    guards: list[AdviceGuardReason] = []
    h_years = bucket.horizon_months / 12.0

    mu = sum(s.prob * s.expected_return for s in bucket.scenarios)
    sigma_sq = sum(s.prob * (s.expected_return - mu) ** 2 for s in bucket.scenarios)

    if sigma_sq < 1e-9:
        guards.append(AdviceGuardReason(
            code="sigma_zero", detail=f"σ² = {sigma_sq:.2e} (退化情景)",
        ))

    total_p = sum(s.prob for s in bucket.scenarios)
    if abs(total_p - 1.0) > 0.02:
        guards.append(AdviceGuardReason(
            code="prob_degenerate", detail=f"Σp = {total_p:.4f}",
        ))

    if math.isnan(mu) or math.isnan(sigma_sq):
        guards.append(AdviceGuardReason(
            code="nan_encountered", detail="μ 或 σ² 为 NaN",
        ))

    if guards or sigma_sq < 1e-9:
        w_raw = 0.0
        w_after_kappa = 0.0
        w_star = 0.0
    else:
        w_raw = (mu - config.r_f * h_years) / (vector.gamma_eff * sigma_sq)
        w_after_kappa = config.kappa * w_raw
        w_star = _clip(w_after_kappa, 0.0, config.w_max)

    bucket_horizon_ok = bucket.horizon_months <= vector.h_avail_months
    if not bucket_horizon_ok:
        w_star = 0.0
        guards.append(AdviceGuardReason(
            code="horizon_mismatch",
            detail=f"桶期限 {bucket.horizon_months} 月 > H_avail {vector.h_avail_months:.1f} 月",
        ))

    action = _action_for(w_star, config)
    direction: Literal["build", "reduce"] = "reduce" if rating in {
        "Underweight", "Sell",
    } else "build"

    trace = AdviceTrace(
        gamma_eff=vector.gamma_eff, mu=mu, sigma_sq=sigma_sq,
        w_raw=w_raw, w_after_kappa=w_after_kappa, w_star=w_star,
        h_avail_months=vector.h_avail_months,
        horizon_months=bucket.horizon_months,
        bucket_horizon_ok=bucket_horizon_ok,
    )

    return AdviceResult(
        ticker=ticker, date=date,
        with_position=AdvicePosition(action=action, direction=direction, weight_star=w_star),
        without_position=AdvicePosition(action=action, direction=direction, weight_star=w_star),
        trace=trace, guard_reasons=guards,
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
