# Crypto Lab — Phase 1 基础模拟交易开发计划

## 0. 文档信息

| 属性 | 内容 |
|---|---|
| 文档版本 | V0.8 |
| 当前阶段 | Phase 1 |
| 前置验收 | Phase 0-A 已通过 |
| 并行研究 | Phase 0-B Pending |
| 状态 | Active |

## 1. 目标

基于已经验证的真实市场数据，构建只使用虚拟资金的现货模拟交易系统。进入 Web 应用开发前，先完成订单簿驱动的自动撮合、实时限价单、模拟执行延迟及交易引擎一致性验证。

Phase 1 不连接真实账户、不使用交易权限 API、不连接钱包，也不执行真实订单。

Phase 0-B 保持独立研究状态，不阻塞 Phase 1；若长期实验发现重大数据质量、时序或行情可用性问题，必须重新评估 Phase 1 的行情依赖及相关验收结论。

## 2. 开发路线

| Task | 名称 | 状态 |
|---|---|---|
| 1.1 | 模拟账户与资金流水 | Completed |
| 1.2 | 模拟订单模型 | Completed |
| 1.3 | 模拟成交引擎 | Completed |
| 1.4 | 持仓与估值 | Completed |
| 1.5 | 订单簿驱动的模拟撮合与滑点 | Completed |
| 1.6 | 限价单实时自动撮合 | Completed |
| 1.7 | 模拟执行延迟 | Completed |
| 1.8 | 交易引擎集成与一致性验证 | Completed |
| 1.9 | 数据持久化 | Completed |
| 1.10 | 后端服务与 REST API | Completed |
| 1.11 | 实时行情服务 | Completed |
| 1.12 | React 前端应用 | Completed（Gate E Accepted，2026-11-26） |
| 1.13 | 前后端联调与 Phase 1 验收 | In Progress |

### Task 1.1 — 模拟账户与资金流水

- [x] 建立交易所隔离的模拟账户。
- [x] 使用 Decimal 管理可用及冻结余额。
- [x] 所有余额变化生成不可变资金流水。
- [x] 禁止可用余额及冻结余额变为负数。
- [x] 支持初始虚拟资金、冻结和释放操作。
- [x] 覆盖重复流水、非法资产及边界值测试。

### Task 1.2 — 模拟订单模型

- [x] 定义现货市价单及限价单。
- [x] 定义订单状态转换。
- [x] 下单前执行余额校验及资金冻结。
- [x] 支持取消订单及释放资金。

### Task 1.3 — 模拟成交引擎

- [x] 买入参考 Ask，卖出参考 Bid。
- [x] 引入手续费和明确的成交模型。
- [x] 支持部分成交及失败结果。
- [x] 生成成交记录和结算流水。

当前成交模型约束：

- 只接受质量状态为 VALID 且交易品种一致的 Ticker。
- 市场买入使用 Ask，市场卖出使用 Bid，不使用 Last Price。
- 手续费当前以计价资产收取，并由调用方显式传入费率。
- 限价买入不得高于限价成交，限价卖出不得低于限价成交。
- 多资产结算使用批量原子流水，任一余额不足时整次成交失败。
- 当前成交价格及部分成交数量由调用方提供；Task 1.5 起改由市场数据及撮合模型产生。

### Task 1.4 — 持仓与估值

- [x] 计算持仓数量及成本。
- [x] 区分已实现及未实现盈亏。
- [x] 明确估值价格来源和时间。

当前持仓模型约束：

- 使用移动平均成本法，买入手续费计入持仓成本。
- 卖出实现盈亏等于卖出金额减手续费和对应持仓成本。
- 未实现盈亏使用同一交易品种有效 Ticker 的 Bid 估值，不使用 Last Price。
- 估值结果记录价格事件 ID、接收时间和价格依据。
- 持仓可由成交历史重建；重复、乱序及超额卖出成交被拒绝。

### Task 1.5 — 订单簿驱动的模拟撮合与滑点

