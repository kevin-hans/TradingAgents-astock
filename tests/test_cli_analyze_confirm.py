"""TDD tests for `analyze --json + --confirm + --depth` two-phase semantics."""
import json
import subprocess


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

    def test_json_confirm_returns_not_implemented(self):
        """--json + --confirm v1 返 exit 5 + not_implemented（run_analysis 未支持结构化返回）。"""
        r = _run("analyze", "--json", "--confirm")
        assert r.returncode == 5
        payload = json.loads(r.stdout)
        assert payload["error"] == "not_implemented"


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
