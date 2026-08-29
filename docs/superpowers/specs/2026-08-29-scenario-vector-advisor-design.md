# 情景树 + 投资者向量（Scenario-Vector Advisor）设计

- 日期：2026-08-29
- 状态：已定稿（2026-08-29 评审通过，含四轮评审修订：MCP 面 / 消费只读 / 同日守卫 / --force 归档）
- 分期：P1（情景树生成）→ P2（引擎 + 问卷 + 消费端）→ P3（执行巡检）

## 1. 背景与动机

框架目前的最终产出是"一份评级 + 散文式执行方案"，对所有读者相同。但同一份研究，
不同投资者应得到不同建议（风险耐受、期限、年龄不同）。讨论中先后否决了三种方案
（见 §2 决策记录），最终收敛为：

**研究产出可复用的"情景分布"数据资产；建议 = 分布 × 投资者向量的确定性函数。**

理论依据是金融学标准分解：研究负责估计收益分布（客观部分），投资者维度定义效用
函数（主观部分），建议 = 效用代入分布的最优行动（CRRA 效用 / Merton 组合公式）。
卖方研报"短线观望、长线配置"的口语化写法，本方案将其结构化。

关键收益：

1. **一次研究，多方复用**——15 个 agent 的昂贵分析只跑一次，任何投资者向量随时
   查询；picoclaw skill / Web UI / CLI 消费均零额外 LLM 调用。
2. **建议一致性有数学保证**——同一研究对不同人的分歧只来自效用差异，LLM 的
   谄媚与前后不一致在消费端结构上不存在。
3. **研究纯度零妥协**——研究管线零人格注入，记忆日志与绩效统计口径完全不变。
4. **差研究对所有人都是回避**——个性化放大好研究的参与度，不会把坏研究包装给
   任何人（适当性的数学保证）。

## 2. 决策记录（被否决的方案）

| 方案 | 否决原因 |
|---|---|
| A. 人格注入决策层（FinMem 路线） | 注入可被长上下文稀释；约束无强制力。FinMem 是自营交易 agent（人格属于交易员），本框架是给人的研究工具（人格属于读者），产品类别不同 |
| B. Investor Advocate 代言人节点 | 现实中投资者对投研的参与权止于产品选择（申购/赎回），不存在于研究过程中；客户人格进研究会污染证据链 |
| C. LLM 顾问层（研报后置问答） | 引入第二个 LLM 环节，建议不可复现、有谄媚风险；被"矩阵/函数预计算进研报"取代 |

保留的正确洞见：B 讨论确立的"证据层隔离 / 单向膜 / 结构化事实而非自由人格"原则
由本方案的架构天然满足（研究端根本无人格入口，消费端是纯函数）。

## 3. 架构总览

```
[研究管线] 完全通用，人格零注入（除 PM schema 扩展外零改动）
  7 Analysts → Quality Gate → Bull/Bear → Research Manager → Trader
  → 三方风险辩论 → Portfolio Manager（裁决 + 情景树 + 证伪条件）
        ↓ 落盘
  scenario_<ticker>_<date>.json   ← 研报数据资产（v1 schema，带 version）
        ↓ 消费（纯函数，零 LLM）
  advisor.engine.advise(scenario, investor_vector, config) → AdviceResult
        ↓
  CLI advise / Web UI 矩阵 / review 巡检 / picoclaw skill
```

不变量：

- 引擎是唯一计算入口，所有消费端只做 I/O。
- 向量函数是真相源；报告中的 3×3 矩阵只是其采样渲染，两者逐格相等。
- 评级管方向，数学管参与度（仓位/动作）。
- **消费端只读制品，永不触发研究**——一次分析是分钟级+几十次 LLM 调用的开销，
  不能藏在一次"查询"后面默默发生（成本透明原则）。消费端查不到研报返回
  `not_found` 并提示先分析；P3+ 若提供 `analyze` 触发工具必须带显式确认语义。
