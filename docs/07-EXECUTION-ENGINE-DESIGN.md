# Crypto Lab — 交易引擎专项设计

## 0. 文档信息

| 属性 | 内容 |
|---|---|
| 文档版本 | V0.4 |
| 对应任务 | Phase 1 Task 1.5～1.8 |
| 状态 | Active / Task 1.5～1.8 已实现 |
| 设计范围 | Python 领域层 |

本文档同时记录设计与实施状态；只有明确标记“已完成”的能力才视为已经实现。核心原则是：AI 负责开发和解释，程序负责采集和计算。

## 1. 现状审查

### 1.1 实际审查范围

- 规范与路线：`AGENTS.md`、`docs/AGENT.md`、`docs/00-PROJECT-OVERVIEW.md`、`docs/02-MARKET-DATA-SCHEMA.md`、`docs/06-PHASE-1-PLAN.md`。
- 领域代码：`trading/models.py`、`ledger.py`、`orders.py`、`order_service.py`、`execution.py`、`portfolio.py`。
- 行情代码：`models/common.py`、`models/ticker.py`、`market_data/normalizers.py`、`market_data/ordering.py`、`scripts/probe_rest.py`、`scripts/probe_websocket.py`。
- 测试与提交：Task 1.1～1.4 的交易测试，以及提交 `ce380a5`、`e535fec`、`352e33e`、`b0840e4`。

### 1.2 当前能力

| 能力 | 当前实现 | 结论 |
|---|---|---|
| 余额及冻结 | Account Ledger 批量校验后原子追加流水 | 可复用 |
| 订单 | 市价/限价、部分成交、取消、冻结/释放 | 可扩展 |
| 成交 | 调用方传入单一价格和数量；可多次部分成交 | 需增加撮合计划 |
| 限价保护 | 买不高于限价、卖不低于限价 | 保留 |
| 手续费 | 显式费率，统一计价资产收费 | 需增加 Maker/Taker 角色 |
| 持仓 | 移动平均成本，可应用多条部分成交 | 可复用 |
| 估值 | 有效 Ticker 的 Bid | 保留 |
| 行情模型 | 已实现 Ticker；文档定义 OrderBook/Trade | 实现落后于文档 |
| WebSocket | 交易所协议探测及部分序列检查 | 不是可复用 Market State |

### 1.3 文档与代码差异

1. Market Data Schema 已定义 `OrderBookSnapshot`、`OrderBookDelta`、`Trade`，但 Python Canonical Model、Normalizer 及统一 Market State 尚未实现。
2. Phase 0 脚本能探测 REST 深度和 WebSocket 订单簿消息，但不提供交易引擎可直接消费的规范化、持续同步订单簿；真实 Trade 事件也未形成统一采集链路。
3. `ExecutionSimulator` 可通过多次调用形成多个部分成交并累计平均价，但不能一次接收多档 `FillPlan`，也不能保证多档成交、流动性扣减与结算共同原子提交。
4. 当前 `execute_from_ticker` 只校验品种及质量状态，没有订单簿同步、序列、过期、交易所及市场类型的完整有效性门禁。
5. Portfolio 能正确应用多个部分成交并可由成交历史重建，但它在当前 Execution Simulator 原子边界之外。
6. Order 状态没有明确的待执行状态、挂单入场时间及 GTC/TIF；`OPEN` 同时承担过多语义。
7. 市价买单按提交参考价和预计费率冻结资金，延迟后价格上涨可能使结算失败，尚未定义“按预算部分成交”或“整单拒绝”的统一规则。

上述差异均不得仅靠文档声称已经完成，必须在相应 Task 中实现并测试。

## Part A — 订单簿驱动的模拟撮合

### A.1 设计目标

根据执行时有效真实订单簿自动确定可成交数量、逐档价格及数量、总金额、VWAP、剩余数量、滑点、手续费及模拟成交状态。前端只提交订单意图，不得指定成交价格、成交数量或伪造成交结果。

建议增加不可变值对象：

- `FillLeg(price, quantity, quote_amount, book_level_key)`
- `MatchPlan(order_id, book_event_id, book_version, fills, remaining_quantity, status)`
- `SlippageMetrics(submission_reference_price, execution_reference_price, book_slippage_amount, price_drift, total_slippage_amount, slippage_rate)`

