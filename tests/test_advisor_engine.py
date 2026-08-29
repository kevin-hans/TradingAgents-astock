import pytest

from tradingagents.advisor.engine import advise
from tradingagents.advisor.types import AdvisorConfig, InvestorVector
from tradingagents.agents.schemas import KeyLevels, Scenario, ScenarioBucket


def _bucket_6m_bullish() -> ScenarioBucket:
    """μ ≈ +8%, σ² > 0. 好研究，看多。"""
    return ScenarioBucket(
        horizon_months=6,
        scenarios=[
            Scenario(name="bull", thesis="...", expected_return=0.25, prob=0.35),
            Scenario(name="base", thesis="...", expected_return=0.05, prob=0.45),
            Scenario(name="bear", thesis="...", expected_return=-0.15, prob=0.20),
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
        vec = InvestorVector(gamma_eff=5.0, hc=0.7, h_avail_months=3.0)
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
                Scenario(name="bull", thesis="...", expected_return=1.0, prob=0.6),
                Scenario(name="base", thesis="...", expected_return=0.3, prob=0.35),
                Scenario(name="bear", thesis="...", expected_return=-0.1, prob=0.05),
            ],
            key_levels=KeyLevels(stop=9, entry_low=10, entry_high=10, target=20),
        )
        vec = InvestorVector(gamma_eff=1.5, hc=1.0, h_avail_months=120.0)
        result = advise(bucket, vec, AdvisorConfig())
        assert result.trace.w_star == 0.25

    def test_mu_below_rf_gives_zero(self):
        """μ < r_f·h → w* 恒为 0."""
        bucket = ScenarioBucket(
            horizon_months=6,
            scenarios=[
                Scenario(name="bull", thesis="...", expected_return=0.01, prob=0.3),
                Scenario(name="base", thesis="...", expected_return=0.0, prob=0.4),
                Scenario(name="bear", thesis="...", expected_return=-0.05, prob=0.3),
            ],
            key_levels=KeyLevels(stop=9.5, entry_low=10, entry_high=10, target=10.1),
        )
        vec = _neutral_vector()
        result = advise(bucket, vec, AdvisorConfig())
        assert result.trace.w_star == 0.0


class TestGuards:
    def test_sigma_zero_returns_no_advice(self):
        bucket = ScenarioBucket(
            horizon_months=6,
            scenarios=[
                Scenario(name="bull", thesis="...", expected_return=0.05, prob=0.33),
                Scenario(name="base", thesis="...", expected_return=0.05, prob=0.34),
                Scenario(name="bear", thesis="...", expected_return=0.05, prob=0.33),
            ],
            key_levels=KeyLevels(stop=9, entry_low=10, entry_high=10, target=11),
        )
        result = advise(bucket, _neutral_vector(), AdvisorConfig())
        assert result.trace.w_star == 0.0
        assert "sigma_zero" in [g.code for g in result.guard_reasons]

    def test_valid_probs_no_prob_degenerate_guard(self):
        bucket = _bucket_6m_bullish()
        result = advise(bucket, _neutral_vector(), AdvisorConfig())
        assert result.trace.sigma_sq > 0
        assert "prob_degenerate" not in [g.code for g in result.guard_reasons]

    def test_nan_encountered_guard(self):
        """NaN return → nan_encountered guard fires"""
        import math
        bucket = ScenarioBucket(
            horizon_months=6,
            scenarios=[
                Scenario(name="bull", thesis="...", expected_return=float("nan"), prob=0.35),
                Scenario(name="base", thesis="...", expected_return=0.05, prob=0.45),
                Scenario(name="bear", thesis="...", expected_return=-0.15, prob=0.20),
            ],
            key_levels=KeyLevels(stop=9, entry_low=10, entry_high=10, target=12),
        )
        result = advise(bucket, _neutral_vector(), AdvisorConfig())
        assert result.trace.w_star == 0.0
        assert "nan_encountered" in [g.code for g in result.guard_reasons]

    def test_prob_degenerate_guard(self):
        """Σp 显著偏 1 → prob_degenerate guard fires

        绕过 pydantic 校验注入非法概率来测引擎自身守卫。
        """
        bucket = ScenarioBucket(
            horizon_months=6,
            scenarios=[
                Scenario(name="bull", thesis="...", expected_return=0.25, prob=0.55),
                Scenario(name="base", thesis="...", expected_return=0.05, prob=0.45),
                Scenario(name="bear", thesis="...", expected_return=-0.15, prob=0.20),
            ],
            key_levels=KeyLevels(stop=9, entry_low=10, entry_high=10, target=12),
        )
        result = advise(bucket, _neutral_vector(), AdvisorConfig())
        assert "prob_degenerate" in [g.code for g in result.guard_reasons]


