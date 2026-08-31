"""scenario.json 读侧。归档文件 (.archived-*) 被 glob 精确匹配自动过滤。"""
import os
import re
from pathlib import Path

from pydantic import BaseModel

from tradingagents.agents.schemas import Falsification, ScenarioBucket
from tradingagents.cloud import get_store


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


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
    if not entries and date is not None:
        # 本地无 + 指定了具体日期 → 尝试从云端拉一次
        if _try_cloud_download(ticker, date):
            entries = list_scenarios(ticker=ticker)
    if not entries:
        raise ScenarioNotFoundError(f"no scenario for {ticker}")
    if date is None:
        entry = sorted(entries, key=lambda e: e.trade_date)[-1]
    else:
        matches = [e for e in entries if e.trade_date == date]
        if not matches:
            # 指定日期本地未命中 → 也试一次云端
            if _try_cloud_download(ticker, date):
                matches = [
                    e for e in list_scenarios(ticker=ticker) if e.trade_date == date
                ]
        if not matches:
            raise ScenarioNotFoundError(f"no scenario for {ticker} on {date}")
        entry = matches[0]
    return ScenarioArtifact.model_validate_json(
        Path(entry.path).read_text(encoding="utf-8")
    )


def _try_cloud_download(ticker: str, date: str) -> bool:
    """尝试从 cloud store 拉 scenario.json 到本地 {reports_dir}/{ticker}/{date}/。

    caller 侧不 import 具体后端——工厂返回什么就是什么。
    """
    store = get_store()
    if store is None:
        return False
    target = _reports_dir() / ticker / date / "scenario.json"
    return store.download_scenario(ticker, date, target)


def list_scenarios(ticker: str | None = None) -> list[ScenarioIndexEntry]:
    directory = _reports_dir()
    if not directory.exists():
        return []
    entries: list[ScenarioIndexEntry] = []
    for path in directory.rglob("scenario.json"):
        d = path.parent.name
        t = path.parent.parent.name
        if not _DATE_RE.match(d):
            continue
        if ticker is not None and t != ticker:
            continue
        entries.append(ScenarioIndexEntry(ticker=t, trade_date=d, path=str(path)))
    return entries
