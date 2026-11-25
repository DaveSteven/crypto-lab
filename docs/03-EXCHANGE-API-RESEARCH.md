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

