# Crypto Lab — Trading Journal Architecture & Design

## 0. 文档信息

| 属性 | 内容 |
|---|---|
| 文档版本 | V0.3 |
| 对应任务 | Task 1.14.1 — Architecture & Design |
| 状态 | Accepted |
| 日期 | 2026-11-27 |
| 上游基线 | Phase 1 Accepted；docs/08、docs/09、docs/11、docs/12、docs/15 |

本文定义架构、数据模型、REST Contract、UI/UX、计算语义、测试策略和实施计划。V0.2 已纳入负责人对第 13 节全部事项的确认；Task 1.14.1 设计 Gate 已关闭，Migration 与业务代码由 Task 1.14.2 起独立实施。

## 1. 目标与边界

Trading Journal 用于个人金融学习、交易计划、纪律训练和复盘。一个日志代表一项可持续更新的交易计划，可关联多个模拟订单及其成交。

**Trade Planner 是 Task 1.14 的 P0 核心能力，不推迟到 Task 1.16。** Journal 负责叙事、纪律和复盘；Trade Planner 负责计划参数、Decimal 计算、权威规则校验、首次确认快照及计划与实际结果对照。

本模块必须：

- 按模拟环境及账户隔离。
- 与撮合、余额、订单、Execution 和 Ledger 权威状态解耦。
- 使用 PostgreSQL 持久化主观记录及关联关系。
- 支持交易前计划、执行过程记录和交易后复盘。
- 为未来 Trading Experiment、Strategy Version 和 Experiment Analytics 保留稳定扩展点。

本模块不得：

- 修改订单、Execution、资金流水、余额、持仓或模拟流动性。
- 将计划止损、止盈描述成自动订单或自动执行能力。
- 生成不存在的行情、盈亏、手续费、胜率或实验结论。
- 引入 AI 买卖建议、真实交易权限或移动端适配。
- 加入交易引擎串行事件队列或改变交易 `state_version`。

## 2. 现状审查

### 2.1 后端与持久化

- 当前使用 SQLAlchemy Core、同步 Session、PostgreSQL 16 和 Alembic。
- 交易写入以 `simulation_environments` 行锁串行化；Ledger、Order、Execution 是客观事实来源。
- `paper_accounts` 已包含 `environment_id`，但账户与环境的组合约束应在 Journal 外键中继续显式校验。
- 金融字段统一为 `NUMERIC(50,24)`，时间为 UTC Epoch Milliseconds，业务 ID 为字符串。
- 写接口已有 `api_idempotency_keys`；列表目前使用有限 `limit`，尚未形成通用游标组件。

### 2.2 REST 与前端

- FastAPI Route、Application Service、Persistence Store 分层，外部 Schema 严格拒绝未知字段。
- REST 是权威快照来源；WebSocket 用于交易及行情通知。
- 前端使用 React、TanStack Query、Zustand、Zod、React Router 和共享 UI/金融格式化模块。
- 当前路由为 `/trading`、`/overview`、`/markets`、`/settings`；Journal 应新增独立 `/journal` 与 `/journal/{journal_id}`。

### 2.3 兼容性结论

Journal 属于低频、用户驱动的账户级 CRUD，可使用独立短事务和 REST，不需要环境交易行锁、实时 Event Hub 或交易 Snapshot。关联 Order/Execution 时只读取并验证现有权威表，不更新它们。

### 2.4 Trade Planner 现有能力差距

- 后端实际 Fee Schedule 当前在应用启动时配置，REST 未提供只读查询；前端的 0.1% 仅是参考常量，不能作为 Planner 权威输入。
- OKX Market Rules 已存在后端配置，但 REST instruments 响应未包含 tick size、quantity step、min quantity、min notional。
- Overview 有效资产目前由前端基于有效 Bid 计算，后端尚无带估值状态/时间的权威 Planner Context。
- 现有订单 API 不接受 `journal_id`，Order Entry 也无来源草稿元数据；联动需保持可选且不得改变下单/撮合语义。

因此 Task 1.14.2 必须先提供只读 Planner Context 与无副作用 Preview Contract，再实施 P0 Editor。不得直接复用前端参考费率冒充真实配置。

## 3. 领域模型

### 3.1 Trade Plan 生命周期

确认采用以下业务状态：

| 状态 | 语义 |
|---|---|
| `DRAFT` | 计划尚未通过完整校验，可编辑 |
| `READY` | 首次确认快照已保存，数值规则通过；不代表市场信号成立 |
| `ACTIVE` | 已开始执行，至少存在关联的有效订单或成交 |
| `CLOSED` | 关联交易客观上已平仓且无活动订单，尚未完成复盘 |
| `REVIEWED` | 复盘完成，可作为完整研究样本候选 |
| `CANCELLED` | 计划终止且未构成完整交易；记录原因，不删除 |

基本转换：`DRAFT → READY → ACTIVE → CLOSED → REVIEWED`。`DRAFT / READY → CANCELLED`；ACTIVE 计划不得仅因某个订单被拒绝或取消而自动变为 CLOSED 或 CANCELLED。必要的撤单、减仓和平仓不受风险校验阻止。

首次进入 READY 时必须保存不可变的确认快照。READY 后的计划修改创建新 Revision，不覆盖首次风险参数；影响风险的修改必须重新校验并明确确认。REVIEWED 记录不硬删除，纠错通过追加 Revision 和审计原因完成。

