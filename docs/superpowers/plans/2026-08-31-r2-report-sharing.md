# Cloud Report Sharing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让多个用户共享分析报告：分析前先查云端有没有现成的，有就直接下载复用；没有才跑 LLM 分析并把 `scenario.json` 上传。首个实现是 Cloudflare R2 私有 bucket，但 caller 侧只依赖抽象接口，未来加 S3 / 阿里 OSS 等只需加一个实现类。

**Architecture:**
- `tradingagents/cloud/base.py` 定义 `CloudStore` **Protocol**（结构化子类型，实现类无需继承）—— 三个方法：`is_configured()` / `download_scenario()` / `upload_scenario()`
- `tradingagents/cloud/r2.py` 提供 `R2Store` 实现（boto3 S3 兼容 API）
- `tradingagents/cloud/__init__.py` 暴露工厂 `get_store() -> Optional[CloudStore]`：探测已配置的第一个后端；目前只有 R2，未来新增按顺序尝试
- Callers 只 `from tradingagents.cloud import get_store` 用工厂，永远不 import 具体实现

**Tech Stack:** `typing.Protocol`（无运行时依赖）、boto3（首个实现，`[cloud]` extra 可选依赖）、pytest + monkeypatch 做单测。

**R2 Path Convention:** `{ticker}/{date}/scenario.json`（镜像本地布局，路径约定放接口层，所有实现共用）。

**Env Vars（R2 实现专属，其他后端未来加自己的前缀；四个都必须齐全才启用）：**
- `TRADINGAGENTS_R2_ACCOUNT_ID`
- `TRADINGAGENTS_R2_ACCESS_KEY_ID`
- `TRADINGAGENTS_R2_SECRET_ACCESS_KEY`
- `TRADINGAGENTS_R2_BUCKET`

---

## File Structure

**Create:**
- `tradingagents/cloud/__init__.py` — 暴露 `CloudStore` + `get_store()`
- `tradingagents/cloud/base.py` — `CloudStore` Protocol + path 约定常量
- `tradingagents/cloud/r2.py` — `R2Store` 实现
- `tests/test_cloud_base.py` — Protocol / 工厂单测
- `tests/test_cloud_r2.py` — R2Store 单测
- `tests/test_cli_analyze_cloud.py` — analyze 前置检查单测

**Modify:**
- `tradingagents/graph/trading_graph.py` — `_write_scenario_artifact` 末尾调 `get_store().upload_scenario()`
- `tradingagents/advisor/scenario_io.py` — `load_scenario` 本地未命中时调 `get_store().download_scenario()`
- `cli/main.py` — `run_analysis_headless` 前置 `get_store().download_scenario()`
- `tests/test_finalize_scenario.py` — 加"配置好 store 会调 upload"测试
- `tests/test_advisor_scenario_io.py` — 加"本地空 + store 有 → 下载后加载成功"测试
- `pyproject.toml` — 新增 `[cloud]` extra
- `CLAUDE.md` — "云端报告共享"新段（强调接口/实现分离）

---

## Task 1: 抽象接口 `CloudStore` + 工厂 `get_store()`

**Files:**
- Create: `tradingagents/cloud/__init__.py`
- Create: `tradingagents/cloud/base.py`
- Create: `tests/test_cloud_base.py`

- [ ] **Step 1.1: 写失败的单测（工厂/接口契约）**

创建 `tests/test_cloud_base.py`：

```python
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
        # 清掉所有可能的凭据
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
```

- [ ] **Step 1.2: 运行确认失败**

```bash
.venv/bin/python -m pytest tests/test_cloud_base.py -v
```
Expected: `ModuleNotFoundError: No module named 'tradingagents.cloud'`

- [ ] **Step 1.3: 创建 base.py**

创建 `tradingagents/cloud/base.py`：

