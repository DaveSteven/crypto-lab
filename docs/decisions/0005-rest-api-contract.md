# ADR-0005：REST API Contract 与应用服务边界

- 状态：Proposed
- 日期：2026-11-26
- 适用范围：Phase 1 Task 1.10～1.13

## 背景

领域层与 PostgreSQL 持久化已经完成，但不能直接暴露为 HTTP。REST API 必须保护金融规则、环境隔离、事务及幂等性，同时为后续 React 和 WebSocket 联调提供稳定 Contract。

## 决策提案

1. 使用 FastAPI、Pydantic 和同步 SQLAlchemy Session；Route 使用同步函数。
2. API 版本前缀为 `/api/v1`。
3. API Schema 与领域/数据库模型分离，Decimal 使用字符串，时间使用 Epoch Milliseconds。
4. Route 只调用 Application Service；Application Service 管理环境锁事务、领域调用、幂等及错误翻译。
5. 创建环境、账户、订单及取消操作强制 `Idempotency-Key`，记录与业务状态同事务提交。
6. 客户端只提交订单意图，不提交成交价格、成交数量、手续费或成交结果。
7. 订单提交同步完成校验、冻结和 Pending 状态；撮合由串行事件处理。
8. Phase 1 无认证，默认只绑定本机并关闭 CORS；实时推送属于 Task 1.11。

## 影响

- 需要新增 FastAPI、Uvicorn 和 HTTP 测试依赖。
- PostgreSQL 增加 API 幂等记录表及迁移。
- 需要建立 Application Service 和类型化 Event Dispatcher；不能从 Route 直接修改 Repository 或领域对象。
- 后续前端以生成的 OpenAPI 为 Contract，不另行维护冲突的手写字段定义。

## 待确认

以上方案及 [`../09-REST-API-DESIGN.md`](../09-REST-API-DESIGN.md) 的 Endpoint、幂等、错误和安全约定需项目负责人确认后实施。
