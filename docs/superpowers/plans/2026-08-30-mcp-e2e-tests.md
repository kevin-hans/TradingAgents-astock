# MCP E2E Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 18 end-to-end tests (9 cases × stdio + SSE) that launch a real `tradingagents mcp-serve` subprocess, connect via `mcp.client`, and exercise all 6 tools — zero LLM calls, reusing existing 600519/2026-08-30 artifacts.

**Architecture:** Three files are touched: `tests/conftest.py` gains four new fixtures; `tests/test_mcp_e2e_stdio.py` and `tests/test_mcp_e2e_sse.py` each run the same 9 test cases against their respective transport. Both files are guarded by `pytest.importorskip("mcp")` so they skip cleanly without `[dev]` extra installed.

**Tech Stack:** `mcp 2.1.0` (`stdio_client`, `sse_client`, `ClientSession`), `httpx 0.25.2` (SSE readiness probe), `pytest-asyncio`, `asyncio.create_subprocess_exec`, `shutil.copytree`.

---

## Known behavior facts (read before writing any test)

| Scenario | CLI exit | `CLIResult.ok` | MCP `is_error` | JSON key to assert |
|----------|----------|----------------|----------------|--------------------|
| `analyze --json` (no `--confirm`) | 0 | True | False | `mode == "estimate"` |
| `analyze --json --confirm` same-day artifact | 1 | False | **True** | `error == "artifacts_exist"` |
| Unknown tool name | — | — | **True** | `error == "unknown_tool"` |
| `advise` missing `kyc_answers` | — | — | **True** | `error == "internal"` |
| `advise` success JSON | 0 | True | False | `with_position.action`, `trace.w_star` |

The server never raises to the MCP client — all errors are caught by `on_call_tool` and returned as `_err_result(...)` (`is_error=True`).

---

## File map

| File | Action | Responsibility |
|------|--------|----------------|
| `tests/conftest.py` | **Modify** | Add `unused_tcp_port`, `tmp_artifacts_env`, `stdio_mcp_session`, `sse_mcp_session` |
| `tests/test_mcp_e2e_stdio.py` | **Create** | 9 tests over stdio transport |
| `tests/test_mcp_e2e_sse.py` | **Create** | Same 9 tests over SSE transport |

---

## Task 1 — Base conftest fixtures (`unused_tcp_port` + `tmp_artifacts_env`)

**Files:**
- Modify: `tests/conftest.py`

- [x] **Step 1: Append the two fixtures to `tests/conftest.py`**

Open `tests/conftest.py` and append at the bottom:

```python
# ── MCP e2e helpers ────────────────────────────────────────────────────────────

import shutil
import socket


@pytest.fixture
def unused_tcp_port() -> int:
    """Return a free TCP port by binding and releasing it."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


@pytest.fixture
def tmp_artifacts_env(tmp_path):
    """Copy real 600519/2026-08-30 artifacts to tmp_path and point TRADINGAGENTS_RESULTS_DIR there.

    Each test gets a fresh writable copy; the real log directory is never touched.
    """
    import os as _os
    src = _os.path.expanduser("~/.tradingagents/logs/600519")
    dst = tmp_path / "logs" / "600519"
    shutil.copytree(src, dst)
    results_dir = str(tmp_path / "logs")
    prev = _os.environ.get("TRADINGAGENTS_RESULTS_DIR")
    _os.environ["TRADINGAGENTS_RESULTS_DIR"] = results_dir
    yield results_dir
    if prev is None:
        _os.environ.pop("TRADINGAGENTS_RESULTS_DIR", None)
    else:
        _os.environ["TRADINGAGENTS_RESULTS_DIR"] = prev
```

- [x] **Step 2: Verify the fixture works in isolation**

Create a throwaway script (do NOT commit it):

```bash
.venv/bin/python -c "
import os, shutil, tempfile
src = os.path.expanduser('~/.tradingagents/logs/600519')
with tempfile.TemporaryDirectory() as tmp:
    dst = os.path.join(tmp, 'logs', '600519')
    shutil.copytree(src, dst)
    files = list(os.walk(dst))
    print('Copied OK, dirs:', len(files))
"
```

Expected: prints `Copied OK, dirs: 1` (or more).

- [x] **Step 3: Run existing tests to confirm no regression**

```bash
.venv/bin/python -m pytest tests/ -x -q 2>&1 | tail -5
```