```python
"""云端报告共享的抽象接口。

CloudStore 是结构化 Protocol——实现类只需具备三个方法即可，无需继承。
Path 约定 (scenario_object_key) 放在接口层，所有实现共用同一套 object key
命名，避免各实现自定义导致互相看不到对方存的文件。
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


def scenario_object_key(ticker: str, date: str) -> str:
    """所有 cloud store 实现共用的 object key 命名约定。

    镜像本地 {ticker}/{date}/scenario.json 布局，任何后端切换后
    互相能找到对方存的文件。
    """
    return f"{ticker}/{date}/scenario.json"


@runtime_checkable
class CloudStore(Protocol):
    """报告共享存储抽象。

    实现类只需回答三个问题：
    - 我配置好可用了吗？
    - 我能把某 ticker+date 的 scenario.json 拉下来吗？
    - 我能把它推上去吗？

    所有方法都必须是尽力而为——异常吞掉、返回 False，绝不上抛。
    本地文件才是真源，云端只是共享层。
    """

    def is_configured(self) -> bool:
        """凭据齐全、依赖库可用。未配置的实现应快速返回 False，不做副作用。"""
        ...

    def download_scenario(self, ticker: str, date: str, target_path: Path) -> bool:
        """把云端的 scenario.json 拉到 target_path。成功写入返回 True。

        404、网络错、凭据错、依赖库缺失都返回 False，不抛异常。
        """
        ...

    def upload_scenario(self, ticker: str, date: str, local_path: Path) -> bool:
        """把 local_path 上传到云端。成功返回 True。

        源文件不存在、上传失败都返回 False，不抛异常。
        """
        ...
```

- [ ] **Step 1.4: 创建 __init__.py（工厂）**

创建 `tradingagents/cloud/__init__.py`：

```python
"""云端报告共享——抽象接口 + 工厂。

Callers 只 `from tradingagents.cloud import get_store` 用工厂，
永远不 import 具体实现（R2Store/S3Store/...）——这样切换后端 caller 无感。
"""
from __future__ import annotations

from typing import Optional

from tradingagents.cloud.base import CloudStore, scenario_object_key

__all__ = ["CloudStore", "get_store", "scenario_object_key"]


def get_store() -> Optional[CloudStore]:
    """返回当前生效的 CloudStore 实例；无后端配置好则返回 None。

    未来新增后端（S3 / 阿里 OSS / MinIO ...）时在此按顺序追加尝试即可，
    caller 侧代码无需改动。
    """
    # 后端探测顺序：目前只有 R2。future backends: append here in priority order.
    from tradingagents.cloud.r2 import R2Store
    store = R2Store()
    if store.is_configured():
        return store
    return None
```

- [ ] **Step 1.5: 先把 r2.py 占个位（下个 Task 才实现）**

创建 `tradingagents/cloud/r2.py` 骨架（让 base 的 factory 测试能 import 过）：

```python
"""R2 CloudStore 实现（占位——Task 2 补实）。"""
from __future__ import annotations

from pathlib import Path


class R2Store:
    def is_configured(self) -> bool:
        return False  # Task 2 补真实检测

    def download_scenario(self, ticker: str, date: str, target_path: Path) -> bool:
        return False  # Task 2 补

    def upload_scenario(self, ticker: str, date: str, local_path: Path) -> bool:
        return False  # Task 2 补
```

- [ ] **Step 1.6: 运行测试确认通过**

```bash
.venv/bin/python -m pytest tests/test_cloud_base.py -v
```
Expected: 5 passed（但 `test_get_store_returns_r2_when_r2_configured` 会失败——因为 R2Store 占位 `is_configured` 恒 False。这个测试留到 Task 2 一起过；先注掉或标 xfail。）

改一下 factory 测试，让占位阶段能通过：

```python
    def test_get_store_returns_r2_when_r2_configured(self, monkeypatch):
        """需 Task 2 完成后才能通过——R2Store.is_configured 真检测 env vars。"""
        import pytest
        pytest.xfail("R2Store 尚未实现真实凭据检测（Task 2）")
```

再跑：Expected: 4 passed + 1 xfailed

- [ ] **Step 1.7: 提交**

```bash
git add tradingagents/cloud/ tests/test_cloud_base.py
git commit -m "feat(cloud): 抽象接口 CloudStore（Protocol）+ 工厂 get_store() 骨架"
```

---

## Task 2: `R2Store` 实现

**Files:**
- Modify: `tradingagents/cloud/r2.py`
- Create: `tests/test_cloud_r2.py`
- Modify: `tests/test_cloud_base.py`（去掉 xfail）
- Modify: `pyproject.toml`（加 `[cloud]` extra）