- [x] 实现可执行的规范化订单簿 Market State 及有效性校验。
- [x] 市价买单逐档消耗 Ask，市价卖单逐档消耗 Bid。
- [x] 生成多档成交明细、总金额、VWAP、剩余数量及成交状态。
- [x] 分别计算订单簿滑点、执行价格漂移及总滑点。
- [x] 管理同一模拟环境共享的剩余流动性，禁止重复消耗。
- [x] 复用 Task 1.3 结算能力，不由调用方或前端指定成交结果。
- [x] 完成 OKX 真实订单簿 Adapter 及 15 秒短时接口验收。

### Task 1.6 — 限价单实时自动撮合

- [x] 支持可立即成交的限价单及持续挂单。
- [x] 由有效订单簿及真实 Trade 事件触发自动撮合。
- [x] Phase 1 优先支持 GTC，不突破用户限价。
- [x] 默认采用保守的 TRADE_THROUGH 近似模型；TOUCH_FILL 仅作为未来对照模式保留。
- [x] 以价格、有效入场时间及确定性序列管理本地订单优先级。
- [x] 正确处理部分成交、取消、剩余冻结资金及 Maker/Taker 手续费。
- [x] 完成 OKX 真实 Trade Adapter 及 15 秒短时接口验收。

### Task 1.7 — 模拟执行延迟

- [x] 引入 Clock 抽象及 Execution Scheduler，不在领域模型中直接 sleep。
- [x] 支持 0ms、预设延迟及自定义延迟。
- [x] 订单执行时使用当时已接收的最新有效行情，禁止未来数据泄漏。
- [x] 延迟期间保持资金冻结并允许取消。
- [x] 市价买单在显式冻结预算内撮合，部分成交后取消剩余并释放资金。
- [x] 记录提交、计划执行、市场入场、实际执行时间、调度滞后及参考行情。
- [x] 使用 ManualClock 完成确定性测试。

### Task 1.8 — 交易引擎集成与一致性验证

- [x] 串联 Market State、订单校验、调度、撮合、结算、流水及持仓投影。
- [x] 定义订单、成交、流水、持仓及模拟流动性的内存原子提交与恢复边界。
- [x] 防止订单、成交、手续费、流水、市场事件及流动性的重复处理。
- [x] 确定行情、执行、取消及多订单竞争时的事件顺序。
- [x] 验证余额及持仓可重建，且模拟结果可确定性复现。
- [x] 使用失败注入验证 Ledger、Order、Fill、Liquidity、Portfolio、Scheduler 与事件登记回滚。
- [x] 保证 Task 1.1～1.7 全部回归测试通过。

### Task 1.9 — 数据持久化

- [x] 设计 PostgreSQL Schema 与 Alembic 初始迁移。
- [x] 持久化账户、流水、订单、成交、投影及必要行情引用。
- [x] 将领域原子边界映射为环境根行锁保护的数据库事务。
- [x] 持久化并恢复待执行订单、类型化事件、去重登记、ID Counter 和模拟流动性。
- [x] 验证余额、持仓及待执行状态的恢复与重建。
- [x] 使用真实 PostgreSQL 验证迁移 upgrade/downgrade、事务回滚及约束。

### Task 1.10 — 后端服务与 REST API

- [x] 定义同步 Application Service、环境事务锁、幂等及错误边界。
- [x] 初始化 FastAPI 并定义严格的请求、响应和错误 Schema。
- [x] 提供环境、账户、订单、成交、余额及持仓 REST 端点。
- [x] 生成并验证 OpenAPI，强制 Decimal 字符串、写请求幂等键及请求 ID。
- [x] 使用真实 PostgreSQL 验证迁移、环境隔离、冻结、调度、取消和恢复。

### Task 1.11 — 实时行情服务

- [x] 定义面向前端的 WebSocket 协议。
- [x] 推送 Ticker、K 线、订单簿、数据质量及模拟订单状态。
- [x] 处理连接、心跳、断线、重连及过期行情。
- [x] 限制队列和内存增长，记录丢弃及断连事件。

实施补充（2026-11-26，ADR 0007）：

