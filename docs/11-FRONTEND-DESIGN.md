# Crypto Lab — 前端架构设计

## 0. 文档信息

| 属性 | 内容 |
|---|---|
| 文档版本 | V0.1 |
| 对应任务 | Phase 1 Task 1.12.1 |
| 状态 | Proposed（待项目负责人确认 UI/交互后进入 1.12.2） |
| 上游契约 | docs/09-REST-API-DESIGN.md、docs/10-REALTIME-SERVICE-DESIGN.md |

## 1. 目标与边界

为 Phase 1 模拟交易系统定义本地 React 前端的技术架构、状态同步设计、接口清单与需求差距分析。

本阶段不含 UI 布局、视觉风格、页面结构与交互设计（由项目负责人另行确认），不实现真实交易、认证、公网部署或核心金融计算——所有成交价格、手续费、成交结果均来自服务端，前端只提交订单意图。

## 2. 技术选型（候选，工程初始化时锁定版本）

| 用途 | 候选 | 说明 |
|---|---|---|
| 包管理 | pnpm | 工程初始化时确认本机版本 |
| 框架 | React + TypeScript | |
| 构建 | Vite | dev server 代理到 `127.0.0.1:8000`，规避 CORS |
| 样式 | Tailwind CSS + shadcn/ui | |
| 服务端状态 | TanStack Query | REST 快照、列表、轮询兜底 |
| 客户端状态 | Zustand | 行情流、WS 连接状态、环境/账户会话 |
| 路由 | React Router | |
| 图表 | TradingView Lightweight Charts | 仅展示，不做计算 |
| 图标 | Lucide React | |
| 校验 | Zod | 所有外部输入（REST/WS 消息）运行时校验 |
| 数值 | decimal.js | 仅展示层换算；禁止 float 参与资金展示计算 |
| 实时通道 | 原生 WebSocket（`crypto-lab.v1` 子协议） | 不引入 socket.io 等封装 |
| 单测 | Vitest + React Testing Library | |
| E2E | Playwright | 仅针对本地真实后端，不访问交易所网络 |

依赖分批引入：1.12.2 只装工程基座（构建/样式/路由/测试），其余随对应子任务引入。不一次性安装全部依赖。

## 3. 应用架构

```text
页面 / 路由（React Router）
    ↓
特性层（market / trading / account / orders / executions）
    ↓                ↓
TanStack Query    Zustand Store（实时流状态）
    ↓                ↓
REST Client       WS Client（单连接、协议状态机）
    └───────┬────────┘
      Zod Schema（契约唯一来源，对应 OpenAPI + docs/10 消息信封）
```

原则：

- REST 是权威快照来源，WebSocket 只是通知通道（docs/10 §6）；任何怀疑状态不一致时以 REST Resync 收场。
- 契约类型全部由 Zod Schema 推导（`z.infer`），不手写第二份 interface。
- 展示层不得实现核心金融计算；收益率、滑点等仅做只读展示换算（decimal.js），以服务端字段为准。

## 4. REST 与 WebSocket 状态同步

### 4.1 交易状态一致性流程（docs/10 §8.1 的客户端实现）

```text
1. 建立 WS → session.ready（取得 stream_id）
2. subscribe({ topics, resume_from? }) → 缓冲交易事件，不直接应用
3. GET /snapshot?account_id=... → 权威快照 + state_version V
4. 丢弃缓冲中 state_version <= V 的事件
5. 按 (state_version, event_index) 升序应用剩余事件
6. 之后到达的交易事件实时应用；order_id 幂等去重（稳定 event_id）
```

- `stream_id` 变化（进程重启）→ 强制完整 Resync（WS 重连 + REST 快照）。
- `delivery_sequence` 出现缺口（交易事件）→ `resync.required` 同等处理：全量 REST 重建。
- `stream_sequence` 缺口是订阅过滤/合并的正常现象，**不得**触发 Resync。
- 收到 `resync.required` 或重连完成后，必须重新走 4.1 流程。

### 4.2 WS 连接状态机

```text
connecting → ready(session.ready) → subscribed
   ↑              ↑ resync.required / 协议错误
   └── backoff ←──┘ （指数退避，上限 30s；重连携带 resume_from{stream_id, stream_sequence}）
```

- 心跳：服务端 15s `heartbeat` → 客户端立即回 `pong` 并回显 heartbeat ID；45s 静默会被服务端关闭。
- 连接状态（connecting/online/resync/offline）是全局 UI 状态（Zustand），页面据此展示数据新鲜度。

### 4.3 行情与交易的不同可靠性

| 事件类 | 合并性 | 缺口处理 |
|---|---|---|
| market.ticker / market.order_book / 未闭合 candle | 可合并（保留最新） | 缺口无需处理，等下一条 |
| market.trade / market.candle(闭合) / market.quality | 不可静默丢弃 | stream 缺口正常；按 event_id 去重 |
| orders / balances / executions / positions | 不可静默丢弃 | delivery_sequence 缺口 → Resync |

