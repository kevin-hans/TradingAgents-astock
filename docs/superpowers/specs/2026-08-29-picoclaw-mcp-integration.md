# PicoClaw ↔ TradingAgents MCP 集成设计

- 日期：2026-08-29
- 状态：定稿待评审
- 前置：`2026-08-29-scenario-vector-advisor-design.md` P2 交付（advisor 引擎 + CLI advise/review/scenario/reports 的 `--json` 输出）
- 定位：情景向量顾问 spec 的 **§7 MCP 面（P3+）具体化**，同时覆写 §7 的三条前提假设

## 1. 背景与动机

[PicoClaw](https://github.com/sipeed/picoclaw) 是 Sipeed 用 Go 写的超轻量个人 AI Agent，
跑在 $10 硬件 / <10MB RAM 上，原生支持 MCP。已有：自己的 chat LLM、定时调度、
推送通道（Matrix / WeChat / IRC / Discord / system tray）。

用户想在 PicoClaw 上使用本 fork 的深度研究能力。PicoClaw 硬件规格无法直接跑 15 个
Agent 的辩论管线（数百 MB RAM + 分钟级 LLM 调用），需要**把重活留在服务器、
PicoClaw 只做发单和展示**——天然是 MCP client/server 分工。

**关键收益：**

1. PicoClaw 用户在 $10 设备上就能触发和消费 A 股深度研究
2. 复用 P1/P2 已有产出（scenario.json + advisor 引擎），MCP 层零业务逻辑
3. 服务端 MCP 面同时可供 Claude Code / Codex / 其它 MCP 客户端使用（PicoClaw 只是首个宿主）
4. 保持 spec §7 "消费端只读研报、触发需显式确认"的成本透明原则

## 2. 决策记录（覆写现有 spec §7 的前提）

情景向量顾问 spec 于同日定稿，§7 关于 MCP 落点的决定基于三条前提，评审 PicoClaw
场景时逐条重新验证并推翻其中两条：

| 原 spec §7 前提 | 现实核查 | 结论 |
|---|---|---|
| a-stock-data 已经是"MCP 服务" | 实际是 Claude Code Skill（SKILL.md + 内嵌 Python），无 MCP server 代码 | **推翻**：a-stock-data 挂工具需先给它加 MCP server 皮 + 网络传输，工作量远超预期 |
| mcp SDK 依赖 httpx≥0.27，与 mootdx httpx<0.26 冲突 | mcp v2.1.1 已迁移到 **httpx2**（httpx 的独立 fork），不碰 httpx；本仓库 pyproject.toml 就有注释确认此事（`[agentsdk]` extra 通过 claude-agent-sdk → mcp → httpx2 已实测 uv lock 可锁） | **推翻**：本仓库放 MCP 依赖不再有依赖冲突 |
| MCP 层需与主仓解耦以防依赖蔓延 | 本仓库内 MCP 薄壳 import advisor 引擎函数属于同 package 下游依赖，正常层次；且 P2 引擎本就是纯函数无副作用 | **保留原则但形式改变**：解耦通过"MCP 层只暴露引擎已有函数、无独立业务逻辑"实现，不必物理隔离 |

新落点：**本仓库 `tradingagents/mcp/` 子包，作为 `[mcp]` extra，直接 import P2 引擎**。

## 3. 架构总览

```
[PicoClaw 设备侧]                    [服务器侧]
─────────────────                    ────────────────────────────
Go Agent (10MB RAM)                  TradingAgents (Python)
  │                                    │
  ├─ 本地存 KYC 5 题答案                ├─ CLI (人工/其它自动化)
  ├─ chat LLM (远程 API)                │    advise / scenario / review / analyze
  ├─ 定时/调度 (自带)                    │
  ├─ 推送 channels (自带)                └─ tradingagents/mcp/ (本 spec)
  │                                          - MCP server 薄壳
  └─ MCP client                             - 直接 import advisor 引擎
       │                                    - 直接 import CLI 内部函数（analyze 触发）
       │  MCP over HTTP/SSE                 - 暴露 6 个工具
       └──────────────────────────►         - 启动: tradingagents mcp-serve
```

**不变量：**

- MCP 薄壳零业务逻辑：`advise` 工具 = 调 `advisor.engine.advise()`，`scenario` 工具
  = 读盘上的 `scenario_<ticker>_<date>.json`。任何"MCP 独有"的逻辑视为设计违规。
- 引擎是唯一计算入口（同 spec §7）：MCP 层与 CLI 层是**平级**的两张嘴，都调同一
  个引擎函数。CLI 依然是人工与外部脚本的机器接口，MCP 是 AI 客户端的接口。
- 消费端只读原则（同 spec §7）：`advise` / `scenario` / `review` / `reports` 秒级
  返回，永不触发研究。`analyze` 是唯一触发重研究的工具，**必须显式 confirm 才执行**。
- 单一真相源（KYC 校准）：投资者向量的 γ_eff / HC / H_avail 公式只在 Python 端
  `advisor/calibrate.py` 存在；PicoClaw 只发原始 KYC 答案，不复刻公式。
- 服务端无用户会话状态：MCP 层不持有 profile.json（与 CLI 层可选持有解耦）；
  每次请求携带完整投资者向量，天然支持多客户端。

## 4. MCP 工具面板

在 `tradingagents/mcp/tools.py` 定义，`tradingagents/mcp/server.py` 挂载。所有工具
的入参出参 schema 通过 pydantic 声明，MCP SDK 自动生成 tool schema 供客户端发现。

### 4.1 只读工具（秒级，安全）

**`reports(ticker: str | None = None) -> list[ReportEntry]`**

列出可用研报。可选 ticker 过滤。实现直接扫 `~/.tradingagents/reports/` 目录（复用
CLI reports 的扫描逻辑）。

```python
class ReportEntry(BaseModel):
    ticker: str
    date: str                          # YYYY-MM-DD
    has_scenario: bool                 # 是否有 scenario.json
    rating: str | None                 # 记忆日志中的评级（如已结算）
```

**`scenario(ticker: str, date: str | None = None) -> ScenarioTree`**

返回原始情景树（bull/base/bear 概率分布 + key_levels），供 PicoClaw 的 LLM 自己
推理。`date` 缺省取该 ticker 最新的一份。缺文件返回 `not_found` 错误。

出参即 P1 已定 schema：`list[ScenarioBucket]` + `Falsification`（见 scenario-vector
spec §4.1）。

**`advise(ticker: str, kyc_answers: KYCAnswers, date: str | None = None) -> AdviceResult`**

核心工具。MCP 层动作：

```python
async def advise(ticker, kyc_answers, date=None):
    scenario = load_scenario(ticker, date)            # 磁盘读小 JSON
    if scenario is None:
        raise ToolError("not_found", "先跑 analyze 或换一个日期")
    vector = advisor.calibrate.from_kyc(kyc_answers)  # 单一真相源
    result = advisor.engine.advise(scenario, vector)  # 纯函数
    return result.to_dict()                           # 含完整 trace
```

**`review(kyc_answers: KYCAnswers) -> ReviewReport`**

对当前 pending 决策做纪律巡检（止损 / 目标 / 期限 / 证伪）。实现调 P3 `review`
CLI 的等价 Python 函数。

**`kyc_questionnaire() -> Questionnaire`**

返回 5 题 KYC 问卷全文（题目 + 选项标签 + 分值）。用于**首次建档**或**用户主动
更新画像**——PicoClaw 客户端拿到后本地展示、收集答案、存下来。

```python
class KYCOption(BaseModel):
    label: str    # "全部卖出"
    value: int    # 3

class KYCQuestion(BaseModel):
    id: Literal["q1","q2","q3","q4","q5"]
    text: str     # "组合浮亏 20% 的第一反应"
    options: list[KYCOption]

class Questionnaire(BaseModel):
    schema_version: Literal[1] = 1
    questions: list[KYCQuestion]
    note: str     # 指导客户端本地存原始答案 + inline 传的短说明
```

**为什么问卷内容由服务端持有**：题目文本、选项、分值全都是情景向量顾问 spec §5
的一部分，与校准公式强绑定。未来任何调整（加 Q6 / 改分值 / 换措辞）只在 Python
端 `advisor/calibrate.py` 一处改，PicoClaw 及其它 MCP 客户端无需升级——**单一
真相源**（同 §5 让服务端做校准的同源理由）。

### 4.2 触发工具（分钟级，需显式确认）

**`analyze(ticker: str, date: str | None = None, depth: Literal["quick","analyst","full"] = "full", confirm: bool = False, single_analyst: str | None = None) -> AnalyzeResult`**

唯一触发重研究的工具。**两相语义**（spec §7 铁律的具体化）：

```
confirm=False（默认）:
  返回 {
    "estimated_llm_calls": 47,
    "estimated_seconds": 480,
    "depth": "full",
    "note": "确认后调用 analyze(..., confirm=true) 执行"
  }
  不执行

confirm=True:
  真正跑；同步阻塞返回（MCP 长连接足够撑几分钟；PicoClaw 侧可挂着或用自己的调度
  异步获取——服务端不做异步作业管理，保持无状态）
  返回 {
    "artifact_path": "~/.tradingagents/reports/000001_2026-08-29.json",
    "rating": "Buy",
    "has_scenario": true,
    "duration_seconds": 471,
    "warnings": []
  }
```

**为什么两相**：PicoClaw 的小 LLM 可能幻觉调错工具或漏参数；第一次调用返回报价，
用户看到时间/成本预估后主动确认，才真正烧钱。同时 MCP 客户端可以在两次调用之间
渲染确认对话框。

`depth` 分档语义：
- `quick`：跳过深度辩论，只跑数据快照 + 一次 LLM 总结（估算 3~5 次调用，秒级）
- `analyst`：跑单个 analyst（配合 `single_analyst="fundamental"` 等），
  单角色深度分析（估算 5~10 次调用，分钟级）
- `full`：完整 15-agent 管线（估算 40~60 次调用，10 分钟级）

**为什么不是三个独立工具**：spec §7 明确"MCP 只是 CLI 薄包装"精神——工具面板过大
反而让 PicoClaw 的 LLM 更容易调错，`depth` 参数集中在一个工具更好。

### 4.3 首次建档：`kyc_required` 错误 + 内嵌问卷

`advise` 与 `review` 缺 `kyc_answers` 参数时，**不做隐式默认**（不假设"中性向量"，
也不静默出通用建议），返回 `kyc_required` 结构化错误，并**在错误对象里内嵌完整
问卷**——PicoClaw LLM 收到后能立刻据此向用户抛出问题，不必先额外调
`kyc_questionnaire()` 再重试。

```json
{
  "error": "kyc_required",
  "message": "需要先建立投资者画像（5 题问卷）",
  "questionnaire": { ...同 §4.1 Questionnaire 结构 }
}
```

**边界：**

- `kyc_answers` 传了但 schema 违例（`q1=0` / 缺字段）：返回 `invalid_kyc` **而
  非** `kyc_required`，不下发问卷——防止 PicoClaw LLM 陷入"每次错都重问全部 5 题"
  的循环。错误对象附具体字段说明让 LLM 修正后重试
- `scenario` / `reports` / `kyc_questionnaire` / `analyze` 不需要向量，与本节无关

### 4.4 显式 YAGNI 的工具

不做：

- `profile_set` / `profile_get`：向量客户端持有（第 5 节）
- `cancel(job_id)`：v1 同步阻塞，无 job 概念；有需要 v2 再引入 async 作业时一起做
- `history(ticker)`：`reports(ticker)` 已经覆盖
- 数据类工具（get_kline / get_lhb / ...）：这些是 a-stock-data 的职责范围，本
  spec 定位是**分析工具**；未来若 a-stock-data 真的做了 MCP，两个服务并存即可

## 5. 投资者向量的形状

**PicoClaw 端：本地持久化 5 题 KYC 原始答案**（每题一个整数，见 spec §5）：

```json
{
  "schema_version": 1,
  "kyc_answers": {"q1": 7, "q2": 5, "q3": 7, "q4": 7, "q5": 7}
}
```

存储位置由 PicoClaw 侧决定（配置文件 / 内存 / 加密存储都可）。**服务端不做假设**。

**MCP 调用入参形状：**

```python
class KYCAnswers(BaseModel):
    q1: Literal[3, 5, 7, 9]  # 浮亏 20% 反应
    q2: Literal[3, 5, 7, 9]  # 资金动用期限
    q3: Literal[3, 5, 7, 9]  # 投资经验
    q4: Literal[3, 5, 7, 9]  # 收入稳定性
    q5: Literal[3, 5, 7, 9]  # 年龄段
    schema_version: Literal[1] = 1
```

**服务端**：`advisor.calibrate.from_kyc(kyc_answers)` 现场算 γ / HC / H_avail
（spec §5 公式），传给引擎。

**为什么发原始答案而非算好的向量：**

1. 校准公式（`γ_eff = γ×(1+0.5(1−HC))` 等）与 spec 强绑定，未来任何 κ / γ 修正
   在 Python 端一处改；若 PicoClaw 侧复刻公式，双端漂移风险高
2. 5 个整数带宽可忽略
3. 服务端可以在校准时应用 v2/v3 的新维度（如 v1.5 的税务状态），无需 PicoClaw
   升级即可享受

**多客户端支持**：本形状天然支持多用户——每个 PicoClaw 存自己的答案，服务端无
状态。CLI 侧仍可选用 `~/.tradingagents/profile.json`（spec §5 原方案），两条路径
互不干扰。

### 5.1 首次建档流程（PicoClaw 端典型交互）

```
用户: "看看平安银行"
PicoClaw LLM: 调 advise("000001")  ← 首次，本地无答案
Server: 返回 kyc_required + 内嵌问卷
PicoClaw LLM: 依次向用户抛出 5 题
  "先请回答 5 个问题帮我了解你——
   1. 如果你的组合浮亏 20%，你的第一反应是？
      a) 全部卖出  b) 卖一部分  c) 持有  d) 加仓"
  ... (5 轮问答)
用户答完
PicoClaw LLM:
  1. 本地存 {q1:5, q2:7, q3:5, q4:7, q5:7}
  2. 重试 advise("000001", kyc_answers={...})
Server: 正常返回建议
以后所有调用：本地读答案 → inline 传，问卷不再触发
```

**用户想更新画像**：PicoClaw 客户端提供一句自然语言入口即可（"重做投资画像"
→ PicoClaw LLM 主动调 `kyc_questionnaire()` 重来一遍并覆写本地存储）。这是
`kyc_questionnaire` 作为独立工具（而非只依赖 `kyc_required` 错误内嵌）存在的
主要用例。

## 6. `analyze` 的显式确认语义（详）

**为什么必须两相：**

`analyze` 是本工具面板唯一"贵"操作（10 分钟 + 数十次 LLM 调用 + 数据源限流负担）。
PicoClaw 的 chat LLM 幻觉率不低，若能一次直接触发，等于把成本控制权完全交给一个
可能瞎调工具的黑盒。两相设计强制"报价 → 确认"节奏：

```
用户: "分析下 000001"
PicoClaw LLM: 调 analyze("000001") → 收到 "预计 8 分钟 / 47 次调用"
PicoClaw LLM: "跑一次要 ~8 分钟消耗约 47 次 LLM 调用，确认吗？"
用户: "确认"
PicoClaw LLM: 调 analyze("000001", confirm=true) → 阻塞等 → 拿到报告
```

**报价怎么估**：

- `quick`：常数（3-5 次调用，10 秒）
- `analyst`：常数按角色查表（约 5-10 次，1-2 分钟）
- `full`：读历史近 N 次 `full_states_log` 的实际调用数与时长取中位数，缺历史用
  保守默认（60 次 / 10 分钟）

估算函数 `advisor.estimate.estimate_analyze(ticker, date, depth)` 纯计算，秒级返回。

**同日守卫**：`analyze(..., confirm=true)` 在真正执行前**同样调 P2 §7 已有的同日
守卫**（存在制品则拒绝除非再传 `force=True`）。这一层不是 MCP 独有，是 CLI 层已有
逻辑复用。

**中途失败**：任何环节报错，返回错误对象带原因码；不留半成品制品（复用 CLI 已有
的原子写与归档逻辑）。

## 7. 部署拓扑

### 7.1 服务端

```bash
# 一台机器上（可以是家里的 NAS / 云 VPS / 老笔记本）
git clone https://github.com/kevin-hans/TradingAgents-astock
cd TradingAgents-astock
pip install -e .[mcp]   # mcp 依赖复用 [agentsdk] 已有的 mcp SDK

# 启动 MCP server（SSE 传输供远程连接）
tradingagents mcp-serve --transport sse --host 0.0.0.0 --port 8765

# 或本地 stdio（PicoClaw 也装在同一机器上时）
tradingagents mcp-serve --transport stdio
```

**新增 CLI 子命令**：`tradingagents mcp-serve`。**必须过 `tests/test_cli_default_command.py`**
（v0.5.9 血泪教训：加子命令不能坏裸跑）。

### 7.2 PicoClaw 端

用 PicoClaw v0.2.8 引入的 MCP CLI 注册：

```bash
picoclaw mcp add tradingagents \
  --transport sse \
  --url http://<server-ip>:8765/sse
picoclaw mcp test tradingagents   # 确认 6 个工具能被发现
```

之后 PicoClaw 的 chat LLM 会在 tool 面板里看到这 6 个工具，自主决定何时调用。

### 7.3 网络与安全

**v1 不做鉴权**：假设服务端在**用户可控的私网 / VPN / 反向代理带鉴权的公网端点后**。

- MCP server 只监听指定 host（默认 `127.0.0.1`）
- 不加内置 token / mTLS
- 若需公网暴露，用户自己配 Cloudflare Tunnel / Tailscale / Caddy basic auth 之类

**v2 可加**：`--auth-token` 参数，请求头 `Authorization: Bearer <token>` 校验。
YAGNI 到 v2 再说，避免过早引入运维复杂度。

## 8. 依赖与打包

### 8.1 pyproject.toml 改动

新增 `[mcp]` extra（复用现有 mcp SDK）：

```toml
[project.optional-dependencies]
agentsdk = ["claude-agent-sdk>=0.2.82"]
mcp = ["mcp>=2.1.0"]   # 与 agentsdk 传递依赖同源，实测无冲突
```

**为什么单独 extra 而不是主依赖**：不用 MCP 的用户零影响；干净 clone `pip install -e .`
不装 mcp SDK，测试 baseline 保持 361 passed / 0 failed（CLAUDE.md 明规）。

### 8.2 模块布局

```
tradingagents/
├── mcp/
│   ├── __init__.py
│   ├── server.py       # MCP server 启动、工具挂载
│   ├── tools.py        # 6 个工具的 pydantic schema + 实现
│   └── estimate.py     # analyze 报价函数
```

### 8.3 CLI 入口

`cli/main.py` 加 `mcp-serve` 子命令：

```python
@app.command("mcp-serve")
def mcp_serve(
    transport: Literal["stdio", "sse"] = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
):
    from tradingagents.mcp.server import run
    run(transport=transport, host=host, port=port)
```

回调 `@app.callback(invoke_without_command=True)` 保持——CLAUDE.md 明规裸跑不能坏。

## 9. 错误处理与降级矩阵

| 层 | 故障 | 处理 |
|---|---|---|
| MCP 传输 | 客户端断连 | 服务端不追踪；下次请求重新握手 |
| MCP 传输 | 请求超时（>15 min） | 客户端自己重试；服务端不做超时逻辑（阻塞完成即返回） |
| 工具 | ticker 不存在（`_normalize_ticker` 拒绝港美股） | 返回 `invalid_ticker` 错误码 |
| 工具 | `advise` 找不到 scenario.json | 返回 `not_found`，提示先 `analyze` |
| 工具 | `advise` 找到旧版无情景数据的报告 | 返回 `scenario_unavailable`，附评级但无个性化建议 |
| 工具 | `advise` / `review` 缺 `kyc_answers` | 返回 `kyc_required` + 内嵌完整问卷（§4.3） |
| 工具 | KYC schema 违例（值/字段错） | pydantic 层拦截，返回 `invalid_kyc` + 具体字段（**不下发问卷**，防重问循环） |
| 工具 | 引擎守卫触发（σ²→0 / NaN） | 返回 `no_advice` + 原因码（引擎已有） |
| 工具 | `analyze` 中途 LLM provider 挂 | 返回错误 + 已完成节点数；无残缺制品（CLI 原子写） |
| 工具 | `analyze` 同日已有制品且未 force | 返回 `artifact_exists`，附现有 artifact_path |
| 服务端 | `mcp-serve` 端口占用 | 快速失败，明确报错 |
| 服务端 | 引擎依赖未装（P2 未交付） | 启动时 import 失败，明确提示"需先完成 P2" |

**核心原则**：所有错误必须**结构化**（错误码 + 描述 + 提示动作），供 PicoClaw 的
LLM 理解并向用户解释——不能返回堆栈或裸文本。

## 10. 测试策略

| 层 | 内容 |
|---|---|
| 工具单测（mock 引擎） | 每个工具的成功路径 + 错误路径全覆盖；schema 契约（新增字段=minor，改语义=version bump） |
| KYC 校验测试 | 边界值（q1=3/5/7/9 全枚举）+ 违例（q1=0 / q1=None / 缺字段）；确认 pydantic 拦截 |
| KYC 建档流程测试 | `advise` / `review` 缺参数触发 `kyc_required` + 内嵌问卷；违例触发 `invalid_kyc` **不**下发问卷；`kyc_questionnaire()` 独立工具返回 schema 等价于错误内嵌 payload（防两处漂移） |
| `analyze` 两相测试 | `confirm=false` 只返报价不跑；`confirm=true` 才真跑；同日守卫触发 |
| MCP 服务器集成测试 | 用 mcp SDK 的 test client 跑起 server → 发现 6 个工具 → 调用一遍 |
| CLI 兼容 | `test_cli_default_command`（裸跑不能坏）；`mcp-serve` 子命令 --help 输出稳定 |
| Extra 隔离测试 | 干净 venv 不装 `[mcp]` → `pip install -e .` 成功 → 全量测试保持当前 baseline 不变（P1 后为 425 passed / 0 failed，CLAUDE.md 干净 clone 场景为 361）；`import tradingagents.mcp` 应 raise 清晰 ImportError |
| 端到端（可选，标 `slow`） | 起真实 server + 用真实 PicoClaw / MCP inspector 调 `advise` 端到端跑通 |

## 11. 分期交付

| 阶段 | 内容 | 独立价值 |
|---|---|---|
| M1 | `tradingagents/mcp/` 骨架 + 只读工具 5 个（reports/scenario/advise/review/kyc_questionnaire）+ `kyc_required` 错误 + `mcp-serve` CLI + `[mcp]` extra | 已能被 PicoClaw 消费现有研报并完成首次建档 |
| M2 | `analyze` 工具（含估算 + 两相 confirm） | 完整触发闭环，PicoClaw 能下单新分析 |
| M3 | 端到端联调 + PicoClaw skill 注册文档 | 交付使用 |

**前置条件**：M1 依赖情景向量顾问 spec 的 P2 分期（advisor 引擎 + CLI
advise/review/scenario/reports 的 `--json`）已完成。若 P2 尚未开工，本 spec 转为
**并行开发**——先出接口契约（工具 schema），M1 实施时对接 P2 完成的实际引擎。

## 12. 明确不做（YAGNI）

- **服务端异步作业队列**：v1 `analyze(confirm=true)` 就是同步阻塞。MCP 长连接可撑
  15 分钟，PicoClaw 侧可自选"挂着等"或"自己调度"。真的需要 async 作业追踪时
  引入，届时加 `job_id` + `status` 工具即可
- **服务端持有 profile.json（在 MCP 路径下）**：客户端持有向量是有意的设计选择，
  多客户端场景零冲突。CLI 层的 profile.json 保持不变（人工使用场景）
- **鉴权 / 授权**：v1 走网络隔离；v2 加 bearer token
- **推送 / 事件流**：spec §7 与 PicoClaw 讨论已澄清——推送是 PicoClaw 自己的事，
  服务端只被动响应
- **`cancel` / `list_jobs`**：无 async 作业就无需要
- **多语言支持**：MCP 工具描述可选带 `zh-CN` / `en`，但不做 i18n 框架
- **数据类工具（get_kline 等）**：a-stock-data 的定位；本 spec 只做分析工具

## 13. 风险与开放问题

1. **P2 尚未开工的调度风险**：本 spec 强依赖 P2 交付。若 P2 延后，本 spec 只能
   出 schema 契约，M1 实施阻塞。缓解：M1 可先实现 `reports` 与 `scenario` 两个
   不依赖引擎的工具，`advise` / `review` 挂 stub 返回 "engine not ready"
2. **PicoClaw MCP client 兼容性**：spec 假设 PicoClaw v0.2.8+ 的 MCP CLI
   （`add/list/test` 命令）与我们实现的 MCP server 完全互通。M3 端到端联调时验证；
   若不兼容需回本 spec 调整传输参数
3. **长时同步阻塞的稳定性**：`analyze(confirm=true)` 阻塞几分钟依赖 HTTP/SSE
   长连接稳定。生产上若客户端网络抖动导致连接断开而服务端仍在跑，会浪费一次
   完整分析。缓解：v2 引入 async 作业模式（YAGNI 到确实观察到问题）
4. **鉴权缺失下的公网暴露**：v1 明确不鉴权，用户若直接把 8765 端口贴到公网
   等于把 LLM 账单和数据白送。M3 文档必须显著警告，推荐 Cloudflare Tunnel / Tailscale
5. **PicoClaw 的 LLM 幻觉调 analyze 两次都 confirm=true**：真的存在这种客户端也
   没救。两相语义只做"善意提醒"，不做强反滥用。若观察到滥用，v2 加"最近 N 分钟
   analyze 计数上限"守卫
