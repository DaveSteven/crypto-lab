# ADR 0009 — Phase 1 本地 Docker Compose 部署架构

## 状态

Accepted / Implemented（2026-11-26）。项目负责人已确认设计，Task 1.13 已完成容器化实施与备份恢复演练。

## 背景

Phase 1 目前以开发方式运行（本机 Python 进程 + PostgreSQL 容器 + Vite 开发服务器）。需要一个可一键启停、数据可持久化、与开发/测试数据隔离的本地运行形态，同时不引入超出 Phase 1 范围的基础设施。

## 问题

如何在单机上稳定运行 Crypto Lab，且保证：不暴露不必要端口、迁移失败不启动业务服务、测试不会清空正式模拟数据、重启后不使用失效行情撮合。

## 候选方案

1. 继续手动启动三个进程。
2. Docker Compose 三容器（Frontend / Backend / Database）。
3. 增加 Redis、Kafka、Kubernetes 或拆分微服务（超出 Phase 1 范围，否决）。

## 最终决定

采用方案 2。三个长期运行的容器，**保持单 API 进程、单 Worker**，不引入 Redis、Kafka、Kubernetes 或额外微服务：

| 容器 | 内容 |
|---|---|
| Frontend | React Production Build + Nginx |
| Backend | Python + FastAPI + Market Feed + Trading Engine + Scheduler + Realtime Hub（单进程单 Worker） |
| Database | PostgreSQL |

### 运行环境与数据隔离

| 环境 | 形态 | 说明 |
|---|---|---|
| Development | 本机前后端热更新 + PostgreSQL Docker | 开发库 |
| Local Production | 完整 Docker Compose | 正式模拟数据库 |
| Test | 独立 PostgreSQL 测试容器 | 默认关闭真实 Feed |

三个环境使用**独立业务数据库**；测试工具禁止连接 Local Production 数据库，不得清空正式模拟账户数据（实施时在测试夹具中增加库名/URL 防护）。

### 网络

- 默认访问地址 `http://localhost:18080`，**仅绑定本机回环地址**（宿主机端口映射 `127.0.0.1:18080`）。容器内 Nginx 仍监听 8080，宿主机端口可通过 `CRYPTO_LAB_WEB_PORT` 覆盖。
- Nginx 统一代理 REST 与 WebSocket；WebSocket 代理必须支持连接升级（`Upgrade/Connection`）与长连接（读写超时大于应用心跳间隔 15s / 客户端超时 45s，docs/10）。
- PostgreSQL 与 Backend 仅在 Docker 内部网络；正式运行环境不向宿主机暴露其端口。
- 无认证机制前禁止默认公网部署。
- Backend 监听地址由 `CRYPTO_LAB_API_HOST` 配置；容器中使用 `0.0.0.0`，但不映射宿主机端口。

### 容器生命周期

- 一键启动与停止（Compose 命令封装）。
- Database Health Check；Backend Readiness Check（沿用 `/health/ready`：数据库 + Alembic Head）。
- Alembic Migration 自动或显式执行；**Migration 失败时不得启动不兼容的业务服务**（独立 migrate 一次性任务，Backend `depends_on` 其成功完成）。
- 正确关闭 Feed、Scheduler 与 WebSocket（SIGTERM 优雅停止，复用 lifespan 关闭流程，Task 1.13 验证）。
- 容器重启后保留数据库业务数据。
- 行情重新同步前不得使用失效数据撮合：已由现有机制保证（重启后内存订单簿为空，须收到有效订单簿才可撮合；重启恢复规则见 docs/08 §6.1，过期待执行订单不补执行）。
- 使用单 Worker 运行 FastAPI（调度与共享 Feed 依赖单进程，ADR 0007）。

### 数据持久化

- PostgreSQL 使用 Docker Named Volume。
- 支持 `pg_dump` 备份与恢复；支持容器重建后数据保留。
- 不允许默认清空正式模拟账户数据库。
- **不将 Docker Volume 视为唯一备份**；备份文件存放于项目外的本机目录，并在 Task 1.13 演练恢复。

### 平台与镜像

- 优先 macOS Apple Silicon（ARM64）。
- Multi-stage Docker Build；生产镜像不带全部开发依赖。
- 配置与环境变量通过 `.env` 管理，提供 `.env.example`，**不提交**本地敏感配置（`.gitignore`）。

## 决策原因

最小增量满足“本地可靠运行”：沿用现有单进程架构（ADR 0001/0007）、不改变数据模型，部署形态与数据隔离同时解决测试污染正式数据的风险。

## 影响范围

- 已新增：Backend/Frontend Multi-stage Dockerfile、`compose.yaml`、Nginx 配置、`.env.example`、备份恢复脚本、Backend 监听地址配置及 README 运行说明。
- 不影响：交易、撮合、持久化与 REST/WebSocket Contract。

## 验收（Task 1.13）

一键启停；迁移失败时业务服务不启动；容器重启与重建后数据保留；`pg_dump` 备份与恢复演练；WebSocket 经 Nginx 长连接与重连；仅本机回环可访问且除 8080 外无多余宿主机端口；重启恢复规则在容器重启下成立；测试不触及正式库。

## 当前状态

已实施并在 macOS ARM64 完成验收：构建、一键启动、迁移门禁、REST/WebSocket 反向代理、回环端口约束、Backend 重启后数据保留，以及 `pg_dump` 备份恢复演练。完整 Phase 1 联调与性能基线仍属于 Task 1.13 后续子任务。
