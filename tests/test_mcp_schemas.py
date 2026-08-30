import pytest
from pydantic import ValidationError

from tradingagents.mcp.schemas import (
    KYCAnswersIn,
    AnalyzeArgs,
    AdviseArgs,
    ReviewArgs,
    ScenarioArgs,
    ReportsArgs,
)


class TestKYCAnswersIn:
    def test_valid(self):
        a = KYCAnswersIn(q1=7, q2=5, q3=7, q4=7, q5=7)
        assert a.q1 == 7

    def test_ordinal_passes_through_to_cli(self):
        # 薄壳：MCP 层不解释答案语义（序号/带圈/值都透传，CLI 归一化）
        a = KYCAnswersIn(q1=4, q2="③", q3=7, q4=7, q5=7)
        assert a.q1 == 4
        assert a.q2 == "③"


class TestToolArgs:
    def test_analyze_defaults(self):
        a = AnalyzeArgs(ticker="000001")
        assert a.depth == "full"
        assert a.confirm is False
        assert a.force is False

    def test_analyze_invalid_depth(self):
        with pytest.raises(ValidationError):
            AnalyzeArgs(ticker="000001", depth="bogus")

    def test_advise_kyc_optional(self):
        a = AdviseArgs(ticker="000001")
        assert a.kyc_answers is None

    def test_review_kyc_optional(self):
        r = ReviewArgs()
        assert r.kyc_answers is None

    def test_scenario_minimal(self):
        s = ScenarioArgs(ticker="000001")
        assert s.date is None

    def test_reports_default_ticker_none(self):
        r = ReportsArgs()
        assert r.ticker is None