- 共享 OkxMarketFeed 由 Lifespan 管理，一进程一逻辑 Feed；candle 频道走 OKX Business 端点。
- EnvironmentMarketDispatcher 将 Canonical 行情按环境串行写入交易引擎（TRADE_THROUGH 撮合、流动性同步、到期订单执行），环境间完全隔离。
- 新环境注册时注入当前有效市场快照；订单簿失效期间到期订单按 MARKET_DATA_UNAVAILABLE 拒绝，不使用旧报价撮合。
- 配置经 CRYPTO_LAB_FEED_* 环境变量管理；自动化测试显式禁用或注入可控连接。
- 完成 15 秒 OKX 公共 WebSocket 真实接口验证（0 订阅错误、0 重连），报告见 data/okx_realtime_feed_verification.json。

最终验收（2026-11-26）：

- 独立 PostgreSQL 测试容器完成迁移并补跑全部数据库集成测试（含 12 项此前跳过），无剩余数据库跳过项。
- 完整交易链路端到端验证通过：市价买卖、延迟执行、限价单穿价成交、资金流水、持仓盈亏、提交后事件发布、回滚零事件、重复 Trade 去重、行情失效拒绝成交（7 项测试）。
- Scheduler lag 已持久化区分 configured_latency 与 scheduler_lag；Candle 验收矩阵及未完成项记录见 docs/10 §13。
- 验收修复 4 项缺陷：NUMERIC 恢复尺度溢出、平仓持仓投影残留、Dispatcher 回滚后内存缓存不一致、持仓投影缺少本次成交。

### Task 1.12 — React 前端应用（2026-11-26 重新划分）

权威规范：docs/12-UI-UX-DESIGN.md V1.1（Accepted，含 Desktop Only 修订）；架构：docs/11 V0.3；多周期订阅：ADR 0008（Accepted / Implemented）。

按项目负责人 Instruction 划分为 1.12.1～1.12.12，对应 Gate A～E。**说明**：旧划分下的 1.12.1～1.12.7 工程已提前交付（commits 至 178d8f2），下表状态按新划分如实映射，剩余工作在对应子任务内完成。

#### Gate A — Architecture

##### Task 1.12.1 — Architecture & Design（**Gate A Accepted**，2026-11-26）

- [x] 审查 REST Contract、WebSocket Contract、ADR 0006/0007、实际源码及数据模型。
- [x] docs/12-UI-UX-DESIGN.md V1.1 落盘（Accepted 规范 + Desktop Only 修订）。
- [x] docs/11 V0.3：Feature-based 架构、API Capability Matrix（S/P/N 全量矩阵）、差距清单 G1～G12。
- [x] ADR 0008（**Accepted**）：Candle 多周期动态订阅——常驻 1m + 动态引用计数、上限 32 可配置、非常驻频道 30 秒宽限释放；Task 1.12.6 实施。
- [x] 四项架构决策确认（详见 docs/11 §11）：ADR 0008、账户默认延迟后端持久化、订单预估本地参考估算、持仓估值遵循有效 Bid 语义。
- [x] Gate A 验收结论：原则上通过；四项决策已回写文档。

#### Gate B — Foundation

##### Task 1.12.2 — Project Setup

- [x] pnpm + Vite + React 19 + TS 7 + Tailwind 4 + Router + Vitest/RTL + Playwright（版本见 docs/11 §2）。

##### Task 1.12.3 — Design System & App Shell（UI 验收通过，2026-11-26）

- [x] Dark Theme Tokens（docs/12 §4.1 全量 CSS Variables + Tailwind v4 @theme；tabular-nums；prefers-reduced-motion）。
- [x] 基础 UI 组件（shared/ui：Button/Input/Select/Label/Badge/Panel/Tabs/StatusDot/TermTip/Empty/Error；shadcn 约定 + cva）。
- [x] Feature-based 目录结构迁移（app / features/{market,trading,account,workspace} / shared/{api,lib,ui}，git mv 保留历史）。
- [x] App Shell：48px 顶栏（品牌、已实现导航项、环境选择器、Paper Trading 徽标、连接徽标）、24px 状态栏（Feed/质量/最近行情/WS/同步/时区）。
- [x] 可调整三栏 Trading Workspace（54/21/25）+ 底部 Activity Panel 五 Tab（28%），版本化 localStorage 自动保存，键盘可操作分隔线。
- [x] Desktop Only：<1280px 显示使用提示；路由 / → /trading；未实现页面不出导航入口（§5.2）。
- [x] 负责人 UI 验收通过（截图已提交：bootstrap / workspace / order-entry 1440×900）。
- 技术取舍：Lucide React 随 1.12.7+ 图标需求引入；TermTip 采用纯 CSS 实现（无 Radix 依赖），键盘可聚焦。

