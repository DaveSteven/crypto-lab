# Crypto Lab — 交易所 API 调查与验证记录

## 0. 文档信息

| 属性 | 内容 |
|---|---|
| 文档版本 | V0.1 |
| 当前阶段 | Phase 0 |
| 验证日期 | 2026-11-25 |
| 验证地点 | 日本网络环境 |
| 状态 | 首次 REST smoke test 已完成 |

## 1. 验证范围

本次仅调用无需认证的公开现货市场数据接口，不使用 API Key，不访问账户或交易接口。

- Binance、OKX、Bybit、Kraken、Coinbase：BTC/USDT 与 ETH/USDT。
- bitbank：BTC/JPY 与 ETH/JPY，仅作为日本市场补充，不与 USDT 市场直接计算价差。
- 数据类型：交易品种信息、Ticker、1 分钟 K 线、订单簿快照。

探测脚本：`scripts/probe_rest.py`。

## 2. 官方资料

| 交易所 | 官方资料 | 调查状态 |
|---|---|---|
| Binance | [Spot REST Market Data](https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints) | Documented |
| OKX | [API V5](https://www.okx.com/docs-v5/en/) | Documented |
| Bybit | [V5 Introduction](https://bybit-exchange.github.io/docs/v5/intro)、[Rate Limits](https://bybit-exchange.github.io/docs/v5/rate-limit) | Documented |
| Kraken | [Spot REST API](https://docs.kraken.com/api/docs/category/spot-market-data/) | Documented |
| Coinbase | [Exchange REST API](https://docs.cdp.coinbase.com/exchange/reference/exchangerestapi_getproducts) | Documented |
| bitbank | [Public REST API](https://github.com/bitbankinc/bitbank-api-docs/blob/master/public-api.md) | Documented |

接口文档会变化，接入代码不得假设以上行为永久不变。

WebSocket 补充资料：

- [Binance Spot WebSocket Streams](https://developers.binance.com/docs/binance-spot-api-docs/web-socket-streams)
- [OKX API V5 WebSocket](https://www.okx.com/docs-v5/en/)
- [Bybit Public Orderbook](https://bybit-exchange.github.io/docs/v5/websocket/public/orderbook)
- [Kraken WebSocket v2](https://docs.kraken.com/api/docs/category/websocket-v2/)
- [Coinbase Advanced Trade WebSocket Channels](https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/websocket/websocket-channels)
- [bitbank Public Streams](https://github.com/bitbankinc/bitbank-api-docs/blob/master/public-stream.md)

## 3. 首次真实验证结果

验证时间约为 2026-11-25 07:47 UTC（16:47 JST）。每个平台执行 8 个请求，即两个交易对分别验证 4 类数据。

| 交易所 | 成功/总数 | HTTP 状态 | 最短耗时 | 平均耗时 | 最长耗时 | 状态 |
|---|---:|---|---:|---:|---:|---|
| Binance | 8/8 | 200 | 35 ms | 43.9 ms | 52 ms | Verified |
| OKX | 8/8 | 200 | 50 ms | 88.6 ms | 165 ms | Verified |
| Bybit | 8/8 | 200 | 41 ms | 89.8 ms | 136 ms | Verified |
| Kraken | 8/8 | 200 | 44 ms | 254.8 ms | 361 ms | Verified |
| Coinbase | 8/8 | 200 | 45 ms | 136.8 ms | 243 ms | Verified |
| bitbank | 8/8 | 200 | 38 ms | 49.5 ms | 64 ms | Verified |

本轮合计 48/48 个请求成功。成功条件同时要求：HTTP 2xx、响应为合法 JSON，且响应体中不存在交易所级错误码。

本地证据文件：`data/probes/2026-11-25/rest-074734.jsonl`。该文件属于运行数据，不提交 Git。

## 4. 限流与错误处理

- 本轮按顺序执行单次请求，没有出现 HTTP 429 或交易所级限流错误。
- OKX 公共未认证 REST 限流按 IP 计算；达到限制时记录错误码 `50011`。具体额度按端点定义。
- Bybit 官方当前说明默认 IP 限制为 5 秒内 600 次请求；超过频率可能返回 HTTP 403，接口级限流可能返回 `retCode=10006`。本项目不得接近该上限运行。
- Binance、Kraken、Coinbase 与 bitbank 的持续采集速率仍需在实施 Collector 前逐端点确认，当前状态为 Pending。
- 探测工具单请求默认超时 10 秒、响应上限 2 MB，不进行无限重试。

不得通过故意压测公共接口来触发限流。后续采集频率应保守配置并优先采用 WebSocket。

## 5. 已确认差异

- 交易对格式不同：`BTCUSDT`、`BTC-USDT`、Kraken 的 `XBTUSDT`、bitbank 的 `btc_jpy`。
- HTTP 200 不必然代表业务成功；OKX、Bybit、Kraken 和 bitbank 等会在 JSON 响应内返回业务错误状态。
- bitbank 的验证市场以 JPY 计价，不能与 USDT 市场直接比较价差。
- 本轮耗时为客户端观测到的请求往返时间，不等于交易所行情生成延迟。
- 一次 smoke test 只能证明验证时刻可访问，不能证明持续稳定性。

## 6. 尚未完成

- 30 分钟和 24 小时稳定性实验尚未执行。
- 尚未验证高频运行下的数据成功率、429 行为或各平台长期网络稳定性。
- 尚未把各平台响应转换为统一 Ticker、Candle 和 OrderBook Schema。

## 7. WebSocket 首次验证

验证时间约为 2026-11-25 07:55 UTC（16:55 JST），每个平台并发观察约 12 秒。

| 交易所 | 消息数 | Ticker | 快照 | 增量 | 心跳 | 同步状态 |
|---|---:|---|---|---|---|---|
| Binance | 3,895 | Yes | Yes | Yes | Pass | Partial |
| OKX | 197 | Yes | Yes | Yes | Pass | Verified |
| Bybit | 547 | Yes | Yes | Yes | Pass | Verified |
| Kraken | 1,093 | Yes | Yes | Yes | Pass | Partial |
| Coinbase | 210 | Yes | Yes | Yes | Pass | Verified |
| bitbank | 49 | Yes | Yes | Yes | Pass | Verified |

本轮 6/6 个 WebSocket smoke probe 成功。证据文件为：

`data/probes/2026-11-25/websocket-075700.jsonl`

成功条件包括订阅确认、协议 ping/pong、实时 Ticker、订单簿快照、行情未过期和未发现序列倒退。探测器实现最多两次连接尝试，但本轮所有平台均在第一次连接成功，因此断线后的实际重连恢复仍为 Pending。

### 7.1 同步结论

- OKX：`books` 初始快照后收到增量，并验证 `prevSeqId` 与上一条 `seqId` 连续。
- Bybit：收到 snapshot/delta，并检查更新 ID 未倒退。
- Coinbase：使用无需认证的 Advanced Trade WebSocket，验证连接级 `sequence_num` 连续，并收到 `l2_data` snapshot/update。
- bitbank：同时订阅 `depth_whole` 与 `depth_diff`，验证共享序列单调递增。
- Binance：同时收到 partial depth 快照和 diff depth 更新，但尚未按照官方流程用 REST `lastUpdateId` 桥接缓存增量，因此状态只能是 Partial。
- Kraken：收到 book snapshot/update，但本轮未实现官方 checksum 计算，因此状态只能是 Partial。

Partial 或 Unsynced 订单簿不得进入套利及模拟成交分析。

### 7.2 实际发现

Coinbase Exchange WebSocket 的 `level2` 订阅在本次实际请求中返回需要认证的错误。由于项目禁止使用账户 API Key，验证器改用无需认证的 Coinbase Advanced Trade 公共 WebSocket，并成功收到 Level 2 数据。

OKX 已使用不带 `:8443` 的 443 端口地址。根据官方变更说明，公共网络的 8443 端口已于 2026-10-31 停止接受连接。

## 8. Ticker 标准化验证

验证时间约为 2026-11-25 08:00 UTC（17:00 JST）。使用六家交易所的真实公开 REST Ticker 各生成一条 Canonical Market Event。

| 交易所 | Canonical Instrument | 质量状态 | Exchange Timestamp |
|---|---|---|---|
| Binance | `binance:SPOT:BTC/USDT` | VALID | null |
| OKX | `okx:SPOT:BTC/USDT` | VALID | provided |
| Bybit | `bybit:SPOT:BTC/USDT` | VALID | provided |
| Kraken | `kraken:SPOT:BTC/USDT` | VALID | null |
| Coinbase | `coinbase:SPOT:BTC/USDT` | VALID | provided |
| bitbank | `bitbank:SPOT:BTC/JPY` | VALID | provided |

本轮 6/6 条记录标准化成功。证据文件：

`data/normalized/2026-11-25/ticker-rest-080057.jsonl`

验证结果：

- 价格、数量和成交量在 JSON 中均为十进制字符串。
- 缺失字段保留为 `null`；Binance 与 Kraken 未提供可用事件时间时，没有用本地时间冒充。
- Instrument ID 统一为 `{exchange}:SPOT:{BASE}/{QUOTE}`。
- Bid 高于 Ask 时标记为 INVALID；缺少可执行 Bid 或 Ask 时标记为 INCOMPLETE。
- 重复事件和同一数据流中的时间倒退由有界 `EventSequenceTracker` 检测。

时间戳仍需按接口语义解释。例如 Coinbase REST Ticker 的 `time` 与最近成交相关，不能单独作为最佳买卖报价的新鲜度证明。行情过期判断必须结合接收时间、连接状态和具体频道语义。

## 9. 跨交易所价差验证

验证时间约为 2026-11-25 08:06–08:07 UTC（17:06–17:07 JST）。比较 Binance、OKX、Bybit、Kraken、Coinbase 的 BTC/USDT 现货报价；bitbank 的 BTC/JPY 因计价资产不同被排除。

### 9.1 无成本假设实验

- 保存全部 20 个有向交易所组合，不筛除负价差。
- 20/20 报价满足初始时效阈值。
- 7 个方向出现正毛价差。
- 最大观测毛价差率约为 `0.00027095`，即约 `0.0271%`。
- 因缺少完整且已验证的成本输入，所有净收益字段均为 `null`。

证据：`data/experiments/2026-11-25/spread-rest-080655.jsonl`

### 9.2 明确假设成本实验

实验目标数量为 `0.001 BTC`，仅用于验证计算路径。假设参数：

- 买入 Taker Fee：0.1%。
- 卖出 Taker Fee：0.1%。
- 额外执行成本：0.05%。
- 资金再平衡成本：0.1%。

结果：20 个方向中 12 个具备买一/卖一数量，可计算净估值；12 个结果均为负。其余 8 个方向涉及未提供顶层数量的 Coinbase Ticker，净收益保持 `null`。最佳假设净收益率约为 `-0.3261%`。

证据：`data/experiments/2026-11-25/spread-rest-080702.jsonl`

以上成本均为 Assumed，不是已验证的账户实际费率。正毛价差不等于可执行套利利润。

订单簿深度计算器已通过多档价格、共同成交数量、排序错误及零数量边界测试，但尚未使用六家交易所的实时完整订单簿执行深度实验；该项将在持续采集实验前补充。

## 10. Phase 0-B 采集程序状态

已实现有界稳定性采集程序，支持：

- 可配置运行时长、采样间隔、请求超时及日志等级。
- JSONL 文件轮换和总存储容量上限。
- 请求成功率、失败类型、有效观测、正毛价差频率和持续区间统计。
- 安全信号停止及自动生成结构化 `summary.json`。

采集程序开发完成不代表 Phase 0-B 验收完成。30 分钟及 24 小时实验结果仍须由独立任务实际运行并在结束后分析。

### 10.1 60 秒短时功能测试

2026-11-25 08:19 UTC 执行独立的 60 秒功能测试：

- 6/6 采样周期成功。
- 30/30 公开 REST 请求成功。
- 120/120 价差观测通过时效校验。
- 写入 114,789 bytes，未触发文件轮换或容量保护。
- `safe_stop_reason` 为 `null`。

汇总：`data/experiments/2026-11-25/stability-081936-885417/summary.json`

该结果仅证明短时采集功能正常，不代表长期稳定性、延迟分布或套利机会研究已经验收。