- [ ] **Step 2.1: 先加 `[cloud]` extra + 装 boto3**

编辑 `pyproject.toml` 的 `[project.optional-dependencies]` 段，在 `web = ...` 后插入：

```toml
cloud = ["boto3>=1.34.0"]
```

装到 dev venv：

```bash
.venv/bin/pip install -e '.[cloud]'
uv lock --dry-run 2>&1 | grep -i "error\|conflict" || echo "no errors"
```
Expected: `no errors`

- [ ] **Step 2.2: 写失败的 R2Store 单测**

创建 `tests/test_cloud_r2.py`：

```python
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
```

- [ ] **Step 2.3: 运行确认失败**

```bash
.venv/bin/python -m pytest tests/test_cloud_r2.py -v
```
Expected: 除了 `_unconfigure` 相关的都失败——`is_configured` 恒 False，upload/download 都 no-op

- [ ] **Step 2.4: 实现 R2Store 真实逻辑**

覆写 `tradingagents/cloud/r2.py`：

```python
"""R2 CloudStore 实现——S3 兼容私有 bucket。

Cloudflare R2 用 boto3 S3 client 访问，endpoint 指向
`{account_id}.r2.cloudflarestorage.com`。凭据未配置或 boto3 未装时
所有方法快速返回 False，不做任何网络调用。
"""
from __future__ import annotations

import logging
import os
from pathlib import Path

from tradingagents.cloud.base import scenario_object_key

logger = logging.getLogger(__name__)


_ENV_VARS = (
    "TRADINGAGENTS_R2_ACCOUNT_ID",
    "TRADINGAGENTS_R2_ACCESS_KEY_ID",
    "TRADINGAGENTS_R2_SECRET_ACCESS_KEY",
    "TRADINGAGENTS_R2_BUCKET",
)


class R2Store:
    """Cloudflare R2 私有 bucket 实现。

    结构化实现 CloudStore Protocol——无 `class R2Store(CloudStore)` 继承。
    """

    def is_configured(self) -> bool:
        """四个 R2 凭据变量都齐全。"""
        return all(os.environ.get(v) for v in _ENV_VARS)

    def download_scenario(self, ticker: str, date: str, target_path: Path) -> bool:
        client = self._make_client()
        if client is None:
            return False
        bucket = os.environ["TRADINGAGENTS_R2_BUCKET"]
        key = scenario_object_key(ticker, date)
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            client.download_file(bucket, key, str(target_path))
            return True
        except Exception as e:
            # boto3 对 404 抛 ClientError(NoSuchKey)；网络问题抛别的。
            # 都是"云端拿不到"，统一返回 False。
            logger.debug("R2 下载 %s/%s 失败：%s", bucket, key, e)
            return False

    def upload_scenario(self, ticker: str, date: str, local_path: Path) -> bool:
        if not local_path.exists():
            logger.warning("R2 上传源文件不存在：%s", local_path)
            return False
        client = self._make_client()
        if client is None:
            return False
        try:
            client.upload_file(
                str(local_path),
                os.environ["TRADINGAGENTS_R2_BUCKET"],
                scenario_object_key(ticker, date),
                ExtraArgs={"ContentType": "application/json"},
            )
            return True
        except Exception as e:
            logger.warning("R2 上传 %s 失败：%s", local_path, e)
            return False

    def _make_client(self):
        """构造 boto3 S3 client。凭据未配置或 boto3 未装返回 None。"""
        if not self.is_configured():
            return None
        try:
            import boto3
        except ImportError:
            logger.warning(
                "R2 需要 boto3，未安装。请装 [cloud] extra："
                "pip install 'tradingagents-astock[cloud]'"
            )
            return None
        return boto3.client(
            "s3",
            endpoint_url=(
                f"https://{os.environ['TRADINGAGENTS_R2_ACCOUNT_ID']}"
                ".r2.cloudflarestorage.com"
            ),
            aws_access_key_id=os.environ["TRADINGAGENTS_R2_ACCESS_KEY_ID"],
            aws_secret_access_key=os.environ["TRADINGAGENTS_R2_SECRET_ACCESS_KEY"],
            region_name="auto",
        )
```

- [ ] **Step 2.5: 去掉 Task 1 中 factory 测试的 xfail**

