import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def tmp_env(tmp_path: Path, monkeypatch):
    log = tmp_path / "memory" / "trading_memory.md"
    log.parent.mkdir(parents=True)
    monkeypatch.setenv("TRADINGAGENTS_MEMORY_LOG_PATH", str(log))
    reports = tmp_path / "reports"
    reports.mkdir()
    monkeypatch.setenv("TRADINGAGENTS_REPORTS_DIR", str(reports))
    monkeypatch.setenv("HOME", str(tmp_path))
    return {"log": log, "reports": reports, "home": tmp_path}


def _run(*args):
    import os
    return subprocess.run(
        [".venv/bin/python", "-m", "cli.main", *args],
        capture_output=True, text=True,
        env={"TRADINGAGENTS_MEMORY_LOG_PATH": os.environ["TRADINGAGENTS_MEMORY_LOG_PATH"],
             "TRADINGAGENTS_REPORTS_DIR": os.environ["TRADINGAGENTS_REPORTS_DIR"],
             "HOME": os.environ["HOME"],
             "PATH": os.environ.get("PATH", "/usr/bin:/bin")},
    )


def _write_pending(log: Path):
    log.write_text("""[2026-08-01 | 000001 | Buy | pending]

DECISION:
buy

<!-- ENTRY_END -->
""", encoding="utf-8")


KYC = '{"q1":7,"q2":7,"q3":7,"q4":7,"q5":7}'


class TestReviewCLI:
    def test_no_pending_exit_0_empty(self, tmp_env):
        r = _run("review", "--json", "--kyc-json", KYC)
        assert r.returncode == 0, f"{r.stderr}\n{r.stdout}"
        payload = json.loads(r.stdout)
        assert payload["items"] == []
        assert payload["skipped"] == []

    def test_kyc_required_exit_3(self, tmp_env):
        _write_pending(tmp_env["log"])
        r = _run("review", "--json")
        assert r.returncode == 3
        payload = json.loads(r.stdout)
        assert payload["error"] == "kyc_required"
        assert len(payload["questionnaire"]["questions"]) == 5

    def test_invalid_kyc_exit_2(self, tmp_env):
        r = _run("review", "--json", "--kyc-json", '{"q1":4}')
        assert r.returncode == 2
        assert json.loads(r.stdout)["error"] == "invalid_kyc"

    def test_mutex_exit_5(self, tmp_env):
        r = _run("review", "--json", "--kyc-json", KYC, "--assume-neutral")
        assert r.returncode == 5

    def test_fake_quotes_no_scenario_exit_0(self, tmp_env):
        """pending 决策 + fake 行情成功 + 无制品 → no_scenario，exit 0。"""
        _write_pending(tmp_env["log"])
        r = _run("review", "--json", "--kyc-json", KYC,
                 "--fake-quotes", '{"000001": 8.9}')
        assert r.returncode == 0, f"{r.stderr}\n{r.stdout}"
        payload = json.loads(r.stdout)
        assert payload["skipped"][0]["reason"] == "no_scenario"

    def test_fake_quotes_empty_exit_6(self, tmp_env):
        """fake 行情为空 dict → quote_failed → exit 6（制品存在才能走到行情检查）。"""
        _write_pending(tmp_env["log"])
        (tmp_env["reports"] / "scenario_000001_2026-08-01.json").write_text(json.dumps({
            "version": 1, "ticker": "000001", "trade_date": "2026-08-01",
            "rating": "Buy",
            "scenario_buckets": [{
                "horizon_months": 6,
                "scenarios": [
                    {"name": "bull", "thesis": "t", "expected_return": 0.25, "prob": 0.35},
                    {"name": "base", "thesis": "t", "expected_return": 0.05, "prob": 0.45},
                    {"name": "bear", "thesis": "t", "expected_return": -0.15, "prob": 0.20},
                ],
                "key_levels": {"stop": 9.0, "entry_low": 9.5, "entry_high": 10.5,
                               "target": 12.0},
            }],
            "falsification": {"conditions": []},
        }), encoding="utf-8")
        r = _run("review", "--json", "--kyc-json", KYC, "--fake-quotes", "{}")
        assert r.returncode == 6
        payload = json.loads(r.stdout)
        assert payload["skipped"][0]["reason"] == "quote_failed"

    def test_fake_quotes_full_check(self, tmp_env):
        """制品 + fake 行情止损价 → 完整检查路径 + w* hint。"""
        _write_pending(tmp_env["log"])
        (tmp_env["reports"] / "scenario_000001_2026-08-01.json").write_text(json.dumps({
            "version": 1, "ticker": "000001", "trade_date": "2026-08-01",
            "rating": "Buy",
            "scenario_buckets": [{
                "horizon_months": 6,
                "scenarios": [
                    {"name": "bull", "thesis": "t", "expected_return": 0.25, "prob": 0.35},
                    {"name": "base", "thesis": "t", "expected_return": 0.05, "prob": 0.45},
                    {"name": "bear", "thesis": "t", "expected_return": -0.15, "prob": 0.20},
                ],
                "key_levels": {"stop": 9.0, "entry_low": 9.5, "entry_high": 10.5,
                               "target": 12.0},
            }],
            "falsification": {"conditions": ["watch X"]},
        }), encoding="utf-8")
        r = _run("review", "--json", "--kyc-json", KYC,
                 "--fake-quotes", '{"000001": 8.9}')
        assert r.returncode == 0, f"{r.stderr}\n{r.stdout}"
        payload = json.loads(r.stdout)
        assert len(payload["items"]) == 1
        item = payload["items"][0]
        assert item["checks"][0]["stop_triggered"] is True
        assert item["checks"][0]["w_star_hint"] is not None
        assert payload["manual_checklist"] == ["watch X"]
