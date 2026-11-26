# ADR-0006：实时 WebSocket Contract 与背压策略

- 状态：Accepted
- 日期：2026-11-26
- 适用范围：Phase 1 Task 1.11～1.13

## 背景

REST API 已提供权威快照和幂等写入，但前端需要低延迟获知行情及模拟交易状态。高频行情、慢客户端、事务回滚和断线恢复会直接影响数据真实性与内存安全，因此必须先确认协议和一致性边界。

## 决策

1. 使用环境范围的 `/api/v1/ws/environments/{environment_id}` 和 `crypto-lab.v1` Subprotocol。
2. 使用单进程 In-memory Event Hub；Task 1.11 不引入 Redis、消息队列或多进程广播。
3. 交易状态只在数据库事务提交后发布；WebSocket 不成为权威来源。
4. 每连接使用有界队列；行情状态允许按 Topic/Instrument 合并，交易事件不得静默丢弃。
5. 慢客户端无法保持一致时以 1013 断开，并通过 REST Resync。
6. 提供有限的进程内 Replay；缓冲缺口或进程重启不承诺续传。
7. 客户端只进行订阅、取消订阅及心跳；订单写入继续使用 REST。
8. Candle 仅接受真实 Canonical 数据，不使用 Ticker 合成。
9. Environment Hub 拥有 `stream_id`、环境级 `stream_sequence` 及有界 Replay；连接拥有连续 `delivery_sequence`。
10. 交易事务单调增加持久化 `state_version`，提交后事件携带该版本；REST 聚合快照返回事务内读取的版本。
11. 客户端建立订阅并缓冲事件后读取 REST 快照，只应用高于快照版本的交易事件；无法证明连续性时重新 Resync。

## 影响

- 简化 Phase 1 部署并保持环境隔离，但只支持单 API 进程。
- 客户端必须实现序列缺口检测、重连及 REST 快照恢复。
- 需要有界 Hub、连接管理、消息 Schema、可测试 Clock 和提交后发布接口。
- 未来多进程部署需要持久化 Outbox 或外部 Broker，并通过新 ADR 确认。

## 确认记录

项目负责人已于 2026-11-26 确认核心方案，并补充 Sequence、Environment Ring Buffer、REST Resync、提交后发布、背压、Heartbeat 及 Canonical Candle 实施要求。按 [`../10-REALTIME-SERVICE-DESIGN.md`](../10-REALTIME-SERVICE-DESIGN.md) 实施。
