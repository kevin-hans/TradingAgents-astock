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
        """60+ 岁 + 不稳定收入 + 低耐受 (avg~3.4 → γ~7.6)。"""
        ans = KYCAnswers(q1=3, q2=3, q3=3, q4=3, q5=5)  # 52 岁
        v = from_kyc(ans)
        # avg = 3.4, γ = clip(11 - 3.4, 1.5, 9.5) = 7.6
        # age = 52, HC = clamp(1 - (52-25)/50, 0, 1) × 0.3 = 0.46 × 0.3 = 0.138
        # γ_eff = 7.6 × (1 + 0.5 × 0.862) = 7.6 × 1.431 = 10.8756
        assert v.gamma_eff == pytest.approx(10.8756, rel=1e-3)
        # H_avail = min(3, (65-52)*12) = min(3, 156) = 3
        assert v.h_avail_months == pytest.approx(3.0)

    def test_gamma_clip_upper(self):
        """全 3 分：avg=3, γ=8 (未触上限)."""
        ans = KYCAnswers(q1=3, q2=3, q3=3, q4=3, q5=3)
        v = from_kyc(ans)
        # γ = 8, age=65, hc_raw=0.2, HC=0.2×0.3=0.06, γ_eff=8×(1+0.5×0.94)=11.76
        assert v.gamma_eff == pytest.approx(11.76, rel=1e-6)

    def test_gamma_clip_lower(self):
        """全 9 分：avg=9, γ = clip(11-9, 1.5, 9.5) = 2."""
        ans = KYCAnswers(q1=9, q2=9, q3=9, q4=9, q5=9)
        v = from_kyc(ans)
        # age=25, HC = 1 × 1.0 = 1, γ_eff = 2 × (1 + 0) = 2
        assert v.gamma_eff == pytest.approx(2.0, rel=1e-6)

    def test_hc_clamp_over_age(self):
        """65 岁：(65-25)/50 = 0.8, 1-0.8 = 0.2, × income (1.0) = 0.2."""
        ans = KYCAnswers(q1=5, q2=5, q3=5, q4=9, q5=3)
        v = from_kyc(ans)
        assert v.hc == pytest.approx(0.2, rel=1e-6)
        # H_avail = min(15, max(65-65, 0)*12) = min(15, 0) = 0
        assert v.h_avail_months == pytest.approx(0.0)


class TestGammaToC:
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
