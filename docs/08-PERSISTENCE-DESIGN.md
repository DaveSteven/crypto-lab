# Crypto Lab — Phase 1 数据持久化设计

## 0. 文档信息

| 属性 | 内容 |
|---|---|
| 文档版本 | V0.2 |
| 对应任务 | Phase 1 Task 1.9 |
| 状态 | Implemented / Task 1.9 Completed |
| 数据库 | PostgreSQL |

本文档记录已确认并实现的持久化架构，不改变现有领域金融规则。

## 1. 目标与边界

Task 1.9 将 Task 1.8 的进程内原子边界映射为 PostgreSQL 单事务，并支持恢复：

- Account Ledger、Order State 和 Fill History 权威事实。
- Portfolio、Asset Balance 等可重建投影。
- Pending Execution、串行事件队列和处理结果。
- 模拟流动性消费及确定性 ID 计数。
- 必要的 Market Event 引用，不复制 Phase 0 原始高频行情文件。

本任务不引入 FastAPI、前端、Redis、外部消息队列、分布式事务或真实交易接口。

## 2. 技术方案

建议依赖：

| 组件 | 方案 |
|---|---|
| ORM / SQL | SQLAlchemy 2.x |
| PostgreSQL Driver | psycopg 3 |
| Migration | Alembic |
| 测试 | pytest + 独立 PostgreSQL 测试库 |

领域模型继续使用 Pydantic 和 Decimal。持久化 Adapter 位于独立模块，不让 SQLAlchemy Model 成为领域模型或金融规则权威来源。

建议先使用同步 SQLAlchemy Session。Task 1.10 的 FastAPI 服务层可以在线程池或明确事务边界中调用；是否切换 AsyncSession 应基于实际并发需求另行评估，不在 Task 1.9 同时维护同步/异步两套 Repository。

## 3. 类型约定

- 业务 ID：`VARCHAR(64)`，兼容 UUID 字符串及稳定外部事件 ID；不依赖数据库随机生成。
- 金额、价格、数量及费率：`NUMERIC(50, 24)`，写入前后均使用 Decimal，禁止 float。
- 业务事件时间：`BIGINT` 毫秒，与 Canonical Schema 和 ManualClock 一致。
- 数据库审计时间：可额外使用 `TIMESTAMPTZ`，不参与模拟排序及确定性重放。
- Enum：初期使用带 `CHECK` 的 `VARCHAR`，避免 PostgreSQL Enum 迁移锁定演进。
- 可变结构化元数据：JSONB；其中 Decimal 必须编码为字符串。

任何超出 NUMERIC 范围或精度的数据必须拒绝，禁止静默舍入。

## 4. 建议 Schema

### 4.1 `simulation_environments`

每个环境的事务串行化根：

- `environment_id` PK。
- `name`。
- `status`。
- `id_namespace` UNIQUE。
- `last_event_ts_ms`。
- `next_arrival_sequence`。
- `created_at` / `updated_at`。

处理事件时对本行执行 `SELECT ... FOR UPDATE`，同一环境只允许一个写事务；不同环境可并行。

### 4.2 `paper_accounts`

- `account_id` PK。
- `environment_id` FK。
- `exchange_id`。
- `name`。
- `created_ts_ms`。
- UNIQUE (`environment_id`, `account_id`)。

### 4.3 `ledger_entries`

Append-only 余额权威事实：

- `entry_id` PK。
- `environment_id`、`account_id` FK。
- `exchange_id`、`asset`。
- `available_delta`、`locked_delta`。
- `reason`、`reference_id`。
- `created_ts_ms`。

禁止 UPDATE/DELETE 的应用路径。`entry_id` 唯一约束承担幂等保护。

### 4.4 `asset_balances`

Ledger 的同步投影：

- PK (`account_id`, `asset`)。
- `available`、`locked`。
- `last_entry_id`。
- `updated_ts_ms`。

与 Ledger Entry 在同一事务更新；可从完整 Ledger 重建并核对。任何负数由 CHECK 和领域校验双重拒绝。

### 4.5 `paper_orders`

映射当前 `PaperOrder` 全部字段，包括：

