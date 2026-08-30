import json
import subprocess


def _run(*args):
    return subprocess.run(
        [".venv/bin/python", "-m", "cli.main", *args],
        capture_output=True, text=True,
    )


class TestReviewStub:
    def test_returns_not_implemented_exit_5(self):
        r = _run("review", "--json")
        assert r.returncode == 5
        payload = json.loads(r.stdout)
        assert payload["error"] == "not_implemented"

    def test_accepts_kyc_json_without_cracking(self):
        r = _run("review", "--json", "--kyc-json", '{"q1":7,"q2":7,"q3":7,"q4":7,"q5":7}')
        assert r.returncode == 5
        assert json.loads(r.stdout)["error"] == "not_implemented"
