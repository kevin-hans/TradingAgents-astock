"""P1 scenario_<ticker>_<date>.json 读侧。归档文件 (.archived-*) 跳过。"""
import os
import re
from pathlib import Path

from pydantic import BaseModel

from tradingagents.agents.schemas import Falsification, ScenarioBucket


_FILENAME_RE = re.compile(
    r"^scenario_(?P<ticker>[^_]+)_(?P<date>\d{4}-\d{2}-\d{2})\.json$"
)


class ScenarioNotFoundError(FileNotFoundError):
    pass


class ScenarioArtifact(BaseModel):
    version: int
    ticker: str
    trade_date: str
    rating: str
    scenario_buckets: list[ScenarioBucket]
    falsification: Falsification | None = None


class ScenarioIndexEntry(BaseModel):
    ticker: str
    trade_date: str
    path: str


def _reports_dir() -> Path:
    """获取扫描根目录。优先级：TRADINGAGENTS_REPORTS_DIR (测试用) > TRADINGAGENTS_RESULTS_DIR > default."""
    env_reports = os.environ.get("TRADINGAGENTS_REPORTS_DIR")
    if env_reports:
        return Path(env_reports)
    env_results = os.environ.get("TRADINGAGENTS_RESULTS_DIR")
    if env_results:
        return Path(env_results)
    return Path(os.path.expanduser("~")) / ".tradingagents" / "logs"


def load_scenario(ticker: str, date: str | None = None) -> ScenarioArtifact:
    entries = list_scenarios(ticker=ticker)
    if not entries:
        raise ScenarioNotFoundError(f"no scenario for {ticker}")
    if date is None:
        entry = sorted(entries, key=lambda e: e.trade_date)[-1]
    else:
        matches = [e for e in entries if e.trade_date == date]
        if not matches:
            raise ScenarioNotFoundError(f"no scenario for {ticker} on {date}")
        entry = matches[0]
    return ScenarioArtifact.model_validate_json(
        Path(entry.path).read_text(encoding="utf-8")
    )


def list_scenarios(ticker: str | None = None) -> list[ScenarioIndexEntry]:
    directory = _reports_dir()
    if not directory.exists():
        return []
    entries: list[ScenarioIndexEntry] = []
    for path in directory.rglob("scenario_*.json"):  # 递归扫，兼容 P1 嵌套路径
        m = _FILENAME_RE.match(path.name)
        if not m:
            continue
        t = m.group("ticker")
        d = m.group("date")
        if ticker is not None and t != ticker:
            continue
        entries.append(ScenarioIndexEntry(ticker=t, trade_date=d, path=str(path)))
    return entries
