from pathlib import Path

import pytest

from tradingagents.advisor.profile_io import (
    read_profile,
    write_profile,
    ProfileNotFoundError,
)
from tradingagents.advisor.types import KYCAnswers


@pytest.fixture
def tmp_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


class TestEnvOverride:
    def test_profile_env_var_takes_priority(self, tmp_home: Path, monkeypatch: pytest.MonkeyPatch):
        custom = tmp_home / "custom_profile.json"
        monkeypatch.setenv("TRADINGAGENTS_PROFILE", str(custom))
        write_profile(KYCAnswers(q1=7, q2=7, q3=7, q4=7, q5=7))
        assert custom.exists()
        assert read_profile().q1 == 7

    def test_missing_env_profile_raises_not_found(self, tmp_home: Path, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("TRADINGAGENTS_PROFILE", str(tmp_home / "nope.json"))
        with pytest.raises(ProfileNotFoundError):
            read_profile()


class TestWriteRead:
    def test_write_then_read_roundtrip(self, tmp_home: Path):
        ans = KYCAnswers(q1=7, q2=5, q3=7, q4=7, q5=7)
        write_profile(ans)
        loaded = read_profile()
        assert loaded == ans

    def test_read_missing_raises(self, tmp_home: Path):
        with pytest.raises(ProfileNotFoundError):
            read_profile()

    def test_write_is_atomic_no_temp_leftovers(self, tmp_home: Path):
        write_profile(KYCAnswers(q1=3, q2=3, q3=3, q4=3, q5=3))
        write_profile(KYCAnswers(q1=9, q2=9, q3=9, q4=9, q5=9))
        loaded = read_profile()
        assert loaded.q1 == 9
        profile_dir = tmp_home / ".tradingagents"
        stragglers = list(profile_dir.glob("*.tmp"))
        assert stragglers == []
