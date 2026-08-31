"""analyze 命令的云端前置检查：cloud 有 → 下载 + 跳过 LLM。"""
import json

import pytest


def _fake_store_with_payload(payload):
    class FakeStore:
        def is_configured(self):
            return True
        def download_scenario(self, ticker, date, target_path):
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(json.dumps(payload), encoding="utf-8")
            return True
        def upload_scenario(self, *a, **kw):
            return True
    return FakeStore()


def test_headless_analyze_uses_cloud_when_available(tmp_path, monkeypatch):
    """cloud 命中 → 不跑 graph，直接返回 downloaded scenario 的评级。"""
    from tradingagents.default_config import DEFAULT_CONFIG
    from cli import main as cli_main
    from cli.main import run_analysis_headless

    monkeypatch.setitem(DEFAULT_CONFIG, "results_dir", str(tmp_path))

    payload = {
        "version": 1, "ticker": "600519", "trade_date": "2026-09-01",
        "rating": "Buy",
        "scenario_buckets": [{
            "horizon_months": 6,
            "scenarios": [
                {"name": "bull", "thesis": "t", "expected_return": 0.2, "prob": 0.3},
                {"name": "base", "thesis": "t", "expected_return": 0.05, "prob": 0.5},
                {"name": "bear", "thesis": "t", "expected_return": -0.1, "prob": 0.2},
            ],
            "key_levels": {"stop": 9, "entry_low": 10, "entry_high": 10, "target": 12},
        }],
        "falsification": {"conditions": []},
    }

    monkeypatch.setattr(cli_main, "get_store", lambda: _fake_store_with_payload(payload), raising=False)

    # graph 不该被构造
    def graph_ctor_should_not_be_called(*a, **kw):
        raise AssertionError("cloud 命中应跳过 graph 构造")
    monkeypatch.setattr(cli_main, "TradingAgentsGraph", graph_ctor_should_not_be_called)

    result = run_analysis_headless(
        ticker="600519", analysis_date="2026-09-01",
        analyst_keys=["market"], debate_rounds=0,
    )
    assert result["mode"] == "result"
    assert result["source"] == "cloud"
    assert result["rating"] == "Buy"
    assert result["ticker"] == "600519"


def test_headless_analyze_falls_through_when_no_store(tmp_path, monkeypatch):
    """无 store → 走原有 graph 分析路径（验证进了 graph 构造）。"""
    from tradingagents.default_config import DEFAULT_CONFIG
    from cli import main as cli_main
    from cli.main import run_analysis_headless

    monkeypatch.setitem(DEFAULT_CONFIG, "results_dir", str(tmp_path))
    monkeypatch.setattr(cli_main, "get_store", lambda: None, raising=False)

    ctor_called = []
    def fake_ctor(*a, **kw):
        ctor_called.append(1)
        raise RuntimeError("stop here — 只验证 ctor 被调用了")
    monkeypatch.setattr(cli_main, "TradingAgentsGraph", fake_ctor)

    with pytest.raises(RuntimeError, match="stop here"):
        run_analysis_headless(
            ticker="600519", analysis_date="2026-09-01",
            analyst_keys=["market"], debate_rounds=0,
        )
    assert ctor_called == [1]