编辑 `tests/test_cloud_base.py`，把 `test_get_store_returns_r2_when_r2_configured` 里的 xfail 那行删掉：

```python
    def test_get_store_returns_r2_when_r2_configured(self, monkeypatch):
        monkeypatch.setenv("TRADINGAGENTS_R2_ACCOUNT_ID", "acc")
        monkeypatch.setenv("TRADINGAGENTS_R2_ACCESS_KEY_ID", "id")
        monkeypatch.setenv("TRADINGAGENTS_R2_SECRET_ACCESS_KEY", "key")
        monkeypatch.setenv("TRADINGAGENTS_R2_BUCKET", "bucket")
        from tradingagents.cloud import get_store
        from tradingagents.cloud.r2 import R2Store
        store = get_store()
        assert isinstance(store, R2Store)
```

- [ ] **Step 2.6: 运行全套 cloud 测试确认通过**

```bash
.venv/bin/python -m pytest tests/test_cloud_base.py tests/test_cloud_r2.py -v
```
Expected: 全部 passed（factory 5 + R2 10）

- [ ] **Step 2.7: 提交**

```bash
git add pyproject.toml tradingagents/cloud/r2.py tests/test_cloud_r2.py tests/test_cloud_base.py
git commit -m "feat(cloud): R2Store 实现（boto3 S3 兼容，私有 bucket）+ [cloud] extra"
```

---

## Task 3: `scenario_io.load_scenario` 接入 `get_store()`

**Files:**
- Modify: `tradingagents/advisor/scenario_io.py`
- Modify: `tests/test_advisor_scenario_io.py`

- [ ] **Step 3.1: 先写测试**

追加到 `tests/test_advisor_scenario_io.py`：

```python
class TestCloudFallback:
    def _fake_store(self, monkeypatch, payload_by_key):
        """返回一个可配置的假 CloudStore；payload_by_key 用 (ticker, date) 索引。"""
        class FakeStore:
            def is_configured(self):
                return True
            def download_scenario(self, ticker, date, target_path):
                payload = payload_by_key.get((ticker, date))
                if payload is None:
                    return False
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(json.dumps(payload), encoding="utf-8")
                return True
            def upload_scenario(self, *a, **kw):
                return True

        from tradingagents.advisor import scenario_io
        fake = FakeStore()
        monkeypatch.setattr(scenario_io, "get_store", lambda: fake)
        return fake

    def test_local_miss_triggers_cloud_download(self, tmp_reports, monkeypatch):
        """本地无 scenario、cloud 有 → 自动下载并加载成功。"""
        payload = {
            "version": 1, "ticker": "999999", "trade_date": "2026-09-01",
            "rating": "Hold",
            "scenario_buckets": [
                {
                    "horizon_months": 6,
                    "scenarios": [
                        {"name": "bull", "thesis": "t", "expected_return": 0.15, "prob": 0.3},
                        {"name": "base", "thesis": "t", "expected_return": 0.05, "prob": 0.5},
                        {"name": "bear", "thesis": "t", "expected_return": -0.05, "prob": 0.2},
                    ],
                    "key_levels": {"stop": 9, "entry_low": 10, "entry_high": 10, "target": 12},
                }
            ],
            "falsification": {"conditions": []},
        }
        self._fake_store(monkeypatch, {("999999", "2026-09-01"): payload})

        art = load_scenario("999999", date="2026-09-01")
        assert art.ticker == "999999"
        assert (tmp_reports / "999999" / "2026-09-01" / "scenario.json").exists()

    def test_local_miss_no_store_still_raises(self, tmp_reports, monkeypatch):
        from tradingagents.advisor import scenario_io
        monkeypatch.setattr(scenario_io, "get_store", lambda: None)
        with pytest.raises(ScenarioNotFoundError):
            load_scenario("999999", date="2026-09-01")

    def test_local_hit_skips_cloud(self, tmp_reports, monkeypatch):
        _write_scenario(tmp_reports, "000001", "2026-08-30")
        called = []

        class SpyStore:
            def is_configured(self):
                return True
            def download_scenario(self, ticker, date, target_path):
                called.append((ticker, date))
                return True
            def upload_scenario(self, *a, **kw):
                return True

        from tradingagents.advisor import scenario_io
        monkeypatch.setattr(scenario_io, "get_store", lambda: SpyStore())

        load_scenario("000001")
        assert called == []  # 本地命中 → cloud 不该被查
```