##### Task 1.12.4 — REST API Client

- [x] Zod 契约 Schema、RestClient（幂等键、错误信封、列表/快照/K 线校验）。

##### Task 1.12.5 — Realtime Client

- [x] WSClient 状态机（resume 游标、心跳、退避重连、delivery_sequence/stream_id 语义）、TradingStateSync。

#### Gate C — Trading Experience

##### Task 1.12.6 — Candlestick Chart

- [x] Lightweight Charts 蜡烛图：REST seed + WS upsert、闭合保护、分页、断线补齐、周期切换。
- [x] Volume 副图（无成交量不补 0）、Last Price Line、OHLC 图例（Crosshair 联动）、个人成交标记（§9.6，按真实成交时间所在 K 线聚合，保留 execution_id/order_id 追溯）、初始化竞态隔离（迟到未闭合 REST 页不覆盖已闭合/更新的实时 K 线）、缺失区间留空并提示（不生成假 K 线）。已通过 vitest（64 项）与 tsc/build；尚未做真实浏览器视觉验收。
- [x] 多周期实时能力落地（ADR 0008 已实施：引用计数动态订阅、常驻 1m、上限 32、30 秒宽限、SUBSCRIPTION_LIMIT）；单元/接线测试通过，真实 OKX 动态订阅实测待做。

##### Task 1.12.7 — Market Workspace

- [x] 三栏 Resizable Panels + 底部 Activity Panel + 布局持久化（1.12.3 已交付）。
- [x] Market Header（§8）：最新价、Bid/Ask、24H 涨跌（由交易所 last 与 open_24h 派生，缺失显示 --）、24H 高/低/量、质量徽标。交易对选择器暂不提供：Feed 当前只配置 BTC/USDT，不构造不存在的品种。
- [x] Order Book / Market Trades Tab 面板：累计深度条、Spread（交叉或单边盘口不显示）、点击价格填入限价（自动切换为限价单，不自动下单）、行情非 VALID 时提示且禁止取价；最新成交有界 50 条并按 trade_id 去重；面板自订阅 store 切片。
- [x] 底部状态栏（1.12.3 已交付）。
- 验证：vitest 75 项、tsc、build 通过；真实 OKX 行情 + 浏览器 1440×900 复查订单簿、最新成交、点击填价通过。未做：ETH/USDT 等多品种；行情失效态的真实触发。

##### Task 1.12.8 — Order Entry

- [x] 订单意图表单基础（方向/类型、预算、延迟预设、Zod 校验、防重复、幂等键、错误展示、交易闸门）。
- [x] 下单确认 Dialog（§11.4）：环境/账户（ID 缩写，名称待后续）/品种/方向类型/数量/参考价（限价；市价买用 Ask、市价卖用 Bid）/预算/预估成交金额与手续费/延迟毫秒；明确标注“本地参考估算”，费率 0.1% 仅为参照后端 `phase1-default-v1` 的前端常量，不读取后端。每笔订单必经确认，Esc/返回修改不发请求；预估超预算时提示部分成交规则；行情缺失显示 `--`。
- [x] 可用余额展示、25/50/75/100% 快捷（decimal.js，向下取整到 8 位，买入按含手续费反推数量；市价买同时填预算）、订单簿价格填入限价、术语提示（限价/预算/延迟）。
- 验证：vitest 86 项、tsc、build 通过；真实行情浏览器复查：50% 快捷 → 确认弹窗 → 提交 → 订单以 PENDING_EXECUTION 出现在当前委托。未做：账户默认延迟后端持久化（决策已定，待后端迁移）；ETH 品种；预览 VWAP/滑点（无可靠依据，不展示）。

