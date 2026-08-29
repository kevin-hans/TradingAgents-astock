# tests/test_cli_force_flag.py
"""--force flag plumbing and the same-day artifact detector (spec §7)."""
from typer.testing import CliRunner

from cli.main import app, existing_artifacts

runner = CliRunner()


def test_force_flag_exposed_on_analyze():
    result = runner.invoke(app, ["analyze", "--help"])
    assert result.exit_code == 0
    assert "--force" in result.output


def test_force_flag_exposed_on_bare_callback():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "--force" in result.output


def test_existing_artifacts_detects_log_and_scenario(tmp_path):
    log_dir = tmp_path / "600519" / "TradingAgentsStrategy_logs"
    log_dir.mkdir(parents=True)
    (log_dir / "full_states_log_2026-08-25.json").touch()
    found = existing_artifacts(str(tmp_path), "600519", "2026-08-25")
    assert any("full_states_log" in p.name for p in found)
    (log_dir / "scenario_600519_2026-08-25.json").touch()
    found = existing_artifacts(str(tmp_path), "600519", "2026-08-25")
    assert len(found) == 2


def test_existing_artifacts_empty_when_none(tmp_path):
    assert existing_artifacts(str(tmp_path), "600519", "2026-08-25") == []