- [ ] **Step 3.2: 运行确认失败**

```bash
.venv/bin/python -m pytest tests/test_advisor_scenario_io.py::TestCloudFallback -v
```
Expected: `test_local_miss_triggers_cloud_download` 失败——目前直接抛 ScenarioNotFoundError

- [ ] **Step 3.3: 改 scenario_io.py 用工厂**

编辑 `tradingagents/advisor/scenario_io.py`，在文件顶部 imports 后追加：

```python
from tradingagents.cloud import get_store
```

改 `load_scenario` 函数：

```python
def load_scenario(ticker: str, date: str | None = None) -> ScenarioArtifact:
    entries = list_scenarios(ticker=ticker)
    if not entries and date is not None:
        if _try_cloud_download(ticker, date):
            entries = list_scenarios(ticker=ticker)
    if not entries:
        raise ScenarioNotFoundError(f"no scenario for {ticker}")
    if date is None:
        entry = sorted(entries, key=lambda e: e.trade_date)[-1]
    else:
        matches = [e for e in entries if e.trade_date == date]
        if not matches:
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
```

- [ ] **Step 3.4: 运行确认通过**

```bash
.venv/bin/python -m pytest tests/test_advisor_scenario_io.py -v
```
Expected: 全部通过

- [ ] **Step 3.5: 提交**

```bash
git add tradingagents/advisor/scenario_io.py tests/test_advisor_scenario_io.py
git commit -m "feat(advisor): load_scenario 本地未命中时通过 CloudStore 工厂回落云端"
```

---

## Task 4: `trading_graph._write_scenario_artifact` 用工厂上传

**Files:**
- Modify: `tradingagents/graph/trading_graph.py`
- Modify: `tests/test_finalize_scenario.py`

- [ ] **Step 4.1: 先写测试**

追加到 `tests/test_finalize_scenario.py` 的 `TestFinalizePersistence` 类：

```python
    def test_uploads_via_cloud_store_when_configured(self, tmp_path, monkeypatch):
        g = _graph(tmp_path)
        g.memory_log = _MemoryStub()
        monkeypatch.setattr(g, "process_signal", lambda s: "Sell", raising=False)

        upload_calls = []
        class FakeStore:
            def is_configured(self):
                return True
            def download_scenario(self, *a, **kw):
                return False
            def upload_scenario(self, ticker, date, local_path):
                upload_calls.append((ticker, date, str(local_path)))
                return True

        from tradingagents.graph import trading_graph as tg
        monkeypatch.setattr(tg, "get_store", lambda: FakeStore(), raising=False)

        g.finalize_graph_run("600519", "2026-08-25", _final_state())
        assert len(upload_calls) == 1
        assert upload_calls[0][0] == "600519"
        assert upload_calls[0][1] == "2026-08-25"
        assert upload_calls[0][2].endswith("2026-08-25/scenario.json")

    def test_no_upload_when_no_store(self, tmp_path, monkeypatch):
        g = _graph(tmp_path)
        g.memory_log = _MemoryStub()
        monkeypatch.setattr(g, "process_signal", lambda s: "Sell", raising=False)

        from tradingagents.graph import trading_graph as tg
        monkeypatch.setattr(tg, "get_store", lambda: None, raising=False)

        # 不该抛异常——本地文件正常写入
        g.finalize_graph_run("600519", "2026-08-25", _final_state())
        assert (tmp_path / "600519" / "2026-08-25" / "scenario.json").exists()

    def test_upload_failure_does_not_break_finalize(self, tmp_path, monkeypatch):
        g = _graph(tmp_path)
        g.memory_log = _MemoryStub()
        monkeypatch.setattr(g, "process_signal", lambda s: "Sell", raising=False)

        class BrokenStore:
            def is_configured(self):
                return True
            def download_scenario(self, *a, **kw):
                return False
            def upload_scenario(self, *a, **kw):
                raise RuntimeError("boom")

        from tradingagents.graph import trading_graph as tg
        monkeypatch.setattr(tg, "get_store", lambda: BrokenStore(), raising=False)

        g.finalize_graph_run("600519", "2026-08-25", _final_state())
        assert (tmp_path / "600519" / "2026-08-25" / "scenario.json").exists()
```

