# ADR 0008 — Candle 多周期动态订阅方案（Proposed）

## 状态

Proposed（待项目负责人确认后实施；对应 docs/12 §9.5 与 Task 1.12 Instruction §7）

## 背景

ADR 0007 交付的共享 Feed 通过静态环境变量 `CRYPTO_LAB_FEED_CANDLE_INTERVALS` 配置推送周期，进程生命周期内固定。UI/UX 规范 §9.3 要求全部六个周期（1m～1d）具备真实历史及实时数据能力，§9.5 要求"根据前端实际订阅动态管理上游 Candle Channel"。

现有事实：

- OKX candle\* 频道位于 Business WebSocket 端点；同一连接可承载多频道。
- Feed 每进程单实例，多环境/多浏览器共享（ADR 0007 第 4 节）。
- 前端当前按品种订阅 `market.candle`（无 interval 过滤），收到全部已配置周期。

## 问题

静态周期列表无法保证：未配置周期只有 REST 历史而无实时更新；固定全量六个周期则在上游未使用时浪费上游订阅与推送带宽。

## 候选方案

1. **静态全量订阅**：环境变量配置全部六周期，Feed 恒定推送。实现最简单；带宽与上游订阅量恒定偏高；周期集合仍需重启进程才能变更。
2. **动态引用计数订阅（推荐）**：Feed 暴露进程内订阅管理接口，按 `(instrument_id, interval)` 引用计数管理上游频道；计数归零退订。前端 Gateway 在页面/组件订阅周期时注册，卸载时注销；相同 (品种, 周期) 复用；设全局上游频道数上限（如 32）；断线重连后按当前活跃集合重新订阅。
3. **每浏览器独立上游连接**：违反 ADR 0007 与 docs/12 §9.5 的明确禁令，否决。

## 最终决定（建议）

方案 2，边界如下：

- 上游连接仍为每进程一组（公共 + Business），不随浏览器连接数增长。
- 引用计数键为 `(exchange_id, instrument_id, interval)`；REST 历史不占用引用。
- 订阅接口为进程内同步调用（async-safe 转交），不新增 REST/WS 管理端点；前端通过现有 WS 订阅声明 `interval`，服务端 Hub 将订阅意图转译为 Feed 引用计数。
- 保留 `CRYPTO_LAB_FEED_CANDLE_INTERVALS` 作为"常驻周期"初始集合（如默认 1m、5m），其余周期按需动态订阅。
- 引用计数状态不持久化；进程重启后由前端重连订阅行为自然重建。
- 全局频道上限超限时拒绝新订阅并返回 `error`（code: `SUBSCRIPTION_LIMIT`），不静默丢弃。

## 影响范围

- `crypto_lab.realtime.feed`（频道生命周期管理、退订、上限）
- `crypto_lab.realtime.hub` / 协议层（订阅意图 → Feed 引用的转译；`Subscription.interval` 已存在，需扩展 candle 语义）
- 前端 Gateway（周期订阅注册/注销时机）
- ADR 0007 修订记录、docs/10 Topic 章节补充、前后端测试

## 待确认事项

1. 是否接受"常驻周期 + 动态订阅"混合模式（方案 2 + 常驻集合）。
2. 全局上游频道上限取值（建议 32）。
3. 实施窗口：建议在 Task 1.12.6（Candlestick Chart，新划分）验收前完成，与 docs/12 §9.3"所有周期必须具备实时能力"对齐。