### 3.2 Journal 聚合

建议字段分组：

- 身份：`journal_id`、`environment_id`、`account_id`、`title`、`status`、`version`、当前 `plan_revision`。
- 市场范围：`instrument_id`、`market_type`（Phase 1.14 固定 SPOT）、观察周期、市场趋势。
- 交易计划：方向偏好、交易理由、入场条件、计划入场价、计划仓位金额、止损价、止盈价，以及计算得出的数量、费用、净盈利/亏损、风险比例和收益风险比。
- 执行记录：执行备注、计划偏差说明。
- 心理与纪律：交易前/中/后情绪、强度、纪律 Checklist。
- 复盘：结果摘要、做得好的事项、错误、经验、下次改进、完成时间。
- 扩展关系：逻辑上允许未来关联 Experiment / Strategy Version；Task 1.14 Contract 暂不暴露未实现字段。
- 审计：创建、更新时间及最后编辑原因。

计划金融值是用户计划记录，不是订单或成交结果。所有 Decimal 以字符串传输并用 `NUMERIC(50,24)` 存储；缺失值为 null，不以零代替。前端预览与后端权威校验使用相同版本化公式，但后端结果优先。

### 3.3 Trade Planner 输入、输出与数据来源

输入：计划入场价、仓位金额、SL、TP；当前账户有效资产、可用余额；实际手续费配置；适用的风险限制。

数据来源：

- 有效资产沿用 Overview 的有效 Bid 估值语义，并带 `valuation_status`、时间与不可估值资产；估值不完整时默认不能把风险比例标为通过。
- 可用余额来自 Account Ledger 投影。
- 价格/数量步长、最小数量和最小金额来自后端已验证的 Market Rules，不由前端静态猜测。
- 手续费必须来自后端实际版本化 Fee Schedule，并明确计划采用 Maker、Taker 或保守的 `max(maker,taker)` 假设；未知费率时结果为不可校验，不使用 0 或本地默认值。
- 风险限制可来自当前计划的显式 Policy Snapshot；Task 1.16 上线后由锁定的 Strategy Version 提供并禁止计划自行放宽。

自动输出：预计数量、入场/退出手续费、预计净盈利、预计净亏损、净收益风险比、账户风险比例、仓位比例、最大允许仓位，以及每项校验结果和输入版本。

### 3.4 P0 计算公式（Spot Long）

Task 1.14 P0 仅支持现货 Long 计划；不支持 Short、杠杆、合约及自动策略执行。全部运算使用 Decimal，数量最终按交易所 step size 向下取整。默认权威风险校验使用实际 Fee Schedule 的 `max(maker_fee_rate, taker_fee_rate)` 作为入场和退出的保守费率；用户可查看其他 Maker/Taker 情景，但不能用其绕过已锁定的实验风险规则。

当前模拟执行引擎已经验证的手续费结算语义为：手续费按成交 quote notional 计算并从 quote asset 收取。因此当前 Spot Long 公式为：

```text
quantity = floor_to_step(planned_position_notional / entry_price)
entry_notional = entry_price × quantity
entry_fee = entry_notional × entry_fee_rate

exit_fee_at_tp = take_profit_price × quantity × exit_fee_rate
exit_fee_at_sl = stop_loss_price × quantity × exit_fee_rate

estimated_net_profit =
    (take_profit_price - entry_price) × quantity
    - entry_fee - exit_fee_at_tp

estimated_net_loss =
    (entry_price - stop_loss_price) × quantity
    + entry_fee + exit_fee_at_sl

net_reward_risk_ratio = estimated_net_profit / estimated_net_loss
account_risk_ratio = estimated_net_loss / effective_account_equity
position_ratio = entry_notional / effective_account_equity
```

`planned_position_notional` 和 Policy 单笔仓位上限均为不含手续费的名义交易金额；实际资金占用为 `entry_notional + entry_fee`。`estimated_net_loss` 是计划价格下的估算，不是保证最大亏损；真实退出可能受滑点、延迟、流动性和人工执行影响。零或负分母不计算比率。

Fee Schedule Contract 必须返回手续费资产语义。若未来执行引擎支持 base asset、平台币或其他资产扣费，Planner 必须按该语义重新计算净入账数量与平仓完整性，不能继续假设手续费均以 USDT/quote asset 支付。费率或扣费资产语义未知时相关结果为 UNAVAILABLE。

最大允许仓位取以下约束的最小值，并再次应用数量精度及最小交易限制：

- Policy 单笔仓位上限。
- 可用余额扣除预计入场手续费后的上限。
- 风险预算 `effective_equity × max_risk_rate` 按每单位计划净亏损反推的上限。

### 3.5 P0 权威校验

后端逐项返回 PASS / FAIL / UNAVAILABLE：仓位上限、计划风险上限、最低净收益风险比、`SL < Entry < TP`、可用余额、最小金额/数量、价格与数量精度、行情有效性、有效资产完整性、Fee Schedule 有效性。

账户有效资产采用有效 Bid 估值并包含可用及冻结资产。任一非零资产无法取得当前有效估值时，整体估值标记为不完整，账户风险比例校验返回 UNAVAILABLE；不得用过期估值冒充当前值。可用余额只用于资金充足性校验，有效资产只用于风险和仓位比例校验，两者不得混用。