##### Task 1.12.9 — Order Management

- [x] 订单列表（限价列、三列延迟口径、取消+幂等+Resync）、成交记录、余额持仓视图、手动刷新。
- [x] Activity Panel 五个 Tab（1.12.3 已有）+ 账户同步三态徽标（已同步 / 同步中 / 连接中断数据可能过期）；订单表新增“剩余”列与“详情”入口，成交表新增订单/成交 ID 与“详情”入口。
- [x] Execution Detail Drawer（§14）：基本信息、成交分析（提交参考价/均价/累计成交额/手续费与费率）、延迟分析（配置/计划/实际时间/调度滞后/实际模拟延迟，并注明不等于真实网络延迟）、实际各笔成交明细（从成交记录打开时高亮该笔）。后端未提供的 Maker/Taker、VWAP、滑点显示“后端暂未提供”，不本地构造。
- [x] 订单状态中文映射（§13）；部分成交后取消/终止同时展示“已成交 x，取消剩余 y”，不隐藏已成交数量。
- [x] 附带：`formatDecimal` 去除数据库 NUMERIC 刻度噪声（`0E-24`→`0`、尾随 0），仅用 Decimal，不改变数值。
- 验证：vitest 93 项、tsc、build 通过；真实环境浏览器复查成交详情抽屉通过。未做：历史订单筛选/分页（§12.2，后端 Contract 支持度待确认）；Maker/Taker 等分析字段待后端提供。
- 缺陷已修复并按负责人规则完善（2026-11-26，后端）：`register_environment` 此前只在创建环境时调用，重启后已存在环境不被调度。现按 docs/08 §6.1 实现启动恢复：统一基准时间、Feed/Scheduler 启动前逐环境原子处理；已过期 PENDING_EXECUTION → `REJECTED`/`EXECUTION_EXPIRED_ON_RESTART`（释放冻结、无 Fill、不耗流动性、不补执行，即使订单簿已恢复）；未到期保留计划；GTC 挂单/部分成交保留并仅依新事件撮合；幂等；环境失败隔离并在 `GET /health/recovery` 明示，5 秒重试。验证：新增 8 项 PostgreSQL 生命周期集成测试 + 登记单元测试；复用独立测试容器 `crypto-lab-task111-test` 的 `crypto_lab_test` 库，全量 pytest 317 通过、0 跳过（连续 3 次）。已知限制：重启时 Feed 尚未启动，故恢复期间不依赖行情；`ruff` 仅剩既有 `service.py` import 排序 1 条。

#### Gate D — Account Experience

##### Task 1.12.10 — Account & Portfolio

- [x] 账户页余额与持仓（Ledger/Fill History 投影）。
- [x] Overview 页 `/overview`（§15，顶栏新增“总览”入口）：总资产/可用/冻结/已实现/未实现盈亏/累计手续费（按手续费币种分列）、资产分布、当前持仓（市值与未实现盈亏）、最近 5 笔模拟成交；明确标注估值币种 USDT、估值依据与数据时间；无收益曲线。
- 估值规则（落实 Gate A 决策：有效 Bid，非 Last）：币种按“有效买一价 × 数量”（Decimal）；仅在行情质量 VALID 且买一价不早于 5 秒（对齐后端 max_book_age）时估值；无买一价/已过期/无行情对（如 ETH）的资产单独列为“无法估值资产”，总资产标注“不完整”且不含它们；行情失效时不把旧估值当实时显示，未实现盈亏显示 `--`。
- 已知限制（已由 Task 1.12.10-A 解决）：原已实现盈亏仅汇总当前持仓投影；现改用后端累计值。总资产估值覆盖范围见下。
- 验证：vitest 103 项、tsc、build 通过；真实环境浏览器复查 `/overview`（BTC 市值 + USDT = 总资产，核对一致）。

##### Task 1.12.11 — Markets & Settings