`MatchPlan` 是撮合计算结果，不是已经结算的成交；只有原子提交成功后才生成 Fill History。

### A.2 市价单撮合规则

- 市价买单按 Ask 从低到高逐档撮合。
- 市价卖单按 Bid 从高到低逐档撮合。
- 达到目标数量或有效深度耗尽时停止。
- 深度不足允许部分成交；剩余部分默认取消并释放相应冻结资金。
- 零流动性不得伪造档位，结果为未成交并释放冻结资金。
- 每档价格和数量必须满足交易所价格精度、数量精度、最小数量及最小名义金额约束。

撮合器只读取 `SimulatedLiquidityView`，不得修改原始市场事件。

### A.3 VWAP 计算

```text
total_notional = sum(fill_price × fill_quantity)
total_filled_quantity = sum(fill_quantity)
vwap = total_notional / total_filled_quantity
```

所有输入、中间值及结果使用 `Decimal`。零成交数量时 `vwap = null`，不得执行除法。

### A.4 滑点计算

订单簿滑点反映同一执行时点的深度成本：

```text
BUY:  book_slippage_amount = (vwap - execution_best_ask) × filled_quantity
SELL: book_slippage_amount = (execution_best_bid - vwap) × filled_quantity
```

执行价格漂移反映提交至执行之间的最优可执行报价变化：

```text
BUY:  price_drift = execution_best_ask - submission_best_ask
SELL: price_drift = submission_best_bid - execution_best_bid
```

总滑点以提交时可执行参考报价为基准：

```text
BUY:  total_slippage_amount = (vwap - submission_best_ask) × filled_quantity
SELL: total_slippage_amount = (submission_best_bid - vwap) × filled_quantity

reference_notional = submission_reference_price × filled_quantity
slippage_rate = total_slippage_amount / reference_notional
```

统一约定：正值表示不利，负值表示有利；手续费单独计算；VWAP 已包含的价格影响不得再次扣款。缺少提交或执行参考报价时，对应指标为 `null`。零成交时全部基于成交的滑点指标为 `null`。

### A.5 模拟流动性消耗

定义三层状态：

1. `ExternalOrderBook`：只读的真实行情投影。
2. `SimulatedLiquidityView`：按模拟环境隔离的可用流动性。
3. `LiquidityConsumption`：按环境、行情版本、档位及订单记录已消耗数量。

默认规则：

- 同一 `simulation_environment_id` 的账户和订单共享模拟流动性。
- 独立对照实验使用不同环境，获得独立视图。
- 同一行情版本内，撮合成功提交后才扣减流动性；失败必须回滚。
- 对连续增量的绝对数量更新，`residual_new = max(0, residual_old + external_new - external_old)`；市场数量减少会压低剩余量，市场新增数量才增加剩余量，不能把本地已消耗数量无条件补回。
- 序列缺口、断线或无连续谱系的新快照使旧视图失效。完成重新同步后建立新 `book_version`；旧版本不得继续成交。
- 全量重同步代表一个新的可观察市场状态，不等于模拟订单真实冲击已经消失。该近似及重同步策略必须进入实验元数据。

公开市场数据不能提供模拟订单对真实市场的反事实冲击，也不能精确还原隐藏流动性、其他参与者撤单及排队位置；结果只能视为受约束的模拟估计。

### A.6 订单簿有效性校验

出现以下任一情况禁止撮合：订单簿不存在或过期、质量状态非 VALID、未同步、序列缺口、交易所/品种/市场类型不匹配、报价非正或交叉异常、必要时间缺失、数据源断开且超过有效期。

时效阈值从配置读取。Market State 应保留 `event_id`、交易所序列、接收时间、交易所事件时间（若有）、同步状态、质量状态及断线状态。执行时只允许读取 `received_ts_ms <= execution_decision_ts_ms` 的事件。

### A.7 Task 1.5 实施方案

