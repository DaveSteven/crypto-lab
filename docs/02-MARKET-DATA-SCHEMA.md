# Crypto Lab — Market Data Schema

## 0. 文档信息

| 属性 | 内容 |
|---|---|
| 项目名称 | Crypto Lab |
| 文档版本 | V0.1 |
| 文档状态 | Draft |
| 创建日期 | 2026-11-25 |
| 当前阶段 | Phase 0 |
| Repository | git@github.com:DaveSteven/crypto-lab.git |
| 开发分支 | develop |

## 1. 设计目标

建立独立于具体交易所的统一市场数据模型。

通过 Exchange Adapter 将不同交易所返回的原始数据转换为 Canonical Market Data Schema，供后续行情分析、模拟交易、套利实验及量化策略使用。

设计目标：

- 统一交易所数据格式。
- 保证价格及数量精度。
- 保证数据来源可追溯。
- 支持 REST 与 WebSocket。
- 支持实时及历史行情。
- 支持多交易所比较。
- 支持数据质量检测。
- 支持未来历史行情回放。

## 2. 通用数据规范

### 2.1 数据类型

| 类型 | Python 类型 | JSON 表示 |
|---|---|---|
| Identifier | str | string |
| Price | Decimal | string |
| Quantity | Decimal | string |
| Amount | Decimal | string |
| Ratio | Decimal | string |
| Timestamp | int | integer |
| Duration | int | integer |
| Boolean | bool | boolean |
| Optional | T 或 None | value 或 null |

价格、数量、金额和比例在 JSON 中统一使用十进制字符串表示，避免 JavaScript Number 或 JSON 浮点解析造成精度损失。

### 2.2 时间规范

统一使用 UTC Unix Timestamp，单位为毫秒。

时间字段使用 `_ts_ms` 后缀。

例如：

- exchange_ts_ms
- received_ts_ms
- processed_ts_ms

Python 内部进行日期转换时必须使用 timezone-aware datetime。

人类可读日志及报告可使用 ISO 8601 格式。

用户界面未来可显示 JST，但不得修改底层数据时间。

### 2.3 缺失值

交易所未提供的字段应使用 null。

禁止将缺失价格、数量或时间戳自动设置为 0。

### 2.4 Schema Version

每条持久化的标准化行情记录必须包含：

- schema_version

初始版本：

`1.0.0`

破坏性数据结构变更必须升级主版本。

## 3. 枚举类型

### 3.1 ExchangeId

初期候选值：

- binance
- okx
- bybit
- kraken
- coinbase
- bitbank

新增交易所时必须使用唯一且稳定的标识。

不同地区实体及独立订单簿不得使用同一标识。

### 3.2 MarketType

- SPOT
- MARGIN
- FUTURES
- PERPETUAL
- OPTION

Phase 0 仅支持 SPOT。

其他类型为未来扩展预留，不代表当前支持。

### 3.3 DataSourceType

- LIVE
- HISTORICAL
- MOCK
- SYNTHETIC

### 3.4 TransportType

- REST
- WEBSOCKET
- FILE

### 3.5 TradeSide

- BUY
- SELL
- UNKNOWN

TradeSide 表示主动成交方向。

交易所未提供或无法可靠推导时，使用 UNKNOWN。

### 3.6 DataQualityStatus

- VALID
- INVALID
- STALE
- INCOMPLETE
- UNSYNCED

## 4. MarketEventEnvelope

所有标准化行情事件使用统一元数据结构。

| 字段 | 类型 | 必须 | 说明 |
|---|---|---|---|
| schema_version | str | Yes | Schema 版本 |
| event_id | str | Yes | 系统生成的唯一事件标识 |
| event_type | str | Yes | 事件类型 |
| exchange_id | str | Yes | 交易所标识 |
| instrument_id | str | Yes | 交易品种标识 |
| source_type | DataSourceType | Yes | 数据来源类别 |
| transport | TransportType | Yes | 数据获取方式 |
| exchange_ts_ms | int | No | 交易所事件时间 |
| received_ts_ms | int | Yes | 本地接收时间 |
| processed_ts_ms | int | No | 数据处理完成时间 |
| raw_ref | str | No | 原始数据引用 |
| quality_status | DataQualityStatus | Yes | 数据质量状态 |
| payload | object | Yes | 具体行情内容 |