Expected: `603 passed` (same baseline).

---

## Task 2 — `stdio_mcp_session` fixture + first test

**Files:**
- Modify: `tests/conftest.py`
- Create: `tests/test_mcp_e2e_stdio.py` (stub)

- [x] **Step 1: Write the first failing test**

Create `tests/test_mcp_e2e_stdio.py`:

```python
"""MCP e2e — stdio transport.

Launches a real `tradingagents mcp-serve --transport stdio` subprocess,
connects via mcp.client.stdio, and exercises all 6 tools.

Requires [dev] extra (mcp, pytest-asyncio). Skips cleanly without it.
LLM calls: zero — all tools run against existing 600519/2026-08-30 artifacts.
"""
import json

import pytest

pytest.importorskip("mcp")
pytest.importorskip("pytest_asyncio")

TICKER = "600519"
DATE = "2026-08-30"
KYC = {"q1": 5, "q2": 5, "q3": 5, "q4": 5, "q5": 5}


@pytest.mark.asyncio
async def test_list_tools_returns_six(stdio_mcp_session):
    result = await stdio_mcp_session.list_tools()
    names = {t.name for t in result.tools}
    assert names == {
        "reports", "kyc_questionnaire", "scenario",
        "advise", "review", "analyze",
    }
```

- [x] **Step 2: Run — expect FAIL (fixture not found)**

```bash
.venv/bin/python -m pytest tests/test_mcp_e2e_stdio.py::test_list_tools_returns_six -v 2>&1 | tail -10
```

Expected: `ERRORS` or `FAILED` with `fixture 'stdio_mcp_session' not found`.

- [x] **Step 3: Add `stdio_mcp_session` to `tests/conftest.py`**

Append after the `tmp_artifacts_env` fixture:

```python
@pytest.fixture
def stdio_mcp_session(tmp_artifacts_env):
    """Yield an initialised MCP ClientSession over stdio transport.

    Requires [dev] extra (mcp, pytest-asyncio).
    """
    pytest.importorskip("mcp")
    pytest.importorskip("pytest_asyncio")
    import asyncio
    import os
    import shutil as _shutil
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    cmd = _shutil.which("tradingagents") or str(
        __import__("pathlib").Path(__file__).parent.parent
        / ".venv" / "bin" / "tradingagents"
    )
    params = StdioServerParameters(
        command=cmd,
        args=["mcp-serve", "--transport", "stdio"],
        env={**os.environ},
    )

    async def _run():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session

    # pytest fixtures cannot be async generators directly; bridge via a queue.
    import queue as _queue
    q: _queue.Queue = _queue.Queue()
    loop = asyncio.new_event_loop()

    async def _producer():
        async for s in _run():
            q.put(s)
            await asyncio.get_event_loop().run_in_executor(None, q.join)

    import threading
    t = threading.Thread(target=loop.run_until_complete, args=(_producer(),), daemon=True)
    t.start()
    session = q.get(timeout=15)
    yield session
    q.task_done()
    t.join(timeout=10)
    loop.close()
```

> **Note:** The bridging pattern above is complex. A cleaner alternative using `pytest-asyncio`'s native async fixtures is shown in Step 4.

- [x] **Step 4: Replace with native pytest-asyncio async fixture (simpler)**

The `pytest-asyncio` package allows `async def` fixtures when the test is marked `@pytest.mark.asyncio`. Replace the `stdio_mcp_session` fixture added in Step 3 with:

```python
@pytest.fixture
def stdio_mcp_session(tmp_artifacts_env):
    """Synchronous wrapper — delegates to _stdio_mcp_session_async.

    pytest-asyncio 0.21+ supports async fixtures but requires the test to
    be in the same event loop scope. We expose a sync fixture that holds the
    async context manager open via asyncio.run on a background thread to
    keep fixtures transport-agnostic and compatible with the existing suite.
    """
    import asyncio, os, shutil as _sh, threading, queue as _q
    from mcp.client.session import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    cmd = _sh.which("tradingagents") or str(
        __import__("pathlib").Path(__file__).parent.parent
        / ".venv" / "bin" / "tradingagents"
    )
    params = StdioServerParameters(
        command=cmd,
        args=["mcp-serve", "--transport", "stdio"],
        env={**os.environ},
    )

    ready: _q.Queue = _q.Queue()
    done: _q.Queue = _q.Queue()

    async def _run():
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                ready.put(session)      # unblock the fixture
                await asyncio.to_thread(done.get)  # wait for test teardown

    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_until_complete, args=(_run(),), daemon=True)
    t.start()
    session = ready.get(timeout=15)
    yield session
    done.put(None)       # signal teardown
    t.join(timeout=10)
    loop.close()
```

