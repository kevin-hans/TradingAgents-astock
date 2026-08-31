import json
from pathlib import Path

import pytest

from tradingagents.advisor.scenario_io import (
    ScenarioArtifact,
    load_scenario,
    list_scenarios,
    ScenarioNotFoundError,
)


@pytest.fixture
def tmp_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setenv("TRADINGAGENTS_REPORTS_DIR", str(reports))
    return reports


def _write_scenario(reports: Path, ticker: str, date: str, mu: float = 0.05) -> Path:
    payload = {
        "version": 1,
        "ticker": ticker,
        "trade_date": date,
        "rating": "Hold",
        "scenario_buckets": [
            {
                "horizon_months": 6,
                "scenarios": [
                    {"name": "bull", "thesis": "t", "expected_return": mu + 0.1, "prob": 0.3},
                    {"name": "base", "thesis": "t", "expected_return": mu, "prob": 0.5},
                    {"name": "bear", "thesis": "t", "expected_return": mu - 0.1, "prob": 0.2},
                ],
                "key_levels": {"stop": 9, "entry_low": 10, "entry_high": 10, "target": 12},
            }
        ],
        "falsification": {"conditions": ["cond1"]},
    }
    d = reports / ticker / date
    d.mkdir(parents=True, exist_ok=True)
    p = d / "scenario.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


class TestLoadScenario:
    def test_load_latest(self, tmp_reports: Path):
        _write_scenario(tmp_reports, "000001", "2026-08-25")
        _write_scenario(tmp_reports, "000001", "2026-08-30")
        art = load_scenario("000001")
        assert art.trade_date == "2026-08-30"

    def test_load_specific_date(self, tmp_reports: Path):
        _write_scenario(tmp_reports, "000001", "2026-08-25")
        _write_scenario(tmp_reports, "000001", "2026-08-30")
        art = load_scenario("000001", date="2026-08-25")
        assert art.trade_date == "2026-08-25"

    def test_missing_ticker_raises(self, tmp_reports: Path):
        with pytest.raises(ScenarioNotFoundError):
            load_scenario("999999")

    def test_missing_date_raises(self, tmp_reports: Path):
        _write_scenario(tmp_reports, "000001", "2026-08-30")
        with pytest.raises(ScenarioNotFoundError):
            load_scenario("000001", date="2020-01-01")

    def test_load_from_standard_path(self, tmp_reports: Path):
        """正式路径 {results_dir}/{ticker}/{date}/scenario.json 可被找到。"""
        _write_scenario(tmp_reports, "000001", "2026-08-30")
        art = load_scenario("000001")
        assert art.trade_date == "2026-08-30"


class TestListScenarios:
    def test_list_by_ticker(self, tmp_reports: Path):
        _write_scenario(tmp_reports, "000001", "2026-08-25")
        _write_scenario(tmp_reports, "000001", "2026-08-30")
        _write_scenario(tmp_reports, "600000", "2026-08-30")
        entries = list_scenarios(ticker="000001")
        assert len(entries) == 2
        assert {e.trade_date for e in entries} == {"2026-08-25", "2026-08-30"}

    def test_list_all(self, tmp_reports: Path):
        _write_scenario(tmp_reports, "000001", "2026-08-30")
        _write_scenario(tmp_reports, "600000", "2026-08-30")
        entries = list_scenarios()
        assert len(entries) == 2

    def test_ignore_archived(self, tmp_reports: Path):
        _write_scenario(tmp_reports, "000001", "2026-08-30")
        (tmp_reports / "000001" / "2026-08-30" / "scenario.archived-20260828-120000.json").touch()
        entries = list_scenarios(ticker="000001")
        assert len(entries) == 1