- 主流程永不阻塞；每次降级必须留下可见标记（`scenario_unavailable`、原因码、
  warnings 列表）。静默失败是最坏失败。

## 4. P1：情景树生成端（挂 PM，不新增节点）

PM 已使用 `with_structured_output(PortfolioDecision)`（`agents/utils/structured.py`
的 bind + 自动降级模式），情景树作为嵌套字段加入——同源原则：情景树与最终裁决
必须出自同一次推理，杜绝"裁决减持、情景树算出增持"的内在矛盾；零新增调用。

### 4.1 Schema（`tradingagents/agents/schemas.py` 追加）

```python
class Scenario(BaseModel):
    name: Literal["bull", "base", "bear"]
    thesis: str          # 一句话，注明来自辩论哪一方的哪条论据
    return_pct: float    # 桶期末相对分析日收盘的预期收益
    prob: float          # 0~1

class KeyLevels(BaseModel):
    stop: float
    entry_low: float
    entry_high: float
    target: float

class ScenarioBucket(BaseModel):
    horizon_months: int          # v1 只有两个桶: 6 / 12
    scenarios: list[Scenario]    # 恰好 3 个
    key_levels: KeyLevels

class Falsification(BaseModel):
    conditions: list[str]        # 证伪条件 1~3 条
```

`PortfolioDecision` 增加 `scenario_buckets: list[ScenarioBucket]` 与
`falsification: Falsification`。

### 4.2 防拍脑袋三道绳（schema 字段 description 下达，沿用"schema 即指令"惯例）

1. **收益锚定价位**：bear.return_pct ≈ stop/p₀ − 1；bull.return_pct ≈
   target/p₀ − 1（p₀ = 分析日收盘价）。数字从辩论产出的价位来。
2. **概率锚定裁决**：Σp = 1；base ∈ [0.35, 0.55]；评级 ≤ Hold 时 P(bear) ≥
   P(bull)，反之亦然；置信度低时 base 取上限（分布收缩）。
3. **论据可溯源**：thesis 必须引用多空辩论的具体论点，禁止空话。

### 4.3 代码侧确定性校验（新 `agents/utils/scenario_check.py`）

```
Σp ∈ [0.99, 1.01]；单调 bull > base > bear；
|bear_ret − (stop/p₀−1)| ≤ 5pp 且 |bull_ret − (target/p₀−1)| ≤ 5pp（锚定容差）；
方向一致性（主桶 = 与裁决 Time Horizon 最接近的桶）：
评级 ≤ Hold 时主桶 μ ≤ +2pp；评级 ≥ Overweight 时主桶 μ > 0；违例 → 重问
```

违例 → 带具体违例说明重问一次 → 仍败 → 降级无树（报告标记
`scenario_unavailable`，主流程完成）。p₀ 不可得时跳过锚定校验并在 trace 标
`unanchored`。结构化路径必须接入 `warn_if_truncated`，四种 provider 形状都要认。

### 4.4 存储与边界

- state 新键 `scenario_tree`（`agents/utils/agent_states.py`）。
- 报告目录独立落盘 `scenario_<ticker>_<date>.json`（v1，带 version）；消费端读
  小 JSON，不解析 full_states_log。
- **记忆日志不存树**——headline 评级不变，绩效统计口径不变。
- 长线桶 v1 不做（外推需引入随机游走假设，v2 显式标注后引入）。

## 5. P2：问卷与校准（`tradingagents/advisor/calibrate.py`）

五题 KYC，每题选项 3/5/7/9 分：

| # | 题目 | 选项 → 分值 |
|---|---|---|
| Q1 | 组合浮亏 20% 的第一反应 | 全部卖出 3 / 卖一部分 5 / 持有 7 / 加仓 9 |
| Q2 | 这笔钱多久内可能被动用 | <6月 3 / 6–24月 5 / 2–5年 7 / >5年 9 |
| Q3 | 权益类投资经验 | 无 3 / 仅基金 5 / 个股 7 / 含衍生品 9 |
| Q4 | 收入稳定性 | 不稳定 3 / 一般 5 / 稳定 7 / 高且上升 9 |
| Q5 | 年龄段 | ≥60 3 / 45–59 5 / 30–44 7 / <30 9 |

