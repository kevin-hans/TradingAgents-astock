from datetime import date

from tradingagents.advisor.review import BucketCheck, build_review_item, check_bucket
from tradingagents.advisor.scenario_io import ScenarioArtifact
from tradingagents.agents.schemas import Falsification, KeyLevels, Scenario, ScenarioBucket


def _bucket(horizon=6, stop=9.0, target=12.0) -> ScenarioBucket:
    return ScenarioBucket(
        horizon_months=horizon,
        scenarios=[
            Scenario(name="bull", thesis="t", expected_return=0.25, prob=0.35),
            Scenario(name="base", thesis="t", expected_return=0.05, prob=0.45),
            Scenario(name="bear", thesis="t", expected_return=-0.15, prob=0.20),
        ],
        key_levels=KeyLevels(stop=stop, entry_low=9.5, entry_high=10.5, target=target),
    )


class TestCheckBucket:
    def test_stop_triggered(self):
        r = check_bucket(_bucket(), price=8.9, today=date(2026, 8, 30),
                         analysis_date=date(2026, 8, 1), p0=10.0)
        assert r.stop_triggered is True
        assert r.target_hit is False

    def test_stop_boundary_inclusive(self):
        r = check_bucket(_bucket(), price=9.0, today=date(2026, 8, 30),
                         analysis_date=date(2026, 8, 1), p0=10.0)
        assert r.stop_triggered is True

    def test_target_hit(self):
        r = check_bucket(_bucket(), price=12.1, today=date(2026, 8, 30),
                         analysis_date=date(2026, 8, 1), p0=10.0)
        assert r.target_hit is True
        assert r.stop_triggered is False

    def test_target_boundary_inclusive(self):
        r = check_bucket(_bucket(), price=12.0, today=date(2026, 8, 30),
                         analysis_date=date(2026, 8, 1), p0=10.0)
        assert r.target_hit is True

    def test_neither_triggered(self):
        r = check_bucket(_bucket(), price=10.5, today=date(2026, 8, 30),
                         analysis_date=date(2026, 8, 1), p0=10.0)
        assert r.stop_triggered is False
        assert r.target_hit is False

    def test_horizon_expired(self):
        r = check_bucket(_bucket(horizon=6), price=10.0, today=date(2026, 8, 30),
                         analysis_date=date(2026, 1, 15), p0=10.0)
        assert r.horizon_expired is True

    def test_horizon_not_expired_same_day(self):
        r = check_bucket(_bucket(horizon=6), price=10.0, today=date(2026, 7, 15),
                         analysis_date=date(2026, 1, 15), p0=10.0)
        assert r.horizon_expired is False

    def test_horizon_month_rollover(self):
        r = check_bucket(_bucket(horizon=1), price=10.0, today=date(2026, 3, 1),
                         analysis_date=date(2026, 1, 31), p0=10.0)
        assert r.horizon_expired is True

    def test_fresh_warning_over_5pct(self):
        r = check_bucket(_bucket(), price=10.6, today=date(2026, 8, 30),
                         analysis_date=date(2026, 8, 1), p0=10.0)
        assert r.fresh_warning is True

    def test_fresh_warning_boundary(self):
        r = check_bucket(_bucket(), price=10.5, today=date(2026, 8, 30),
                         analysis_date=date(2026, 8, 1), p0=10.0)
        assert r.fresh_warning is False

    def test_fresh_warning_downward(self):
        r = check_bucket(_bucket(), price=9.4, today=date(2026, 8, 30),
                         analysis_date=date(2026, 8, 1), p0=10.0)
        assert r.fresh_warning is True

    def test_fresh_warning_none_p0(self):
        r = check_bucket(_bucket(), price=10.0, today=date(2026, 8, 30),
                         analysis_date=date(2026, 8, 1), p0=None)
        assert r.fresh_warning is None

    def test_w_star_hint_default_none(self):
        r = check_bucket(_bucket(), price=10.0, today=date(2026, 8, 30),
                         analysis_date=date(2026, 8, 1), p0=10.0)
        assert r.w_star_hint is None


def _artifact(falsify=("cond1", "cond2")) -> ScenarioArtifact:
    return ScenarioArtifact(
        version=1, ticker="000001", trade_date="2026-08-01", rating="Buy",
        scenario_buckets=[_bucket(horizon=6, stop=9.0, target=12.0)],
        falsification=Falsification(conditions=list(falsify)) if falsify else None,
    )


class TestBuildReviewItem:
    def test_assembles_from_entry_and_artifact(self):
        entry = {"date": "2026-08-01", "ticker": "000001", "rating": "Buy"}
        item = build_review_item(
            entry, _artifact(), price=10.5, p0=10.0, today=date(2026, 8, 30),
        )
        assert item.ticker == "000001"
        assert item.date == "2026-08-01"
        assert item.price == 10.5
        assert item.p0 == 10.0
        assert len(item.checks) == 1
        assert item.falsification == ["cond1", "cond2"]

    def test_multiple_buckets(self):
        artifact = _artifact()
        artifact.scenario_buckets.append(_bucket(horizon=12, stop=8.5, target=14.0))
        entry = {"date": "2026-08-01", "ticker": "000001", "rating": "Buy"}
        item = build_review_item(entry, artifact, price=10.5, p0=10.0,
                                 today=date(2026, 8, 30))
        assert len(item.checks) == 2
        assert item.checks[0].horizon_months == 6
        assert item.checks[1].horizon_months == 12

    def test_no_falsification_empty_list(self):
        entry = {"date": "2026-08-01", "ticker": "000001", "rating": "Buy"}
        item = build_review_item(
            entry, _artifact(falsify=None), price=10.5, p0=10.0, today=date(2026, 8, 30),
        )
        assert item.falsification == []

    def test_stop_price_populates_checks(self):
        entry = {"date": "2026-08-01", "ticker": "000001", "rating": "Buy"}
        item = build_review_item(
            entry, _artifact(), price=8.9, p0=10.0, today=date(2026, 8, 30),
        )
        assert item.checks[0].stop_triggered is True
