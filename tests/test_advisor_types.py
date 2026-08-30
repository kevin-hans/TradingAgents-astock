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

    def test_canonical_values_pass_through(self):
        ans = KYCAnswers(q1=3, q2=5, q3=7, q4=9, q5=3)
        assert (ans.q1, ans.q2, ans.q3, ans.q4, ans.q5) == (3, 5, 7, 9, 3)

    def test_ordinal_ints_normalize(self):
        # 序号 1/2/4 与值集 {3,5,7,9} 无交集，安全按序号归一
        ans = KYCAnswers(q1=1, q2=2, q3=4, q4=1, q5=2)
        assert (ans.q1, ans.q2, ans.q3, ans.q4, ans.q5) == (3, 5, 9, 3, 5)

    def test_circled_digits_normalize(self):
        # 带圈字符一律按序号解释（①→3 ②→5 ③→7 ④→9）
        ans = KYCAnswers(q1="①", q2="②", q3="③", q4="④", q5="③")
        assert (ans.q1, ans.q2, ans.q3, ans.q4, ans.q5) == (3, 5, 7, 9, 7)

    def test_digit_strings_normalize(self):
        ans = KYCAnswers(q1="4", q2="3", q3="5", q4="7", q5="9")
        assert (ans.q1, ans.q2, ans.q3, ans.q4, ans.q5) == (9, 3, 5, 7, 9)

    def test_incident_regression_circled_answers(self):
        # 2026-08-30 联调事故：客户端把选项序号 ④③③③② 当答案发来
        ans = KYCAnswers(q1="④", q2="③", q3="③", q4="③", q5="②")
        assert (ans.q1, ans.q2, ans.q3, ans.q4, ans.q5) == (9, 7, 7, 7, 5)

    def test_ambiguous_three_interpreted_as_value(self):
        # 3 同时是合法 value 与序号 3 —— 一律按 value 解释（文档写明）
        ans = KYCAnswers(q1=3, q2=3, q3=3, q4=3, q5=3)
        assert ans.q1 == 3

    def test_reject_invalid_value(self):
        with pytest.raises(ValidationError):
            KYCAnswers(q1=6, q2=5, q3=7, q4=7, q5=7)  # 6 不是 value 也不是序号

    def test_reject_fifth_circled(self):
        with pytest.raises(ValidationError):
            KYCAnswers(q1="⑤", q2=5, q3=7, q4=7, q5=7)  # 每题只有 4 个选项

    def test_reject_non_numeric_string(self):
        with pytest.raises(ValidationError):
            KYCAnswers(q1="加仓", q2=5, q3=7, q4=7, q5=7)

    def test_reject_missing_field(self):
        with pytest.raises(ValidationError):
            KYCAnswers(q1=7, q2=5, q3=7, q4=7)  # q5 missing


class TestQuestionnaireLadderGuard:
    def test_all_questions_share_canonical_ladder(self):
        """序号归一化依赖所有题的选项 value 都是升序 3/5/7/9。
        加新题或改值序时必须同步 types.py 的归一化表。"""
        from tradingagents.advisor.questionnaire import get_questionnaire

        for q in get_questionnaire().questions:
            values = [opt.value for opt in q.options]
            assert values == [3, 5, 7, 9], f"{q.id} 的选项 value 阶梯变了: {values}"


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
