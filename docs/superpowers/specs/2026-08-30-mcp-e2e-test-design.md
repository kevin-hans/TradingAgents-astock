# MCP E2E Test Design

**Date:** 2026-08-30
**Scope:** End-to-end tests for the MCP server (stdio + SSE transport) using a real MCP client
**LLM calls:** Zero — all tools exercised against existing 600519/2026-08-30 artifacts

---

## Context

The MCP server (`tradingagents/mcp/`) exposes 6 tools over stdio and SSE transport. Existing tests (`test_mcp_server_integration.py`, `test_mcp_tools_unit.py`, etc.) are all mock-based: they patch `run_cli` with `AsyncMock` and never start an actual server process. What's missing is a test that crosses the true process boundary:

```
MCP client (in-process)
  ↕ MCP protocol (JSON-RPC over stdio / HTTP SSE)
tradingagents mcp-serve (subprocess)
  ↕ asyncio.subprocess
tradingagents CLI (analyze / reports / scenario / advise / review)
  ↕ filesystem
~/.tradingagents/logs/  (existing 600519/2026-08-30 artifacts)
```

No LLM is invoked because:
- `reports`, `kyc_questionnaire`, `scenario`, `advise`, `review` are purely read/compute
- `analyze confirm=false` returns a live quote without triggering a pipeline
- `analyze confirm=true` on an already-analyzed date hits the same-day guard and returns `artifacts_exist`

---

## Files

```
tests/
├── conftest.py                  # existing — add stdio_mcp_session, sse_mcp_session, tmp_artifacts_env, unused_tcp_port
├── test_mcp_e2e_stdio.py        # new — 9 cases over stdio
├── test_mcp_e2e_sse.py          # new — 9 cases over SSE
```

No other files are touched. Both test files share the same 9 test cases; only the session fixture differs.

---

## Fixtures (conftest.py additions)

### `unused_tcp_port` (session-scoped)

Binds `('', 0)` to let the OS assign a free port, extracts the number, closes the socket, returns the int. Avoids hardcoded ports and cross-test collisions.

### `tmp_artifacts_env` (function-scoped)

1. Copies `~/.tradingagents/logs/600519/` to `tmp_path/logs/600519/` using `shutil.copytree`
2. Sets `TRADINGAGENTS_RESULTS_DIR=str(tmp_path/logs)` in `os.environ`
3. Yields
4. Restores the original env var (or removes it if it wasn't set)

This makes each test start with a clean writable copy of the real 600519/2026-08-30 artifacts, so tests cannot pollute each other.

### `stdio_mcp_session` (function-scoped, async)

```python
params = StdioServerParameters(
    command=".venv/bin/tradingagents",
    args=["mcp-serve", "--transport", "stdio"],
    env={**os.environ},   # inherits TRADINGAGENTS_RESULTS_DIR from tmp_artifacts_env
)
async with stdio_client(params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        yield session
```

`stdio_client` owns the subprocess lifetime; no explicit teardown needed.

### `sse_mcp_session` (function-scoped, async)

1. Start `tradingagents mcp-serve --transport sse --port {unused_tcp_port}` via `asyncio.create_subprocess_exec`
2. Poll `GET http://127.0.0.1:{port}/sse` with `httpx.AsyncClient` every 0.2 s up to 5 s; if never ready, `proc.terminate()` + `pytest.skip("SSE server did not start in time")`
3. `async with sse_client(f"http://127.0.0.1:{port}/sse") as (read, write):`
4. `async with ClientSession(read, write) as session:` → `initialize()` → yield
5. Teardown: `proc.terminate()` → `proc.wait()`

---

## Test Cases (× 2 transport files)

Both `test_mcp_e2e_stdio.py` and `test_mcp_e2e_sse.py` run the same 9 cases, parameterised only by the session fixture injected.

### Happy path (7 cases)

| # | Name | Tool | Key assertion |
|---|------|------|---------------|
| 1 | `test_list_tools_returns_six` | — | `result.tools` has exactly 6 entries; names match `{reports, kyc_questionnaire, scenario, advise, review, analyze}` |
| 2 | `test_kyc_questionnaire` | `kyc_questionnaire` | Text content contains all of `q1`, `q2`, `q3`, `q4`, `q5` as substrings |
| 3 | `test_reports_returns_list` | `reports` | Parsed JSON has key `reports` whose value is a `list` |
| 4 | `test_scenario_600519` | `scenario` | Parsed JSON has `scenario_buckets` with 2 horizon entries; `rating` is a non-empty string |
| 5 | `test_advise_600519` | `advise` | Parsed JSON contains `w_star` (float) and `action` (string) |
| 6 | `test_analyze_confirm_false` | `analyze` | Parsed JSON has `mode: "quote"`; no new files written under `TRADINGAGENTS_RESULTS_DIR` |
| 7 | `test_analyze_same_day_guard` | `analyze` | `confirm=true` with ticker=600519, date=2026-08-30 → JSON has `error: "artifacts_exist"` |

### Error path (2 cases)

| # | Name | Assertion |
|---|------|-----------|
| 8 | `test_unknown_tool_returns_mcp_error` | `call_tool("nonexistent_tool", {})` raises `McpError` or returns `isError=True` content |
| 9 | `test_advise_missing_kyc_raises` | `call_tool("advise", {"ticker": "600519"})` raises or returns error content (missing required `kyc_answers`) |

**Total: 9 × 2 transport = 18 tests**

---

## Guards and CI Integration

```python
# top of both test files
pytest.importorskip("mcp")
pytest.importorskip("pytest_asyncio")
```

- Without `[dev]` extra: all 18 tests **skip** — existing 603 baseline unaffected
- With `[dev]` extra installed: 18 tests added → target **621 passed**

Both files carry `pytestmark = pytest.mark.asyncio` at module level so every `async def test_*` runs under the asyncio event loop automatically.

---

## Timeout budget

| Stage | Budget |
|-------|--------|
| `session.initialize()` (stdio) | 10 s |
| SSE server readiness poll | 5 s max |
| Each `call_tool` | MCP SDK default (30 s) |
| `analyze confirm=false` | ≤ 10 s (live quote fetch only) |
| `analyze confirm=true` same-day guard | ≤ 5 s (no LLM, just artifact scan) |

---

## Out of Scope

- SSE authentication / TLS
- Multi-client concurrency over SSE
- `analyze confirm=true --force` (would invoke LLM)
- Windows path handling (CI is macOS/Linux)