分桶数值映射（引擎可计算）：Q2 → 月数 {<6月:3, 6–24月:15, 2–5年:42, >5年:120}；
Q5 → 代表年龄 {≥60:65, 45–59:52, 30–44:37, <30:25}；Q4 → 收入稳定系数
{不稳定:0.3, 一般:0.5, 稳定:0.8, 高且上升:1.0}。

```
γ = clip(11 − 平均分, 1.5, 9.5)                      # 分高=更能忍=γ低
HC = clamp(1 − (age−25)/50, 0, 1) × 收入稳定系数      # 人力资本
γ_eff = γ × (1 + 0.5 × (1 − HC))                     # 25岁稳定≈γ；60岁≈1.3–1.4γ
H_avail = min(Q2 月数, max(65 − age, 0) × 12)        # 月；距流动性事件
```

流动性需求不是独立坐标：v1 经 Q2 的月数直接进 H_avail。

- 年龄的理论处理遵循 Samuelson (1969) 的诚实结论：期限本身不改变配置比例；年龄
  经人力资本（未来劳动收入≈债券）与距流动性事件年限两条可计算路径生效。Q5 数据
  一题两用（进平均分也进修正）。
- C1-C5 兼容锚点（双向映射，展示与对接监管口径）：γ≥7.5→C1/C2、5–7.5→C3、
  3–5→C4、<3→C5。
- Profile 存 `~/.tradingagents/profile.json`（带 schema version，原子写，不进 git）。

## 6. P2：数学引擎（`tradingagents/advisor/`，纯函数，零 LLM）

```
模块：types.py / calibrate.py / engine.py / render.py

μ = Σ pᵢrᵢ               σ² = Σ pᵢ(rᵢ−μ)²
w_raw = (μ − r_f·h) / (γ_eff · σ²)          # Merton
w* = clip(κ · w_raw, 0, w_max)              # 打折 + 单票上限
硬门: 桶期限 > H_avail → w* = 0             # 期限/流动性不匹配即不适配
动作: w*=0→回避 | (0,5%)→观望 | [5,15%)→持有/低配 | ≥15%→增持/高配
方向: 由评级定（Underweight/Sell→减仓方向；Buy/Overweight→建仓方向）
```

- **方向与仓位分离**：`AdviceResult` 对有仓/无仓双状态各给一条（无仓者"回避/
  分批参与"，持有者"减仓至 w*"）。
- **可审计性**：输出携带完整 trace（γ_eff → μ/σ → w_raw → 打折/截断 → w*）。

v1 参数表（全部进 config，标注校准值）：

| 参数 | 默认 | 说明 |
|---|---|---|
| κ | 0.3 | Merton 打折系数（半-Kelly 精神；原始值会给出 ~60% 的荒谬仓位） |
| w_max | 0.25 | 单票硬上限 |
| r_f | 1.5%/年 | v1 常数，v2 接国债数据 |
| 动作阈值 | 5% / 15% | 观望/低配/高配分界 |
| γ_eff 修正 | ×(1+0.5(1−HC)) | 年龄-人力资本通路 |
| 退休锚 | 65 岁 | H_avail |
| 锚定容差 | 5pp | 情景校验 |

一致性不变量（进 property 测试）：w* 对 γ 单调不增、对 μ 单调不减、μ < r_f·h 时
恒为 0；矩阵渲染 ≡ 引擎逐格直算；纯函数可复现；守卫触发（σ²→0、概率退化、NaN）
返回"无建议 + 原因码"，永不输出垃圾数。

## 7. 消费端接口

