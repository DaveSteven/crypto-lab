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
| 1.12 | React 前端应用 | In Progress（1.12.1～1.12.6 Completed，剩余 1.12.7） |
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

### Task 1.12 — React 前端应用

架构设计见 [`11-FRONTEND-DESIGN.md`](11-FRONTEND-DESIGN.md)；依赖分批引入，UI 布局与交互由项目负责人另行确认。

#### Task 1.12.1 — 前端架构设计与接口调查

- [x] 审查 REST Contract（docs/09）与实际接口及数据模型。
- [x] 审查 WebSocket Contract（docs/10）及消息信封语义。
- [x] 编写前端架构设计、REST/WS 接口清单与差距分析（G1～G8）。
- [x] 明确状态同步（stream_id/stream_sequence/delivery_sequence、Resync、状态版本）与 Decimal 字符串处理。

#### Task 1.12.2 — 工程初始化

- [x] pnpm + Vite + React + TypeScript + Tailwind CSS 基座（shadcn/ui 基础设施：路径别名、cn 工具、CSS 变量随组件引入时落地）。
- [x] React Router 路由骨架、布局占位与模拟交易声明页脚。
- [x] Vitest + React Testing Library 测试工具链；Playwright 独立配置（浏览器按需安装）。
- [x] 依赖版本记录（pnpm-lock.yaml）：React 19.3、Vite 8.3、TypeScript 7.0、Tailwind 4.3、React Router 7.18、Vitest 5.1、Playwright 1.65、pnpm 12.23、Node 26。
- [x] 后端基线保持不变（300 passed，含 G1～G3 新增测试）。

#### Task 1.12.3 — API 与 WebSocket 客户端层

- [x] Zod 契约 Schema（对应 OpenAPI 与 WS 消息信封，含 delivery_sequence 与控制消息）。
- [x] REST Client：幂等键生成、错误信封解析为 ApiError、Decimal 字符串、列表/快照/K 线响应校验。
- [x] WS Client：连接状态机、订阅自动附加 resume_from 游标、心跳应答、退避重连；delivery_sequence 缺口与 stream_id 变更触发 resync，stream_sequence 缺口视为正常。
- [x] TradingStateSync：缓冲 → REST 快照 → 丢弃过期版本 → 按 (state_version, event_index) 应用，event_id 去重。
- [x] 17 项客户端层测试（MSW REST 场景 + 脚本化 WS 套接字），build/lint 通过；后端基线保持 300 passed。

#### Task 1.12.4 — 布局框架与页面骨架

- [x] 全局布局、导航与模拟交易声明。
- [x] 环境引导（创建环境与虚拟资金账户，会话持久化与重置）。
- [x] 连接状态全局徽标（连接中/已连接/同步中/离线）与 RealtimeGateway（单连接绑定活动环境，订阅后 REST 快照恢复一致性）。
- [x] 后端默认端口改为 127.0.0.1:8642（CRYPTO_LAB_API_PORT 可覆盖；前端代理 VITE_API_ORIGIN 对应）。前端 25 项测试通过；后端基线保持 300 passed。

#### Task 1.12.5 — Market 行情页面

- [x] Lightweight Charts K 线（REST 历史 + WS 实时合并、闭合保护、增量 update）。
- [x] 历史分页（before 游标）与断线缺口补齐（resync 后以 after 拉取缺失区间）。
- [x] 行情质量状态展示与下单闸门联动（非 VALID / 离线时提示暂停交易）；来源与数据时间标注。
- [x] 真实联调冒烟：经 Vite 代理创建环境/账户，WS 收到 54 条真实 OKX 双周期 K 线，delivery_sequence 连续。前端 44 项测试通过。

#### Task 1.12.6 — 模拟交易与账户页面

- [x] 下单意图表单：方向/类型切换、市价买预算必填、延迟预设（含 CUSTOM）、客户端 Zod 校验镜像后端契约、提交中禁用防重复、每次提交新幂等键、错误码可读展示。
- [x] 交易闸门：行情非 VALID 或连接离线时禁用下单并说明原因。
- [x] 订单列表/取消（幂等键 + 网关 Resync）、成交记录（只读）、余额与持仓（G2/G3 实时 topic 驱动）。
- [x] 配置延迟、实际模拟延迟、调度滞后三列分开展示并附说明；费用、来源、数据时间声明齐全。前端 58 项测试通过。

#### Task 1.12.7 — 前端测试与验收准备

- [ ] Vitest/RTL 单测与 Playwright 关键流程（本地真实后端 + 测试库，禁用真实 Feed）。
- [ ] 无障碍与加载/错误态检查；联调准备清单输出。

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