- [x] **Step 5: Run — expect PASS**

```bash
.venv/bin/python -m pytest tests/test_mcp_e2e_stdio.py::test_list_tools_returns_six -v 2>&1 | tail -10
```

Expected:
```
PASSED tests/test_mcp_e2e_stdio.py::test_list_tools_returns_six
1 passed in ...
```

- [x] **Step 6: Commit**

```bash
git add tests/conftest.py tests/test_mcp_e2e_stdio.py
git commit -m "test(mcp): stdio e2e fixture + list_tools smoke test"
```

---

## Task 3 — stdio happy path (remaining 6 tests)

**Files:**
- Modify: `tests/test_mcp_e2e_stdio.py`

- [x] **Step 1: Add helper and 6 more test functions**

Append to `tests/test_mcp_e2e_stdio.py` after `test_list_tools_returns_six`:

```python
# ── helpers ───────────────────────────────────────────────────────────────────

def _parse(result) -> dict:
    """Parse JSON from the first text content block of a CallToolResult."""
    return json.loads(result.content[0].text)


# ── happy path ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_kyc_questionnaire(stdio_mcp_session):
    result = await stdio_mcp_session.call_tool("kyc_questionnaire", {})
    text = result.content[0].text
    for q in ("q1", "q2", "q3", "q4", "q5"):
        assert q in text, f"expected {q!r} in kyc_questionnaire response"


@pytest.mark.asyncio
async def test_reports_returns_list(stdio_mcp_session):
    result = await stdio_mcp_session.call_tool("reports", {})
    assert not result.is_error
    data = _parse(result)
    assert isinstance(data.get("reports"), list)


@pytest.mark.asyncio
async def test_scenario_600519(stdio_mcp_session):
    result = await stdio_mcp_session.call_tool(
        "scenario", {"ticker": TICKER, "date": DATE}
    )
    assert not result.is_error
    data = _parse(result)
    assert isinstance(data.get("scenario_buckets"), list)
    assert len(data["scenario_buckets"]) == 2
    assert isinstance(data.get("rating"), str) and data["rating"]


@pytest.mark.asyncio
async def test_advise_600519(stdio_mcp_session):
    result = await stdio_mcp_session.call_tool(
        "advise",
        {"ticker": TICKER, "date": DATE, "kyc_answers": KYC},
    )
    assert not result.is_error
    data = _parse(result)
    assert "with_position" in data
    assert "action" in data["with_position"]
    assert "trace" in data
    assert isinstance(data["trace"].get("w_star"), float)


@pytest.mark.asyncio
async def test_analyze_confirm_false(stdio_mcp_session):
    result = await stdio_mcp_session.call_tool(
        "analyze", {"ticker": TICKER, "depth": "quick", "confirm": False}
    )
    assert not result.is_error
    data = _parse(result)
    assert data.get("mode") == "estimate"
    assert "estimated_llm_calls" in data


@pytest.mark.asyncio
async def test_analyze_same_day_guard(stdio_mcp_session):
    # confirm=True on an already-analysed date → same-day guard fires, no LLM
    result = await stdio_mcp_session.call_tool(
        "analyze",
        {"ticker": TICKER, "date": DATE, "depth": "quick", "confirm": True},
    )
    assert result.is_error
    data = _parse(result)
    assert data.get("error") == "artifacts_exist"
```

- [x] **Step 2: Run the 6 new tests**

```bash
.venv/bin/python -m pytest tests/test_mcp_e2e_stdio.py -v -k "not error" 2>&1 | tail -15
```

Expected: `7 passed` (list_tools + 6 happy path).

- [x] **Step 3: Commit**

```bash
git add tests/test_mcp_e2e_stdio.py
git commit -m "test(mcp): stdio e2e happy path (7 tests)"
```

---

## Task 4 — stdio error path (2 tests)

**Files:**
- Modify: `tests/test_mcp_e2e_stdio.py`

- [x] **Step 1: Append the 2 error-path tests**

