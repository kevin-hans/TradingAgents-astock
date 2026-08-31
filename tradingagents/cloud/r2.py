"""R2 CloudStore 实现（占位——Task 2 补实）。"""
from __future__ import annotations

from pathlib import Path


class R2Store:
    def is_configured(self) -> bool:
        return False

    def download_scenario(self, ticker: str, date: str, target_path: Path) -> bool:
        return False

    def upload_scenario(self, ticker: str, date: str, local_path: Path) -> bool:
        return False
