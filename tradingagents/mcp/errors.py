"""CLI exit code + stderr/stdout JSON → MCP 错误码映射。

CLAUDE.md 薄壳方针：本文件只 import 标准库。
"""
import json
from dataclasses import dataclass, field
from typing import Any


MCP_ERROR_NOT_FOUND = "not_found"
MCP_ERROR_INVALID_KYC = "invalid_kyc"
MCP_ERROR_KYC_REQUIRED = "kyc_required"
MCP_ERROR_INTERNAL = "internal"
MCP_ERROR_NOT_IMPLEMENTED = "not_implemented"
MCP_ERROR_ARTIFACT_EXISTS = "artifact_exists"
MCP_ERROR_PARTIAL_DATA = "partial_data_failure"


@dataclass
class CLIError:
    code: str
    message: str
    payload: dict[str, Any] = field(default_factory=dict)


_CODE_MAP = {
    1: MCP_ERROR_NOT_FOUND,
    2: MCP_ERROR_INVALID_KYC,
    3: MCP_ERROR_KYC_REQUIRED,
    4: MCP_ERROR_INTERNAL,
    5: MCP_ERROR_NOT_IMPLEMENTED,
    6: MCP_ERROR_PARTIAL_DATA,
}


def map_cli_error(exit_code: int, body: bytes | str) -> CLIError:
    """把 CLI 非零 exit + JSON payload 转成结构化 CLIError。

    body 可能是 stdout（CLI 用 print_json 走 stdout）或 stderr。
    """
    text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    payload: dict[str, Any] = {}

    if text.strip():
        try:
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                payload = parsed
            else:
                payload = {"raw_stderr": text}
        except json.JSONDecodeError:
            payload = {"raw_stderr": text}

    # 优先看 payload["error"] 字段；没有则回退到 exit code 映射
    code_from_payload = payload.get("error")
    code = code_from_payload or _CODE_MAP.get(exit_code, MCP_ERROR_INTERNAL)

    # message 提取：有 payload.message 就用，否则用 raw text
    if "message" in payload:
        message = payload["message"]
    else:
        message = text.strip()

    return CLIError(code=code, message=message, payload=payload)