数值规则通过只表示计划参数满足约束，不代表趋势判断、支撑位或反弹确认信号成立。人工信号结论必须单独记录，不得伪装为自动校验。

### 3.6 标签、情绪与纪律

- 策略标签采用规范化标签表及关联表，支持筛选并避免不可查询的 JSON 字符串集合。
- 情绪记录为追加式时间线，建议字段为阶段、情绪标签、强度 1～5、备注、记录时间；它不是医学评估。
- Checklist 项在创建 Journal 时保存标签快照、排序、是否必选、完成状态和备注。未来实验模板可生成 Checklist，但已创建 Journal 的文本不随模板版本改变。
- 已完成日志原则上不直接覆盖关键历史记录；修订必须更新时间和版本，实验阶段可进一步增加完整审计表。

## 4. PostgreSQL 模型设计

### 4.1 `trading_journals`

核心列：

- `journal_id VARCHAR(64)` PK。
- `environment_id VARCHAR(64)`、`account_id VARCHAR(64)`，组合 FK 指向 `paper_accounts(environment_id, account_id)`。
- `instrument_id VARCHAR(100)`，Phase 1.14 每个 Journal 一个主品种。
- `title VARCHAR(200)`、`status VARCHAR(20)`、`version BIGINT`、`current_plan_revision_id VARCHAR(64)` nullable。
- `timeframe VARCHAR(20)`、`market_trend VARCHAR(32)`、`trade_bias VARCHAR(16)`。
- 计划价格/数量/金额/风险字段：`NUMERIC(50,24)` nullable。
- 文本字段：交易理由、入场条件、执行备注及复盘字段，使用 `TEXT`。
- Task 1.14 不提前建立无 FK 的 `experiment_id` / `strategy_version_id` 占位列。Task 1.16 建表后，通过独立 Migration 增加 nullable FK 和索引，避免孤儿标识及虚假能力。
- `created_ts_ms`、`updated_ts_ms`、`ready_ts_ms`、`activated_ts_ms`、`closed_ts_ms`、`reviewed_ts_ms`、`cancelled_ts_ms`。

约束：`version > 0`；状态和时间组合合法。索引建议为 `(environment_id, account_id, updated_ts_ms DESC)`、状态、品种及未来实验关联。计划金融参数不直接覆盖写在主表，以 Revision 为权威历史。

### 4.2 `trade_plan_revisions`

计划历史使用不可变 Revision：

- `plan_revision_id` PK、`journal_id` FK、`revision_number`，Journal 内唯一。
- 用户输入：entry、position notional、SL、TP、人工信号说明。
- 计算输入快照：有效资产、可用余额、Fee Schedule ID/费率、Market Rules ID/精度、风险限制及行情引用/时间。
- 计算输出：数量、入场/两种退出手续费、预计净盈利/亏损、收益风险比、账户风险比例、仓位比例和最大允许仓位。
- `validation_status`、逐项 `validation_results_json`、公式版本 `calculator_version`。
- `revision_reason`、`created_ts_ms`、`confirmed_ts_ms`；首次 READY Revision 标记 `is_initial_confirmed=true`，只允许一条。

JSONB 内所有 Decimal 必须编码为字符串。保存 Revision 与更新 Journal 当前 Revision、状态及 version 在同一事务完成。Revision 不 UPDATE/DELETE；修改计划创建下一版本。

### 4.3 `trade_plan_actual_comparisons`

实际结果主要从关联 Execution 动态派生。若为复盘保存对照快照，记录 `journal_id`、`as_of_execution_sequence`、实际数量/VWAP/费用/已实现盈亏、偏差及计算版本；它是可重建研究快照，不取代 Execution 权威来源。

### 4.4 `journal_tags` / `journal_tag_links`

- 标签按账户隔离：`tag_id`、环境、账户、标准化名称、显示名称、颜色。
- 同一账户的标准化标签名唯一。
- Link 使用 `(journal_id, tag_id)` PK。

### 4.5 `journal_order_links`

- `(journal_id, order_id)` PK。
- 冗余保存并校验 `environment_id`、`account_id`，防止跨范围关联。
- `linked_ts_ms`、`note`、`link_sequence`。
- 建议 `order_id` UNIQUE：一个订单最多归属于一个 Journal，避免日志级统计重复归因。

Execution 不建立独立可编辑关联表。Journal 的有效 Fill 集合由已关联订单的 `executions` 权威记录派生，因此后续部分成交会自动纳入，且不存在 Order 与 Fill 关联不一致。API 应返回派生的 Execution 列表。

如果负责人未来要求“一个订单拆分到多个 Journal”，必须另行设计不可变的 execution quantity allocation；本轮不以简单多对多关系实现，避免重复计算。

### 4.6 `journal_emotion_entries`

- `emotion_entry_id` PK、`journal_id` FK。
- `phase`：PRE_TRADE / IN_TRADE / POST_TRADE。
- `emotion_code`、`intensity`（1～5）、`note`、`recorded_ts_ms`、确定性排序字段。

情绪记录可追加和修订，但不得影响客观交易结果或实验规则校验。

### 4.7 `journal_discipline_items`

- `discipline_item_id` PK、`journal_id` FK。
- `label_snapshot`、`description_snapshot`、`sort_order`、`is_required`。
- `is_checked`、`checked_ts_ms`、`note`。
- 未来可空 `source_strategy_rule_id`，供 Strategy Version 追溯。

