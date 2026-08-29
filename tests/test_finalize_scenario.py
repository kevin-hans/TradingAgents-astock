# tests/test_finalize_scenario.py
"""Artifact persistence: scenario.json write + archive-on-rerun (spec §4.4/§7)."""
import json

import pytest

from tests.test_scenario_schemas import _decision


def _graph(tmp_path):
    from tradingagents.graph.trading_graph import TradingAgentsGraph
    g = object.__new__(TradingAgentsGraph)  # 绕过 LLM 初始化，只测持久化方法
    g.config = {"results_dir": str(tmp_path), "data_cache_dir": str(tmp_path / "cache")}
    g.ticker = "600519"
    g.log_states_dict = {}
    return g


def _final_state(with_tree=True):
    decision = _decision()
    return {
        "company_of_interest": "贵州茅台",
        "trade_date": "2026-08-25",
        "market_report": "market",
        "sentiment_report": "sentiment",
        "news_report": "news",
        "fundamentals_report": "fundamentals",
        "investment_debate_state": {
            "bull_history": [],
            "bear_history": [],
            "history": [],
            "current_response": "response",
            "judge_decision": "judge",
        },
        "trader_investment_plan": "trader_plan",
        "risk_debate_state": {
            "aggressive_history": [],
            "conservative_history": [],
            "neutral_history": [],
            "history": [],
            "judge_decision": "risk_judge",
        },
        "investment_plan": "plan",
        "final_trade_decision": "ignored",
        "scenario_tree": ({
            "decision": decision.model_dump(mode="json"),
            "scenario_meta": {"available": True},
        } if with_tree else None),
    }


class _MemoryStub:
    def __init__(self):
        self.calls = []

    def store_decision(self, **kw):
        self.calls.append(kw)


@pytest.mark.unit
class TestFinalizePersistence:
    def test_writes_scenario_artifact(self, tmp_path, monkeypatch):
        g = _graph(tmp_path)
        g.memory_log = _MemoryStub()
        monkeypatch.setattr(g, "process_signal", lambda s: "Sell", raising=False)
        g.finalize_graph_run("600519", "2026-08-25", _final_state())
        art = tmp_path / "600519" / "TradingAgentsStrategy_logs" / "scenario_600519_2026-08-25.json"
        assert art.exists()
        payload = json.loads(art.read_text())
        assert payload["version"] == 1
        assert payload["ticker"] == "600519"
        assert payload["trade_date"] == "2026-08-25"
        assert payload["rating"] == "Underweight"
        assert len(payload["scenario_buckets"]) == 2
        assert payload["scenario_meta"] == {"available": True}
        assert payload["generated_at"]

    def test_no_tree_no_artifact(self, tmp_path, monkeypatch):
        g = _graph(tmp_path)
        g.memory_log = _MemoryStub()
        monkeypatch.setattr(g, "process_signal", lambda s: "Sell", raising=False)
        g.finalize_graph_run("600519", "2026-08-25", _final_state(with_tree=False))
        log_dir = tmp_path / "600519" / "TradingAgentsStrategy_logs"
        fresh = [p for p in log_dir.glob("scenario_*.json") if "archived" not in p.name]
        assert fresh == []

    def test_full_states_log_contains_scenario_tree(self, tmp_path, monkeypatch):
        g = _graph(tmp_path)
        g.memory_log = _MemoryStub()
        monkeypatch.setattr(g, "process_signal", lambda s: "Sell", raising=False)
        g.finalize_graph_run("600519", "2026-08-25", _final_state())
        log = json.loads((tmp_path / "600519" / "TradingAgentsStrategy_logs" / "full_states_log_2026-08-25.json").read_text())
        assert log["scenario_tree"]["decision"]["rating"] == "Underweight"

    def test_rerun_archives_old_log_and_artifact(self, tmp_path, monkeypatch):
        g = _graph(tmp_path)
        g.memory_log = _MemoryStub()
        monkeypatch.setattr(g, "process_signal", lambda s: "Sell", raising=False)
        g.finalize_graph_run("600519", "2026-08-25", _final_state())
        g.finalize_graph_run("600519", "2026-08-25", _final_state())
        log_dir = tmp_path / "600519" / "TradingAgentsStrategy_logs"
        assert len(list(log_dir.glob("full_states_log_2026-08-25.archived-*.json"))) == 1
        assert len(list(log_dir.glob("scenario_600519_2026-08-25.archived-*.json"))) == 1
        assert (log_dir / "full_states_log_2026-08-25.json").exists()
        assert (log_dir / "scenario_600519_2026-08-25.json").exists()

    def test_checkpoint_config_absent_does_not_break(self, tmp_path, monkeypatch):
        g = _graph(tmp_path)  # config has no checkpoint_enabled key
        g.memory_log = _MemoryStub()
        monkeypatch.setattr(g, "process_signal", lambda s: "Sell", raising=False)
        g.finalize_graph_run("600519", "2026-08-25", _final_state())
        assert (tmp_path / "600519" / "TradingAgentsStrategy_logs" / "scenario_600519_2026-08-25.json").exists()