1. **1.5-A Canonical Market State（已完成）**：已实现订单簿/Trade Canonical Model、绝对数量增量 Market State、序列和时效门禁；OKX `books` Adapter 已按官方 `prevSeqId/seqId` 协议完成并通过 15 秒真实接口验证。其他交易所 Adapter 仍须逐一按官方协议实现，不得复用 OKX 假设。
2. **1.5-B Pure Matcher（已完成）**：已实现无副作用的逐档撮合、VWAP 和滑点计算；滑点金额按成交档位精确求和，避免循环小数 VWAP 反乘产生 Decimal context 尾差。
3. **1.5-C Liquidity View（已完成）**：已实现按模拟环境隔离的共享剩余流动性、连续绝对数量更新、原子消费及重复消费保护；同步世代变化必须显式重置，不会自动恢复已消耗流动性。
4. **1.5-D Settlement Adapter（已完成）**：已将 `MatchPlan` 转换为多档成交记录及单次结算批次；计划会先验证资金、订单及流动性条件，失败时不消费流动性，深度不足的市价单结算实际成交后取消剩余并释放冻结资金。
5. **1.5-E Regression & Acceptance（已完成）**：已通过 EX-001～EX-008、Market State 集成门禁及 Task 1.1～1.4 回归测试；执行路径要求显式提供带版本标识的交易所价格/数量步长及已知最小限制，未提供的限制保留为 `null`，不做零值假设。OKX Adapter 已完成 15 秒真实公开接口验证。

最小变更方向：保留现有 `ExecutionRecord` 及结算公式；增加 `FillLeg/MatchPlan` 和批量执行入口。现有调用方传价的 `execute` 仅保留为内部兼容或测试辅助入口，不对前端开放。

### A.8 Task 1.5 验收标准

- [x] 支持市价买入和卖出的多档撮合。
- [x] 正确计算 VWAP、订单簿滑点、价格漂移及总滑点。
- [x] 深度不足时部分成交，无流动性时不成交。
- [x] 不重复消耗同一模拟流动性。
- [x] 无效、过期、未同步或序列缺口订单簿不得成交。
- [x] 校验交易所精度及最小交易限制。
- [x] 复用已有成交结算，手续费和滑点不重复计算。
- [x] 所有相关测试通过。

## Part B — 限价单实时自动撮合

### B.1 设计目标与限价规则

系统根据实时订单簿及真实 Trade 事件决定限价单成交，不依赖人工传入结果：

```text
BUY:  execution_price <= limit_price
SELL: execution_price >= limit_price
```

任何模式均不得突破限价。

### B.2 Marketable Limit Order

立即可成交的限价单按当前订单簿撮合：买单只消耗不高于限价的 Ask，卖单只消耗不低于限价的 Bid。立即成交部分使用 Taker Fee；GTC 剩余部分进入挂单状态。

实现状态：已完成。立即撮合复用 Task 1.5 的版本化模拟订单簿流动性；成交记录标记为 Taker，部分成交后订单保持 `PARTIALLY_FILLED` 并继续冻结剩余资金，零成交订单以 `OPEN` 进入挂单状态。

### B.3 Resting Limit Order

未立即成交部分由有效 `Trade` 触发被动撮合；订单簿仅用于入场时的立即撮合，不以 Last Price、K 线或报价触碰直接完成被动订单。Phase 1 只实现 GTC；IOC/FOK 不实现。订单进入市场记录确定性 `market_entry_ts_ms` 和本地序列。

### B.4 成交模型

- `TOUCH_FILL`：报价满足限价时按模拟可用深度尝试成交，仅用于理想化实验，不代表真实排队。
- `TRADE_THROUGH`：Phase 1 默认。挂买单只接受价格严格低于限价且主动方向为 SELL 的真实成交；挂卖单只接受价格严格高于限价且主动方向为 BUY 的真实成交。等于限价、UNKNOWN 方向、入场前、无可靠交易所时间、无效、过期、重复、乱序或错误品种事件均不成交。
- `QUEUE_SIMULATION`：未来增强，Phase 1 不实现。

TRADE_THROUGH 按真实成交事件的剩余可分配数量做部分分配，不能因价格穿透就完成全单。同一模拟环境中，一个 Trade 事件的数量按本地订单优先级共享，不能给多个订单重复完整分配。被动成交固定使用订单限价，Phase 1 不提供价格改善。

实现状态：已完成。OKX `trades` 公开频道中的 `side` 按官方定义解释为 Taker Side；聚合消息的 `sz` 作为本事件唯一可分配数量，`tradeId` 用于源级去重。15 秒真实接口验证共归一化 105 条成交，Trade ID 无重复，方向均可识别。

