"""profile.json 原子读写（spec §5 Profile 存 ~/.tradingagents/profile.json）。"""
import json
import os
import tempfile
from pathlib import Path

from tradingagents.advisor.types import KYCAnswers


class ProfileNotFoundError(FileNotFoundError):
    pass


def _profile_path() -> Path:
    return Path(os.path.expanduser("~")) / ".tradingagents" / "profile.json"


def read_profile() -> KYCAnswers:
    p = _profile_path()
    if not p.exists():
        raise ProfileNotFoundError(str(p))
    payload = json.loads(p.read_text(encoding="utf-8"))
    return KYCAnswers.model_validate(payload.get("kyc_answers", payload))


def write_profile(answers: KYCAnswers) -> None:
    p = _profile_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema_version": 1, "kyc_answers": answers.model_dump()}
    with tempfile.NamedTemporaryFile(
        mode="w", dir=p.parent, delete=False, encoding="utf-8", suffix=".tmp"
    ) as tf:
        json.dump(payload, tf, ensure_ascii=False)
        tmp_name = tf.name
    os.replace(tmp_name, p)
