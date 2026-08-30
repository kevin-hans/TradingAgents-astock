"""TDD tests for `analyze --json + --confirm + --depth` two-phase semantics."""
import json
import subprocess

import pytest


def _run(*args):
    return subprocess.run(
        [".venv/bin/python", "-m", "cli.main", *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


class TestAnalyzeEstimate:
    def test_estimate_full_returns_json(self):
        r = _run("analyze", "--json", "--depth", "full")
        assert r.returncode == 0, f"stderr={r.stderr}"
        payload = json.loads(r.stdout)
        assert "estimated_llm_calls" in payload
        assert "estimated_seconds" in payload
        assert payload["mode"] == "estimate"
        assert payload["depth"] == "full"

    def test_estimate_quick(self):
        r = _run("analyze", "--json", "--depth", "quick")
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        assert payload["depth"] == "quick"
        assert payload["estimated_llm_calls"] < 10

    def test_estimate_analyst(self):
        r = _run("analyze", "--json", "--depth", "analyst")
        assert r.returncode == 0
        payload = json.loads(r.stdout)
        assert payload["depth"] == "analyst"

    def test_invalid_depth_rejected(self):
        r = _run("analyze", "--json", "--depth", "bogus")
        assert r.returncode != 0


class TestAnalyzeConfirmHeadless:
    """Tests for --json --confirm (headless execution path)."""

    def test_json_confirm_missing_ticker_returns_error(self):
        """--json --confirm without ticker → JSON error + exit 2."""
        r = _run("analyze", "--json", "--confirm")
        assert r.returncode == 2
        payload = json.loads(r.stdout)
        assert payload["error"] == "missing_ticker"

    def test_json_confirm_depth_analyst_requires_single_analyst(self):
        """--depth=analyst without --single-analyst → bad_parameter error."""
        r = _run("analyze", "600519", "--json", "--confirm", "--depth", "analyst")
        assert r.returncode == 2
        payload = json.loads(r.stdout)
        assert payload["error"] == "bad_parameter"
        assert "single-analyst" in payload["message"].lower()

    def test_json_confirm_depth_analyst_invalid_role(self):
        """--single-analyst=bogus → bad_parameter error."""
        r = _run(
            "analyze", "600519", "--json", "--confirm",
            "--depth", "analyst", "--single-analyst", "bogus",
        )
        assert r.returncode == 2
        payload = json.loads(r.stdout)
        assert payload["error"] == "bad_parameter"
        assert "bogus" in payload["message"]


class TestAnalyzeConfirmMocked:
    """Tests that mock run_analysis_headless to avoid real LLM calls."""

    def test_json_confirm_success(self, monkeypatch):
        """Mocked headless run → mode=result + exit 0."""
        import cli.main as m

        fake_result = {
            "mode": "result",
            "ticker": "600519",
            "analysis_date": "2026-08-29",
            "rating": "Buy",
            "final_trade_decision": "test decision",
            "scenario_tree": None,
            "stats": {
                "llm_calls": 5,
                "tool_calls": 10,
                "tokens_in": 1000,
                "tokens_out": 500,
                "elapsed_seconds": 30.0,
            },
            "artifacts_dir": "/tmp/results/600519/2026-08-29",
        }
        monkeypatch.setattr(m, "run_analysis_headless", lambda **kw: fake_result)

        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(
            m.app,
            ["analyze", "600519", "--json", "--confirm", "--date", "2026-08-29"],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["mode"] == "result"
        assert payload["rating"] == "Buy"
        assert payload["depth"] == "full"

    def test_json_confirm_artifacts_exist(self, monkeypatch):
        """Existing artifacts without --force → artifacts_exist error + exit 1."""
        import cli.main as m

        fake_result = {
            "error": "artifacts_exist",
            "message": "已有研报制品",
            "artifacts": ["/tmp/a.json"],
        }
        monkeypatch.setattr(m, "run_analysis_headless", lambda **kw: fake_result)

        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(
            m.app,
            ["analyze", "600519", "--json", "--confirm", "--date", "2026-08-29"],
        )
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["error"] == "artifacts_exist"

    def test_json_confirm_execution_error(self, monkeypatch):
        """Exception in run_analysis_headless → execution_failed + exit 1."""
        import cli.main as m

        def _boom(**kw):
            raise RuntimeError("LLM connection failed")

        monkeypatch.setattr(m, "run_analysis_headless", _boom)

        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(
            m.app,
            ["analyze", "600519", "--json", "--confirm", "--date", "2026-08-29"],
        )
        assert result.exit_code == 1
        payload = json.loads(result.output)
        assert payload["error"] == "execution_failed"
        assert "LLM connection failed" in payload["message"]

    def test_json_confirm_date_defaults_to_today(self, monkeypatch):
        """Without --date, analysis_date should default to today."""
        import cli.main as m
        import datetime

        captured_kwargs = {}

        def _capture(**kw):
            captured_kwargs.update(kw)
            return {"mode": "result", "ticker": kw["ticker"],
                    "analysis_date": kw["analysis_date"], "rating": "Hold",
                    "final_trade_decision": "", "scenario_tree": None,
                    "stats": {"llm_calls": 0, "tool_calls": 0,
                              "tokens_in": 0, "tokens_out": 0,
                              "elapsed_seconds": 0},
                    "artifacts_dir": "/tmp"}

        monkeypatch.setattr(m, "run_analysis_headless", _capture)

        from typer.testing import CliRunner
        runner = CliRunner()
        result = runner.invoke(
            m.app,
            ["analyze", "600519", "--json", "--confirm"],
        )
        assert result.exit_code == 0, result.output
        assert captured_kwargs["analysis_date"] == datetime.date.today().isoformat()


class TestAnalyzeDefaultCompat:
    def test_help_still_lists_analyze(self):
        r = subprocess.run(
            [".venv/bin/python", "-m", "cli.main", "--help"],
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0
        assert "analyze" in r.stdout

    def test_positional_ticker_accepted_in_estimate_mode(self):
        """CLI analyze 现在接受可选位置 ticker（v1 用于 MCP 兼容，交互式内部依然收 ticker）。"""
        r = _run("analyze", "000001", "--json", "--depth", "full")
        assert r.returncode == 0, r.stderr
        payload = json.loads(r.stdout)
        assert payload["mode"] == "estimate"