### B.5 本地优先级与幂等

同一环境采用价格优先、相同价格按 `market_entry_ts_ms`、相同时间按确定性订单序列排序。这只是本地模拟订单优先级，不代表真实交易所排队位置。

同一环境内按交易所、品种和交易所 `tradeId` 去重；缺少 `tradeId` 时退化为 `event_id`。执行标识由模拟环境、Trade 身份及订单身份确定性生成。事件处理期间维护共享剩余数量，结算成功后才扣减；结算失败保留进度和剩余数量供安全重试。

### B.6 手续费及冻结

- 立即吃单使用 Taker Fee，挂单被动成交使用 Maker Fee。
- 费率必须来自显式版本化配置；未知费率禁止成交，不能默认为零。
- 继续遵循当前计价资产收费规则，除非项目负责人确认变更。
- 限价买单冻结限价名义金额及显式费用缓冲；价格改善后的多余资金保留在冻结余额，直至订单完成或取消时释放。
- 部分成交后只保留剩余订单所需冻结；取消释放全部剩余冻结。

### B.6.1 已确认实现约束

项目负责人已确认 ADR-0002：默认 GTC 和 TRADE_THROUGH，被动成交使用订单限价且不提供价格改善；限价买单按 Maker/Taker 中较高费率冻结费用缓冲。Order Model 已增加提交时间、可空市场入场时间及确定性本地序列，时间来源可在测试中替换，不包含 Task 1.7 调度逻辑。

### B.7 Task 1.6 验收标准

- [x] 支持立即成交限价单、持续挂单、部分成交及取消。
- [x] 行情事件自动触发撮合且不突破限价。
- [x] 正确处理剩余冻结资金和 Maker/Taker Fee。
- [x] 同一 Trade 事件不被重复处理或超额分配。
- [x] 默认模型不过度乐观，已取消订单不得成交。
- [x] 无效、过期、未来、乱序、错误品种及入场前事件不得成交。
- [x] 真实 Trade Adapter 完成短时验证。
- [x] Task 1.1～1.5 回归及 Task 1.6 测试全部通过。

## Part C — 模拟执行延迟

### C.1 参数与限制

| 配置 | 延迟 |
|---|---:|
| IDEAL | 0ms |
| FAST | 50ms |
| NORMAL | 100ms |
| MEDIUM | 250ms |
| SLOW | 500ms |
| HIGH | 1000ms |
| CUSTOM | 自定义 |

默认暂定 100ms。这些是实验参数，不代表真实交易所延迟。延迟期间市场可变化，禁止用提交时旧报价直接完成延迟后的撮合。

### C.2 Clock 与 Scheduler

定义 `Clock.now_utc_ms()` 和单调耗时接口，候选实现为 `SystemClock`、测试用 `ManualClock`、未来 `ReplayClock`。核心领域不得直接调用 `sleep`。

`ExecutionScheduler` 接收已校验并冻结资金的订单，记录提交和计划执行时间，管理待执行队列，在 Clock 到期后读取当时最新有效 Market State，再交给市价或限价 Matcher。调度器还负责取消、异常终止及防重复出队。

实现状态：已完成。`SystemClock` 提供 UTC 事件时间及单调耗时，`ManualClock` 用于无真实等待的确定性测试。调度器按 `(scheduled_execution_ts_ms, order_sequence)` 排序，0ms 订单也必须经过相同调度流程；取消和到期执行以串行调用顺序决定胜者。

### C.3 生命周期与时间字段

```text
Submit → Validate → Reserve Funds → Pending Execution
       → Execution Time Reached → Validate Latest Market Data
       → Market/Limit Matching → Atomic Settlement
       → Update Order & Portfolio
```

已实现：`submitted_ts_ms`、`scheduled_execution_ts_ms`、`market_entry_ts_ms`、`executed_ts_ms`、`configured_latency_ms`、`actual_simulated_delay_ms`、`scheduler_lag_ms`、`submission_quote_event_id`、`execution_quote_event_id`。其中配置延迟、实际提交至执行时间及调度器超期滞后分别记录，不解释为真实网络延迟。

项目负责人已确认并实现 `PENDING_EXECUTION`：完成校验和冻结但尚未进入模拟市场；到期后 `OPEN` 只表示已进入市场的活动订单或 GTC 挂单。

