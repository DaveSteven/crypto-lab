# ADR 0007 — 实时行情 Feed 接入交易引擎的集成方案

## 状态

Accepted（2026-11-26，经项目负责人确认"应用启动时自动开启"方案并补充实施要求）

## 背景

Task 1.11 需要向本地 React 客户端推送真实 Canonical 行情，并要求行情事件进入交易引擎统一串行处理入口：Market State 更新、TRADE_THROUGH 限价单自动撮合、Execution Scheduler 到期执行。此前行情仅存在于独立验证脚本，REST 服务依赖手工种子数据。

## 问题

- API 进程如何获得真实行情，且不阻塞 FastAPI 启动与 REST 可用性。
- 行情如何在不破坏 Task 1.8 串行处理与原子一致性的前提下驱动各模拟环境交易引擎。
- 断线、订单簿失效期间如何避免用旧报价撮合。
- OKX 实际频道协议与文档假设不一致时的连接管理。

## 候选方案

1. 每个模拟环境独立连接交易所 Feed。
2. 每个浏览器连接触发独立 Feed。
3. 单 API 进程共享一个逻辑 Feed，行情事件分发到各环境引擎。
4. 独立喂送进程 + 进程间队列。

## 最终决定

方案 3。约束如下：

- **生命周期**：Feed 与调度驱动任务由 FastAPI Lifespan 管理；一个 API 进程最多一个逻辑 Feed；启动仅创建后台任务，不做同步网络等待；关闭时取消任务、关闭连接、释放资源。
- **连接管理**：OKX candle\* 频道位于 Business WebSocket 端点（`/ws/v5/business`），tickers/trades/books 位于公共端点（`/ws/v5/public`），Feed 按端点维护多条上游连接并视为一个逻辑会话。默认 `wss://ws.okx.com:443/...`（8443 已公告退役）。真实验证发现本地系统代理 WSS CONNECT 失败，默认绕过系统代理直连。
- **分发**：`EnvironmentMarketDispatcher` 对每个注册环境在独立数据库事务中应用事件：Trade → `TradeThroughEngine` 被动撮合；订单簿 → 共享 `LatestBookState` 门 + 各环境 `SimulatedLiquidityView` 同步；到期订单 → 现有 `ExecutionScheduler` + `ScheduledOrderExecutor`。每笔 Trade 以 `processed_market_events` 去重并保存保守排序键，重启后恢复顺序状态。
- **隔离**：仅 Canonical 行情数据共享；订单、资金、持仓、模拟流动性、调度器完全按环境隔离。
- **失效处理**：订单簿过期或失效时，到期订单按既有语义以 `MARKET_DATA_UNAVAILABLE` 拒绝（Task 1.7 保守模型），旧订单簿不会恢复为有效状态；重连后必须重新快照同步。
- **配置**：`CRYPTO_LAB_FEED_ENABLED`（默认 true）、`CRYPTO_LAB_FEED_INSTRUMENTS`（默认 BTC/USDT）、`CRYPTO_LAB_FEED_EXCHANGE`（默认 okx）、`CRYPTO_LAB_FEED_RECONNECT_ENABLED`（默认 true）、`CRYPTO_LAB_FEED_CANDLE_INTERVAL`、`CRYPTO_LAB_FEED_DISPATCH_INTERVAL_MS`、`CRYPTO_LAB_FEED_MAX_BOOK_AGE_MS`。自动化测试必须显式禁用 Feed 或注入可控连接工厂。
- **Market Rules**：Phase 1 使用 `OKX:DOCUMENTED:SPOT:V1` 静态规则（Documented，非每次运行 Verified）；接入更多品种前应从 OKX instruments 端点刷新。

## 被否决的方案

- 方案 1/2：违反"不得为每个模拟环境或浏览器连接重复创建交易所 Feed"的要求，且成倍放大交易所连接与限流压力。
- 方案 4：Phase 1 维持单进程边界（ADR 0006 第 12.3 条），不提前引入跨进程基础设施。

## 影响范围

- `crypto_lab.realtime.feed`（多端点连接管理、keepalive、stale/quality）
- `crypto_lab.realtime.dispatch`（新增，环境串行分发）
- `crypto_lab.api.app`（Lifespan 任务、配置、环境注册）
- `crypto_lab.api.market_feed`（新增，配置与组合）
- `crypto_lab.persistence.store`（流动性乐观恢复、到期调度分组、市场事件去重登记）

## 已知限制

- 多账户环境按账户分组串行执行，跨账户的同一时刻订单不保证全局严格有序（Phase 1 单账户场景不受影响）。
- 进程重启后行情事件不回放（ADR 0006 第 8 节），客户端以 REST 恢复。
- 调度驱动间隔默认 200ms，市价单实际执行时间存在该量级的 scheduler lag；订单已持久化区分 `configured_latency_ms` 与 `scheduler_lag_ms`（见 docs/10 §13.2）。高精度事件驱动调度器留待后续评估。
- WebSocket Feed 每进程只推送一个配置的 K 线周期；多周期推送待 Task 1.12 按前端需要评估。
- Dispatcher 端到端持久化测试需要 `CRYPTO_LAB_TEST_DATABASE_URL`（独立测试容器），未配置时跳过。
