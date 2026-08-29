# tests/test_scenario_check.py
"""Full violation matrix for the scenario validator (spec §4.3).

照 CLAUDE.md 评级边界三轮返工的教训：枚举所有违例形状跑整张矩阵，
不是只测自己想到的一两个用例。
"""
import pytest

from tradingagents.agents.schemas import PortfolioDecision, PortfolioRating
from tradingagents.agents.utils.scenario_check import (
    fetch_p0,
    parse_horizon_months,
    validate_scenario_tree,
)

from tests.test_scenario_schemas import _bucket, _decision

P0 = 1500.0


def _anchored_bucket(horizon, rating_sign=-1):
    # stop=1365 → -9%; entry 1440-1500; target=1785 → +19%
    # rating_sign < 0: bearish (bear prob >= bull prob)
    # rating_sign > 0: bullish (bull prob >= bear prob)
    if rating_sign < 0:
        # For bearish: need mu ≤ +2%
        # Using returns: bull=+19%, base=-2%, bear=-9%
        # With probs 0.20, 0.45, 0.35 → mu = 0.20*0.19 + 0.45*(-0.02) + 0.35*(-0.09) = 0.038 - 0.009 - 0.0315 = -0.0025
        p_bull, p_base, p_bear = 0.20, 0.45, 0.35
        bull_return = 0.19
        base_return = -0.02
        bear_return = -0.09
    else:
        # For bullish: need mu > 0%
        # Using returns: bull=+19%, base=+4%, bear=-9%
        # With probs 0.35, 0.40, 0.25 → mu = 0.35*0.19 + 0.40*0.04 + 0.25*(-0.09) = 0.0665 + 0.016 - 0.0225 = 0.06
        p_bull, p_base, p_bear = 0.35, 0.40, 0.25
        bull_return = 0.19
        base_return = 0.04
        bear_return = -0.09
    return _bucket(
        horizon,
        bull=bull_return, base=base_return, bear=bear_return,
        p_bull=p_bull, p_base=p_base, p_bear=p_bear,
        stop=1365.0, entry_low=1440.0, entry_high=1500.0, target=1785.0,
    )


@pytest.mark.unit
class TestParseHorizonMonths:
    @pytest.mark.parametrize("text,expected", [
        ("3-6 months", 6), ("6-12个月", 12), ("1-2 years", 24),
        ("3-6 Months", 6), ("", 6), (None, 6), ("garbage", 6),
    ])
    def test_parse(self, text, expected):
        assert parse_horizon_months(text) == expected


@pytest.mark.unit
class TestValidateScenarioTree:
    def _valid(self, rating=PortfolioRating.UNDERWEIGHT):
        d = _decision()
        d.rating = rating
        d.scenario_buckets = [_anchored_bucket(6), _anchored_bucket(12)]
        return d

    def test_valid_bearish(self):
        assert validate_scenario_tree(self._valid(), P0) == []

    def test_valid_bullish(self):
        d = self._valid(rating=PortfolioRating.OVERWEIGHT)
        d.scenario_buckets = [_anchored_bucket(6, 1), _anchored_bucket(12, 1)]
        assert validate_scenario_tree(d, P0) == []

    def test_empty_tree_reports_missing(self):
        assert validate_scenario_tree(_decision(with_tree=False), P0) == ["scenario tree missing"]

    def test_wrong_horizons(self):
        d = self._valid()
        d.scenario_buckets[1].horizon_months = 24
        assert any("horizons" in v for v in validate_scenario_tree(d, P0))

    def test_prob_sum_off(self):
        d = self._valid()
        d.scenario_buckets[0].scenarios[0].prob = 0.40  # sum 1.10
        assert any("sum" in v for v in validate_scenario_tree(d, P0))

    def test_base_prob_out_of_range(self):
        d = self._valid()
        s = d.scenario_buckets[0].scenarios
        s[0].prob, s[1].prob, s[2].prob = 0.30, 0.60, 0.10
        assert any("base prob" in v for v in validate_scenario_tree(d, P0))

    def test_not_monotonic(self):
        d = self._valid()
        d.scenario_buckets[0].scenarios[1].expected_return = -0.20  # base < bear
        assert any("bull > base > bear" in v for v in validate_scenario_tree(d, P0))

    def test_levels_order_violated(self):
        d = self._valid()
        d.scenario_buckets[0].key_levels.stop = 1600.0
        assert any("stop < entry" in v for v in validate_scenario_tree(d, P0))

    def test_bear_anchor_drift(self):
        d = self._valid()
        d.scenario_buckets[0].scenarios[2].expected_return = -0.30  # vs stop anchor -9%
        assert any("not anchored to stop" in v for v in validate_scenario_tree(d, P0))

    def test_bull_anchor_drift(self):
        d = self._valid()
        d.scenario_buckets[0].scenarios[0].expected_return = 0.50  # vs target anchor +19%
        assert any("not anchored to target" in v for v in validate_scenario_tree(d, P0))

    def test_anchor_skipped_when_p0_none(self):
        d = self._valid()
        d.scenario_buckets[0].scenarios[2].expected_return = -0.30
        vs = validate_scenario_tree(d, None)
        assert not any("anchored" in v for v in vs)

    def test_direction_contradiction_bearish_rating_positive_mu(self):
        d = self._valid()  # Underweight
        d.scenario_buckets[0].scenarios[0].expected_return = 0.60
        d.scenario_buckets[0].scenarios[0].prob = 0.40
        d.scenario_buckets[0].scenarios[2].prob = 0.10  # mu > +2% on main bucket
        assert any("contradicts rating" in v for v in validate_scenario_tree(d, None))

    def test_direction_contradiction_bullish_rating_negative_mu(self):
        d = self._valid(rating=PortfolioRating.OVERWEIGHT)
        for b in d.scenario_buckets:
            b.scenarios[0].expected_return = 0.02
            b.scenarios[1].expected_return = 0.01
            b.scenarios[2].expected_return = -0.30
        assert any("contradicts rating" in v for v in validate_scenario_tree(d, None))

    def test_probability_direction_rule(self):
        d = self._valid()  # Underweight, but anchored bucket gives bear==bull
        d.scenario_buckets[0].scenarios[0].prob = 0.45
        d.scenario_buckets[0].scenarios[2].prob = 0.05
        d.scenario_buckets[0].scenarios[1].prob = 0.50
        assert any("P(bear)" in v for v in validate_scenario_tree(d, None))


@pytest.mark.unit
class TestFetchP0:
    def test_returns_none_on_any_failure(self, monkeypatch):
        def mock_sina(*a, **k):
            raise RuntimeError("net")
        monkeypatch.setattr(
            "tradingagents.dataflows.a_stock._sina_kline_fallback",
            mock_sina
        )
        assert fetch_p0("600519", "2026-08-25") is None

    def test_picks_last_close_on_or_before_date(self, monkeypatch):
        import pandas as pd
        df = pd.DataFrame({
            "Date": pd.to_datetime(["2026-08-24", "2026-08-25", "2026-08-26"]),
            "Close": [10.0, 11.0, 12.0],
        })
        monkeypatch.setattr(
            "tradingagents.dataflows.a_stock._sina_kline_fallback",
            lambda *a, **k: df
        )
        assert fetch_p0("600519", "2026-08-25") == 11.0
