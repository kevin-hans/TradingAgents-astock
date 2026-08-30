# TradingAgents MCP Server 部署

MCP server 把 TradingAgents 的分析能力暴露给任何 MCP 客户端（PicoClaw / Claude
Code / Codex / 其它）。6 个工具全部通过 subprocess 调 CLI，MCP 层零业务逻辑
（项目级薄壳方针，见 CLAUDE.md）。

## 安装

服务器需装 Python 3.10+ 与完整 TradingAgents：

```bash
git clone https://github.com/simonlin1212/TradingAgents-astock
cd TradingAgents-astock
python -m venv .venv
.venv/bin/pip install -e .[mcp]
```

`[mcp]` extra 引入 mcp SDK（依赖 httpx2，与 mootdx 的 httpx<0.26 无冲突）。

## 启动

**stdio（本地单机 / 客户端自己拉起子进程）**：

```bash
.venv/bin/tradingagents mcp-serve --transport stdio
```

**HTTP（远程，小设备客户端连服务器）**：

```bash
.venv/bin/tradingagents mcp-serve --transport sse --host 0.0.0.0 --port 8765
```

一个进程同时挂两套 HTTP 传输（`tradingagents/mcp/server.py` 的 `build_http_app`）：

| 端点 | 传输 | 说明 |
|---|---|---|
| `http://<host>:<port>/mcp` | **Streamable HTTP（推荐）** | POST 直接回 JSON（`json_response=True`），无空闲 SSE 流脆弱性——KYC 问卷这种人机长间隔交互必须用这个 |
| `http://<host>:<port>/sse` | legacy SSE | GET 建流 + POST `/messages/?session_id=`；仅收 GET（非 GET 返 405），为老客户端保留 |

实现基于 starlette + uvicorn（mcp 传递依赖，无需另装）。注意：starlette 1.6 的
`Request` 没有 `.send`，本项目用纯 ASGI 三件套接 `SseServerTransport.connect_sse`
与 `StreamableHTTPSessionManager.handle_request`——升级 starlette/mcp 时若路由
行为异常，先查这段。

## 客户端接入

**PicoClaw**（v0.2.8+ 的 MCP CLI）：

```bash
picoclaw mcp add tradingagents \
  --transport streamable-http \
  --url http://<server-ip>:8765/mcp
picoclaw mcp test tradingagents   # 应发现 6 个工具
```

（老版 PicoClaw 只支持 SSE 时用 `--transport sse --url http://<server-ip>:8765/sse`。）

**Claude Code / Claude Desktop**（stdio，客户端同机）：

```json
{
  "mcpServers": {
    "tradingagents": {
      "command": "/path/to/TradingAgents-astock/.venv/bin/tradingagents",
      "args": ["mcp-serve", "--transport", "stdio"]
    }
  }
}
```

## 工具面板

| 工具 | 消耗 | 说明 |
|---|---|---|
| `reports([ticker])` | 秒 | 列出可用研报 |
| `kyc_questionnaire()` | 秒 | 返回 5 题 KYC 问卷（首次建档） |
| `scenario(ticker, [date])` | 秒 | 原始情景分布（bull/base/bear + key_levels），读 scenario artifact |
| `advise(ticker, [kyc_answers], [date])` | 秒 | 个性化建议；KYC 答案 inline 传，省略则用已存档画像（`~/.tradingagents/profile.json`，可用 `TRADINGAGENTS_PROFILE` 覆盖） |
| `review([kyc_answers])` | 秒 | 决策纪律巡检（止损/目标/期限/证伪/新鲜度；部分行情失败返回 `partial_data_failure`）；KYC 同上可省略 |
| `analyze(ticker, [depth], [confirm])` | 报价秒 / 执行分钟级 | 两相：`confirm=false` 只返报价；`confirm=true` 才真跑 |

**首次建档流程**：客户端调 `advise` 不带 `kyc_answers` → 收 `kyc_required`
错误（内嵌完整问卷）→ 客户端向用户收集 5 题答案本地存储 → 之后每次调用 inline
传。校准公式（γ_eff / HC / H_avail）只住服务端，客户端永不复刻。

**当前已知边界**：`review` 需服务端能访问腾讯行情与新浪 K 线（拉现价和分析日
收盘）；行情不通的条目落入 `skipped`（`quote_failed`），exit 6。无 scenario
制品的 pending 决策标 `no_scenario` 跳过（属数据边界，不算失败）。

## 安全

**v1 不做鉴权**。生产必须满足以下之一：

- 仅监听 `127.0.0.1`（默认）+ 客户端同机或 SSH 隧道
- Tailscale / WireGuard 等私有网络
- 反向代理（Caddy / nginx basic auth / Cloudflare Tunnel）挡在公网与 8765 之间

**切勿把 8765 端口直接暴露公网**——任何能连上的人都能触发 `analyze
confirm=true` 烧你的 LLM 账单，并读取你的研报与投资者画像。

## 更多

- 设计 spec：`docs/superpowers/specs/2026-08-29-picoclaw-mcp-integration.md`
- 实现计划：`docs/superpowers/plans/2026-08-30-picoclaw-mcp-integration.md`
- 薄壳方针（为什么 MCP 层没有业务逻辑）：CLAUDE.md「MCP 集成规范」段
