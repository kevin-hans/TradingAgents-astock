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

    def test_reject_invalid_value(self):
        with pytest.raises(ValidationError):
            KYCAnswersIn(q1=4, q2=5, q3=7, q4=7, q5=7)


class TestToolArgs:
    def test_analyze_defaults(self):
        a = AnalyzeArgs(ticker="000001")
        assert a.depth == "full"
        assert a.confirm is False
        assert a.force is False

    def test_analyze_invalid_depth(self):
        with pytest.raises(ValidationError):
            AnalyzeArgs(ticker="000001", depth="bogus")

    def test_advise_requires_kyc(self):
        with pytest.raises(ValidationError):
            AdviseArgs(ticker="000001")

    def test_review_requires_kyc(self):
        with pytest.raises(ValidationError):
            ReviewArgs()

    def test_scenario_minimal(self):
        s = ScenarioArgs(ticker="000001")
        assert s.date is None

    def test_reports_default_ticker_none(self):
        r = ReportsArgs()
        assert r.ticker is None
