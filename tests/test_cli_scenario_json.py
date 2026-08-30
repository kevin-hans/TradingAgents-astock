import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def tmp_reports(tmp_path: Path):
    reports = tmp_path / "reports"
    reports.mkdir()
    return reports


def _write_scenario(reports: Path, ticker="000001", date="2026-08-30"):
    (reports / f"scenario_{ticker}_{date}.json").write_text(json.dumps({
        "version": 1, "ticker": ticker, "trade_date": date, "rating": "Buy",
        "scenario_buckets": [{
            "horizon_months": 6,
            "scenarios": [
                {"name": "bull", "thesis": "t", "expected_return": 0.25, "prob": 0.35},
                {"name": "base", "thesis": "t", "expected_return": 0.05, "prob": 0.45},
                {"name": "bear", "thesis": "t", "expected_return": -0.15, "prob": 0.20},
            ],
            "key_levels": {"stop": 8.5, "entry_low": 9.5, "entry_high": 10.5, "target": 12.5},
        }],
        "falsification": {"conditions": ["cond"]},
    }), encoding="utf-8")


def _run(reports: Path, *args):
    import os
    return subprocess.run(
        [".venv/bin/python", "-m", "cli.main", *args],
        capture_output=True, text=True,
        env={"TRADINGAGENTS_REPORTS_DIR": str(reports),
             "HOME": str(reports.parent),
             "PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    )


class TestScenarioJSON:
    def test_json_output(self, tmp_reports):
        _write_scenario(tmp_reports)
        r = _run(tmp_reports, "scenario", "000001", "--json")
        assert r.returncode == 0, r.stderr
        payload = json.loads(r.stdout)
        assert payload["ticker"] == "000001"
        assert payload["scenario_buckets"][0]["horizon_months"] == 6
        assert len(payload["scenario_buckets"][0]["scenarios"]) == 3

    def test_missing_returns_not_found(self, tmp_reports):
        r = _run(tmp_reports, "scenario", "999999", "--json")
        assert r.returncode == 1
        payload = json.loads(r.stdout)
        assert payload["error"] == "not_found"

    def test_specific_date(self, tmp_reports):
        _write_scenario(tmp_reports, date="2026-08-25")
        _write_scenario(tmp_reports, date="2026-08-30")
        r = _run(tmp_reports, "scenario", "000001", "--json", "--date", "2026-08-25")
        assert r.returncode == 0
        assert json.loads(r.stdout)["trade_date"] == "2026-08-25"