交易所未提供事件时间时，不得使用本地时间冒充交易所时间。

## 5. Exchange

交易所基础信息。

| 字段 | 类型 | 必须 | 说明 |
|---|---|---|---|
| exchange_id | str | Yes | 唯一标识 |
| name | str | Yes | 显示名称 |
| market_types | list | Yes | 支持的市场类型 |
| rest_supported | bool | Yes | 是否支持 REST |
| websocket_supported | bool | Yes | 是否支持 WebSocket |
| enabled | bool | Yes | 当前是否启用 |
| documentation_url | str | No | 官方文档 |
| verified_ts_ms | int | No | 最近验证时间 |

说明：

- REST 支持不代表日本地区一定能够访问。
- 接口实际连通性由独立的 API 验证结果记录。
- 未验证的交易所不得标记为已验证。

## 6. Instrument

定义具体交易所中的交易品种。

| 字段 | 类型 | 必须 | 说明 |
|---|---|---|---|
| instrument_id | str | Yes | 唯一标识 |
| exchange_id | str | Yes | 所属交易所 |
| exchange_symbol | str | Yes | 交易所原始交易对 |
| canonical_symbol | str | Yes | 标准化交易对 |
| base_asset | str | Yes | 基础资产 |
| quote_asset | str | Yes | 计价资产 |
| market_type | MarketType | Yes | 市场类型 |
| price_tick_size | Decimal | No | 最小价格变动 |
| quantity_step_size | Decimal | No | 最小数量变动 |
| min_quantity | Decimal | No | 最小交易数量 |
| min_notional | Decimal | No | 最小交易金额 |
| active | bool | No | 是否处于交易状态 |
| updated_ts_ms | int | Yes | 元数据更新时间 |

Instrument ID 格式：

`{exchange_id}:{market_type}:{canonical_symbol}`

例如：

`binance:SPOT:ETH/USDT`

交易所市场配置可能发生变化，应保留验证时间。

不得仅根据交易对名称判断不同平台中的资产完全相同。

## 7. Ticker

用于表示交易所的市场行情摘要。

| 字段 | 类型 | 必须 | 说明 |
|---|---|---|---|
| bid | Decimal | No | 当前最高买入报价 |
| bid_size | Decimal | No | 买一数量 |
| ask | Decimal | No | 当前最低卖出报价 |
| ask_size | Decimal | No | 卖一数量 |
| last | Decimal | No | 最近成交价格 |
| open_24h | Decimal | No | 24 小时开盘价 |
| high_24h | Decimal | No | 24 小时最高价 |
| low_24h | Decimal | No | 24 小时最低价 |
| base_volume_24h | Decimal | No | 基础资产成交量 |
| quote_volume_24h | Decimal | No | 计价资产成交金额 |

示例 payload：

```json
{
  "bid": "1665.10",
  "bid_size": "2.50",
  "ask": "1665.20",
  "ask_size": "1.80",
  "last": "1665.15",
  "open_24h": "1650.00",
  "high_24h": "1680.00",
  "low_24h": "1640.00",
  "base_volume_24h": "25000.00",
  "quote_volume_24h": null
}
```

以上为 MOCK 示例，不代表实际市场行情。

### 校验规则

- 已提供的价格必须大于 0。
- 数量不得为负数。
- 正常情况下 bid 不得大于 ask。
- 用于立即成交分析时，必须存在对应方向的有效报价。
- 用于订单簿深度分析时，必须存在对应数量。
- 不同交易所的 24 小时统计窗口必须经过确认后才能直接比较。

## 8. OrderBook

表示交易所当前买卖挂单。

### 8.1 PriceLevel

每个价格档位包含：

| 字段 | 类型 | 说明 |
|---|---|---|
| price | Decimal | 价格 |
| quantity | Decimal | 挂单数量 |

### 8.2 OrderBookSnapshot

| 字段 | 类型 | 必须 | 说明 |
|---|---|---|---|
| bids | list[PriceLevel] | Yes | 买方挂单 |
| asks | list[PriceLevel] | Yes | 卖方挂单 |
| depth | int | Yes | 请求或维护的最大深度 |
| sequence_id | str | No | 交易所序列标识 |
| checksum | str | No | 校验值 |
| synchronized | bool | Yes | 是否完成同步 |