**CLI：`tradingagents advise <ticker> [--date] [--json] [--assume-neutral]`**
零 LLM、瞬时。读最新（或指定日）scenario.json + profile → 引擎 → 建议表 + 公式
trace + 有仓/无仓双建议；`--json` 供机器消费（picoclaw skill 的接法）。加子命令
必须过 `tests/test_cli_default_command.py`（v0.5.9 教训：裸跑不能坏）。

**生成端同日守卫**：propagate 前检测当日该票已有完整制品（full_states_log +
scenario.json）→ 提示"复用现有研报或 --force 重跑"，提示不硬拦截（换模型/重测
是合法动机）。现状同日重跑会全管线重烧（数据层有缓存但 LLM 管线无去重），且
`full_states_log` 为覆盖写——`--force` 重跑前先将既有制品归档（rename 加时间
后缀），旧结果不因重跑丢失（换模型对比是合法需求）。

**Web UI**：侧栏"投资者画像"面板（五题滑杆/单选，`web/components/sidebar.py`，
写 profile.json）；报告页渲染 3×3 矩阵并高亮用户格子（高亮格直接调引擎）。旧报
告无 scenario.json → 矩阵区显示"旧版研报无情景数据"，正文照常。

**`tradingagents review`（P3 巡检，零 LLM）**：扫带 scenario.json 的 pending 决策
→ 拉现价 → 检查：

| 检查项 | 判据 | 动作 |
|---|---|---|
| 止损触发 | 现价 ≤ stop | 高亮 + 按 w* 提示减仓幅度 |
| 目标达成 | 现价 ≥ target | 提示兑现/移动止损 |
| 期限到期 | 今天 > 分析日+桶期限 | 提示重新分析 |
| 证伪条件 | v1 不自动判定 | 列为人工核查清单（v2 可选 LLM 辅助） |

新鲜度告警：现价较分析日收盘偏离 >5% 时在输出中告警（v1 不重锚定；stop/target
为绝对价位不受影响）。行情拉取失败跳过该条目并汇总说明，exit code 区分
全部成功/部分失败。

**MCP 面（P3+，第四张嘴）**：宿主 LLM 出智能，工具保持零 LLM 纯函数。工具面板：
`advise(ticker, date?)` / `scenario(ticker, date?)`（暴露原始分布供宿主推理）/
`review()` / `profile_set(answers)` / `reports()`。

- 定位铁律：MCP 只是 **CLI `--json` 的薄包装**（subprocess 调用），CLI 仍是唯一
  机器接口；MCP 层不 import 引擎，防依赖蔓延。
- 不进本仓库核心依赖：MCP 官方 SDK 需 httpx≥0.27 一线，与 mootdx 钉死的
  `httpx<0.26` 结构性冲突（同 google-genai 案例）。落点三选：
  A. 本仓库 `[mcp]` extra（`--no-deps` 安装，体验糙）；
  **B. a-stock-data 挂工具（推荐）**——现有 MCP 服务 subprocess 调 CLI，本仓库零新依赖；
  C. 独立小包 `tradingagents-mcp`。
- 不做 CLI 子命令形式（console-script 独立入口），避开 v0.5.9 裸跑风险。

## 8. 维度扩展机制

维度扩展按"进哪个机关"分五类，加维度 = 加一个坐标 + 一项修正，schema 保持小核心
+ 可选坐标（缺省取中性默认值，version 管版本）：

| 机制 | 候选维度 | 版本 |
|---|---|---|
| 效用参数 | γ、期限偏好 | v1 |
| γ_eff 修正子 | 人力资本（年龄×收入）；背景风险（需持仓数据） | v1 / v2+ |
| 硬约束 | 流动性需求（v1 经 Q2 进 H_avail）、杠杆上限、税务状态（A 股持股>1 年免红利税） | v1 / v1.5 |
| 过滤集 | 行业/主题排除、ST/次新排除、复杂度适当性 | v1.5 |
| 行为偏误 | 止损纪律差→自动止损条款；过度交易→降频 | v2 |

## 9. 错误处理与降级矩阵

