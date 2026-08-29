# tests/test_pm_scenario_wiring.py
"""PM wiring: typed capture, validate -> retry-once -> degrade, state stash."""
from unittest.mock import MagicMock

import pytest

from tradingagents.agents.schemas import PortfolioDecision, PortfolioRating
from tests.test_scenario_schemas import _decision


def _state():
    risk_state = {
        "history": "aggressive: risk priced in; conservative: ATR too high",
        "aggressive_history": "a", "conservative_history": "c", "neutral_history": "n",
        "latest_speaker": "Conservative",
        "current_aggressive_response": "", "current_conservative_response": "",
        "current_neutral_response": "", "count": 1, "judge_decision": "",
    }
    return {
        "company_of_interest": "600519",
        "trade_date": "2026-08-25",
        "investment_plan": "**Recommendation**: Hold",
        "trader_investment_plan": "**Action**: Hold",
        "risk_debate_state": risk_state,
        "past_context": "",
    }


def _llm(returning):
    llm = MagicMock()
    response = MagicMock()
    response.content = returning
    llm.invoke.return_value = response
    return llm


@pytest.mark.unit
class TestPMScenarioWiring:
    def _run(self, structured_obj_sequence, monkeypatch=None):
        import tradingagents.agents.managers.portfolio_manager as pmm
        structured = MagicMock()
        structured.invoke.side_effect = list(structured_obj_sequence)
        original = pmm.bind_structured
        pmm.bind_structured = lambda llm, schema, name: structured
        try:
            node = pmm.create_portfolio_manager(_llm("free text fallback"))
        finally:
            pmm.bind_structured = original
        return node(_state()), structured

    def test_valid_tree_stashed_to_state(self, monkeypatch):
        import tradingagents.agents.managers.portfolio_manager as pmm
        good = _decision()
        monkeypatch.setattr(pmm, "validate_scenario_tree", lambda d, p0: [])
        monkeypatch.setattr(pmm, "fetch_p0", lambda t, d: 1500.0)
        out, structured = self._run([good])
        assert out["scenario_tree"]["decision"]["rating"] == "Underweight"
        assert out["scenario_tree"]["scenario_meta"]["available"] is True
        assert "unanchored" not in out["scenario_tree"]["scenario_meta"]
        assert structured.invoke.call_count == 1
        assert "**Scenario Tree**:" in out["final_trade_decision"]

    def test_violations_retry_once_then_accept(self, monkeypatch):
        import tradingagents.agents.managers.portfolio_manager as pmm
        good = _decision()
        results = iter([["6M: bad"], []])
        monkeypatch.setattr(pmm, "validate_scenario_tree", lambda d, p0: next(results))
        monkeypatch.setattr(pmm, "fetch_p0", lambda t, d: None)
        out, structured = self._run([good, good])
        assert structured.invoke.call_count == 2  # 原始 + 重问一次
        assert out["scenario_tree"]["scenario_meta"]["available"] is True
        assert out["scenario_tree"]["scenario_meta"]["unanchored"] is True
        # 重问 prompt 携带违例说明
        second_call = structured.invoke.call_args_list[1]
        assert "6M: bad" in str(second_call)

    def test_retry_failure_degrades_tree(self, monkeypatch):
        import tradingagents.agents.managers.portfolio_manager as pmm
        good = _decision()
        monkeypatch.setattr(pmm, "validate_scenario_tree", lambda d, p0: ["always bad"])
        monkeypatch.setattr(pmm, "fetch_p0", lambda t, d: 1500.0)
        out, structured = self._run([good, good])
        assert structured.invoke.call_count == 2
        assert out["scenario_tree"]["decision"]["scenario_buckets"] == []
        assert out["scenario_tree"]["decision"]["falsification"] is None
        assert out["scenario_tree"]["scenario_meta"]["available"] is False
        assert out["scenario_tree"]["scenario_meta"]["degraded"] == ["always bad"]
        assert "**Scenario Tree**:" not in out["final_trade_decision"]

    def test_no_tree_no_validation_no_meta(self, monkeypatch):
        import tradingagents.agents.managers.portfolio_manager as pmm
        bare = _decision(with_tree=False)
        v = MagicMock(return_value=["should not be called"])
        monkeypatch.setattr(pmm, "validate_scenario_tree", v)
        out, structured = self._run([bare])
        v.assert_not_called()
        assert out["scenario_tree"]["decision"]["scenario_buckets"] == []
        assert out["scenario_tree"]["scenario_meta"]["available"] is False

    def test_freetext_fallback_stashes_none(self):
        import tradingagents.agents.managers.portfolio_manager as pmm
        original = pmm.bind_structured
        pmm.bind_structured = lambda llm, schema, name: None
        try:
            node = pmm.create_portfolio_manager(_llm("free text"))
        finally:
            pmm.bind_structured = original
        out = node(_state())
        assert out["final_trade_decision"] == "free text"
        assert out["scenario_tree"] is None

    def test_unexpected_validator_exception_never_breaks_node(self, monkeypatch):
        import tradingagents.agents.managers.portfolio_manager as pmm
        good = _decision()

        def boom(decision, p0):
            raise ZeroDivisionError("p0 was 0")
        monkeypatch.setattr(pmm, "validate_scenario_tree", boom)
        monkeypatch.setattr(pmm, "fetch_p0", lambda t, d: 0.0)
        out, structured = self._run([good])
        assert out["scenario_tree"]["scenario_meta"]["available"] is False
        assert any("unexpected error" in v for v in out["scenario_tree"]["scenario_meta"]["degraded"])
        assert out["scenario_tree"]["decision"]["scenario_buckets"] == []
        assert "**Scenario Tree**:" not in out["final_trade_decision"]
        assert out["final_trade_decision"].startswith("**Rating**")
