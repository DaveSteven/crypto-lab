# Crypto Lab — 实时行情与订单推送设计

## 0. 文档信息

| 属性 | 内容 |
|---|---|
| 文档版本 | V0.1 |
| 对应任务 | Phase 1 Task 1.11 |
| 状态 | Proposed / Awaiting Confirmation |
| 传输 | FastAPI WebSocket |

## 1. 目标与边界

Task 1.11 向本地 React 客户端推送 Canonical Market Data、数据质量和模拟交易状态。程序负责接收、标准化及发布，浏览器只消费服务端事件，不直接连接交易所。

本任务不实现 React、真实交易、认证、Redis、外部消息队列、多进程广播或长期行情存储。Phase 1 维持单 API 进程；进程重启后客户端必须通过 REST 获取权威快照。

## 2. Endpoint 与连接范围

```text
WS /api/v1/ws/environments/{environment_id}
Subprotocol: crypto-lab.v1
```

- 一个连接固定属于一个 Simulation Environment。
- 连接前验证环境存在；无效环境以 1008 关闭。
- Phase 1 无认证，只允许本机服务。
- Origin 默认不跨域放行；Task 1.12 只允许显式开发 Origin。
- 服务端在 `accept()` 后首先发送 `session.ready`。

## 3. 消息信封

所有服务端消息使用统一 JSON 信封：

```json
{
  "protocol_version": "1.0.0",
  "type": "market.ticker",
  "environment_id": "env_...",
  "stream_sequence": 42,
  "event_id": "...",
  "event_ts_ms": 1000,
  "published_ts_ms": 1002,
  "payload": {}
}
```

约束：

- Decimal 继续使用字符串，时间使用 UTC Epoch Milliseconds。
- `stream_sequence` 在单环境、单进程生命周期内严格递增，用于检测缺口，不作为持久业务 ID。
- `event_id` 保留 Canonical 行情事件或模拟事件身份。
- 未提供的值使用 `null`，不得用 0 或本地时间伪造。
- 客户端不得通过 WebSocket 提交或取消订单；写操作继续使用 REST 幂等接口。

## 4. 客户端控制消息

### 4.1 Subscribe

```json
{
  "type": "subscribe",
  "request_id": "client-1",
  "topics": [
    {"name": "market.ticker", "instrument_id": "okx:SPOT:BTC/USDT"},
    {"name": "orders", "account_id": "account-1"}
  ]
}
```

服务端以 `subscription.ack` 或 `error` 响应。单连接 Topic 数和消息大小必须有限制；重复订阅幂等。

### 4.2 Unsubscribe、Ping 与 Pong

- `unsubscribe` 使用与订阅相同的过滤器。
- 客户端 `ping` 得到服务端 `pong`。
- 服务端每 15 秒发送 `heartbeat`；45 秒内未收到任意客户端消息则关闭连接。
- 心跳时间为连接健康指标，不得解释为交易所网络延迟。

## 5. Topic

| Topic | Payload 来源 | 过滤条件 |
|---|---|---|
| `market.ticker` | Canonical `Ticker` Envelope | instrument |
| `market.trade` | Canonical `Trade` Envelope | instrument |
| `market.order_book` | 有效 `OrderBookView` 快照 | instrument、depth |
| `market.candle` | Canonical `Candle` Envelope | instrument、interval |
| `market.quality` | 连接、同步、序列及 stale 状态 | instrument |
| `orders` | 已提交的 Order State | account |
| `executions` | Fill History 新记录 | account/order |
| `balances` | Ledger 投影变化 | account |
| `positions` | Portfolio 投影变化 | account |

订单簿面向前端发布当前有效快照，而不是要求浏览器重建交易所增量。原始高频增量仍由后端处理。

当前代码尚未实现 Canonical `Candle` Model 和真实 Candle Adapter。Task 1.11 可以实现模型、校验和发布通道，但在真实来源完成前必须返回 `TOPIC_UNAVAILABLE`，不得由 Ticker 或 Last Price 伪造 OHLCV。

## 6. 发布一致性

- 行情事件只有经过 Adapter 校验及顺序处理后才能发布。
- 模拟交易事件只在数据库事务成功提交后发布，禁止广播可能回滚的中间状态。
- Account Ledger、Order State、Fill History 和 Portfolio 仍是权威来源；WebSocket 只是通知通道。
- 同一业务事件生成稳定 `event_id`，重复发布不应导致客户端重复应用。
- 客户端发现序列缺口、收到 `resync.required` 或重连后，必须用 REST 重新读取订单、余额、持仓及成交。

