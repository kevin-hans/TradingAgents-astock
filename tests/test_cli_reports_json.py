import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def tmp_reports(tmp_path: Path):
    reports = tmp_path / "reports"
    reports.mkdir()
    return reports


def _write_scenario(reports: Path, ticker: str, date: str):
    d = reports / ticker / date
    d.mkdir(parents=True, exist_ok=True)
    (d / "scenario.json").write_text(json.dumps({
        "version": 1, "ticker": ticker, "trade_date": date, "rating": "Buy",
        "scenario_buckets": [{
            "horizon_months": 6,
            "scenarios": [
                {"name": "bull", "thesis": "t", "expected_return": 0.2, "prob": 0.3},
                {"name": "base", "thesis": "t", "expected_return": 0.05, "prob": 0.5},
                {"name": "bear", "thesis": "t", "expected_return": -0.1, "prob": 0.2},
            ],
            "key_levels": {"stop": 9, "entry_low": 10, "entry_high": 10, "target": 12},
        }],
        "falsification": {"conditions": ["c"]},
    }), encoding="utf-8")


def _run(reports: Path, *args):
    import os
    return subprocess.run(
        [".venv/bin/python", "-m", "cli.main", *args],
        capture_output=True, text=True,
        env={"TRADINGAGENTS_REPORTS_DIR": str(reports),
             "HOME": str(reports.parent),
             "PATH": os.environ.get("PATH", "/usr/bin:/bin")},
        cwd="/Users/kankan/dev/source/TradingAgents-astock",
    )


class TestReportsJSON:
    def test_empty(self, tmp_reports):
        r = _run(tmp_reports, "reports", "--json")
        assert r.returncode == 0, r.stderr
        assert json.loads(r.stdout) == {"reports": []}

    def test_list_all(self, tmp_reports):
        _write_scenario(tmp_reports, "000001", "2026-08-30")
        _write_scenario(tmp_reports, "600000", "2026-08-25")
        r = _run(tmp_reports, "reports", "--json")
        payload = json.loads(r.stdout)
        assert len(payload["reports"]) == 2
        assert {e["ticker"] for e in payload["reports"]} == {"000001", "600000"}

    def test_filter_by_ticker(self, tmp_reports):
        _write_scenario(tmp_reports, "000001", "2026-08-25")
        _write_scenario(tmp_reports, "000001", "2026-08-30")
        _write_scenario(tmp_reports, "600000", "2026-08-30")
        r = _run(tmp_reports, "reports", "--ticker", "000001", "--json")
        payload = json.loads(r.stdout)
        assert len(payload["reports"]) == 2
        assert all(e["ticker"] == "000001" for e in payload["reports"])