- [x] Markets 页 `/markets`（§16）：仅列出 `GET /api/v1/market/instruments` 的实际接入品种；交易所、最新价、24H 涨跌（派生）、24H 成交量、数据质量；搜索、排序（缺失值始终排最后）；点击进入 Trading 并选中该品种。缺失字段 `--`；有 ticker 且无降级事件时质量视为有效（与图表/下单一致）。
- [x] 交易品种可选：新增 `instrumentStore`，图表、订单簿/成交、下单面板、状态栏均随所选品种（BTC/USDT、ETH/USDT）；切换品种时下单草稿重置；订单请求使用所选品种与对应资产标签。
- [x] Settings 页 `/settings`（§17）：模拟环境（列表、当前标记、切换、创建并切换；Contract 不提供删除/重置，页面明示）、账户（默认延迟/手续费配置标注“后端暂未提供”）、工作区（恢复默认面板布局、时区、清除本地会话选择需确认且不删服务端数据）、系统状态（API、WebSocket、Feed、品种与周期、数据质量、启动恢复状态含失败环境、Scheduler 配置“后端暂未提供”）。
- [x] 顶栏环境选择器 + “设置”入口（替换临时“重置”按钮）；新增后端只读 `GET /api/v1/environments`。
- [x] 环境切换（§17.5）：先停旧订阅，再清空交易/行情 store、详情抽屉与全部 Query 缓存，最后写入新会话；新环境快照到位前 `tradingStore.synced=false`，下单禁用并提示“账户状态同步中”；目标环境无账户时拒绝切换且不拆除当前状态。
- 验证：vitest 129 通过（含 Markets/Settings/环境切换新增 12 项）、tsc、build、ruff 通过；后端 pytest 343 通过（PostgreSQL，独立测试库）。真实环境浏览器复查 Markets（BTC/ETH 真实行情）、Settings、创建并切换到新环境后 Overview 显示全新账户（10000 USDT、盈亏 0、无旧订单/持仓），以及无账户环境的切换被拒绝。未做：账户选择器（单账户环境不需要）；环境重命名（无 Contract 支持）。

##### Task 1.12.10-A — Account Realized PnL & Valuation Completion（2026-11-26，等待验收）