| 层 | 故障 | 处理 |
|---|---|---|
| 生成端 | Provider 不支持结构化输出 | 自由文本，无树，标记 `scenario_unavailable` |
| 生成端 | JSON 畸形 / schema 违例 / 校验违例 | 重问一次（写明违例项）→ 仍败 → 降级无树 |
| 生成端 | p₀ 不可得 | 跳过锚定校验，trace 标 `unanchored` |
| 生成端 | 输出截断 | 接入 warn_if_truncated（四种 provider 形状） |
| 引擎端 | σ²→0 / 概率退化 / NaN / γ_eff 越界 | 无建议 + 原因码，trace 保留中间量 |
| 引擎端 | config 非法（κ≤0 等） | 启动时快速失败（内部契约不运行时兜底） |
| 消费端 | 旧报告无 scenario.json | 明示"旧版研报" |
| 消费端 | 无 profile | 提示建档或 `--assume-neutral` 演示 |
| 消费端 | 行情拉取失败（review） | 跳过条目 + 汇总说明，exit code 区分部分失败 |
| 消费端 | profile.json 并发写 | tmp+replace 原子写 |

## 10. 测试策略

| 层 | 内容 |
|---|---|
| 校验器全矩阵单测 | 枚举所有违例形状（Σp 偏离/不单调/锚点漂移/方向矛盾/缺字段/多情景）——跑整张矩阵，不是只测想到的用例（评级边界三轮返工教训） |
| 引擎 property 测试 | 单调性、μ<r_f→0、纯函数、clip 边界、守卫触发、矩阵≡引擎（9 格逐格） |
| calibrate 单测 | γ 边界与 clip、γ_eff 端点（25岁稳定 vs 60岁不稳定）、H_avail、C1-C5 双向映射 |
| 管线集成（mock LLM） | 好树落盘可查；坏树重问一次后降级不阻塞；无结构化 provider 全流程不炸 |
| CLI 兼容 | test_cli_default_command（裸跑）；advise --json schema；review fixture + mock 行情；exit code |
| Schema 契约 | scenario.json v1 快照：加字段=minor，改语义=必须 version bump |
| 全量回归 | 干净 clone `pytest tests/` 保持 0 failed（当前基线 361 passed / 13 skipped） |

## 11. 分期交付

| 阶段 | 内容 | 独立价值 |
|---|---|---|
| P1 | PM schema 扩展 + 校验器 + scenario.json 落盘 + 证伪条件 | 研报成为可复用数据资产，可单独发版 |
| P2 | advisor 包（calibrate/engine/render）+ CLI advise + Web 画像面板与矩阵 | 建议查询全面可用 |
| P3 | tradingagents review 巡检 | 决策纪律闭环 |
| P3+ | MCP 面（§7，落点 B 推荐） | Claude Code / picoclaw 等 MCP 宿主原生消费 |

## 12. 明确不做（YAGNI）

- 代言人节点 / 管线人格注入 / LLM 顾问层（见 §2）。
- 长线桶外推（v2，须显式标注随机游走假设）。
- 证伪条件自动判定（v2 可选 LLM 辅助）。
- 组合层背景风险与集中度（需持仓追踪，roadmap）。
- 人格随净值动态切换（FinMem Self-Adaptive）：受托场景下等于把恐慌卖出写进系统；
  亏损收紧一律走硬规则（止损/减仓线写进 key_levels + review 巡检）。

## 13. 风险与开放问题

1. **κ 与阈值的校准**：v1 手工设定；后续可用历史研报 + 已结算记忆
   （`TradingMemoryLog` 的 raw/alpha）回测校准——绩效系统与本方案的天然接口。
2. **情景分布的精度天花板**：μ/σ 来自 LLM 对辩论的估计，数学层保证一致性与可
   解释性，不保证预测精度——精度责任在研究端，消费端只做忠实映射。
3. **免责边界**：advice 输出须带"研究工具输出，非投资建议"声明；C1-C5 映射仅
   为展示口径，不构成监管意义上的适当性评估。