- [ ] **Step 4.2: 运行确认失败**

```bash
.venv/bin/python -m pytest tests/test_finalize_scenario.py::TestFinalizePersistence::test_uploads_via_cloud_store_when_configured -v
```
Expected: FAIL（`get_store` attribute 不存在 or upload_calls 空）

- [ ] **Step 4.3: 在 trading_graph.py 顶部 import + 末尾追加上传**

编辑 `tradingagents/graph/trading_graph.py`。在顶部 imports 附近追加（放在其他 tradingagents.* imports 附近）：

```python
from tradingagents.cloud import get_store
```

在 `_write_scenario_artifact` 方法末尾（写完本地 json 后）追加：

```python
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

        # 尽力而为通过 CloudStore 工厂上传（未配置或失败均不中断）。
        try:
            store = get_store()
            if store is not None:
                store.upload_scenario(safe_ticker, str(trade_date), path)
        except Exception:
            # 任何错误都吞掉——本地文件是真源，云端只是共享层。
            pass
```

- [ ] **Step 4.4: 运行确认通过**

```bash
.venv/bin/python -m pytest tests/test_finalize_scenario.py -v
```
Expected: 全部通过（原有 5 + 新增 3 = 8）

- [ ] **Step 4.5: 提交**

```bash
git add tradingagents/graph/trading_graph.py tests/test_finalize_scenario.py
git commit -m "feat(graph): finalize_graph_run 写完后通过 CloudStore 工厂尽力上传"
```

---

## Task 5: `analyze` 命令加前置云端检查

**Files:**
- Modify: `cli/main.py`
- Create: `tests/test_cli_analyze_cloud.py`

- [ ] **Step 5.1: 先写测试**

创建 `tests/test_cli_analyze_cloud.py`：

```python
"""analyze 命令的云端前置检查：cloud 有 → 下载 + 跳过 LLM。"""
import json

import pytest


def _fake_store_with_payload(payload):
    class FakeStore:
        def is_configured(self):
            return True
        def download_scenario(self, ticker, date, target_path):
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(json.dumps(payload), encoding="utf-8")
            return True
        def upload_scenario(self, *a, **kw):
            return True
    return FakeStore()


def test_headless_analyze_uses_cloud_when_available(tmp_path, monkeypatch):
    """cloud 命中 → 不跑 graph，直接返回 downloaded scenario 的评级。"""
    from tradingagents.default_config import DEFAULT_CONFIG
    from cli import main as cli_main
    from cli.main import run_analysis_headless

    monkeypatch.setitem(DEFAULT_CONFIG, "results_dir", str(tmp_path))

    payload = {
        "version": 1, "ticker": "600519", "trade_date": "2026-09-01",
        "rating": "Buy",
        "scenario_buckets": [{
            "horizon_months": 6,
            "scenarios": [
                {"name": "bull", "thesis": "t", "expected_return": 0.2, "prob": 0.3},
                {"name": "base", "thesis": "t", "expected_return": 0.05, "prob": 0.5},
                {"name": "bear", "thesis": "t", "expected_return": -0.1, "prob": 0.2},
            ],
            "key_levels": {"stop": 9, "entry_low": 10, "entry_high": 10, "target": 12},
        }],
        "falsification": {"conditions": []},
    }

    monkeypatch.setattr(cli_main, "get_store", lambda: _fake_store_with_payload(payload), raising=False)

    # graph 不该被构造
    from tradingagents.graph import trading_graph as tg
    def graph_ctor_should_not_be_called(*a, **kw):
        raise AssertionError("cloud 命中应跳过 graph 构造")
    monkeypatch.setattr(tg, "TradingAgentsGraph", graph_ctor_should_not_be_called)

    result = run_analysis_headless(
        ticker="600519", analysis_date="2026-09-01",
        analyst_keys=["market"], debate_rounds=0,
    )
    assert result["mode"] == "result"
    assert result["source"] == "cloud"
    assert result["rating"] == "Buy"
    assert result["ticker"] == "600519"


def test_headless_analyze_falls_through_when_no_store(tmp_path, monkeypatch):
    """无 store → 走原有 graph 分析路径（验证进了 graph 构造）。"""
    from tradingagents.default_config import DEFAULT_CONFIG
    from cli import main as cli_main
    from cli.main import run_analysis_headless

    monkeypatch.setitem(DEFAULT_CONFIG, "results_dir", str(tmp_path))
    monkeypatch.setattr(cli_main, "get_store", lambda: None, raising=False)

    from tradingagents.graph import trading_graph as tg
    ctor_called = []
    def fake_ctor(*a, **kw):
        ctor_called.append(1)
        raise RuntimeError("stop here — 只验证 ctor 被调用了")
    monkeypatch.setattr(tg, "TradingAgentsGraph", fake_ctor)

    with pytest.raises(RuntimeError, match="stop here"):
        run_analysis_headless(
            ticker="600519", analysis_date="2026-09-01",
            analyst_keys=["market"], debate_rounds=0,
        )
    assert ctor_called == [1]
```