## 7. 背压与有界内存

每个连接使用固定容量队列，建议默认 256、可配置范围 32～4096：

- Ticker、订单簿和未闭合 Candle 属于可合并状态，只保留同 Topic/Instrument 最新值。
- Trade、Order、Execution、Balance 和 Position 属于不可静默丢弃事件。
- 不可丢弃事件遇到满队列时发送 `resync.required`（如仍可发送），随后以 1013 关闭慢客户端。
- 记录连接数、队列高水位、合并数、丢弃数、关闭码和原因；禁止逐条输出高频行情日志。
- 全局连接数、每环境连接数、订阅数、消息大小及发送超时均需配置上限。

## 8. 重连与恢复

Phase 1 不承诺进程重启后的 WebSocket Event Replay。连接内保留小型有界 Ring Buffer（建议 1000 条或 60 秒，以先达到者为准）：

- 客户端可在首次消息中提供 `resume_after_sequence`。
- 缓冲仍覆盖该序列时按原顺序重放。
- 无法覆盖、环境不匹配或进程已重启时发送 `resync.required`。
- REST 快照完成后，客户端重新订阅并从新的 `session.ready` 序列继续。

持久化 Outbox、跨进程广播和长期 Replay 属于后续增强，不在 Task 1.11 引入。

## 9. 组件设计

```text
Canonical Market / Committed Trading Event
                    ↓
            RealtimePublisher
                    ↓
       Environment Event Hub (bounded)
                    ↓
       Subscription Filter / Coalescing
                    ↓
          Per-connection Send Queue
                    ↓
             FastAPI WebSocket
```

- `RealtimePublisher`：同步业务代码可调用的提交后发布接口。
- `EnvironmentEventHub`：环境隔离、序列、Ring Buffer 和连接登记。
- `RealtimeConnection`：订阅、队列、合并、心跳及统计。
- FastAPI Endpoint：协议解析、关闭码和连接生命周期；不包含交易计算。
- 单进程内通过 async-safe 调度将同步事务提交后的事件转交给 Hub，不阻塞数据库事务。

## 10. 错误及关闭码

| Code | 场景 |
|---:|---|
| 1000 | 正常关闭 |
| 1003 | 非 JSON 或不支持的数据类型 |
| 1008 | 环境、Origin、订阅或协议违反策略 |
| 1009 | 消息超过配置上限 |
| 1011 | 未分类服务端错误 |
| 1012 | 服务关闭或重启 |
| 1013 | 慢客户端或暂时过载 |

应用错误消息包含稳定 `code`、`message`、`request_id` 和有限 `details`，不得泄露堆栈及数据库信息。

## 11. 测试与验收

- 协议 Schema、Decimal、时间及未知字段校验。
- 连接、订阅、取消订阅、重复订阅及非法环境。
- Ticker、Trade、订单簿、Candle、质量及交易状态过滤。
- 事务提交前不发布，回滚不发布，提交后按序发布。
- 环境、账户和 Instrument 隔离。
- 多客户端广播及断开清理。
- 心跳、超时、服务关闭及关闭码。
- 有界队列、状态合并、慢客户端 1013 和统计。
- 重连恢复、Ring Buffer 命中与 `resync.required`。
- 重复事件和确定性序列。
- 完整 REST、Persistence 和交易引擎回归。

测试使用 TestClient、ManualClock 和可控发布器，不依赖真实交易所网络，不用真实等待验证心跳。

## 12. 待确认事项

1. Endpoint 使用 `/api/v1/ws/environments/{environment_id}`，Subprotocol 为 `crypto-lab.v1`。
2. 客户端仅订阅和心跳；下单、取消继续使用 REST。
3. 单进程内存 Event Hub，不提前引入 Redis 或外部消息队列。
4. 每连接有界队列默认 256；行情状态可合并，交易状态不可静默丢弃。
5. 慢客户端无法保证完整事件时以 1013 断开，并要求 REST Resync。
6. 连接内提供有限 Replay；进程重启或缓冲缺口通过 REST 恢复。
7. 服务端心跳 15 秒、客户端静默超时 45 秒，均可配置。
8. 订单簿向浏览器推送当前快照，不推送交易所原始增量。
9. Candle 只发布真实 Canonical 数据；来源未实现时明确不可用，不合成虚假 K 线。
10. Task 1.11 仍维持本机无认证边界，不进入 React 或多进程部署。
