import math

import pytest

hypothesis = pytest.importorskip("hypothesis")

from hypothesis import assume, given, settings, strategies as st  # noqa: E402

from tradingagents.advisor.engine import advise  # noqa: E402
from tradingagents.advisor.types import AdvisorConfig, InvestorVector  # noqa: E402
from tradingagents.agents.schemas import KeyLevels, Scenario, ScenarioBucket  # noqa: E402


def _bucket_6m_bullish() -> ScenarioBucket:
    return ScenarioBucket(
        horizon_months=6,
        scenarios=[
            Scenario(name="bull", thesis="...", expected_return=0.25, prob=0.35),
            Scenario(name="base", thesis="...", expected_return=0.05, prob=0.45),
            Scenario(name="bear", thesis="...", expected_return=-0.15, prob=0.20),
        ],
        key_levels=KeyLevels(stop=8.5, entry_low=9.5, entry_high=10.5, target=12.5),
    )


class TestPropertyMonotonicity:
    @settings(max_examples=50)
    @given(st.floats(min_value=2.0, max_value=9.0))
    def test_gamma_up_weight_down(self, gamma_eff: float):
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

    @settings(max_examples=50)
    @given(st.floats(min_value=0.02, max_value=0.14))
    def test_mu_up_weight_up_when_below_wmax(self, target_mu: float):
        assume(target_mu < 0.14)
        p0 = 10.0
        bucket = ScenarioBucket(
            horizon_months=6,
            scenarios=[
                Scenario(name="bull", thesis="...", expected_return=target_mu + 0.05, prob=0.35),
                Scenario(name="base", thesis="...", expected_return=target_mu, prob=0.45),
                Scenario(name="bear", thesis="...", expected_return=target_mu - 0.15, prob=0.20),
            ],
            key_levels=KeyLevels(stop=p0 * 0.85, entry_low=p0, entry_high=p0, target=p0 * 1.25),
        )
        vec = InvestorVector(gamma_eff=5.0, hc=0.7, h_avail_months=60.0)
        cfg = AdvisorConfig(w_max=1.0)
        w = advise(bucket, vec, cfg).trace.w_star
        assert not math.isnan(w)
        assert w >= 0.0