### C.4 资金、取消及未来数据

- 提交后立即冻结，延迟期间不可复用。
- 延迟期间允许取消并释放资金；取消胜出后调度器必须幂等跳过。
- 延迟市价买单必须显式提供 `max_quote_budget`；执行时逐档包含 Taker Fee 计算可成交量，并按 quantity increment 向下调整。
- 价格上涨时只在冻结预算内成交；不足以完成全单则保留实际 Fill、取消剩余并释放资金，不使用其他可用余额追加预算。
- 市价卖单受冻结基础资产和 Bid 深度限制，部分成交后同样取消剩余。
- GTC 限价单到期后先做 Taker 撮合，剩余进入活动挂单并继续使用 TRADE_THROUGH，而非套用市价单取消规则。
- Phase 1 不模拟取消请求自身的网络延迟，此限制写入实验元数据。
- 选择行情的条件是系统接收时间不晚于决策时间；不得使用之后收到的行情，即使其交易所事件时间更早。

无订单簿、过期、失效、断线或未来行情时，尚未入场订单以 `MARKET_DATA_UNAVAILABLE` 拒绝并释放冻结资金，不进行无期限自动重试。撮合或结算失败时不消耗模拟流动性。

### C.5 Task 1.7 验收标准

- [x] 支持配置延迟，预定时间前不得成交。
- [x] 执行时使用最新有效但非未来行情。
- [x] 延迟期间资金冻结且支持取消。
- [x] 资金不足按确认策略处理且不透支。
- [x] 市价买单执行符合显式预算、手续费、步长及最小限制。
- [x] 市价卖单深度不足时部分成交并释放剩余资产。
- [x] GTC 限价单未成交部分继续挂单。
- [x] ManualClock 测试无真实等待。
- [x] 记录提交及执行参考行情，正确计算价格漂移和总滑点。
- [x] 撮合失败不错误消耗模拟流动性。
- [x] Task 1.1～1.6 回归及 Task 1.7 测试全部通过。

## Part D — 交易引擎集成与一致性

### D.1 逻辑架构

```text
Canonical Market Data → Market State → Order/Risk Validation
                      → Execution Scheduler → Market/Limit Matcher
                      → Execution Unit of Work → Account Ledger
                                               → Fill History
                                               → Order Model
                                               → Portfolio Projection
                                               → Liquidity Consumption
```

这是职责划分，不要求每项成为独立 Package。优先在现有 `trading` 与 `market_data` 结构内做最小必要扩展。

### D.2 权威来源

- Account Ledger：余额权威来源。
- Order Model：订单生命周期权威来源。
- Fill History：成交事实权威来源。
- Portfolio：可由 Fill History 重建的投影。
- Market State：当前有效行情投影。
- Execution Scheduler：待执行集合权威来源。
- Liquidity Consumption：指定模拟环境内剩余流动性的权威记录。

禁止再建立另一套可独立修改的余额或持仓。

### D.3 原子一致性与恢复

一次提交边界包含订单状态、全部 Fill、手续费、资金流水、冻结变化、流动性消耗及持仓投影。领域层先使用内存 Unit of Work：验证所有预条件，计算不可变候选变更，全部成功后一次提交；任何失败不暴露部分状态。

Portfolio 属可重建投影。若当前阶段不能与事实记录同一原子提交，则先原子提交 Ledger、Order、Fill 和 Liquidity，再用 Fill History 重建或重放 Portfolio，并明确记录投影失败。Task 1.9 再映射至数据库事务及 Outbox/投影恢复机制。

实现状态：已完成进程内 Snapshot/Restore Unit of Work。事务开始时只快照实际参与者的可变业务状态，不深拷贝完整原始行情；Market State 的当前不可变 View 映射、ManualClock、确定性 ID 计数、Ledger、Order、Fill History、Liquidity、Scheduler、事件登记和 Portfolio 均可参与事务。操作及提交钩子全部成功后才返回结果，任何异常按参与者逆序恢复并继续向调用方抛出，不以捕获异常后继续执行掩盖部分提交。

Portfolio 在 Fill 发布阶段自动增量更新；失败由同一 Unit of Work 回滚。读取结果可由完整 Fill History 重建，增量与重建结果已验证一致。当前保证仅限进程内；崩溃恢复及数据库事务属于 Task 1.9。