class TestActionMapping:
    def test_action_zero_avoid(self):
        bucket = _bucket_6m_bullish()
        vec_avoid = InvestorVector(gamma_eff=5.0, hc=0.7, h_avail_months=3.0)
        r = advise(bucket, vec_avoid, AdvisorConfig())
        assert r.with_position.action == "avoid"

    def test_action_mid_range(self):
        """温和 → observe 或 hold_underweight 或 increase_overweight（依赖具体数值）。"""
        bucket_small = ScenarioBucket(
            horizon_months=6,
            scenarios=[
                Scenario(name="bull", thesis="...", expected_return=0.10, prob=0.30),
                Scenario(name="base", thesis="...", expected_return=0.03, prob=0.45),
                Scenario(name="bear", thesis="...", expected_return=-0.08, prob=0.25),
            ],
            key_levels=KeyLevels(stop=9, entry_low=10, entry_high=10, target=11),
        )
        r = advise(bucket_small, _neutral_vector(), AdvisorConfig())
        assert r.with_position.action in (
            "observe", "hold_underweight", "increase_overweight",
        )

    def test_action_observe(self):
        """w* ∈ (0, 0.05) → observe"""
        bucket = ScenarioBucket(
            horizon_months=6,
            scenarios=[
                Scenario(name="bull", thesis="...", expected_return=0.15, prob=0.25),
                Scenario(name="base", thesis="...", expected_return=0.03, prob=0.45),
                Scenario(name="bear", thesis="...", expected_return=-0.12, prob=0.30),
            ],
            key_levels=KeyLevels(stop=9, entry_low=10, entry_high=10, target=11),
        )
        vec = InvestorVector(gamma_eff=5.0, hc=0.7, h_avail_months=60.0)
        r = advise(bucket, vec, AdvisorConfig())
        assert 0 < r.trace.w_star < 0.05, f"w*={r.trace.w_star}"
        assert r.with_position.action == "observe"

    def test_action_hold_underweight(self):
        """w* ∈ [0.05, 0.15) → hold_underweight"""
        bucket = ScenarioBucket(
            horizon_months=6,
            scenarios=[
                Scenario(name="bull", thesis="...", expected_return=0.15, prob=0.35),
                Scenario(name="base", thesis="...", expected_return=0.05, prob=0.45),
                Scenario(name="bear", thesis="...", expected_return=-0.10, prob=0.20),
            ],
            key_levels=KeyLevels(stop=9, entry_low=10, entry_high=10, target=11.5),
        )
        vec = InvestorVector(gamma_eff=15.0, hc=0.7, h_avail_months=60.0)
        r = advise(bucket, vec, AdvisorConfig())
        assert 0.05 <= r.trace.w_star < 0.15, f"w*={r.trace.w_star}"
        assert r.with_position.action == "hold_underweight"

    def test_action_increase_overweight(self):
        """w* ≥ 0.15 → increase_overweight"""
        bucket = ScenarioBucket(
            horizon_months=6,
            scenarios=[
                Scenario(name="bull", thesis="...", expected_return=0.30, prob=0.45),
                Scenario(name="base", thesis="...", expected_return=0.10, prob=0.40),
                Scenario(name="bear", thesis="...", expected_return=-0.10, prob=0.15),
            ],
            key_levels=KeyLevels(stop=9, entry_low=10, entry_high=10, target=13),
        )
        vec = InvestorVector(gamma_eff=2.5, hc=1.0, h_avail_months=120.0)
        r = advise(bucket, vec, AdvisorConfig())
        assert r.trace.w_star >= 0.15, f"w*={r.trace.w_star}"
        assert r.with_position.action == "increase_overweight"


class TestDirection:
    def test_default_rating_gives_build(self):
        bucket = _bucket_6m_bullish()
        result = advise(bucket, _neutral_vector(), AdvisorConfig())
        assert result.with_position.direction == "build"

    def test_sell_rating_gives_reduce(self):
        bucket = _bucket_6m_bullish()
        result = advise(bucket, _neutral_vector(), AdvisorConfig(), rating="Sell")
        assert result.with_position.direction == "reduce"

    def test_underweight_gives_reduce(self):
        bucket = _bucket_6m_bullish()
        result = advise(bucket, _neutral_vector(), AdvisorConfig(), rating="Underweight")
        assert result.with_position.direction == "reduce"
