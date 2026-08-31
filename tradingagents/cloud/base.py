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
