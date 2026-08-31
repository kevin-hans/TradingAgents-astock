"""R2Store 单测——凭据检测、上下行、错误吞掉。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


_ENV_VARS = (
    "TRADINGAGENTS_R2_ACCOUNT_ID",
    "TRADINGAGENTS_R2_ACCESS_KEY_ID",
    "TRADINGAGENTS_R2_SECRET_ACCESS_KEY",
    "TRADINGAGENTS_R2_BUCKET",
)


def _configure(monkeypatch):
    monkeypatch.setenv("TRADINGAGENTS_R2_ACCOUNT_ID", "acc")
    monkeypatch.setenv("TRADINGAGENTS_R2_ACCESS_KEY_ID", "id")
    monkeypatch.setenv("TRADINGAGENTS_R2_SECRET_ACCESS_KEY", "key")
    monkeypatch.setenv("TRADINGAGENTS_R2_BUCKET", "bucket")


def _unconfigure(monkeypatch):
    for v in _ENV_VARS:
        monkeypatch.delenv(v, raising=False)


class TestIsConfigured:
    def test_true_when_all_four_vars_set(self, monkeypatch):
        from tradingagents.cloud.r2 import R2Store
        _configure(monkeypatch)
        assert R2Store().is_configured() is True

    def test_false_by_default(self, monkeypatch):
        from tradingagents.cloud.r2 import R2Store
        _unconfigure(monkeypatch)
        assert R2Store().is_configured() is False

    def test_false_when_one_var_missing(self, monkeypatch):
        from tradingagents.cloud.r2 import R2Store
        _configure(monkeypatch)
        monkeypatch.delenv("TRADINGAGENTS_R2_BUCKET", raising=False)
        assert R2Store().is_configured() is False


class TestDownload:
    def test_download_success_writes_target(self, monkeypatch, tmp_path):
        pytest.importorskip("boto3")
        from tradingagents.cloud.r2 import R2Store

        _configure(monkeypatch)
        client_mock = MagicMock()

        def fake_download_file(bucket, key, dest):
            Path(dest).write_bytes(b'{"ticker":"600519"}')

        client_mock.download_file.side_effect = fake_download_file

        store = R2Store()
        monkeypatch.setattr(store, "_make_client", lambda: client_mock)

        target = tmp_path / "logs" / "600519" / "2026-08-30" / "scenario.json"
        assert store.download_scenario("600519", "2026-08-30", target) is True
        assert target.read_bytes() == b'{"ticker":"600519"}'
        client_mock.download_file.assert_called_once_with(
            "bucket", "600519/2026-08-30/scenario.json", str(target),
        )

    def test_download_returns_false_on_error(self, monkeypatch, tmp_path):
        pytest.importorskip("boto3")
        from tradingagents.cloud.r2 import R2Store

        _configure(monkeypatch)
        client_mock = MagicMock()
        client_mock.download_file.side_effect = Exception("NoSuchKey")

        store = R2Store()
        monkeypatch.setattr(store, "_make_client", lambda: client_mock)

        assert store.download_scenario("999999", "2026-01-01", tmp_path / "a.json") is False

    def test_download_returns_false_when_not_configured(self, monkeypatch, tmp_path):
        from tradingagents.cloud.r2 import R2Store
        _unconfigure(monkeypatch)
        assert R2Store().download_scenario("600519", "2026-08-30", tmp_path / "a.json") is False


class TestUpload:
    def test_upload_calls_boto3_upload_file(self, monkeypatch, tmp_path):
        pytest.importorskip("boto3")
        from tradingagents.cloud.r2 import R2Store

        _configure(monkeypatch)
        src = tmp_path / "scenario.json"
        src.write_text('{"x":1}')

        client_mock = MagicMock()
        store = R2Store()
        monkeypatch.setattr(store, "_make_client", lambda: client_mock)

        assert store.upload_scenario("600519", "2026-08-30", src) is True
        client_mock.upload_file.assert_called_once_with(
            str(src), "bucket", "600519/2026-08-30/scenario.json",
            ExtraArgs={"ContentType": "application/json"},
        )

    def test_upload_returns_false_when_not_configured(self, monkeypatch, tmp_path):
        from tradingagents.cloud.r2 import R2Store
        _unconfigure(monkeypatch)
        src = tmp_path / "scenario.json"
        src.write_text('{}')
        assert R2Store().upload_scenario("600519", "2026-08-30", src) is False

    def test_upload_returns_false_when_source_missing(self, monkeypatch, tmp_path):
        from tradingagents.cloud.r2 import R2Store
        _configure(monkeypatch)
        assert R2Store().upload_scenario("600519", "2026-08-30", tmp_path / "nope.json") is False


class TestProtocolConformance:
    def test_r2_store_satisfies_cloud_store_protocol(self, monkeypatch):
        from tradingagents.cloud.base import CloudStore
        from tradingagents.cloud.r2 import R2Store
        assert isinstance(R2Store(), CloudStore)
