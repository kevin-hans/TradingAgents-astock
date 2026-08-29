import json
import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def tmp_env(tmp_path: Path):
    reports = tmp_path / "reports"
    reports.mkdir()
    return {"reports": reports, "home": tmp_path}


def _write_scenario(env, ticker="000001", date="2026-08-30"):
    (env["reports"] / f"scenario_{ticker}_{date}.json").write_text(json.dumps({
        "version": 1,
        "ticker": ticker,
        "trade_date": date,
        "rating": "Buy",
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


def _write_profile(env):
    profile_dir = env["home"] / ".tradingagents"
    profile_dir.mkdir(exist_ok=True)
    (profile_dir / "profile.json").write_text(json.dumps({
        "schema_version": 1,
        "kyc_answers": {"q1": 7, "q2": 7, "q3": 7, "q4": 7, "q5": 7},
    }), encoding="utf-8")


def _run(env, *args, extra_env: dict[str, str] | None = None):
    import os
    e = {
        "TRADINGAGENTS_REPORTS_DIR": str(env["reports"]),
        "HOME": str(env["home"]),
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }
    if extra_env:
        e.update(extra_env)
    return subprocess.run(
        [".venv/bin/python", "-m", "cli.main", *args],
        capture_output=True, text=True, env=e,
    )


class TestAdviseJSON:
    def test_json_output_success(self, tmp_env):
        _write_scenario(tmp_env)
        _write_profile(tmp_env)
        r = _run(tmp_env, "advise", "000001", "--json")
        assert r.returncode == 0, f"stderr={r.stderr}\nstdout={r.stdout}"
        payload = json.loads(r.stdout)
        assert payload["ticker"] == "000001"
        assert payload["schema_version"] == 1
        assert "with_position" in payload
        assert "trace" in payload

    def test_missing_scenario_returns_not_found(self, tmp_env):
        _write_profile(tmp_env)
        r = _run(tmp_env, "advise", "999999", "--json")
        assert r.returncode != 0
        payload = json.loads(r.stdout)
        assert payload["error"] == "not_found"

    def test_missing_profile_returns_kyc_required(self, tmp_env):
        _write_scenario(tmp_env)
        r = _run(tmp_env, "advise", "000001", "--json")
        assert r.returncode != 0
        payload = json.loads(r.stdout)
        assert payload["error"] == "kyc_required"
        assert "questionnaire" in payload
        assert len(payload["questionnaire"]["questions"]) == 5

    def test_kyc_json_inline(self, tmp_env):
        _write_scenario(tmp_env)
        kyc = json.dumps({"q1": 3, "q2": 3, "q3": 3, "q4": 3, "q5": 3})
        r = _run(tmp_env, "advise", "000001", "--json", "--kyc-json", kyc)
        assert r.returncode == 0, f"stderr={r.stderr}\nstdout={r.stdout}"
        payload = json.loads(r.stdout)
        assert payload["ticker"] == "000001"

    def test_invalid_kyc_json(self, tmp_env):
        _write_scenario(tmp_env)
        r = _run(tmp_env, "advise", "000001", "--json", "--kyc-json", '{"q1": 4}')
        assert r.returncode != 0
        payload = json.loads(r.stdout)
        assert payload["error"] == "invalid_kyc"

    def test_assume_neutral(self, tmp_env):
        _write_scenario(tmp_env)
        r = _run(tmp_env, "advise", "000001", "--json", "--assume-neutral")
        assert r.returncode == 0, f"stderr={r.stderr}\nstdout={r.stdout}"
        payload = json.loads(r.stdout)
        assert payload["ticker"] == "000001"

    def test_specific_date(self, tmp_env):
        _write_profile(tmp_env)
        _write_scenario(tmp_env, date="2026-08-25")
        _write_scenario(tmp_env, date="2026-08-30")
        r = _run(tmp_env, "advise", "000001", "--json", "--date", "2026-08-25")
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        assert payload["date"] == "2026-08-25"


class TestAdviseCLIDefaultCompat:
    def test_help_lists_advise(self):
        r = subprocess.run(
            [".venv/bin/python", "-m", "cli.main", "--help"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0
        assert "advise" in r.stdout
