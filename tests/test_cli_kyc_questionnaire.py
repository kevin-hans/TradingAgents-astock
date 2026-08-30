import json
import subprocess


def _run(*args):
    return subprocess.run(
        [".venv/bin/python", "-m", "cli.main", *args],
        capture_output=True, text=True,
    )


class TestKycQuestionnaireJSON:
    def test_returns_five_questions(self):
        r = _run("kyc-questionnaire", "--json")
        assert r.returncode == 0, r.stderr
        payload = json.loads(r.stdout)
        assert payload["schema_version"] == 1
        assert len(payload["questions"]) == 5
        assert [q["id"] for q in payload["questions"]] == ["q1", "q2", "q3", "q4", "q5"]

    def test_options_have_correct_values(self):
        r = _run("kyc-questionnaire", "--json")
        payload = json.loads(r.stdout)
        for q in payload["questions"]:
            values = sorted(opt["value"] for opt in q["options"])
            assert values == [3, 5, 7, 9]

    def test_has_note_field(self):
        r = _run("kyc-questionnaire", "--json")
        payload = json.loads(r.stdout)
        assert "note" in payload
        assert "客户端" in payload["note"]

    def test_default_command_still_works(self):
        r = subprocess.run(
            [".venv/bin/python", "-m", "cli.main", "--help"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0
        assert "kyc-questionnaire" in r.stdout
