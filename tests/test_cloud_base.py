"""CloudStore Protocol + 工厂 get_store() 单测。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional


class TestCloudStoreProtocol:
    def test_protocol_defines_three_methods(self):
        from tradingagents.cloud.base import CloudStore
        # Protocol 有这三个方法
        assert hasattr(CloudStore, "is_configured")
        assert hasattr(CloudStore, "download_scenario")
        assert hasattr(CloudStore, "upload_scenario")

    def test_duck_typed_class_satisfies_protocol(self):
        """结构化子类型：只要方法齐全就算实现，不需要显式继承。"""
        from tradingagents.cloud.base import CloudStore

        class FakeStore:
            def is_configured(self) -> bool:
                return True
            def download_scenario(self, ticker: str, date: str, target_path: Path) -> bool:
                return True
            def upload_scenario(self, ticker: str, date: str, local_path: Path) -> bool:
                return True

        # runtime_checkable Protocol：isinstance 应通过
        assert isinstance(FakeStore(), CloudStore)


class TestFactory:
    def test_get_store_returns_none_when_no_backend_configured(self, monkeypatch):
        for v in ("TRADINGAGENTS_R2_ACCOUNT_ID",
                  "TRADINGAGENTS_R2_ACCESS_KEY_ID",
                  "TRADINGAGENTS_R2_SECRET_ACCESS_KEY",
                  "TRADINGAGENTS_R2_BUCKET"):
            monkeypatch.delenv(v, raising=False)
        from tradingagents.cloud import get_store
        assert get_store() is None

    def test_get_store_returns_r2_when_r2_configured(self, monkeypatch):
        monkeypatch.setenv("TRADINGAGENTS_R2_ACCOUNT_ID", "acc")
        monkeypatch.setenv("TRADINGAGENTS_R2_ACCESS_KEY_ID", "id")
        monkeypatch.setenv("TRADINGAGENTS_R2_SECRET_ACCESS_KEY", "key")
        monkeypatch.setenv("TRADINGAGENTS_R2_BUCKET", "bucket")
        from tradingagents.cloud import get_store
        from tradingagents.cloud.r2 import R2Store
        store = get_store()
        assert isinstance(store, R2Store)


class TestScenarioKeyConvention:
    def test_scenario_key_format(self):
        from tradingagents.cloud.base import scenario_object_key
        assert scenario_object_key("600519", "2026-08-30") == "600519/2026-08-30/scenario.json"