## 5. 数据类型与 Decimal

- 所有金额、价格、数量字段以 JSON 字符串传输；Zod Schema 统一 `z.string()` + 精度/正则校验。
- 展示换算（如百分比、市值）使用 decimal.js，从字符串构造，禁止从 float 构造。
- 时间字段为 UTC Epoch Milliseconds；展示层转换为本地时区，来源标注为服务端时间。
- 每个行情/订单展示必须带数据来源与时间（exchange_ts / received_ts / state_version）。

## 6. 真实行情与模拟交易的区分

- 全局布局固定展示"模拟交易声明"（虚拟资金、无真实订单）。
- 行情数据标注来源（`OKX 公共行情`）、传输类型与数据时间。
- 订单/成交/持仓页面标注手续费费率来源（`phase1-default-v1` 模拟配置）、执行延迟为**模拟配置延迟**并区分展示 scheduler lag。
- 行情质量状态（`market.quality`）驱动行情区域的可见状态：VALID / STALE / UNSYNCED / INCOMPLETE，失效时禁止引导下单（下单按钮置为不可用并说明原因）。

## 7. K 线设计

- **合并**：REST 历史（`GET /api/v1/market/candles`，默认倒序）与 WS 实时（`market.candle`）以 `(interval, open_ts_ms)` 为键合并；`event_id` 内含 confirm 标记，闭合 K 线以 `is_closed=true` 为准且不可被未闭合更新覆盖。
- **分页**：以最早 `open_ts_ms` 作为 `before` 游标向更早加载；OKX 返回行序为倒序，需在客户端按 `open_ts_ms` 升序排列。
- **缺口补齐**：WS 断线重连后，对比本地最新 `open_ts_ms` 与服务器历史，用 REST 拉取缺失区间后再拼接。
- **多周期动态订阅**：当前后端仅推送单一配置周期（见 §13 差距 G1）；前端按订阅过滤 `interval`，多周期推送需后端先行支持。

## 8. 高频行情与 React 渲染分离

- WS 消息由 WS Client 写入 Zustand store（非 React 状态）；ticker/order_book 采用"保留最新 + 定时 flush"（如 rAF 或 250ms interval）批量提交，避免每消息触发渲染。
- 图表组件对 K 线序列使用 `series.update()` 增量更新，不整表重绘。
- 订单/成交等交易事件即时提交渲染（低频、不可合并）。
- 组件按 selector 订阅切片状态，避免整 store 重渲染。

## 9. 模拟订单提交与取消

- 表单经 Zod 校验后构造 `OrderCreate`；数量/价格以字符串传输。
- 每次提交生成新的 UUID `Idempotency-Key`（取消同理）；请求在飞行中时禁用按钮（防重复下单），响应 201 后跳转/刷新订单列表。
- 收到 `409 IDEMPOTENCY_KEY_REUSED`、`409 INVALID_ORDER_STATE`、`503 MARKET_DATA_UNAVAILABLE` 等按 docs/09 错误模型展示可理解原因。
- 订单展示字段直接映射 PaperOrder：状态、数量/已成交、均价、累计手续费、`configured_latency_ms`、`actual_simulated_delay_ms`、`scheduler_lag_ms`（标注为模拟调度滞后）。

## 10. 前端所需 REST API 清单

Base Path `/api/v1`；除查询外均需 `Idempotency-Key`；错误信封见 docs/09 §6。

| Method | Path | 前端用途 | 触发时机 |
|---|---|---|---|
| GET | `/health/ready` | 启动自检 | 应用加载 |
| POST | `/environments` | 首次使用创建环境 | 引导流程 |
| GET | `/environments/{id}` | 环境状态/版本 | 会话恢复 |
| POST | `/environments/{id}/accounts` | 创建模拟账户 | 引导流程 |
| GET | `/environments/{id}/accounts` | 账户选择 | 会话恢复 |
| GET | `/environments/{id}/accounts/{account_id}` | 账户详情 | 会话恢复 |
| GET | `/environments/{id}/accounts/{account_id}/balances` | 余额（可用/冻结） | 快照 + 订阅兜底 |
| GET | `/environments/{id}/accounts/{account_id}/positions` | 持仓与成本 | 快照 + 订阅兜底 |
| POST | `/environments/{id}/orders` | 提交订单意图 | 交易表单 |
| GET | `/environments/{id}/orders` | 订单列表（limit ≤ 200，account/status 过滤） | 订单页 |
| GET | `/environments/{id}/orders/{order_id}` | 订单详情 | 订单页 |
| POST | `/environments/{id}/orders/{order_id}/cancel` | 取消挂单 | 订单操作 |
| GET | `/environments/{id}/executions` | 成交列表（account/order 过滤） | 成交页 |
| GET | `/environments/{id}/executions/{execution_id}` | 成交详情 | 成交页 |
| GET | `/environments/{id}/snapshot?account_id=...` | 一致性快照（含 state_version） | Resync 流程 |
| GET | `/market/candles?instrument_id&interval&limit&before&after` | K 线历史/分页/缺口补齐 | 行情页 |

