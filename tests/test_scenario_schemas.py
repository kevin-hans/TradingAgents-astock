# tests/test_scenario_schemas.py
"""Scenario tree schema models and rendering (spec §4.1)."""
import pytest

from tradingagents.agents.schemas import (
    Falsification,
    KeyLevels,
    PortfolioDecision,
    PortfolioRating,
    Scenario,
    ScenarioBucket,
    render_pm_decision,
)


def _bucket(horizon=6, *, bull=0.25, base=0.05, bear=-0.18,
            p_bull=0.30, p_base=0.45, p_bear=0.25,
            stop=1450.0, entry_low=1480.0, entry_high=1520.0, target=1750.0):
    return ScenarioBucket(
        horizon_months=horizon,
        scenarios=[
            Scenario(name="bull", thesis="多空辩论多方: 估值锚+资金回流", expected_return=bull, prob=p_bull),
            Scenario(name="base", thesis="综合裁决: 区间震荡", expected_return=base, prob=p_base),
            Scenario(name="bear", thesis="空方: 中报负增长+主力流出", expected_return=bear, prob=p_bear),
        ],
        key_levels=KeyLevels(stop=stop, entry_low=entry_low, entry_high=entry_high, target=target),
    )


def _decision(with_tree=True):
    return PortfolioDecision(
        rating=PortfolioRating.UNDERWEIGHT,
        executive_summary="证据偏空但非结构性利空。",
        investment_thesis="空方新增证据可信度高，牛方论据陈旧。",
        time_horizon="3-6 months",
        scenario_buckets=[_bucket(6), _bucket(12)] if with_tree else [],
        falsification=Falsification(conditions=["跌破 1450 且放量", "应收账款周转天数 > 90"]) if with_tree else None,
    )


@pytest.mark.unit
class TestScenarioModels:
    def test_scenario_name_literal_rejects_other(self):
        with pytest.raises(Exception):
            Scenario(name="moon", thesis="x", expected_return=0.1, prob=0.5)

    def test_decision_without_tree_renders_identical(self):
        md = render_pm_decision(_decision(with_tree=False))
        assert "**Rating**: Underweight" in md
        assert "Scenario Tree" not in md
        assert "Falsification" not in md

    def test_decision_with_tree_renders_sections(self):
        md = render_pm_decision(_decision())
        assert "**Scenario Tree**:" in md
        assert "6M:" in md and "12M:" in md
        assert "bull +25%" in md          # 0.25 → +25%
        assert "stop 1450" in md
        assert "**Falsification**:" in md
        assert "跌破 1450 且放量" in md

    def test_model_dump_json_mode_gives_plain_types(self):
        dumped = _decision().model_dump(mode="json")
        import json
        json.dumps(dumped)  # must not raise on enum/date
        assert dumped["rating"] == "Underweight"
        assert dumped["scenario_buckets"][0]["horizon_months"] == 6