```python
# ── error path ────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unknown_tool_returns_error(stdio_mcp_session):
    result = await stdio_mcp_session.call_tool("nonexistent_tool", {})
    assert result.is_error
    data = _parse(result)
    assert data.get("error") == "unknown_tool"


@pytest.mark.asyncio
async def test_advise_missing_kyc_raises(stdio_mcp_session):
    # kyc_answers is a required field in AdviseArgs — omitting it triggers
    # a pydantic ValidationError caught by on_call_tool's generic handler.
    result = await stdio_mcp_session.call_tool("advise", {"ticker": TICKER})
    assert result.is_error
    data = _parse(result)
    assert "error" in data
```

- [x] **Step 2: Run all 9 stdio tests**

```bash
.venv/bin/python -m pytest tests/test_mcp_e2e_stdio.py -v 2>&1 | tail -15
```

Expected:
```
PASSED tests/test_mcp_e2e_stdio.py::test_list_tools_returns_six
PASSED tests/test_mcp_e2e_stdio.py::test_kyc_questionnaire
PASSED tests/test_mcp_e2e_stdio.py::test_reports_returns_list
PASSED tests/test_mcp_e2e_stdio.py::test_scenario_600519
PASSED tests/test_mcp_e2e_stdio.py::test_advise_600519
PASSED tests/test_mcp_e2e_stdio.py::test_analyze_confirm_false
PASSED tests/test_mcp_e2e_stdio.py::test_analyze_same_day_guard
PASSED tests/test_mcp_e2e_stdio.py::test_unknown_tool_returns_error
PASSED tests/test_mcp_e2e_stdio.py::test_advise_missing_kyc_raises
9 passed in ...
```

- [x] **Step 3: Commit**

```bash
git add tests/test_mcp_e2e_stdio.py
git commit -m "test(mcp): stdio e2e error path (9 tests complete)"
```

---

## Task 5 — `sse_mcp_session` fixture

**Files:**
- Modify: `tests/conftest.py`

- [x] **Step 1: Add `sse_mcp_session` to `tests/conftest.py`**

Append after `stdio_mcp_session`:

```python
@pytest.fixture
def sse_mcp_session(tmp_artifacts_env, unused_tcp_port):
    """Yield an initialised MCP ClientSession over SSE transport.

    Starts `tradingagents mcp-serve --transport sse --port N` as a subprocess,
    waits up to 5 s for the /sse endpoint to respond, then connects.

    Skips (not fails) if the server does not start in time.
    """
    import asyncio, os, shutil as _sh, threading, queue as _q
    from mcp.client.session import ClientSession
    from mcp.client.sse import sse_client
    import httpx

    port = unused_tcp_port
    cmd = _sh.which("tradingagents") or str(
        __import__("pathlib").Path(__file__).parent.parent
        / ".venv" / "bin" / "tradingagents"
    )
    base_url = f"http://127.0.0.1:{port}"
    sse_url = f"{base_url}/sse"

    ready: _q.Queue = _q.Queue()
    done: _q.Queue = _q.Queue()
    proc_holder: list = []

    async def _run():
        proc = await asyncio.create_subprocess_exec(
            cmd, "mcp-serve", "--transport", "sse", "--port", str(port),
            env={**os.environ},
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        proc_holder.append(proc)

        # Wait for SSE endpoint to be ready (max 5 s, 0.2 s interval → 25 tries)
        async with httpx.AsyncClient() as http:
            for _ in range(25):
                try:
                    async with http.stream("GET", sse_url, timeout=0.5) as r:
                        if r.status_code == 200:
                            break
                except Exception:
                    pass
                await asyncio.sleep(0.2)
            else:
                proc.terminate()
                await proc.wait()
                ready.put(None)   # signal: server did not start
                return

        try:
            async with sse_client(sse_url) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    ready.put(session)
                    await asyncio.to_thread(done.get)
        finally:
            proc.terminate()
            await proc.wait()

    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_until_complete, args=(_run(),), daemon=True)
    t.start()
    session = ready.get(timeout=15)

    if session is None:
        t.join(timeout=5)
        loop.close()
        pytest.skip("SSE server did not start in time")

    yield session
    done.put(None)
    t.join(timeout=15)
    loop.close()
```

- [x] **Step 2: Write a minimal smoke test to validate the fixture**