### 4.8 删除、归档与审计

不提供硬删除 Journal 或 Plan Revision。DRAFT 也转 CANCELLED 并保留原因，以保证研究样本不被选择性删除。允许归档，但归档不改变客观统计归属。已完成交易的订单归属变更、解除关联、状态转换、首次风险参数、原始 SL/TP 及后续变更必须写入追加式审计记录并包含原因。数据库级 FK 对交易事实使用 RESTRICT，不级联删除订单或成交。

## 5. Order / Fill 关联规则

关联时必须验证：

1. Journal、Order 属于同一环境和账户。
2. Order 品种与 Journal 主品种一致。
3. Order 尚未关联其他 Journal。
4. Execution 只通过 Order 派生，且必须属于该 Order。
5. 关联操作不得修改 Order、Execution、Ledger、Portfolio 或 `state_version`。
6. 取消关联只删除主观归属，不删除任何交易事实；ACTIVE/CLOSED/REVIEWED Journal 的取消关联需要显式原因和审计记录。

建议允许订单提交后关联，也为未来提供“从 Journal 发起下单意图时附带 `journal_id`”的应用层便利，但订单接口不能依赖 Journal 才可交易，自由交易模式必须继续存在。

订单成功创建而 Journal Link 失败时，客户端不得重新提交订单。关联操作必须具有独立 Idempotency-Key，并允许使用既有 `order_id` 安全恢复关联；重复恢复返回同一关联结果。关联和状态转换使用 Journal 行锁、版本条件或等价并发控制。Journal 写事务不得锁定或递增交易引擎 `state_version`。

## 6. 日志级盈亏语义

### 6.1 权威来源

- Fill History 是成交权威来源。
- Account Ledger 是余额权威来源。
- Journal 只保存关联，不保存可编辑的“实际盈亏”。
- 实际指标在读取时由关联 Order 的 Execution 和账户完整 Fill History 派生，使用既有移动平均成本法。

### 6.2 建议计算口径

为避免建立第二套成本权威，重放该账户、该品种的完整 Execution 历史；每个卖出 Execution 会产生确定的 realized PnL 增量。Journal 的：

```text
journal_realized_pnl =
    sum(属于关联订单的卖出 Execution 所产生的 account realized PnL 增量)

journal_fees =
    sum(关联订单全部 Execution 的 fee_amount，按 fee_asset 分币种)
```

该口径使用账户在成交发生时的真实移动平均成本，因此可能包含更早、未归入当前 Journal 的库存成本影响。UI 必须称为“关联成交归因的已实现盈亏”，并展示口径说明。

### 6.3 不应提供的指标

- 仅有买入或尚未完全平仓时，不将现金流差额称为利润。
- 不根据计划止损/止盈计算“实际收益”。
- 不用当前余额变化推断单笔 Journal 盈亏。
- Phase 1.14 不提供 Journal 未实现盈亏；其库存归属在多计划情况下缺乏可靠分配语义。
- 不跨结算币种求和；每种币种分别显示。
- Journal 统计不等于 Experiment Analytics；胜率、Profit Factor、Expectancy 和 Drawdown 留给 Task 1.17。

### 6.4 完整交易判定

客观交易完成与研究复盘完成必须分开：

- Journal 至少关联一个有成交的订单。
- 关联成交在该 Journal 口径下的净基础资产数量精确回到零；计算必须纳入实际手续费资产及净入账数量语义，并应用交易所 Decimal 精度，不使用任意 float 容差掩盖残余仓位。
- 不存在关联订单处于非终态。

满足以上客观条件时进入 `CLOSED`，并计入客观已完成交易数；完成复盘后进入 `REVIEWED`。未来 Analytics 分别统计已完成交易、已完成复盘、待复盘，以及规则遵守、违规和待评估数量。违规交易不得从客观结果中排除。Experiment 001 的完成条件为 30 笔客观完整交易全部进入 REVIEWED。

如果关联订单只是卖出账户既有库存，或关联范围不闭合，显示“样本不完整”，不得纳入未来 Experiment 的完整交易样本数。

ACTIVE 状态下若所有关联订单均已进入终态且从未产生 Fill，可由用户显式取消计划并记录原因；订单拒绝或取消本身不等于完成交易。

## 7. REST API Contract

建议 Base Path：

`/api/v1/environments/{environment_id}/accounts/{account_id}/journals`

### 7.1 Endpoint