## 11. WebSocket Topic 清单

Endpoint：`/api/v1/ws/environments/{environment_id}`，Subprotocol `crypto-lab.v1`，Origin `http://localhost:5173` 已在服务端白名单。

| Topic | 订阅过滤 | payload 来源 | 前端消费 |
|---|---|---|---|
| `market.ticker` | instrument | OKX tickers 频道 | 行情头部报价 |
| `market.trade` | instrument | OKX trades 频道 | 成交列表（可选） |
| `market.order_book` | instrument（depth 过滤见差距 G4） | 有效订单簿快照 | 盘口展示 |
| `market.candle` | instrument + interval | OKX Business 端点 candle | K 线实时更新 |
| `market.quality` | instrument | Feed 质量/断线/stale | 行情有效性与下单闸门 |
| `orders` | account_id | 事务提交后的订单状态 | 订单列表实时更新 |
| `executions` | account/order | **差距 G2：服务端尚未推送** | 成交页实时更新 |
| `balances` | account_id | Ledger 投影变化 | 余额实时更新 |
| `positions` | account_id | **差距 G3：服务端尚未推送** | 持仓实时更新 |

控制消息：`subscribe`（含 `resume_from`）、`unsubscribe`、`ping`/`pong`、服务端 `heartbeat`、`subscription.ack`、`error`、`resync.required`、`session.ready`。

## 12. 测试策略

- Vitest + RTL：WS Client 协议状态机（脚本化消息序列）、Zod Schema（含 Decimal 字符串、未知字段拒绝）、状态合并/Resync 逻辑、表单校验；全部离线。
- TanStack Query 与 REST Client：以本地 mock server（Vitest handler）验证幂等键、错误信封解析。
- Playwright：真实本地后端 + 测试数据库，覆盖下单/取消/成交/余额流程与刷新恢复；不访问交易所网络（后端 Feed 可禁用注入固定事件）。
- 保持后端 296 项测试基线不变；前端测试纳入独立 `pnpm test`，不混合进 pytest。

## 13. 后端能力与前端需求差距分析

| 编号 | 差距 | 影响 | 建议 |
|---|---|---|---|
| G1 | WS K 线仅推送单一配置周期（`CRYPTO_LAB_FEED_CANDLE_INTERVAL`），无法动态多周期订阅 | 行情页多周期切换只能 REST 轮询 | 后端将 Feed 配置改为周期列表（如 `1m,5m,15m,1h`）并全部发布；前端按 interval 过滤。Market 页开工（1.12.5）前实施 |
| G2 | `executions` topic 在 docs/10 §5 已定义，但服务端事务仅暂存 orders+balances，未暂存成交事件 | 成交页无实时推送，只能轮询 | 在订单成交事务中同批暂存 `executions` 事件（与 state_version 同事务），1.12.6 前实施 |
| G3 | `positions` topic 同样未暂存 | 持仓页无实时推送 | 同 G2 一并处理 |
| G4 | `Subscription` 无 depth 字段，`market.order_book` 推送全部档位（合并后单条） | 带宽可接受（合并后非高频）；前端切片 top-N 展示 | Phase 1 前端自行切片；后端 depth 过滤列为可选增强 |
| G5 | 无 `GET /api/v1/environments` 环境列表端点 | 多环境切换需自行记录 environment_id | Phase 1 前端本地持久化当前环境 ID + 引导创建；列表端点列为可选增强 |
| G6 | 无 instrument 元数据端点（tick size、最小数量） | 下单表单精度提示只能硬编码 | 前端静态配置（与后端 `OKX:DOCUMENTED:SPOT:V1` 同源），标注 Documented |
| G7 | 无行情快照 REST 端点（首屏在 WS 首条消息前无报价） | 首屏短暂显示"连接中" | 可接受；可选增强 `GET /market/ticker` |
| G8 | 游标分页（cursor）未实现，列表用 limit（≤200） | 数据量小可接受 | 按 docs/09 当前限制记录 |

## 14. 安全与边界

- dev 通过 Vite 代理访问 `127.0.0.1:8000`，无 CORS 暴露；不修改后端 CORS 配置（docs/09 §7）。
- 不引入认证、不上传任何密钥；行情与账户数据仅本机。
- 所有页面固定可见"模拟交易声明"；不得展示任何"实盘/收益保证"措辞。

## 15. 待项目负责人确认事项

1. UI 布局、视觉风格、页面结构与交互设计（本文档不涉及）。
2. 差距 G1/G2/G3 的后端补充实施顺序（建议 G1 先于 1.12.5，G2/G3 先于 1.12.6）。
3. 工程初始化时锁定各依赖版本并记录（1.12.2 交付物）。