```bash
.venv/bin/python -c "
import asyncio, os, httpx

async def main():
    import subprocess, time, socket
    with socket.socket() as s:
        s.bind(('', 0))
        port = s.getsockname()[1]
    env = {**os.environ, 'TRADINGAGENTS_RESULTS_DIR': '/tmp/smoke_test'}
    p = await asyncio.create_subprocess_exec(
        '.venv/bin/tradingagents', 'mcp-serve', '--transport', 'sse', '--port', str(port),
        env=env, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
    )
    ok = False
    async with httpx.AsyncClient() as c:
        for _ in range(25):
            try:
                async with c.stream('GET', f'http://127.0.0.1:{port}/sse', timeout=0.5) as r:
                    if r.status_code == 200:
                        ok = True
                        break
            except Exception:
                pass
            await asyncio.sleep(0.2)
    p.terminate()
    await p.wait()
    print('SSE server started:', ok)

asyncio.run(main())
"
```

Expected: `SSE server started: True`.

- [x] **Step 3: Commit**

```bash
git add tests/conftest.py
git commit -m "test(mcp): sse_mcp_session fixture"
```

---

## Task 6 — SSE test file (9 tests)

**Files:**
- Create: `tests/test_mcp_e2e_sse.py`

- [x] **Step 1: Write the SSE test file**

Create `tests/test_mcp_e2e_sse.py` — identical test logic to the stdio file, only the session fixture name differs:

```python
"""MCP e2e — SSE transport.

Launches a real `tradingagents mcp-serve --transport sse --port N` subprocess,
connects via mcp.client.sse, and exercises all 6 tools.

Requires [dev] extra (mcp, pytest-asyncio). Skips cleanly without it.
LLM calls: zero — all tools run against existing 600519/2026-08-30 artifacts.
"""
import json

import pytest

pytest.importorskip("mcp")
pytest.importorskip("pytest_asyncio")

TICKER = "600519"
DATE = "2026-08-30"
KYC = {"q1": 5, "q2": 5, "q3": 5, "q4": 5, "q5": 5}


def _parse(result) -> dict:
    return json.loads(result.content[0].text)


@pytest.mark.asyncio
async def test_list_tools_returns_six(sse_mcp_session):
    result = await sse_mcp_session.list_tools()
    names = {t.name for t in result.tools}
    assert names == {
        "reports", "kyc_questionnaire", "scenario",
        "advise", "review", "analyze",
    }


@pytest.mark.asyncio
async def test_kyc_questionnaire(sse_mcp_session):
    result = await sse_mcp_session.call_tool("kyc_questionnaire", {})
    text = result.content[0].text
    for q in ("q1", "q2", "q3", "q4", "q5"):
        assert q in text, f"expected {q!r} in kyc_questionnaire response"


@pytest.mark.asyncio
async def test_reports_returns_list(sse_mcp_session):
    result = await sse_mcp_session.call_tool("reports", {})
    assert not result.is_error
    data = _parse(result)
    assert isinstance(data.get("reports"), list)


@pytest.mark.asyncio
async def test_scenario_600519(sse_mcp_session):
    result = await sse_mcp_session.call_tool(
        "scenario", {"ticker": TICKER, "date": DATE}
    )
    assert not result.is_error
    data = _parse(result)
    assert isinstance(data.get("scenario_buckets"), list)
    assert len(data["scenario_buckets"]) == 2
    assert isinstance(data.get("rating"), str) and data["rating"]


@pytest.mark.asyncio
async def test_advise_600519(sse_mcp_session):
    result = await sse_mcp_session.call_tool(
        "advise",
        {"ticker": TICKER, "date": DATE, "kyc_answers": KYC},
    )
    assert not result.is_error
    data = _parse(result)
    assert "with_position" in data
    assert "action" in data["with_position"]
    assert "trace" in data
    assert isinstance(data["trace"].get("w_star"), float)


@pytest.mark.asyncio
async def test_analyze_confirm_false(sse_mcp_session):
    result = await sse_mcp_session.call_tool(
        "analyze", {"ticker": TICKER, "depth": "quick", "confirm": False}
    )
    assert not result.is_error
    data = _parse(result)
    assert data.get("mode") == "estimate"
    assert "estimated_llm_calls" in data


@pytest.mark.asyncio
async def test_analyze_same_day_guard(sse_mcp_session):
    result = await sse_mcp_session.call_tool(
        "analyze",
        {"ticker": TICKER, "date": DATE, "depth": "quick", "confirm": True},
    )
    assert result.is_error
    data = _parse(result)
    assert data.get("error") == "artifacts_exist"


@pytest.mark.asyncio
async def test_unknown_tool_returns_error(sse_mcp_session):
    result = await sse_mcp_session.call_tool("nonexistent_tool", {})
    assert result.is_error
    data = _parse(result)
    assert data.get("error") == "unknown_tool"


@pytest.mark.asyncio
async def test_advise_missing_kyc_raises(sse_mcp_session):
    result = await sse_mcp_session.call_tool("advise", {"ticker": TICKER})
    assert result.is_error
    data = _parse(result)
    assert "error" in data
```

