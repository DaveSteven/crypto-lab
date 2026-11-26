# ADR 0008 — Candle 多周期动态订阅方案

## 状态

Accepted（2026-11-26，项目负责人确认）；**Implemented**（2026-11-26，Task 1.12.6）

## 背景

ADR 0007 交付的共享 Feed 通过静态环境变量 `CRYPTO_LAB_FEED_CANDLE_INTERVALS` 配置推送周期，进程生命周期内固定。UI/UX 规范（docs/12 §9.3）要求全部六个周期（1m～1d）具备真实历史及实时数据能力，§9.5 要求"根据前端实际订阅动态管理上游 Candle Channel"。

现有事实：

- OKX candle\* 频道位于 Business WebSocket 端点；同一连接可承载多频道。
- Feed 每进程单实例，多环境/多浏览器共享（ADR 0007）。
- 前端 Gateway 按品种订阅 `market.candle`，`Subscription.interval` 字段已存在于 Hub 协议层。

## 问题

静态周期列表无法保证：未配置周期只有 REST 历史而无实时更新；固定全量六周期则在上游未使用时浪费上游订阅与推送带宽；且无法响应前端实际的周期订阅需求。

## 候选方案

1. 静态全量订阅（恒定推送全部六周期）。
2. 动态引用计数订阅 + 常驻周期混合模式。
3. 每浏览器独立上游连接（违反 ADR 0007 与 docs/12 §9.5，否决）。

## 最终决定（Accepted）

方案 2 混合模式，细化规则如下（2026-11-26 项目负责人确认）：

- **常驻周期**：默认仅 `1m`；常驻交易对来自已配置的 Feed Instruments。
- **动态周期**：其余周期（5m/15m/1h/4h/1d）按前端实际订阅动态管理。
- **上游频道复用**：相同 `(exchange_id, instrument_id, interval)` 共享同一上游频道，引用计数管理生命周期。
- **频道上限**：默认 32，可配置；超过限制返回明确错误（`SUBSCRIPTION_LIMIT`），不静默丢弃。
- **宽限释放**：无订阅者的非常驻频道经过 30 秒宽限期后释放上游订阅。
- **不变量**：引用计数不得出现负值或连接泄漏；常驻频道不受普通客户端取消订阅影响。
- **断线恢复**：重连后恢复当前有效订阅集合（常驻 + 活跃动态频道）。
- **数据完整性**：不得使用其他周期数据冒充目标周期；不得为每个浏览器连接建立独立上游连接。
- **过渡策略**：ADR 0008 实施前，可将 `CRYPTO_LAB_FEED_CANDLE_INTERVALS` 配置为全量六周期作为临时手段（本地带宽可接受），不构成对本月色的替代。

## 影响范围

- `crypto_lab.realtime.feed`（频道生命周期、引用计数、宽限释放、上限）
- `crypto_lab.realtime.hub` / 协议层（带 interval 的 candle 订阅意图 → Feed 引用转译）
- 前端 Gateway（页面级周期订阅注册/注销时机）
- ADR 0007 修订记录、docs/10 Topic 章节补充、前后端测试

## 实施窗口

Task 1.12.6（Candlestick Chart）内实施，与 docs/12 §9.3"所有周期必须具备实时能力"对齐。状态与规则一经实施须回写本 ADR 与相关 Contract 文档。

## 实施记录（2026-11-26）

- 后端：`OkxMarketFeed.acquire_candle / release_candle / release_owner`。引用以 owner（客户端 connection_id）集合计数，同 owner 重复订阅幂等，不会出现负计数；常驻周期（`CRYPTO_LAB_FEED_CANDLE_INTERVALS`，默认 `1m`）不受影响。
- 上限：`CRYPTO_LAB_FEED_MAX_CANDLE_CHANNELS`（默认 32，含常驻频道），超限抛 `SubscriptionLimitError`，WebSocket 返回 `error` 消息 `code=SUBSCRIPTION_LIMIT`，不静默丢弃。
- 宽限：最后一个引用释放后经 `CRYPTO_LAB_FEED_CANDLE_GRACE_SECONDS`（默认 30）才向 OKX 发送 unsubscribe；宽限内重新订阅则取消释放。
- 触发点：WebSocket 控制消息 `subscribe/unsubscribe` 中带 `interval` 的 `market.candle` 主题（必须带 `instrument_id`）；连接断开时 `release_owner`。
- 断线恢复：重连的订阅参数包含常驻 + 当前活跃动态频道（含宽限期内频道）。
- 前端：`gateway.setCandleInterval` 随图表周期切换订阅新周期并退订上一个动态周期；1m 作为常驻频道始终订阅；`SUBSCRIPTION_LIMIT` 在图表下方提示“仅显示历史数据”。
- 测试：`tests/realtime/test_candle_channels.py`（7 项）、`tests/api/test_market_feed_lifespan.py`（WS 接线）、前端 gateway 2 项。全部使用 stub/fake 连接；**未对真实 OKX Business 端点做动态 subscribe/unsubscribe 的实测**（状态：Documented，未 Verified）。

## 真实行情验证（2026-11-26，OKX 公共端点，Verified）

隔离数据库 `crypto_lab_verify` + 本地后端（Feed 开启，常驻 1m）：

- WebSocket 客户端依次订阅 5m、1h：1m 之外的 `market.candle` 事件随即实时到达（15 秒内 5m 12～14 条、1h 15 条，均含当前未闭合 K 线更新）；退订后客户端不再收到。非法周期 `7m` 返回 `INVALID_CONTROL_MESSAGE`。
- Feed 直连验证（宽限期缩短为 3 秒）：订阅 5m 持有期间收到 8 条；释放并过宽限后收到最后 11 条，此后 10 秒内 0 条新增，证明 OKX 端 unsubscribe 生效；期间 `invalid_messages=0`、`subscription_errors=0`、无重连，1m 常驻不受影响。
- 浏览器（1440×900）：1m / 5m 图表显示 Volume、Last Price Line、OHLC 图例；5m 切换后现价线与最新 K 线一致；模拟市价买单成交后出现个人买入标记。
- 未验证：`SUBSCRIPTION_LIMIT` 的真实触发（仅单元/接线测试）；断线重连后动态频道恢复（仅单元测试）；1h/4h/1d 的真实闭合 K 线边界。
- 已修复：成交标记文字靠近最右侧 K 线时被价格轴裁切——时间轴增加 `rightOffset: 8` 留白，浏览器复查标记文字完整可见。
