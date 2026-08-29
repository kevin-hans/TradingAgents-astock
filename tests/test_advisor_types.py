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

    def test_reject_gamma_below_floor(self):
        with pytest.raises(ValidationError):
            InvestorVector(gamma_eff=0.5, hc=0.6, h_avail_months=60.0)


class TestAdvisorConfig:
    def test_defaults(self):
        c = AdvisorConfig()
        assert c.kappa == 0.3
        assert c.w_max == 0.25
        assert c.r_f == 0.015
        assert c.action_watch == 0.05
        assert c.action_overweight == 0.15
        assert c.gamma_hc_coef == 0.5
        assert c.retirement_age == 65
        assert c.anchor_tolerance == 0.05

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