### D.4 幂等与事件顺序

需要唯一键或处理记录保护：`order_id` 执行轮次、`execution_id`、Ledger `entry_id`、市场 `event_id`、流动性消费 ID。已取消/完成订单不得重新进入执行。

Phase 1 使用单模拟环境串行事件处理器，按以下确定性顺序：

1. 以接收时间、数据源序列、内部到达序列排序市场事件。
2. 同一逻辑时刻先应用已经到达的市场事件，再执行到期订单。
3. 取消与执行按进入串行队列的顺序决定胜者。
4. 同一账户和同一流动性视图的竞争订单按调度序列处理。
5. 重复事件忽略；乱序或序列缺口使相关 Market State 失效并触发重同步。

该模型便于测试与历史回放；Phase 1 不引入分布式并发撮合。

实现状态：已完成 `SerialEventProcessor`。同一时间戳先处理 Market Data，其余订单提交、取消、到期执行、Trade 与被动撮合按确定性到达序列处理，因此取消与成交竞争由进入串行队列的先后决定。事件处理成功后才写入去重登记；失败会恢复业务状态、事件队列和去重状态并允许使用相同业务 ID 安全重试。

正式实验使用带模拟环境命名空间的 `DeterministicIdGenerator`。Order、Execution 及 Ledger Entry ID 在相同初始状态和事件序列下可复现；多档 Fill 使用独立 Execution ID，Entry ID 由账户、Execution、资产及流水原因稳定派生。外部真实行情的源 ID 仍以交易所数据为准，不为追求确定性而改写。

### D.5 Task 1.8 验收标准

- [x] 完整市价买卖、限价挂单、部分成交及取消流程。
- [x] 延迟期间价格变化及取消行为正确。
- [x] 订单簿失效后拒绝成交，多订单正确竞争流动性。
- [x] 余额不足、手续费、流水和持仓计算正确。
- [x] 流水可重建余额，成交可重建持仓。
- [x] 不产生负余额、超额卖出或重复成交。
- [x] Ledger、Order、Fill、Liquidity、Portfolio、Scheduler 及事件登记失败可回滚。
- [x] 结果及核心业务 ID 可确定性复现。
- [x] Task 1.1～1.7 回归测试全部通过。

## Part E — 测试设计

### E.1 原则

核心金融计算全部使用固定 MOCK 行情做单元测试，不依赖交易所网络。真实 API 验证与领域测试分离。延迟测试使用 ManualClock，不做真实等待。每个测试必须断言业务结果及失败后的无副作用状态。

### E.2 测试矩阵

| Test ID | 测试内容 | Task |
|---|---|---|
| EX-001 | 单档市价买入 | 1.5 |
| EX-002 | 多档市价买入 | 1.5 |
| EX-003 | 多档市价卖出 | 1.5 |
| EX-004 | 订单簿深度不足 | 1.5 |
| EX-005 | 订单簿不存在 | 1.5 |
| EX-006 | 订单簿过期 | 1.5 |
| EX-007 | VWAP 及滑点计算 | 1.5 |
| EX-008 | 重复流动性消耗 | 1.5 |
| EX-009 | 立即成交限价单 | 1.6 |
| EX-010 | 非立即成交限价单 | 1.6 |
| EX-011 | 价格触及但不保证成交 | 1.6 |
| EX-012 | 价格穿透后的保守成交 | 1.6 |
| EX-013 | 限价单部分成交 | 1.6 |
| EX-014 | 限价单取消 | 1.6 |
| EX-015 | Maker/Taker 手续费 | 1.6 |
| EX-016 | 0ms 执行延迟 | 1.7 |
| EX-017 | 100ms 执行延迟 | 1.7 |
| EX-018 | 延迟期间价格变化 | 1.7 |
| EX-019 | 延迟期间资金不足 | 1.7 |
| EX-020 | 延迟期间取消订单 | 1.7 |
| EX-021 | 重复市场成交事件 | 1.8 |
| EX-022 | 重复订单执行 | 1.8 |
| EX-023 | 结算失败及一致性恢复 | 1.8 |
| EX-024 | 多订单竞争流动性 | 1.8 |
| EX-025 | 交易后余额与持仓重建 | 1.8 |
| EX-026 | 禁止未来行情泄漏 | 1.7/1.8 |