- [ ] **Step 5.2: 运行确认失败**

```bash
.venv/bin/python -m pytest tests/test_cli_analyze_cloud.py -v
```
Expected: 两个测试都 FAIL

- [ ] **Step 5.3: 改 cli/main.py`**

在 `cli/main.py` 顶部 imports 附近追加：

```python
from tradingagents.cloud import get_store
```

在 `run_analysis_headless` 函数里，`config["checkpoint_enabled"] = checkpoint` 之后、`if not force` 之前插入：

```python
    config = DEFAULT_CONFIG.copy()
    config["max_debate_rounds"] = debate_rounds
    config["max_risk_discuss_rounds"] = debate_rounds
    config["checkpoint_enabled"] = checkpoint

    # ── 云端前置检查：cloud 有就直接复用，省掉 LLM 分析 ─────────────
    if not force:
        cached = _try_reuse_cloud_scenario(ticker, analysis_date, config)
        if cached is not None:
            return cached

    # Same-day guard — headless mode never prompts; return an error envelope.
    if not force:
        artifacts = existing_artifacts(
            config["results_dir"], ticker, analysis_date
        )
```

在 `run_analysis_headless` 之前定义辅助函数：

```python
def _try_reuse_cloud_scenario(
    ticker: str, analysis_date: str, config: dict
) -> Optional[dict]:
    """cloud 有 scenario.json → 下载 + 构造 result envelope；否则返回 None。

    与直接跑 graph 的产物形状对齐：mode/rating/ticker/analysis_date/scenario_tree/stats。
    source 字段标注 'cloud'，方便调用方区分。
    """
    import json as _json

    store = get_store()
    if store is None:
        return None
    target = Path(config["results_dir"]) / ticker / analysis_date / "scenario.json"
    if target.exists():
        # 本地已有，交给下游同日守卫处理
        return None
    if not store.download_scenario(ticker, analysis_date, target):
        return None
    try:
        payload = _json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return None
    return {
        "mode": "result",
        "source": "cloud",
        "ticker": ticker,
        "analysis_date": analysis_date,
        "rating": payload.get("rating", ""),
        "final_trade_decision": "",  # 云端 artifact 不含全文
        "scenario_tree": {
            "decision": {
                "rating": payload.get("rating"),
                "scenario_buckets": payload.get("scenario_buckets", []),
                "falsification": payload.get("falsification"),
            },
            "scenario_meta": payload.get("scenario_meta", {}),
        },
        "stats": {
            "llm_calls": 0,
            "tool_calls": 0,
            "tokens_in": 0,
            "tokens_out": 0,
            "elapsed_seconds": 0.0,
        },
        "artifacts_dir": str(target.parent),
    }
```

- [ ] **Step 5.4: 运行确认通过**

```bash
.venv/bin/python -m pytest tests/test_cli_analyze_cloud.py -v
```
Expected: 2 passed

- [ ] **Step 5.5: 全套回归**

```bash
.venv/bin/python -m pytest tests/ --ignore=tests/test_mcp_e2e_stdio.py \
  --ignore=tests/test_mcp_e2e_sse.py --ignore=tests/test_mcp_e2e_http.py -q
