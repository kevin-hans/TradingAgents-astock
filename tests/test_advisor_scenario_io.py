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


class TestCloudFallback:
    def _fake_store(self, monkeypatch, payload_by_key):
        """返回一个可配置的假 CloudStore；payload_by_key 用 (ticker, date) 索引。"""
        class FakeStore:
            def is_configured(self):
                return True
            def download_scenario(self, ticker, date, target_path):
                payload = payload_by_key.get((ticker, date))
                if payload is None:
                    return False
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(json.dumps(payload), encoding="utf-8")
                return True
            def upload_scenario(self, *a, **kw):
                return True

        from tradingagents.advisor import scenario_io
        fake = FakeStore()
        monkeypatch.setattr(scenario_io, "get_store", lambda: fake)
        return fake

    def test_local_miss_triggers_cloud_download(self, tmp_reports, monkeypatch):
        """本地无 scenario、cloud 有 → 自动下载并加载成功。"""
        payload = {
            "version": 1, "ticker": "999999", "trade_date": "2026-09-01",
            "rating": "Hold",
            "scenario_buckets": [
                {
                    "horizon_months": 6,
                    "scenarios": [
                        {"name": "bull", "thesis": "t", "expected_return": 0.15, "prob": 0.3},
                        {"name": "base", "thesis": "t", "expected_return": 0.05, "prob": 0.5},
                        {"name": "bear", "thesis": "t", "expected_return": -0.05, "prob": 0.2},
                    ],
                    "key_levels": {"stop": 9, "entry_low": 10, "entry_high": 10, "target": 12},
                }
            ],
            "falsification": {"conditions": []},
        }
        self._fake_store(monkeypatch, {("999999", "2026-09-01"): payload})

        art = load_scenario("999999", date="2026-09-01")
        assert art.ticker == "999999"
        assert (tmp_reports / "999999" / "2026-09-01" / "scenario.json").exists()

    def test_local_miss_no_store_still_raises(self, tmp_reports, monkeypatch):
        from tradingagents.advisor import scenario_io
        monkeypatch.setattr(scenario_io, "get_store", lambda: None)
        with pytest.raises(ScenarioNotFoundError):
            load_scenario("999999", date="2026-09-01")

    def test_local_hit_skips_cloud(self, tmp_reports, monkeypatch):
        _write_scenario(tmp_reports, "000001", "2026-08-30")
        called = []

        class SpyStore:
            def is_configured(self):
                return True
            def download_scenario(self, ticker, date, target_path):
                called.append((ticker, date))
                return True
            def upload_scenario(self, *a, **kw):
                return True

        from tradingagents.advisor import scenario_io
        monkeypatch.setattr(scenario_io, "get_store", lambda: SpyStore())

        load_scenario("000001")
        assert called == []
