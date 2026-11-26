# Crypto Lab — 后端服务与 REST API 设计

## 0. 文档信息

| 属性 | 内容 |
|---|---|
| 文档版本 | V0.1 |
| 对应任务 | Phase 1 Task 1.10 |
| 状态 | Proposed / 待项目负责人确认 |
| 框架 | FastAPI |

## 1. 目标与边界

Task 1.10 提供本地模拟交易的同步 REST API，包括环境、账户、余额、订单、成交及持仓。API 只接受用户交易意图，不允许客户端提交成交价格、成交数量、手续费、流动性角色或成交结果。

本任务不实现 Task 1.11 的行情 WebSocket，不提供真实交易、钱包、登录注册、策略执行或公网部署。

## 2. 应用结构

```text
HTTP Route / Pydantic API Schema
    ↓
Application Service
    ↓
PostgreSQL Transaction + Environment Row Lock
    ↓
Domain Service / Serial Event Processing
    ↓
Repository / Projection Read Model
```

- Route 只处理 HTTP、Schema 和依赖注入。
- Application Service 负责权限范围、幂等、事务、领域调用和错误翻译。
- Domain 保留金融规则权威，不依赖 FastAPI 或 SQLAlchemy。
- 同步 `def` Route 使用同步 SQLAlchemy Session，由 FastAPI 在线程池运行。
- Engine 生命周期由 FastAPI lifespan 管理，连接 URL 只从环境变量读取。

## 3. API 约定

- Base Path：`/api/v1`。
- Content-Type：`application/json`。
- Decimal：JSON 字符串，禁止二进制 float。
- 时间：UTC Epoch Milliseconds。
- ID：不暴露数据库自增 ID，使用现有业务 ID。
- Enum：使用领域定义的大写值。
- 写请求拒绝未知字段。
- 列表使用 `limit` 和稳定业务 ID / sequence cursor；默认 50，最大 200。
- 成功创建返回 `201`；接受异步事件但尚未形成资源时返回 `202`。

## 4. Endpoint Contract

### 4.1 System

| Method | Path | 用途 |
|---|---|---|
| GET | `/health/live` | 进程存活，不访问外部交易所 |
| GET | `/health/ready` | 验证数据库连接及 Migration Revision |
| GET | `/openapi.json` | OpenAPI Contract |

### 4.2 Simulation Environments

| Method | Path | 用途 |
|---|---|---|
| POST | `/api/v1/environments` | 创建独立模拟环境 |
| GET | `/api/v1/environments/{environment_id}` | 查询环境状态 |

创建请求只包含 `name` 和可选客户端业务 ID；ID Namespace 由服务端确定。Phase 1 不提供删除环境接口。

### 4.3 Accounts

| Method | Path | 用途 |
|---|---|---|
| POST | `/api/v1/environments/{environment_id}/accounts` | 创建模拟账户及初始虚拟资金 |
| GET | `/api/v1/environments/{environment_id}/accounts` | 账户列表 |
| GET | `/api/v1/environments/{environment_id}/accounts/{account_id}` | 账户详情 |
| GET | `/api/v1/environments/{environment_id}/accounts/{account_id}/balances` | 可用/冻结余额 |
| GET | `/api/v1/environments/{environment_id}/accounts/{account_id}/positions` | 持仓与成本投影 |

初始资金仅为模拟资产。请求必须明确交易所、资产和 Decimal 字符串金额。

### 4.4 Orders

| Method | Path | 用途 |
|---|---|---|
| POST | `/api/v1/environments/{environment_id}/orders` | 提交模拟订单意图 |
| GET | `/api/v1/environments/{environment_id}/orders` | 按账户/状态分页查询 |
| GET | `/api/v1/environments/{environment_id}/orders/{order_id}` | 订单详情 |
| POST | `/api/v1/environments/{environment_id}/orders/{order_id}/cancel` | 取消订单 |

订单请求字段：