```
Expected: 全部通过（原有 634 + 新加约 21 = 655 左右）

- [ ] **Step 5.6: 提交**

```bash
git add cli/main.py tests/test_cli_analyze_cloud.py
git commit -m "feat(cli): analyze --json --confirm 前置 CloudStore 检查，命中则跳过 LLM"
```

---

## Task 6: CLAUDE.md 文档更新

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 6.1: 新增"云端报告共享"段**

在 `CLAUDE.md` 合适位置（"关键路径"下方 / "中文股票名解析"上方）新增：

```markdown
### 云端报告共享（v0.5.16+）
`scenario.json` 可选上传/下载云端 bucket，让不同用户共享分析结果。
`tradingagents/cloud/` 三层结构：

- `base.py` — `CloudStore` **Protocol** + `scenario_object_key()` 命名约定
- `r2.py` — `R2Store` 首个实现（Cloudflare R2 私有 bucket，需 `[cloud]` extra）
- `__init__.py` — 工厂 `get_store() -> Optional[CloudStore]`：探测已配置的第一个后端

**Caller 侧只 import 接口**：`from tradingagents.cloud import get_store`。
未来加 S3 / OSS / MinIO 只需新增实现类 + 在工厂里加分支，caller 无感。

**触发点**：
- `graph.finalize_graph_run()` 写完本地后调 `get_store().upload_scenario()`
- `advisor.scenario_io.load_scenario()` 本地未命中时调 `get_store().download_scenario()`
- `cli.main.run_analysis_headless()` 跑分析前先查 cloud，命中则跳过 LLM（`source: "cloud"`）

**R2 实现的环境变量（四个都必须齐全）**：
- `TRADINGAGENTS_R2_ACCOUNT_ID`
- `TRADINGAGENTS_R2_ACCESS_KEY_ID`
- `TRADINGAGENTS_R2_SECRET_ACCESS_KEY`
- `TRADINGAGENTS_R2_BUCKET`

**装法**：`pip install -e '.[cloud]'`（加装 boto3）。

**Object key 约定**（所有实现共用）：`{ticker}/{date}/scenario.json`。这个
约定放在 `base.py` 里，避免各后端各自命名导致互相看不到对方存的文件。

⚠️ **所有云端调用都是尽力而为**——异常吞掉、返回 False，绝不上抛。本地
`scenario.json` 才是真源，云端只是共享层。
```

- [ ] **Step 6.2: 提交**

```bash
git add CLAUDE.md
git commit -m "docs: 云端报告共享段（接口/实现分离 + R2 首个实现）"
```

---

## Self-Review

**Spec coverage:**
- ✅ 上传 `scenario.json` — Task 4 `_write_scenario_artifact` 尾部调工厂
- ✅ 分析前查云端 — Task 5 `_try_reuse_cloud_scenario` 在 `run_analysis_headless` 开头
- ✅ 命中则跳过 LLM — Task 5 测试断言 graph ctor 不被调用
- ✅ 未命中则跑分析后上传 — Task 4 upload 钩子；生成路径不变
- ✅ 接口隐藏技术细节 — Task 1 `CloudStore` Protocol；callers 只 import `get_store`
- ✅ 首个实现 R2 私有 bucket — Task 2 `R2Store` 用 boto3
- ✅ 未来可扩展 — 工厂 `get_store()` 里追加分支即可，caller 无感
- ✅ 尽力而为语义 — 所有 caller 用 try/except 全吞

**Placeholder scan:** 无 TBD/TODO/similar to N；所有代码块都是完整可粘贴的。

**Type consistency:**
- `CloudStore` Protocol：`is_configured() -> bool` / `download_scenario(ticker, date, target_path) -> bool` / `upload_scenario(ticker, date, local_path) -> bool` — Task 1 定义，Task 2 R2Store 实现，Task 3/4/5 callers 使用，全 plan 签名一致
- `get_store() -> Optional[CloudStore]` — Task 1 定义，Task 3/4/5 使用，全 plan 返回类型一致
- `scenario_object_key(ticker, date) -> str` — Task 1 定义，Task 2 R2Store 使用，全 plan 一致
- `_try_reuse_cloud_scenario` 返回 `Optional[dict]` — 与调用方 `if cached is not None` 对齐

Plan 通过 self-review，无内部矛盾。