- **累计已实现盈亏方案**：以完整 Fill History 为唯一权威，读取时用既有 `PortfolioEngine`（移动平均成本法；买入手续费计入成本，卖出手续费冲减盈亏，每笔手续费只计一次）重放（`realized_pnl_summary`）；不新增持久化表、无第二套权威；完全平仓的盈亏保留，零数量持仓仍不入投影；按结算币种分别汇总，绝不跨币种相加；历史账户无需迁移（读取即得）；O(成交数)，规模变大后再引入可重建缓存。
- **API**：`GET /accounts/{id}/pnl`；Snapshot 新增同结构 `pnl`；字段 `cumulative_realized_pnl_by_currency`、`cumulative_fees_by_currency`、`instruments`、`state_version`、`as_of_ts_ms`、`scope`、`cost_method`、`status`；无成交 = `AVAILABLE` + 空对象（合法 0）；重放失败 = `UNAVAILABLE` + 原因，不以 0 掩盖。Snapshot 读取改为 `REPEATABLE READ`，PnL 与订单/成交/余额/持仓同版本。新增 `GET /api/v1/market/instruments`。见 docs/09 §4.3.1。
- **前端**：`tradingStore.pnl` 来自 Snapshot，并由 `positions` WS 事件（含已平仓品种的累计值）增量更新，REST Resync 后以 Snapshot 为准；Overview 显示累计已实现盈亏（多币种分列、负数、新账户 0、不可用 `--`），不再汇总当前持仓。
- **估值审计（ETH 无法估值的实际原因）**：(1) Feed 默认品种配置仅 `BTC/USDT`（ADR 0007 原决定；`CRYPTO_LAB_FEED_INSTRUMENTS` 默认值），ETH/USDT 从未接入，没有 ETH 订单簿；(2) 前端 `EnvironmentGate` 硬编码仅订阅 `BTC/USDT`；(3) Dispatcher 使用单一静态 BTC 规则，直接接入 ETH 会用错 tick/lot（ETH-USDT 实测 tickSz 0.01 / lotSz 0.000001 / minSz 0.0001，BTC 为 0.1 / 0.00000001 / 0.00001）；(4) Market State/订单簿质量/REST/WS 订阅链路本身无问题，ETH 订单簿在接入后质量 VALID（真实 OKX 验证 BTC 与 ETH 各约 100 次有效快照）。Overview 的估值数据本就来自全局 market store，不依赖 Trading 页面所选品种，但数据只来自被订阅的品种。**与负责人此前认知的差异**：默认 Feed 品种在 ADR 0007 中一直是仅 BTC/USDT，BTC/USDT 与 ETH/USDT 是 docs/12 §8 的 UI 初始品种，并非已配置的 Feed 默认。
- **修复**：Feed 默认品种改为 BTC/USDT、ETH/USDT（`DEFAULT_INSTRUMENTS`），规则按品种 `OKX_SPOT_RULES`（均对照 OKX 公共 instruments 端点 Verified）且缺少规则时拒绝启动；前端订阅集合来自 `/api/v1/market/instruments`（失败才回退 BTC）。估值规则不变：仅用有效 Bid、行情过期/失效即“无法估值”、总资产不完整时明确标记、冻结资产按 可用+冻结 计入且只计一次、不使用虚假汇率。
- **审计中发现并修复的缺陷**：`run_due` 在工作线程中执行，Feed 同时更新订单簿；决策时间之后到达的订单簿会触发 no-lookahead 门，使有效订单被误拒为 `MARKET_DATA_UNAVAILABLE`（真实环境 ETH 订单被误拒，加入第二个品种后更易触发）。修复：run 开始时先快照订单簿再取决策时间，并有回归测试。
- **验证**：后端 pytest 342 通过、0 跳过（含 PostgreSQL，复用 `crypto-lab-task111-test` 的 `crypto_lab_test` 库；不触碰 `crypto_lab_verify`/开发数据）；`ruff` 全部通过；前端 vitest 116 通过（保留原 103 项基线）、`tsc`、`build` 通过。真实环境 Overview 截图：`docs/screenshots/1.12.10-A-overview-btc-eth-closed-pnl.jpg`（BTC 已平仓累计 -1.491181 USDT，持有 BTC+ETH，总资产 9996.37528 = 可用 7925.89928 + BTC 1219.066 + ETH 851.41，冻结 0）。
- **未做**：历史收益曲线、Sharpe、最大回撤、胜率、风险分析（按范围排除）；估值覆盖仅 Feed 已接入的品种（BTC、ETH 对 USDT）；ETH 暂无交易页入口（交易页仍只含 BTC/USDT）。

#### Gate E — Frontend Acceptance

##### Task 1.12.12 — Frontend Acceptance

- [x] E2E 基础：真实后端 + 隔离测试库 + 关闭 Feed（引导/下单意图/订单表/账户/会话恢复 2 项通过）；运行须剥离系统代理（docs/11 §9）。
- [x] 完整 E2E（确认流程、成交与余额变化、行情失效禁用与恢复、布局持久化、环境切换隔离）：13 项，连续 4 轮全部通过；使用 SYNTHETIC 脚本化行情的测试专用后端 `tests/support/e2e_server.py`（拒绝非 test 库）。
- [x] Desktop Acceptance Matrix（1280×720 / 1440×900 / 1920×1080 / 2560×1440，含按钮可点击命中测试与截图）、可访问性自动检查、性能检查（Long Task 0、堆增长 < 1.2 MB）。**未做**：Safari/Firefox/Edge、颜色对比度、读屏、真实高频行情下的前端性能。
- [x] Task 1.12 验收报告：docs/13-FRONTEND-ACCEPTANCE-REPORT.md；项目负责人于 2026-11-26 确认 Gate E 通过。订单簿事件随环境数线性放大已确认为 Phase 1 Known Limitation / Technical Debt，不阻塞 Task 1.12；按 Task 1.13 独立性能基线复测。


### Task 1.13 — 前后端联调与 Phase 1 验收

