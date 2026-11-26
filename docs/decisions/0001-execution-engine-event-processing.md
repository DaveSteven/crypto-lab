# ADR-0001：交易引擎事件处理与一致性边界

- 状态：Accepted
- 日期：2026-11-25
- 关联：Phase 1 Task 1.5～1.9

## 背景

订单簿撮合、限价挂单、模拟延迟、取消和多订单流动性竞争会同时改变订单、成交、流水、持仓投影及模拟流动性。现有实现只保证单次成交的资金流水批量原子性，尚未覆盖完整交易事实和市场事件顺序。

## 决策

1. 每个模拟环境使用确定性的串行事件处理器；行情、取消和到期执行按明确内部序列处理。
2. Account Ledger、Order Model、Fill History、Market State、Execution Scheduler 和 Liquidity Consumption 分别拥有单一权威职责；Portfolio 是可重建投影。
3. 使用 Execution Unit of Work 先计算并验证全部候选变更，再共同提交订单、成交、流水、流动性和可同步更新的持仓投影。
4. 原始真实订单簿不可变；每个模拟环境持有版本化的 Simulated Liquidity View。同一环境共享消耗，独立实验显式隔离。
5. Canonical Market Event 的系统接收时间决定可见性；执行决策不得读取之后才收到的事件。

## 原因

- 串行模型比提前引入并发或分布式撮合更容易验证、重放和保证幂等。
- 单一权威来源避免余额、持仓和订单状态出现相互冲突的副本。
- Unit of Work 允许当前内存实现平滑迁移到 Task 1.9 的数据库事务。
- 版本化流动性视图既保护原始行情，也防止同一流动性被无限重复使用。

## 影响

- 需要增加稳定事件 ID、订单/事件处理记录及 book version。
- 现有 Execution Simulator 需要批量 MatchPlan 入口，但核心结算公式可保留。
- Portfolio 若不能同步提交，必须通过 Fill History 重建并报告投影失败。
- 单个环境的吞吐量受串行处理限制；Phase 1 接受该权衡，不提前优化。

## 已确认事项

- 市价买单预算不足时在显式预算内部分成交并取消剩余。
- 使用 `PENDING_EXECUTION` 区分尚未入场订单。
- TRADE_THROUGH 为默认模型，被动成交使用订单限价。
- 同一环境共享版本化模拟流动性；重同步必须显式建立新视图。
- Maker/Taker 费率来自显式版本化配置。
- Portfolio 是由 Fill History 重建的投影并纳入内存事务。
- 影响重放的业务 ID 使用实验命名空间下的确定性生成器。

项目负责人已于 2026-11-26 确认本 ADR；Task 1.8 按本决策实现。
