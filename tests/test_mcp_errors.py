from tradingagents.mcp.errors import (
    CLIError,
    map_cli_error,
    MCP_ERROR_KYC_REQUIRED,
    MCP_ERROR_INVALID_KYC,
    MCP_ERROR_NOT_FOUND,
    MCP_ERROR_INTERNAL,
    MCP_ERROR_NOT_IMPLEMENTED,
)


class TestMapCLIError:
    def test_exit_code_1_not_found(self):
        err = map_cli_error(1, b'{"error": "not_found", "message": "no scenario for X"}')
        assert isinstance(err, CLIError)
        assert err.code == MCP_ERROR_NOT_FOUND
        assert "no scenario" in err.message

    def test_exit_code_2_invalid_kyc(self):
        err = map_cli_error(2, b'{"error": "invalid_kyc", "message": "q1=4"}')
        assert err.code == MCP_ERROR_INVALID_KYC

    def test_exit_code_3_kyc_required(self):
        err = map_cli_error(3, b'{"error": "kyc_required", "questionnaire": {"schema_version": 1}}')
        assert err.code == MCP_ERROR_KYC_REQUIRED
        assert err.payload.get("questionnaire", {}).get("schema_version") == 1

    def test_exit_code_5_not_implemented(self):
        err = map_cli_error(5, b'{"error": "not_implemented", "message": "todo"}')
        assert err.code == MCP_ERROR_NOT_IMPLEMENTED

    def test_unknown_exit_code_falls_back_to_internal(self):
        err = map_cli_error(255, b"segfault or something")
        assert err.code == MCP_ERROR_INTERNAL

    def test_exit_code_6_partial_data(self):
        from tradingagents.mcp.errors import MCP_ERROR_PARTIAL_DATA

        err = map_cli_error(6, b'{"items": [], "skipped": [{"reason": "quote_failed"}]}')
        assert err.code == MCP_ERROR_PARTIAL_DATA

    def test_malformed_stderr_still_returns_internal(self):
        err = map_cli_error(1, b"not json at all")
        # 无 payload.error 时 fallback 到 exit code 映射 (1 → not_found)
        assert err.code == MCP_ERROR_NOT_FOUND
        # message 是 raw stderr（无 message 字段）
        assert err.payload.get("raw_stderr") == "not json at all"

    def test_empty_stderr(self):
        err = map_cli_error(4, b"")
        assert err.code == MCP_ERROR_INTERNAL