示例 payload：

```json
{
  "bids": [
    {"price": "1665.10", "quantity": "2.50"},
    {"price": "1665.00", "quantity": "4.20"}
  ],
  "asks": [
    {"price": "1665.20", "quantity": "1.80"},
    {"price": "1665.30", "quantity": "3.60"}
  ],
  "depth": 2,
  "sequence_id": "123456",
  "checksum": null,
  "synchronized": true
}
```

以上为 MOCK 示例。

### 8.3 OrderBookDelta

用于表示 WebSocket 订单簿增量事件。

| 字段 | 类型 | 必须 |
|---|---|---|
| bid_updates | list[PriceLevel] | Yes |
| ask_updates | list[PriceLevel] | Yes |
| first_sequence_id | str | No |
| last_sequence_id | str | No |
| previous_sequence_id | str | No |
| checksum | str | No |

增量事件中 quantity 为 0 时，通常表示删除对应价格档位。

具体语义必须以交易所官方协议为准。

### 8.4 校验规则

- Bids 按价格降序排列。
- Asks 按价格升序排列。
- 完整快照中相同价格不得重复。
- 完整快照中数量必须大于 0。
- 买卖两侧均存在时，最高 Bid 通常不得高于最低 Ask。
- 未同步的订单簿不得用于交易分析。
- 检测到增量数据缺口时必须停止使用当前订单簿，并重新同步。
- 实际返回深度不足时不得虚构剩余档位。

### 8.5 实现状态

Phase 1 Task 1.5-A 已实现 `PriceLevel`、`OrderBookSnapshot`、`OrderBookDelta`
Canonical Model，以及基于快照和绝对数量增量的内存 Market State。OKX `books` Adapter
已通过 15 秒真实公开接口验证。Market State 会拒绝
未同步、序列缺口、过期、未来接收、数据源断开、无双边报价及质量状态非 VALID 的订单簿。

当前实现不表示各交易所增量协议已经统一接入。交易所 Adapter 仍须按官方协议完成初始快照、
Sequence、Checksum 及重同步，再生成 Canonical Event。

## 9. Trade

表示市场中已经发生的实际成交。

| 字段 | 类型 | 必须 | 说明 |
|---|---|---|---|
| trade_id | str | No | 交易所成交标识 |
| price | Decimal | Yes | 成交价格 |
| quantity | Decimal | Yes | 基础资产成交数量 |
| quote_amount | Decimal | No | 计价资产成交金额 |
| side | TradeSide | Yes | 主动成交方向 |

注意：

- 市场成交记录不等于用户模拟交易记录。
- trade_id 的唯一性范围由交易所协议决定。
- 交易所未提供 trade_id 时，不得伪造交易所标识。
- 推导出的 quote_amount 必须注明计算来源。

Canonical `Trade` Model 已实现，并保留 `UNKNOWN` 主动成交方向；交易所未提供或无法可靠
推导方向时不得猜测。真实 Trade Adapter 及持续采集链路尚未实现。

## 10. Candle

OHLCV K 线数据。

| 字段 | 类型 | 必须 | 说明 |
|---|---|---|---|
| interval | str | Yes | 时间周期 |
| open_ts_ms | int | Yes | 周期开始时间 |
| close_ts_ms | int | Yes | 周期结束边界 |
| open | Decimal | Yes | 开盘价 |
| high | Decimal | Yes | 最高价 |
| low | Decimal | Yes | 最低价 |
| close | Decimal | Yes | 收盘价 |
| base_volume | Decimal | No | 基础资产成交量 |
| quote_volume | Decimal | No | 计价资产成交金额 |
| trade_count | int | No | 成交次数 |
| is_closed | bool | No | K 线是否已结束 |

Phase 0 候选周期：

- 1m
- 5m
- 15m
- 1h
- 4h
- 1d

统一使用左闭右开的时间区间：

`[open_ts_ms, close_ts_ms)`

校验规则：

- 所有价格必须大于 0。
- high 不得低于 open、close 或 low。
- low 不得高于 open、close 或 high。
- 成交量不得为负数。
- 周期时间必须正确。
- 未结束 K 线允许更新。
- 已结束 K 线发生修订时应保留修订记录。
- 回测不得提前使用尚未结束 K 线的最终数据。

## 11. FeeSchedule