| Method | Path | 用途 |
|---|---|---|
| POST | `/journals` | 创建 Draft，强制 Idempotency-Key |
| GET | `/journals` | 按状态、品种、标签、更新时间分页查询 |
| GET | `/journals/{journal_id}` | 详情，包含关联摘要与派生指标 |
| PATCH | `/journals/{journal_id}` | 更新叙事/复盘字段，要求版本号 |
| POST | `/journals/{journal_id}/plan/revisions` | 保存新的计划 Revision 并执行权威计算/校验 |
| POST | `/journals/{journal_id}/ready` | 首次确认计划快照或确认新 Revision |
| POST | `/journals/{journal_id}/activate` | 进入执行阶段，强制 Idempotency-Key |
| POST | `/journals/{journal_id}/close` | 基于客观关联状态进入 Closed |
| POST | `/journals/{journal_id}/review` | 完成复盘进入 Reviewed |
| POST | `/journals/{journal_id}/cancel` | 取消计划并保留原因 |
| PUT | `/journals/{journal_id}/orders/{order_id}` | 关联订单，强制 Idempotency-Key |
| DELETE | `/journals/{journal_id}/orders/{order_id}` | 解除主观关联；需 `reason`，不删除订单 |
| POST | `/journals/{journal_id}/emotions` | 添加情绪记录，强制 Idempotency-Key |
| PATCH | `/journals/{journal_id}/discipline/{item_id}` | 更新 Checklist 项，要求 Journal 版本 |
| GET | `/journals/{journal_id}/metrics` | 读取派生的成交、费用及已实现盈亏口径 |
| POST | `/trade-planner/preview` | 无副作用的权威 Decimal 计算与校验预览 |
| GET | `/trade-planner/context?instrument_id=` | 有效资产、余额、Fee Schedule、Market Rules 及数据质量 |
| GET | `/fee-schedule` | 当前后端实际 Maker/Taker 费率、扣费资产语义及配置身份 |
| GET | `/market-rules/{instrument_id}` | Tick/step/min quantity/min notional 等权威规则 |

列表建议采用 `(updated_ts_ms, journal_id)` 稳定游标，默认 30、最大 100。响应 Decimal 均为字符串，时间为 UTC 毫秒。

### 7.2 并发与幂等

- Create、状态动作、关联和追加记录使用既有 `Idempotency-Key` 机制。
- PATCH 使用 `version` 乐观锁；版本不一致返回 `409 JOURNAL_VERSION_CONFLICT` 和当前版本。
- Journal 写事务锁定 Journal 行，不锁环境交易根；关联时只读并验证 Order。所有状态转换及关键关联变更都必须具备明确并发控制。
- 客观交易在 Journal 编辑期间可继续提交与成交，Journal 详情下次读取时获得最新派生 Fill。
- Preview 不写数据库；保存 Revision 时后端必须重新读取最新 context 并重新校验，不信任前端提交的计算结果。前端计算结果永远不是权威结果。
- Order 创建与 Journal Link 使用不同幂等操作；创建成功但 Link 失败时使用原 `order_id` 恢复关联，禁止为恢复关联重复提交订单。
- Journal 写入不得改变交易引擎 `state_version`。

### 7.3 错误码

建议：`JOURNAL_NOT_FOUND`、`INVALID_JOURNAL_STATE`、`JOURNAL_VERSION_CONFLICT`、`ORDER_SCOPE_MISMATCH`、`ORDER_ALREADY_LINKED`、`INSTRUMENT_MISMATCH`、`INCOMPLETE_REVIEW`、`INVALID_PLAN_VALUE`、`FEE_SCHEDULE_UNAVAILABLE`、`MARKET_RULES_UNAVAILABLE`、`VALUATION_INCOMPLETE`、`RISK_LIMIT_EXCEEDED`。

## 8. UI/UX 设计

### 8.1 导航与页面

- 顶部主导航增加“日志”。
- `/journal`：列表、筛选、新建入口和学习导向空状态。
- `/journal/new`：创建 Draft。
- `/journal/{journal_id}`：详情与编辑工作区。

保持 Desktop Only、Dark Theme、Teal 品牌色、统一 PageContainer/PageHeader 和金融数字格式规范。

### 8.2 Journal 列表

- 顶部：标题、状态筛选、品种、标签、更新时间、创建按钮。
- 行/卡片：标题、状态、品种、方向、周期、更新时间、关联订单/成交数、复盘完成度。
- 只展示由服务端返回的派生盈亏；未知或样本不完整显示明确状态，不显示 0。

### 8.3 Journal 详情

建议双栏：

- 主栏：市场分析、Trade Plan、执行记录、Trade Review。
- 侧栏：状态、Checklist、情绪时间线、关联 Order/Fill、派生指标及口径说明。

编辑使用显式“保存草稿”，离开未保存页面时提醒；不使用不可观察的持续自动保存。REVIEWED 状态默认只读，修订需明确动作和原因。

### 8.4 Trade Plan Editor

- Trade Planner 为页面主操作区，输入 Entry、Position Amount、SL、TP；同时展示账户有效资产、可用余额、Fee Schedule、风险限制和 Market Rules 数据时间。
- 市场趋势与观察周期使用有限枚举，同时提供文字依据；人工入场信号与数值校验分区展示。
- 价格/数量/金额输入保留实际 Decimal 精度；显示层使用现有 FinancialValue。金额默认 2 位，价格/数量遵循交易所精度，比率保留必要精度；详情可查看完整值。
- 前端以 decimal.js 实时预览数量、双边费用、净盈利/亏损、R:R、风险率、仓位率及最大仓位；保存时显示后端权威结果，差异时以后端为准并要求重新确认。
- 所有预计值使用“计划/预计”标签，明确公式、费率角色假设、输入缺失和行情失效状态。
- 止损、止盈旁显示“仅作计划记录，不会自动下单”。
- 关联订单通过当前账户真实订单选择器完成，禁止跨环境/账户候选项。
- READY 后编辑显示 Revision diff，并保留首次确认快照；不得静默覆盖原风险参数。
- 交易前 Checklist 与交易后纪律评估使用不同的数据分组和完成语义，不得以事后评价改写交易前记录。

