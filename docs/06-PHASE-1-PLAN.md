# Crypto Lab — Phase 1 基础模拟交易开发计划

## 0. 文档信息

| 属性 | 内容 |
|---|---|
| 文档版本 | V0.7 |
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
| 1.12 | React 前端应用 | In Progress（Gate A Accepted；1.12.3 UI 验收通过；1.12.6 完成，待真实行情实测） |
| 1.13 | 前后端联调与 Phase 1 验收 | Pending |

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

权威规范：docs/12-UI-UX-DESIGN.md V1.1（Accepted，含 Desktop Only 修订）；架构：docs/11 V0.2；多周期订阅：ADR 0008（Proposed）。

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
- [ ] Activity Panel Tab 化（当前委托/历史订单/成交/余额/持仓）与账户同步三态展示。
- [ ] Execution Detail Drawer（§14：仅展示后端已有字段）、订单状态中文映射（§13）、部分成交展示。

#### Gate D — Account Experience

##### Task 1.12.10 — Account & Portfolio

- [x] 账户页余额与持仓（Ledger/Fill History 投影）。
- [ ] Overview 页（§15：估值标注币种与数据时间、无法估值资产列示；无收益曲线）。

##### Task 1.12.11 — Markets & Settings

- [ ] Markets 页（已接入品种、质量列、点击进入 Trading）。
- [ ] Settings 页（环境/账户/工作区/系统状态，§17）、环境选择器进顶栏、Query 缓存环境隔离。

#### Gate E — Frontend Acceptance

##### Task 1.12.12 — Frontend Acceptance

- [x] E2E 基础：真实后端 + 隔离测试库 + 关闭 Feed（引导/下单意图/订单表/账户/会话恢复 2 项通过）；运行须剥离系统代理（docs/11 §9）。
- [ ] 完整 E2E（确认流程、成交与余额变化、行情失效禁用、布局持久化、环境切换）。
- [ ] Desktop Acceptance Matrix（§21.1 四视口）、可访问性检查、性能检查（§20）。
- [ ] Task 1.12 验收报告。不自动进入 Task 1.13。


### Task 1.13 — 前后端联调与 Phase 1 验收

- [ ] 覆盖行情、下单、延迟、成交、挂单、取消、余额及持仓流程。
- [ ] 执行 API 集成测试和浏览器 E2E 测试。
- [ ] 验证刷新、重连、错误响应、过期行情及恢复场景。
- [ ] 确认系统不调用真实交易接口。

## 3. Task 1.1 验收标准

- 初始资金只存在于指定模拟账户和交易所。
- 相同资产区分 available 与 locked。
- 冻结金额从 available 转入 locked，总额不凭空变化。
- 释放金额从 locked 返回 available，总额不凭空变化。
- 任何会产生负余额的操作必须整体失败，不得部分写入。
- 重复 entry ID 不得重复影响余额。
- 余额可由资金流水完整重建。

Task 1.5～1.8 的详细设计、测试矩阵及验收标准见 [`07-EXECUTION-ENGINE-DESIGN.md`](07-EXECUTION-ENGINE-DESIGN.md)。

Task 1.10 的 REST Contract 见 [`09-REST-API-DESIGN.md`](09-REST-API-DESIGN.md)；Task 1.11 的 Proposed WebSocket Contract 见 [`10-REALTIME-SERVICE-DESIGN.md`](10-REALTIME-SERVICE-DESIGN.md)，须经负责人确认后实施。

## 4. 开发原则

- Account Ledger 是模拟余额的权威来源，Order Model 是订单状态权威来源，Fill History 是成交权威来源。
- 账户之间及交易所之间不得隐式转移资金。
- 不使用 float 处理金额和数量。
- AI 负责开发和解释，程序负责采集和计算。
- Task 1.5～1.8 只开发 Python 领域层，不提前引入 FastAPI、React、PostgreSQL 或完整 Docker 部署。
- 每个 Task 单独设计、实现、测试、验收和 Commit；通过前不默认扩大任务范围。
- 长期实验及长期运行服务不得阻塞 AI 开发会话。
- Phase 0-B 不阻塞本计划，但重大数据问题会触发行情依赖复审。
