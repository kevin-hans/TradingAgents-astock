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
    from tradingagents.cloud.r2 import R2Store
    store = R2Store()
    if store.is_configured():
        return store
    return None