### 8.5 与 Trading / Chart 联动

- “带入下单”仅把当前已确认 Revision 的品种、方向、计划数量/预算和可适用的限价复制到 Order Entry 草稿；不自动提交，不绕过现有强制确认 Dialog。
- SL/TP 不映射为真实订单，不触发自动平仓；用户仍需自行管理模拟订单。
- Order 成功创建后才建立 Journal Link；请求失败不得伪造关联。
- 若 Order 已创建而 Link 失败，UI 保留原 `order_id` 并重试幂等关联，绝不重新下单。
- 详情展示计划 Entry/SL/TP 与实际 Fill VWAP、手续费及结果偏差，不覆盖原计划。
- 为 Task 1.15 定义只读 `PlanPriceLines` 视图模型（Entry/SL/TP、revision ID、颜色语义）；本轮不提前修改图表。

### 8.6 未来 Experiment 模式

Task 1.14 UI 不展示尚未实现的 Experiment 操作，也不在当前 API/组件 Props 中伪造 `experimentId` 或 `strategyVersionId`。组件保持按功能分层，Task 1.16 再增加“实验模式”入口、真实 FK、参数锁定及只读规则来源。自由 Journal 不应被实验规则强制限制。

## 9. Trading Experiment / Strategy Version 扩展设计

未来建议关系：

```text
TradingExperiment 1 ── N StrategyVersion
TradingExperiment 1 ── N TradingJournal
StrategyVersion    1 ── N TradingJournal
TradingJournal     1 ── N Order ── N Execution
```

- Experiment 保存研究目标、初始本金、品种、目标样本量和当前生效策略版本引用。
- Strategy Version 必须不可变，保存参数、规则、Checklist 模板、版本说明及生效时间；规则变更创建新版本。
- Journal 在激活时锁定 `experiment_id` 和 `strategy_version_id`，保证后续分析可复现。
- 自动校验结果与人工判断分离：系统规则结果保存规则版本、输入与结果；人工趋势/信号保留为 Journal 记录。
- 必要的风险降低操作不得被实验限制阻断，但必须留下偏离/违规记录。
- Experiment 001 的本金、仓位、风险、收益风险比、样本目标与禁止事项应在 Task 1.16 作为版本化配置实现；趋势与反弹确认信号尚未确认，不写入规则引擎。

## 10. Experiment Analytics 扩展边界

Task 1.17 只基于锁定的 Strategy Version、完整 Journal 样本及客观 Execution 计算：样本数、净利润、ROI、胜率、实际盈亏比、Profit Factor、Expectancy、回撤口径、最长连亏、执行率、手续费与违规统计。

必须提前保留：

- Journal 的实验及策略版本归属。
- 完整交易判定与排除原因。
- 规则检查结果和违规事件的不可变历史。
- 统计使用的结算币种、估值口径、样本截止时间和计算版本。

不得删除亏损或违规 Journal 来改善统计。归档只改变展示，不应从已锁定实验样本中静默排除。

## 11. 测试策略

### 11.1 单元测试

- 状态转换、Decimal 计划值校验、风险/收益风险比公式。
- step size 向下调整、双边手续费、最大仓位多约束取最小、零分母及极小非零值。
- 保守 `max(maker,taker)` 校验、其他费率情景仅供参考、未知费率/扣费资产语义返回 UNAVAILABLE。
- Quote-asset 手续费净数量语义，以及未来非 quote fee 场景不得误用现有公式。
- Entry/SL/TP 关系、余额不足、最小交易限制、行情/估值/Fee Schedule 不可用。
- 完整交易判定、关联 Fill 派生、按币种费用汇总和 PnL 归因。
- Checklist 完成规则、乐观锁、标签标准化。

### 11.2 PostgreSQL 集成测试

- Migration upgrade/downgrade、约束和索引。
- 环境/账户/品种隔离、Order 唯一关联、FK RESTRICT。
- 幂等、并发 PATCH 冲突、事务回滚、归档后数据保留。
- Journal 写入不改变 Ledger、Order、Execution、Portfolio、流动性或交易 state_version。
- 首次 READY 快照不可变，后续 Revision 不覆盖初始风险参数。
- Order 已创建但 Link 失败后的幂等恢复不会重复订单；并发关联只有一个归属成功。
- CLOSED 与 REVIEWED 分离，归档、解除关联或违规标记不得静默移除客观交易样本。

### 11.3 API 测试

- 严格 Schema、Decimal 字符串、过滤/游标、错误信封与 OpenAPI。
- 跨范围关联拒绝、状态动作、关联后新 Fill 自动出现。
- 指标不可用与样本不完整不返回误导性零值。
- Preview 与保存时重新校验；Fee Schedule、行情或余额变化导致旧预览失效。
- Fee Schedule、Market Rules 与 Planner Context 只读接口只返回后端实际配置，不回退到前端默认值。
- 风险校验不阻止撤单、减仓和平仓；已确认计划不被描述为入场信号，SL/TP 不被描述为自动订单。

### 11.4 前端测试与验收

- 列表/详情/编辑/关联/Checklist/情绪/复盘组件测试。
- 未保存提醒、版本冲突、错误恢复、环境切换缓存隔离。
- 1280×720、1440×900、1920×1080、2560×1440 浏览器验收。
- Docker Compose 下 PostgreSQL 持久化与服务重启验证。