- [x] **Step 2: Run all 9 SSE tests**

```bash
.venv/bin/python -m pytest tests/test_mcp_e2e_sse.py -v 2>&1 | tail -15
```

Expected: `9 passed`.

- [x] **Step 3: Commit**

```bash
git add tests/test_mcp_e2e_sse.py
git commit -m "test(mcp): SSE e2e (9 tests complete)"
```

---

## Task 7 — Full suite verification

**Files:** none modified

- [x] **Step 1: Run entire test suite**

```bash
.venv/bin/python -m pytest tests/ -q 2>&1 | tail -5
```

Expected:
```
621 passed, 1 skipped in ...s
```

(603 baseline + 9 stdio + 9 SSE = 621; the existing 1 skipped remains.)

- [x] **Step 2: Verify e2e tests skip cleanly without `[dev]` extra**

```bash
.venv/bin/python -m pytest tests/test_mcp_e2e_stdio.py tests/test_mcp_e2e_sse.py -v \
  --co 2>&1 | head -5
# then run with a fresh Python that has no mcp installed to confirm skip
python3 -c "import mcp" 2>&1 || echo "mcp not in base python — skip confirmed"
```

Expected: base Python does not have `mcp`, confirming the guard works.

- [x] **Step 3: Final commit**

```bash
git add .
git commit -m "test(mcp): e2e suite complete — 18 tests, stdio + SSE, zero LLM"
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `fixture 'stdio_mcp_session' not found` | conftest changes not saved | Recheck `tests/conftest.py` |
| `ready.get(timeout=15)` hangs | Server took >15 s to start | Check `tradingagents mcp-serve --transport stdio` manually |
| SSE test skipped "did not start in time" | Port conflict or uvicorn slow | Increase `range(25)` retries in `sse_mcp_session` |
| `test_analyze_same_day_guard` fails with `is_error=False` | `TRADINGAGENTS_RESULTS_DIR` not inherited | Confirm subprocess inherits `{**os.environ}` |
| `test_scenario_600519` `not_found` error | `scenario_600519_2026-08-30.json` missing | Run the Portfolio Manager regen script first |
| `621 passed` but some SSE tests red | `httpx` version mismatch | `pip install "httpx>=0.25,<0.26"` already pinned |

---

## Implementation notes (2026-08-30, post-execution)

Deviations from the original spec, all forced by correctness:

1. **Fixture shape = context-manager factory, not async-generator fixture.**
   The spec's Task 2 Step 3/4 threading bridge (and a plain
   `@pytest_asyncio.fixture` async generator) both break: pytest-asyncio
   finalises async-generator fixtures in a **different task**, and anyio
   cancel scopes inside `stdio_client`/`sse_client` are task-bound →
   `RuntimeError: Attempted to exit cancel scope in a different task`
   on teardown (test body itself passes). Fix: fixtures `stdio_mcp` /
   `sse_mcp` return an `@contextlib.asynccontextmanager` factory; each test
   enters `async with stdio_mcp() as session:` inside its own body so
   enter/exit share one task. This mirrors how mcp python-sdk's own tests
   inline the context managers.
2. **CLI resolution is venv-first** (`.venv/bin/tradingagents` before
   `shutil.which`) so tests exercise the repo checkout, not whatever install
   happens to be on PATH.
3. **Baseline drift:** suite was 609 passed / 1 skipped before this plan ran
   (not 603 — later merges added tests). Final: **627 passed / 1 skipped**.
4. `importorskip` guard verified against pytest 9.1.1 semantics: a genuinely
   absent module (ModuleNotFoundError) skips cleanly at module level; a
   *broken* mcp install (plain ImportError raised mid-import) now errors by
   design in pytest 9 — that's desirable, not a regression.