- [ ] 覆盖行情、下单、延迟、成交、挂单、取消、余额及持仓流程。
- [ ] 执行 API 集成测试和浏览器 E2E 测试。
- [ ] 验证刷新、重连、错误响应、过期行情及恢复场景。
- [ ] 确认系统不调用真实交易接口。
- [ ] 本地 Docker Compose 部署（ADR 0009，Accepted）：Frontend（React Build + Nginx，`127.0.0.1:8080`）/ Backend（单进程单 Worker）/ PostgreSQL 三容器；Nginx 代理 REST + WebSocket（升级与长连接）；Backend 监听地址可配置且不对宿主机暴露；Alembic Migration 先于业务服务且失败则不启动；Health/Readiness；优雅关闭 Feed、Scheduler、WebSocket；Named Volume + `pg_dump` 备份与恢复演练；Development / Local Production / Test 三库隔离及测试防护；`.env.example`；ARM64 Multi-stage 镜像；容器重启/重建数据保留与重启恢复规则验证。
- [ ] 使用确定性行情样本分别测试 1、3、5、10、20 个活跃模拟环境。
- [ ] 记录 CPU Usage、Memory Usage、Order Book Processing Time、Event Queue Backlog、Scheduler Lag、Database Transaction Time 和 Event Processing Throughput。
- [ ] 对各环境规模比较模拟成交、余额、持仓、流动性消耗历史及事件顺序，确认相同输入产生一致业务结果。
- [ ] 根据实测数据决定是否启动专项性能优化；本阶段不设置未经测量的硬指标，不引入复杂并行架构。

## 3. Task 1.1 验收标准

- 初始资金只存在于指定模拟账户和交易所。
- 相同资产区分 available 与 locked。
- 冻结金额从 available 转入 locked，总额不凭空变化。
- 释放金额从 locked 返回 available，总额不凭空变化。
- 任何会产生负余额的操作必须整体失败，不得部分写入。
- 重复 entry ID 不得重复影响余额。
- 余额可由资金流水完整重建。

Task 1.5～1.8 的详细设计、测试矩阵及验收标准见 [`07-EXECUTION-ENGINE-DESIGN.md`](07-EXECUTION-ENGINE-DESIGN.md)。

Task 1.10 的 REST Contract 见 [`09-REST-API-DESIGN.md`](09-REST-API-DESIGN.md)；Task 1.11 已按 Accepted ADR 0006/0007 完成，最终 WebSocket Contract、验收结果及已知限制见 [`10-REALTIME-SERVICE-DESIGN.md`](10-REALTIME-SERVICE-DESIGN.md)。

### Phase 1 性能决策（2026-11-26）

Phase 1 接受订单簿处理成本随活跃模拟环境数量线性增长。优先级依次为金融计算正确性、模拟流动性准确性、环境隔离、事件处理确定性、事务一致性和性能优化。该限制记录为 Known Limitation / Technical Debt，在个人使用规模下不阻塞正常验收。

允许共享不可变 Canonical 行情对象、减少复制及重复序列化、优化数据结构/查询索引/非关键日志、增加性能监控，以及对前端推送节流合并，但必须保持业务结果一致并通过完整回归。未经负责人确认，不得跳过无挂单环境更新、合并或丢弃交易引擎输入、改变流动性补充与消耗历史、跨环境共享已消耗流动性、改变撮合顺序、TRADE_THROUGH、执行延迟或引入惰性流动性同步。无当前挂单不代表该环境的路径依赖流动性状态可以忽略。

## 4. 开发原则

- Account Ledger 是模拟余额的权威来源，Order Model 是订单状态权威来源，Fill History 是成交权威来源。
- 账户之间及交易所之间不得隐式转移资金。
- 不使用 float 处理金额和数量。
- AI 负责开发和解释，程序负责采集和计算。
- Task 1.5～1.8 只开发 Python 领域层，不提前引入 FastAPI、React、PostgreSQL 或完整 Docker 部署。
- 每个 Task 单独设计、实现、测试、验收和 Commit；通过前不默认扩大任务范围。
- 长期实验及长期运行服务不得阻塞 AI 开发会话。
- Phase 0-B 不阻塞本计划，但重大数据问题会触发行情依赖复审。