具体测试数量可随实现增加，但不得删除对应风险覆盖。

### E.3 Token Efficiency

- 默认真实接口验证 15 秒，多交易所采集验证 60 秒，稳定性测试不超过 300 秒。
- 长期实验独立运行，不持续轮询，不逐条输出高频行情。
- 原始数据写文件并生成结构化报告；优先分析报告，异常时才读必要样本。
- 短时功能测试与长期稳定性实验分离，短测不能替代长期验收。
- ManualClock 负责延迟测试，禁止为了 50～1000ms 参数做真实等待。

## Part F — Web 应用开发边界

Task 1.5～1.8 保持 Python 领域层开发，不引入 FastAPI、React、PostgreSQL、完整 Docker、自动策略、跨交易所自动套利、AI/LLM API 或真实资金接口。

后续方向：前端 React + TypeScript + Vite + Tailwind CSS，图表 Lightweight Charts，后端 FastAPI，数据库 PostgreSQL + Alembic，实时通信 WebSocket。依赖、Schema、API Contract 和布局在对应 Task 独立设计。

## Part G — 兼容性及影响范围

| 现有模块 | 兼容方式 | 预计影响 |
|---|---|---|
| `AccountLedger` | 保持余额权威与批量原子校验 | 增加 Unit of Work 协调接口 |
| `PaperOrder` | 保留数量、限价和累计字段 | 已增加 GTC、提交/入场时间、费用配置及确定性序列 |
| `OrderService` | 保留冻结/取消规则 | 已接收显式费用配置和可替换时钟；Task 1.7 再增加调度 |
| `ExecutionSimulator` | 保留结算公式和限价保护 | 已支持订单簿 MatchPlan 及被动限价成交原子结算 |
| `ExecutionRecord` | 继续作为 Fill History 基础 | 已增加 Maker/Taker 及市场事件关联字段 |
| `PortfolioEngine` | 保留移动平均成本和重建能力 | 纳入投影恢复或 Unit of Work |
| Ticker | 继续用于估值及提交参考 | 不再作为深度撮合依据 |
| Market Data | 扩展 Canonical OrderBook/Trade | 已实现订单簿状态、有效性门禁及 OKX Trade Adapter |

## Part H — Canonical Schema 评估

已实现 `PriceLevel`、`OrderBookSnapshot`、`OrderBookDelta` 和 `Trade`。兼容扩展仍需明确：

- 内部稳定事件 ID 与交易所原始 ID 的区分。
- `book_version` 或等价的同步世代标识。
- 数据源连接/同步状态及失效原因。
- 事件接收顺序和可选交易所事件时间。
- Trade 主动方向未知时的显式状态，禁止猜测。

这些字段先形成 Schema 变更提案；未确认前不修改已确认金融规则。

## Part I — 待项目负责人确认

1. ~~是否新增 `PENDING_EXECUTION`，并以 `OPEN` 表示进入市场后的活动订单。~~ 已确认并实现。
2. ~~延迟后市价买单预算不足时采用何种策略。~~ 已确认预算内部分成交并取消剩余。
3. ~~TRADE_THROUGH 是否正式作为 Phase 1 默认限价成交模型。~~ 已由 ADR-0002 确认。
4. ~~被动挂单成交是否固定使用限价，及是否支持价格改善。~~ 已确认使用限价且 Phase 1 不改善。
5. ~~Maker/Taker 费率来源、版本管理及买单冻结缓冲。~~ 已确认显式版本配置并按较高费率冻结。
6. 同一模拟环境共享流动性的默认边界，以及对照实验的隔离规则。
7. 全量重同步后的流动性新版本、冷却或恢复策略。
8. Canonical Schema 的其他新增元数据；Trade 主动方向缺失时当前已采取禁止被动成交的保守策略。

## Part J — 架构决策记录

Accepted ADR：[`decisions/0001-execution-engine-event-processing.md`](decisions/0001-execution-engine-event-processing.md)。串行事件模型、权威来源、原子边界、流动性隔离、Portfolio 投影及确定性身份已在 Task 1.8 实现。

Task 1.7 的状态及预算策略由 Accepted ADR [`decisions/0003-delayed-execution-budget.md`](decisions/0003-delayed-execution-budget.md) 记录。