自动化测试不得依赖外部交易所网络；行情或成交场景使用固定 MOCK/SYNTHETIC 数据并明确标识。

## 12. 子任务实施计划

| Task | 内容 | 主要交付 |
|---|---|---|
| 1.14.1 | Architecture & Design | Completed；本文档 V0.2、Roadmap、负责人决策 |
| 1.14.2 | Persistence & REST API | Completed；Journal/Revision Migration、Planner Context/Preview、Fee/Rules 读取、Service、Schema、OpenAPI、PostgreSQL 测试 |
| 1.14.3 | Journal List & Detail | Completed；`/journal`、Draft 创建、详情页、查询、状态及只读 Revision 展示 |
| 1.14.4 | Trade Plan Editor | Completed；P0 Planner、实时 Decimal 预览、权威校验、首次快照、Revision、带入 Order Entry |
| 1.14.5 | Order & Fill Association | Completed；唯一订单归属、派生 Fill、完整历史重放指标、幂等恢复与 UI |
| 1.14.6 | Emotion & Trading Discipline | 情绪时间线、Checklist 快照与完成规则 |
| 1.14.7 | Trade Review | 复盘、完成判定、归档和学习摘要 |
| 1.14.8 | Integration & Acceptance | E2E、桌面矩阵、Docker 持久化、文档及验收报告 |

每个子任务通过相关测试后创建独立本地 Commit；不得自动进入下一阶段或 Push。

## 13. 已确认的设计决策

以下事项已于 2026-11-27 全部由项目负责人确认，Task 1.14.1 Gate 已关闭：

1. P0 仅支持 Spot Long；不支持 Short、杠杆、合约和自动策略执行。
2. 权威风险校验默认使用实际 Fee Schedule 的 `max(maker,taker)`；其他费率场景只供参考，未知费率为 UNAVAILABLE。当前引擎手续费按 quote asset 结算，未来其他扣费资产必须显式建模。
3. 有效资产使用当前有效 Bid 估值，包含可用和冻结资产；任一非零资产不可估值时风险比例为 UNAVAILABLE。100 USDT 仓位上限是不含手续费的名义金额。
4. 一个 Journal 对应一个主品种，可关联多个同品种 Order 及其派生 Fill；禁止跨环境、账户或品种。
5. 一个 Order 最多关联一个 Journal，由数据库唯一约束保证；暂不拆分成交数量。
6. Fill 通过 Order 自动派生，不建立可编辑 Fill Link。
7. Journal 已实现盈亏采用完整账户历史重放并归因关联卖出 Fill 的 realized PnL 增量；复用移动平均成本，不重复扣费，不提供不可靠的 Journal 未实现盈亏，多币种分别统计。
8. `CLOSED` 表示客观交易完成，`REVIEWED` 表示研究复盘完成；已平仓和违规交易不得因复盘状态或违规而从客观结果排除。Experiment 001 需要 30 笔客观完整交易全部复盘。
9. Journal 和 Plan Revision 禁止硬删除；允许取消及归档，已完成交易归属变更必须审计，不能静默改善统计。
10. 采用 `version` 乐观锁、显式保存、不可变 Revision、首次确认快照及重要修改原因；保存时重新读取 Context 做权威校验。
11. Task 1.14 不建立无 FK 的 Experiment / Strategy Version 占位列；Task 1.16 再以正式 Migration 增加关联。
12. Experiment 001 的趋势、支撑和反弹信号保持 Pending，不实现为自动信号。
13. Order 创建成功但 Link 失败时使用独立幂等关联恢复，不得重复下单；所有关键关联和状态转换具备并发控制。
14. 交易前 Checklist 与交易后纪律评估分离；READY 不代表入场信号成立，计划 SL/TP 不代表自动执行。
15. 风险校验不得阻止撤单、减仓和平仓；Journal 写入不得改变交易引擎 `state_version`，也不得改变现有金融结算或撮合规则。

## 14. Task 1.14.2 实施记录

Task 1.14.2 已于 2026-11-27 完成，范围严格限定在 PostgreSQL 与后端 REST：

- Alembic head 更新为 `0004_trading_journal`，新增 Journal、不可变 Plan Revision 和追加式 Audit Event 表；完成独立测试库 upgrade/downgrade/upgrade 验证。
- 实现 Journal 创建、列表、详情、乐观锁更新、READY/CANCELLED 转换，以及 Plan Revision 的幂等保存和首次确认快照。
- 实现只读 Fee Schedule、Market Rules、Planner Context，以及无副作用的权威 Decimal Preview。
- Context 使用有效 Bid 对可用及冻结资产估值；非零资产不可估值时返回 INCOMPLETE，行情缺失或过期时返回 UNAVAILABLE。
- 权威 Preview 使用 `max(maker,taker)`、交易所 tick/step/min 规则和名义仓位/资金占用分离语义；所有 Decimal 经字符串 Contract 传输。
- Revision 保存时重新读取 Context 并重算；Journal 写事务不调用交易状态版本递增，不改变 Ledger、Order、Execution 或撮合状态。
- 一个首次确认快照通过新增不可变 Revision 保存，避免更新既有 Revision。`current_plan_revision_id` 由同一 Journal 事务维护；Revision 自身通过 RESTRICT FK 归属于 Journal。
- Order/Fill Link、Emotion、Checklist、Review UI 与 Journal 前端未提前实现。