用于记录交易手续费配置。

| 字段 | 类型 | 必须 |
|---|---|---|
| fee_schedule_id | str | Yes |
| exchange_id | str | Yes |
| market_type | MarketType | Yes |
| instrument_id | str | No |
| maker_rate | Decimal | No |
| taker_rate | Decimal | No |
| account_tier | str | No |
| source_url | str | No |
| effective_ts_ms | int | No |
| verified_ts_ms | int | No |
| is_assumption | bool | Yes |

手续费率统一使用小数比例。

例如：

`0.001` 表示 `0.1%`。

Phase 0 不查询个人交易账户的实际手续费等级。

无法确认的手续费必须明确标记为假设。

不得将未知手续费默认设置为 0。

## 12. SpreadObservation

记录跨交易所价差观测结果。

此模型不代表已执行交易。

### 12.1 报价信息

| 字段 | 类型 | 必须 |
|---|---|---|
| observation_id | str | Yes |
| canonical_symbol | str | Yes |
| buy_exchange_id | str | Yes |
| sell_exchange_id | str | Yes |
| buy_event_id | str | Yes |
| sell_event_id | str | Yes |
| buy_ask | Decimal | Yes |
| sell_bid | Decimal | Yes |
| buy_available_quantity | Decimal | No |
| sell_available_quantity | Decimal | No |
| observed_ts_ms | int | Yes |
| quote_time_diff_ms | int | No |
| buy_quote_age_ms | int | Yes |
| sell_quote_age_ms | int | Yes |
| timestamp_basis | str | Yes |

### 12.2 分析结果

| 字段 | 类型 | 必须 |
|---|---|---|
| gross_spread | Decimal | Yes |
| gross_spread_rate | Decimal | Yes |
| target_quantity | Decimal | No |
| estimated_executable_quantity | Decimal | No |
| estimated_buy_notional | Decimal | No |
| estimated_sell_notional | Decimal | No |
| estimated_buy_fee | Decimal | No |
| estimated_sell_fee | Decimal | No |
| estimated_execution_cost | Decimal | No |
| estimated_rebalance_cost | Decimal | No |
| estimated_net_profit | Decimal | No |
| estimated_net_return_rate | Decimal | No |
| cost_model_id | str | No |
| quality_status | DataQualityStatus | Yes |

### 12.3 计算规则

毛价差：

`gross_spread = sell_bid - buy_ask`

毛价差率：

`gross_spread_rate = gross_spread / buy_ask`

仅使用买一卖一时，可观察数量上限：

`quantity = min(buy_ask_size, sell_bid_size)`

该数量仅代表观测时的报价数量，不保证真实成交。

基于订单簿深度估算买入及卖出金额后：

`estimated_net_profit = sell_notional - buy_notional - buy_fee - sell_fee - execution_cost - rebalance_cost`

`estimated_net_return_rate = estimated_net_profit / buy_notional`

该收益率以买入金额为分母，不代表完整套利账户的资金收益率。

计算规则：

- 买入与卖出使用相同基础资产数量。
- 比较相同交易品种及计价货币。
- 保留负价差及负收益观测。
- 不得仅保存看起来能够盈利的结果。
- 不得重复扣除已经包含在成交均价中的滑点。
- 成本数据缺失时，净收益结果保留为 null。
- 假设成本与已验证成本必须能够区分。
- 不得将估算可成交数量描述为实际成交数量。

## 13. DataQualityEvent

用于记录数据质量异常。

| 字段 | 类型 | 必须 |
|---|---|---|
| event_id | str | Yes |
| exchange_id | str | Yes |
| instrument_id | str | No |
| related_event_id | str | No |
| event_type | str | Yes |
| severity | str | Yes |
| detected_ts_ms | int | Yes |
| message | str | Yes |
| details | object | No |
| resolved_ts_ms | int | No |

异常类型初始定义：

- CONNECTION_FAILED
- API_TIMEOUT
- RATE_LIMITED
- INVALID_PAYLOAD
- MISSING_FIELD
- INVALID_PRICE
- INVALID_QUANTITY
- CROSSED_ORDER_BOOK
- STALE_DATA
- DUPLICATE_EVENT
- OUT_OF_ORDER_EVENT
- SEQUENCE_GAP
- CHECKSUM_FAILED
- CLOCK_SKEW
- STORAGE_LIMIT_REACHED
- DATA_DROPPED