- `account_id`
- `instrument_id`
- `side`
- `order_type`
- `quantity`
- `limit_price`（Limit 必填）
- `max_quote_budget`（延迟 Market Buy 必填）
- `latency_preset` 及 CUSTOM 时的 `custom_latency_ms`

手续费、交易所精度、行情引用和成交结果由服务端配置及市场状态决定。提交后同步完成校验、冻结和 `PENDING_EXECUTION` 持久化，返回 `201`。撮合执行由串行事件处理，不在 HTTP Route 中 sleep。

取消使用动作端点而非 DELETE，因为订单和取消事件必须保留审计记录。已终态订单返回领域冲突错误。

### 4.5 Executions

| Method | Path | 用途 |
|---|---|---|
| GET | `/api/v1/environments/{environment_id}/executions` | 按账户/订单分页查询 Fill History |
| GET | `/api/v1/environments/{environment_id}/executions/{execution_id}` | 成交详情 |

Execution 只读，不提供创建、修改或删除接口。

## 5. 幂等性

以下请求必须携带 `Idempotency-Key`：

- 创建环境。
- 创建账户。
- 提交订单。
- 取消订单。

数据库新增 `api_idempotency_keys`：scope、key、request hash、response status/body、创建时间。相同 scope/key 且请求 hash 相同时返回原响应；请求内容不同时返回 `409 IDEMPOTENCY_KEY_REUSED`。幂等记录与业务事务同一提交。

## 6. 错误模型

统一响应：

```json
{
  "error": {
    "code": "INSUFFICIENT_BALANCE",
    "message": "insufficient USDT balance",
    "details": {},
    "request_id": "..."
  }
}
```

建议映射：

| HTTP | Code | 场景 |
|---:|---|---|
| 400 | INVALID_REQUEST | 跨字段业务输入错误 |
| 404 | ENVIRONMENT_NOT_FOUND / ACCOUNT_NOT_FOUND / ORDER_NOT_FOUND | 资源不存在或不属于环境 |
| 409 | INVALID_ORDER_STATE / INSUFFICIENT_BALANCE / DUPLICATE_EVENT | 领域冲突 |
| 422 | VALIDATION_ERROR | Pydantic Schema 校验 |
| 503 | MARKET_DATA_UNAVAILABLE / DATABASE_UNAVAILABLE | 暂时不可执行 |
| 500 | INTERNAL_ERROR | 未分类错误；响应不得泄露堆栈及数据库信息 |

每个响应包含或回显 `X-Request-ID`。日志记录错误码和请求 ID，不记录数据库密码或完整敏感 Header。

## 7. 安全与运行约束

- 默认只绑定 `127.0.0.1`。
- Phase 1 无身份认证，因此禁止默认公网监听。
- CORS 默认关闭；Task 1.12 联调时只允许显式开发 Origin。
- 请求体大小、列表 limit 和数据库连接池必须有限制。
- 不在健康检查中调用真实交易所。
- API 文档明确所有资金和交易均为模拟。

## 8. 测试与验收

- Application Service 单元测试不启动 HTTP Server。
- FastAPI TestClient 覆盖 Schema、错误映射和 OpenAPI。
- PostgreSQL 集成测试覆盖事务、幂等、环境隔离和资源归属。
- OpenAPI JSON 保存测试快照或验证关键 path/schema，不手工维护第二份 Contract。
- 测试不得访问外部交易所网络。

## 9. 待确认事项

1. 使用 FastAPI + Pydantic，保持同步 Route / 同步 SQLAlchemy Session。
2. Base Path 使用 `/api/v1`。
3. Decimal 统一以 JSON 字符串传输，时间统一毫秒整数。
4. 写接口强制 `Idempotency-Key`，并新增数据库幂等表。
5. 订单提交同步完成校验、冻结和持久化，撮合由串行事件处理。
6. 使用 `POST .../cancel`，不使用 DELETE 删除订单。
7. Phase 1 不实现认证，服务默认只允许本机绑定且 CORS 关闭。
8. Task 1.10 只提供 REST；行情和订单实时推送留待 Task 1.11。