验收结果：Ruff 全量通过；独立 `crypto_lab_test` PostgreSQL 数据库完整后端回归为 360 passed。正式本地模拟数据库未用于测试或清理。

## 15. Task 1.14.3 实施记录

Task 1.14.3 已于 2026-11-27 完成：

- 顶部导航新增“日志”，并增加 `/journal` 与 `/journal/{journal_id}` 路由。
- 列表按当前环境和账户查询，支持状态及主品种筛选，不跨账户缓存数据。
- 支持创建基础 Draft，仅收集标题、主品种和观察周期；不提前暴露 Planner 输入。
- 详情展示市场分析、当前状态、只读计划值、不可变 Revision 历史及执行/复盘占位状态。
- 计划计算结果始终标记为预计值；无 Order/Fill 关联时不推测成交、盈亏或统计。
- REST 响应使用 Zod 校验，Decimal 保持字符串，不以显示值参与金融计算。

前端验证：Vitest 140 passed；TypeScript/Vite build 通过；Oxlint 无新增告警（保留既有 Chart effect warning）。Docker Compose 已重建，Migration、Backend 与 Frontend 健康，Nginx 代理下 Journal 列表 API 实际返回成功。浏览器控制服务当时不可用，因此本子任务尚缺真实浏览器截图，不能将视觉截图验收描述为已完成。

## 16. Task 1.14.4 实施记录

Task 1.14.4 已于 2026-11-27 完成：

- Draft 详情页提供 Spot Long Trade Planner，输入 Entry、名义仓位、SL、TP、仓位上限、账户风险上限及最低净收益风险比。
- 前端使用 Decimal 实时计算数量、双边费用、预计净盈利/亏损、净收益风险比、账户风险率、仓位率及最大允许仓位；显示计算不回写为后端权威结果。
- Planner Context 只读取后端实际有效资产、可用余额、Fee Schedule、Market Rules 和行情状态，不使用前端参考费率替代。
- “执行权威校验”调用无副作用 Preview；输入修改后旧校验立即失效，未获得当前输入的权威结果时不能保存 Revision。
- Revision 保存由后端重新获取 Context 并重算；READY 动作创建首次确认快照。计划估算、市场信号和实际交易结果在 UI 中明确分离。
- 只有首次确认快照可以带入 Order Entry；联动仅创建 Spot Long LIMIT 草稿，保留原订单校验、预览及强制确认 Dialog，不自动提交订单。
- SL/TP 继续仅作为计划记录，不创建自动止损止盈订单；Order / Fill 关联留给 Task 1.14.5。

验证结果：Vitest 145 passed；TypeScript/Vite build 通过；Oxlint 无新增告警（仅保留既有 Chart effect warning）；Docker Compose 重建及健康检查通过；真实 Planner Context REST 验证通过。当前真实环境当时没有有效订单簿，接口正确返回 `market_status=UNAVAILABLE`，未伪装成可确认行情。浏览器控制未获 Chrome 权限，因此真实浏览器截图仍未完成。

## 17. Task 1.14.5 实施记录

Task 1.14.5 已于 2026-11-27 完成，范围限定为 Order / Fill Association：

- Alembic head 更新为 `0005_journal_order_links`。`journal_order_links` 以 `order_id` 唯一约束保证一个订单至多属于一个 Journal，冗余保存环境/账户范围并以账户复合 FK 约束；应用层在行锁事务内校验 Journal、Order 的环境、账户及品种一致性。
- 关联仅允许 READY / ACTIVE Journal；首次关联使 READY 进入 ACTIVE。关联与解除关联均锁定 Journal、校验 `journal_version`、使用独立 Idempotency-Key，并写入追加式审计事件。
- 解除关联强制记录原因，只删除主观归属；Order、Execution、Ledger、Portfolio 与交易引擎 `state_version` 均不改变。
- Fill 不建立可编辑关联表；详情接口按关联 Order 自动派生全部 Execution，后续部分成交自然纳入。
- 日志指标重放当前账户完整 Fill History，复用移动平均成本法，只累计关联 SELL Execution 产生的 realized PnL 增量；关联成交手续费按 `fee_asset` 分币种汇总，不重复扣费，也不提供不可靠的 Journal 未实现盈亏。
- 客观完整交易要求至少一个关联 Execution、关联基础资产净数量精确归零且无活动关联订单；不使用浮点容差掩盖残余仓位。
- 日志详情可从当前账户真实订单中建立/解除关联，展示派生成交、归因口径、费用及不完整原因。由计划创建订单后自动尝试关联；若关联失败，保留原 `order_id` 并仅重试关联，绝不重复提交订单。
- 该实现没有增加 Experiment / Strategy Version 占位字段，也没有实现 Emotion、Checklist 或 Trade Review。

验证结果：隔离 `crypto_lab_test` 完成 `0005 → 0004 → 0005` 迁移往返；后端完整回归 364 passed；前端 Vitest 146 passed，TypeScript/Vite build 通过，Oxlint 仅保留既有 Chart effect warning。正式 Docker Compose 已重建并健康，正式数据库仅执行向前 Migration，未清理或修改既有模拟账户事实。浏览器控制服务本轮未提供，因此未将真实浏览器截图列为已完成证据。
