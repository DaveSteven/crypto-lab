# ADR-0004：PostgreSQL 持久化与事务边界

- 状态：Proposed
- 日期：2026-11-26
- 适用范围：Phase 1 Task 1.9～1.10

## 背景

Task 1.8 已建立进程内 Unit of Work，但不能恢复进程崩溃。Task 1.9 需要持久化账户、流水、订单、成交、持仓投影、待执行订单、事件处理结果、模拟流动性和确定性 ID 状态，同时保留既有权威来源和原子边界。

## 决策提案

1. 使用 PostgreSQL、SQLAlchemy 2.x、psycopg 3 和 Alembic。
2. Task 1.9 采用同步 Session 和显式事务，不同时维护异步 Repository。
3. 每个事件事务锁定对应 `simulation_environments` 根行，实现环境内串行写入；独立环境互不阻塞。
4. Ledger、Order 和 Fill History 是数据库权威事实；Balance 和 Portfolio 是同事务可重建投影。
5. 事件处理结果、Scheduler、流动性消费和确定性 ID Counter 与金融事实在同一事务提交。
6. 业务时间保存为毫秒整数；金融 Decimal 保存为 `NUMERIC(50, 24)`。
7. 原始高频行情继续存文件，数据库只保存执行所需引用和模拟流动性状态。
8. 使用真实 PostgreSQL 验证迁移、约束、事务回滚和恢复，不以 SQLite 替代。

## 影响

- 需要新增 SQLAlchemy、psycopg 和 Alembic 依赖。
- 现有领域模型保持独立，通过 Repository / Mapper 持久化。
- 现有 Python Callable 事件 Handler 不能直接持久化，需要类型化 Event Payload 和 Dispatcher。
- 数据库事务成为 Task 1.9 后正式应用路径的原子边界；内存 Unit of Work 继续服务纯领域测试和回放。

## 待确认

以上方案及 [`../08-PERSISTENCE-DESIGN.md`](../08-PERSISTENCE-DESIGN.md) 的 Schema、精度、锁和恢复策略需项目负责人确认后方可实施正式代码及迁移。