- 标识、账户、品种、方向、类型、GTC、状态和确定性 `order_sequence`。
- 数量、限价、参考价、最大预算、冻结资产及金额。
- 累计成交数量、金额、费用和均价。
- Fee Schedule 引用。
- 提交、预定执行、入场、执行、更新等毫秒时间。
- 配置延迟、实际模拟延迟、Scheduler Lag。
- Submission / Execution Market Event 引用及终止原因。

约束至少包括累计成交量不超过订单量、非负累计金额及费用、环境内订单序列唯一。

### 4.6 `executions`

Fill History 权威事实：

- `execution_id` PK。
- `environment_id`、`order_id`、`account_id` FK。
- 品种、方向、价格、数量、成交金额。
- Fee Asset / Amount、Maker/Taker。
- `market_event_id`、`executed_ts_ms`。
- `fill_sequence`，UNIQUE (`order_id`, `fill_sequence`)。

多档成交每档一条 Execution；确定性 ID 和唯一约束防止重试重复成交。

### 4.7 `positions`

Fill History 的同步可重建投影：

- PK (`account_id`, `instrument_id`)。
- 数量、成本、均价、已实现盈亏、累计费用。
- `last_execution_id`、`updated_ts_ms`。

投影失败必须回滚同一数据库事务，不对外暴露未标记旧状态。

### 4.8 `simulation_events`

持久化可恢复的串行事件意图和结果：

- `event_id` PK，含 `environment_id` FK。
- `event_kind`、`event_ts_ms`、`arrival_sequence`。
- `payload_json`。
- `status`: PENDING / PROCESSING / PROCESSED / REJECTED。
- `result_json`、`error_code`。
- UNIQUE (`environment_id`, `arrival_sequence`)。

不能持久化 Python Callable。现有 `SerialEventProcessor` 的 Handler 必须由应用层事件类型 Dispatcher 重建。

### 4.9 `scheduled_executions`

- `order_id` PK / FK。
- `environment_id`。
- `scheduled_execution_ts_ms`、`order_sequence`。
- `status`。

待执行订单与 `paper_orders.PENDING_EXECUTION` 必须在同一事务写入或删除。

### 4.10 `processed_market_events`

- PK (`environment_id`, `source_event_key`)。
- `event_type`、`processed_ts_ms`、`result_json`。

用于 Trade、订单簿事件和重连补发的去重。只能在关联业务事务成功时写入。

### 4.11 `simulated_liquidity` 与 `liquidity_consumptions`

`simulated_liquidity` 保存环境、市场、同步世代、源 Book Event 和剩余 Bid/Ask。Phase 1 可用 JSONB 存储按价格排序的 Decimal 字符串数组，避免提前设计高频逐档关系表。

`liquidity_consumptions` 保存 `consumption_id` PK、环境、订单、Book Event、Execution 关联及消费明细。流动性状态与消费记录同事务提交。

### 4.12 `id_generator_state`

- PK (`environment_id`, `id_kind`)。
- `next_sequence`。

与产生的业务事实同事务更新，失败回滚后重试生成相同 ID。

## 5. 数据库事务映射

一次事件处理：

1. 开始数据库事务。
2. `SELECT simulation_environments ... FOR UPDATE`。
3. 加载并校验事件、订单、余额、Scheduler 和流动性状态。
4. 执行纯领域计算。
5. 插入 Ledger Entry、Execution、Liquidity Consumption。
6. 更新 Order、Asset Balance、Portfolio、Scheduler 和 ID Counter。
7. 最后写入 Processed Event Result。
8. Commit 后才向调用方发布成功结果。

任一步失败均 Rollback。建议使用 PostgreSQL 默认 READ COMMITTED 加环境根行锁；Phase 1 不需要全局 SERIALIZABLE，也不需要分布式锁。

## 6. 恢复与重建

启动恢复顺序：

1. 读取环境及账户。
2. 由 Ledger Entries 重建并核对 Asset Balances。
3. 读取 Order 和 Fill History。
4. 由 Fill History 重建并核对 Positions。
5. 恢复 Pending Scheduled Executions。
6. 恢复未完成 Simulation Events。
7. 恢复模拟流动性世代、剩余量和消费 ID。
8. 恢复确定性 ID Counter。

出现投影差异时默认拒绝启动该环境的交易写入，生成结构化恢复报告；不得静默以投影覆盖权威事实。

### 6.1 服务重启恢复规则（项目负责人确认，2026-11-26）

