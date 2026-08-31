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