Severity：

- INFO
- WARNING
- ERROR
- CRITICAL

异常检测阈值应通过配置管理。

## 14. APIProbeResult

记录真实 API 验证结果。

| 字段 | 类型 | 必须 |
|---|---|---|
| probe_id | str | Yes |
| exchange_id | str | Yes |
| endpoint_type | str | Yes |
| endpoint | str | No |
| transport | TransportType | Yes |
| started_ts_ms | int | Yes |
| completed_ts_ms | int | No |
| duration_ms | int | No |
| success | bool | Yes |
| status_code | int | No |
| error_type | str | No |
| error_message | str | No |
| response_ref | str | No |

必须记录真实请求结果。

接口验证失败仍然是有效的研究结果，不得删除失败记录。

## 15. RawDataRecord

原始数据记录用于问题定位及标准化验证。

| 字段 | 类型 | 必须 |
|---|---|---|
| raw_id | str | Yes |
| exchange_id | str | Yes |
| transport | TransportType | Yes |
| endpoint_or_channel | str | Yes |
| received_ts_ms | int | Yes |
| payload_format | str | Yes |
| payload | object 或 str | Yes |

应尽可能保留 API 原始十进制数值表达。

原始数据保存应遵守数据源许可及本地存储容量限制。

## 16. 数据存储规范

Phase 0 使用 JSONL 和 CSV，不引入数据库。

建议目录：

```text
data/
├── raw/
├── normalized/
├── quality/
├── probes/
├── experiments/
└── reports/
```

文件应按日期、数据类型及数据源进行合理划分。

示例：

```text
data/normalized/2026-11-25/binance/ETH_USDT/ticker.jsonl
```

日期分区统一使用 UTC。

原始数据与标准化数据应通过 raw_ref 或实验配置建立可追溯关系。

连续采集必须配置：

- 最大文件大小。
- 文件轮换机制。
- 总存储容量限制。
- 数据保留周期。
- 安全停止条件。

## 17. 数据时效性规范

行情有效性不能仅根据最后一次收到消息的时间判断。

系统应综合考虑：

- 本地接收时间。
- 交易所事件时间。
- WebSocket 连接状态。
- 消息序列状态。
- 订单簿同步状态。
- 数据源时钟偏移。

Phase 0 初始实验参数：

| 参数 | 初始值 |
|---|---|
| max_quote_age_ms | 2000 |
| max_quote_time_diff_ms | 1000 |
| rest_timeout_ms | 10000 |
| initial_order_book_depth | 20 |

以上均为待验证的实验假设，不代表最终生产参数。

交易所不支持所请求深度时，应选择支持的深度并记录实际配置。

## 18. Python 模块结构

建议按以下方式组织：

```text
src/crypto_lab/models/
├── __init__.py
├── enums.py
├── common.py
├── exchange.py
├── instrument.py
├── ticker.py
├── order_book.py
├── trade.py
├── candle.py
├── fee.py
├── spread.py
├── quality.py
├── probe.py
└── raw.py
```

Phase 0 不要求一次性实现全部模型。

应根据当前任务需要逐步实现。

禁止创建没有实际用途的空模块。

## 19. 模型测试要求

至少覆盖：

- Decimal 序列化及反序列化。
- 缺失字段处理。
- 非法价格及数量。
- 时间戳格式。
- 交易对标准化。
- 买卖报价校验。
- 订单簿排序。
- 零数量增量更新。
- K 线合法性。
- 手续费率格式。
- 价差计算。
- 成本缺失处理。
- 行情过期检测。
- 原始数据关联。
- Schema Version。

所有测试应使用明确标记的 MOCK 或真实采集样本。

## 20. 当前设计限制

本 Schema 为 Phase 0 初始设计。

尚未针对所有候选交易所的实际 API 响应完成验证。

以下内容需要在接入过程中进一步确认：

- 各交易所时间戳语义。
- 订单簿序列及校验机制。
- 数量与价格精度。
- 原始交易对映射。
- 交易手续费配置。
- 数据保留容量。
- 数据许可。
- 行情有效性阈值。

数据模型允许根据实际验证结果调整，但所有重要变更必须记录原因，并同步更新文档及测试。