以统一启动恢复时间 `recovery_ts_ms` 为基准，在 Feed 与 Scheduler 启动**之前**逐环境完成（单环境单事务）：

| 遗留状态 | 处理 |
|---|---|
| `PENDING_EXECUTION` 且计划执行时间 ≤ 恢复时间 | 不补执行、不等待行情；转 `REJECTED`，原因 `EXECUTION_EXPIRED_ON_RESTART`；释放全部剩余冻结资金；保留订单与流水；不生成 Fill、不消耗模拟流动性、不写 `executed_ts_ms`。即使重启时已有有效订单簿也不补执行。 |
| `PENDING_EXECUTION` 且尚未到期 | 保留原计划时间、延迟配置与冻结资金，恢复调度；到期按 Task 1.7/1.8 规则执行。 |
| `OPEN` / `PARTIALLY_FILLED` GTC 限价单 | 不改动状态、剩余数量与冻结资金；仅依据恢复后的新市场事件继续撮合，不依据停机期间行情补成交；已登记 Trade 经 `processed_market_events` 去重，不重复结算。 |

保证：恢复幂等（无遗留过期订单时不产生流水、事件或 `state_version` 变化）；单个环境恢复失败时事务回滚、该环境不被登记（不撮合、不执行调度）、其余环境不受影响；失败环境记录于 `GET /health/recovery` 的 `failed`，并每 5 秒以新的基准重试。正常运行期间的 `MARKET_DATA_UNAVAILABLE` 与重启过期语义分离。

## 7. Migration 与测试

- Alembic 初始迁移必须支持 upgrade 和 downgrade。
- 迁移测试使用独立 PostgreSQL 数据库，不使用 SQLite 替代 PostgreSQL 类型及约束验证。
- 测试库 URL 通过环境变量提供；真实凭据不得提交。
- 可用本地 Docker 启动临时 PostgreSQL，但运行时间应受限，测试结束后删除容器。
- 覆盖事务回滚、唯一约束、Decimal 精度、负余额 CHECK、恢复重建及重复事件。

## 8. 待确认事项

1. 采用同步 SQLAlchemy 2.x + psycopg 3，而非在 Task 1.9 提前引入 AsyncSession。
2. 金融字段统一使用 `NUMERIC(50, 24)`。
3. 业务时间以 BIGINT 毫秒存储，TIMESTAMPTZ 只作数据库审计元数据。
4. Asset Balance 与 Position 作为同事务同步投影表。
5. 使用环境根行 `SELECT FOR UPDATE` 实现环境内串行化。
6. 模拟流动性剩余档位 Phase 1 使用 Decimal 字符串 JSONB，不建立高频逐档表。
7. Simulation Event 持久化类型化 payload，由 Dispatcher 重建 Handler，不持久化 Callable。
8. 测试使用真实 PostgreSQL；本机可通过临时 Docker 容器执行。

以上事项已由项目负责人于 2026-11-26 全部确认并实施。

## 9. 实施结果

- 已新增 SQLAlchemy 2、psycopg 3 和 Alembic 依赖。
- 已建立 13 张事务参与表及初始 Alembic Migration。
- 已实现 PostgreSQL 环境根行锁事务、Repository 和恢复 Adapter。
- Ledger 与 Execution 使用显式持久化序列，避免相同毫秒内按随机 ID 错误重排。
- 已实现账户、流水、余额、订单、Execution、Portfolio、Scheduler、事件队列、去重登记、ID Counter 和模拟流动性的持久化/恢复。
- 写入前拒绝超出 `NUMERIC(50,24)` 的 Decimal，不允许数据库静默舍入。
- Python Callable 不入库；持久化事件仅保存类型和 JSON Payload，由后续应用层 Dispatcher 恢复处理逻辑。
- 真实 PostgreSQL 已验证初始 Migration upgrade/downgrade、事务回滚、重复事件、投影重建及恢复一致性。
- 已实现服务重启恢复（6.1）：`EnvironmentMarketDispatcher.restore_environments`、`EXECUTION_EXPIRED_ON_RESTART`、`GET /health/recovery`；8 项真实 PostgreSQL 应用生命周期集成测试（`tests/api/test_restart_recovery_postgres.py`，ManualClock 式可控时间，无外部网络）。
