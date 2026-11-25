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

- WebSocket 连接、心跳、重连及订单簿同步验证属于 Task 0.3。
- 30 分钟和 24 小时稳定性实验尚未执行。
- 尚未验证高频运行下的数据成功率、429 行为或各平台长期网络稳定性。
- 尚未把各平台响应转换为统一 Ticker、Candle 和 OrderBook Schema。

