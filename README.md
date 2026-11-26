# Crypto Lab

Crypto Lab 是一个基于真实虚拟货币市场数据、使用虚拟资金进行交易和量化研究的个人实验平台。

项目当前并行推进 **Phase 1 基础模拟交易** 与 **Phase 0-B 长期实验**。Phase 0-A 已通过，Phase 0-B 仍为 Pending。项目不连接真实交易账户或钱包，也不执行真实交易；任何账户、余额及订单均为本地虚拟数据。

## 环境要求

- Python 3.12
- Git
- Docker Desktop / Docker Engine with Compose v2（本地容器化运行）

本机可能安装了其他 Python 版本，请显式使用 `python3.12`。

数据库迁移使用 Alembic。通过环境变量提供 PostgreSQL URL，禁止将真实凭据写入仓库：

```bash
export CRYPTO_LAB_DATABASE_URL='postgresql+psycopg://user:password@127.0.0.1:5432/crypto_lab'
.venv/bin/alembic upgrade head
```

PostgreSQL 集成测试仅在提供 `CRYPTO_LAB_TEST_DATABASE_URL` 时运行；未配置时自动跳过，不使用 SQLite 替代 PostgreSQL 验收。

## 启动本地模拟交易 API

完成数据库迁移后启动服务：

```bash
export CRYPTO_LAB_DATABASE_URL='postgresql+psycopg://user:password@127.0.0.1:5432/crypto_lab'
python -m crypto_lab.api
```

服务默认绑定 `127.0.0.1:8642`（可用 `CRYPTO_LAB_API_HOST` / `CRYPTO_LAB_API_PORT` 覆盖），OpenAPI 位于 `http://127.0.0.1:8642/docs`。Phase 1 尚无身份认证，不得将服务监听到公网。写接口必须提供 `Idempotency-Key`，所有余额和订单均为模拟数据。

## Docker Compose 本地运行

复制示例配置并设置一个仅用于本机的数据库密码：

```bash
cp .env.example .env
docker compose up --build --wait
```

完成后访问 `http://127.0.0.1:8080`。Compose 只将 Nginx 端口绑定到宿主机回环地址；Backend 和 PostgreSQL 仅在容器网络内可达。迁移任务成功后 Backend 才会启动。

```bash
docker compose down
```

`down` 不删除数据卷；除非明确要丢弃所有本地模拟数据，不要使用 `down -v`。备份和恢复使用项目外的绝对路径：

```bash
./scripts/backup_local_database.sh /absolute/path/crypto-lab-backup.sql
./scripts/restore_local_database.sh /absolute/path/crypto-lab-backup.sql --confirm-replace-local-data
```

恢复会替换当前 Local Production 数据库，并在操作期间停止 Backend 和 Frontend。

## 本地初始化

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.lock
python -m pip install -e . --no-deps
```

## 验证项目

```bash
python -m pytest
python -m ruff check .
```

Task 1.13 多环境性能基线仅允许对名称包含 `test` 的 PostgreSQL 数据库运行，且会清空该测试库：

```bash
export CRYPTO_LAB_TEST_DATABASE_URL='postgresql+psycopg://user:password@127.0.0.1:5432/crypto_lab_performance_test'
python scripts/run_phase1_performance_baseline.py \
  --output data/reports/phase1-performance-baseline.json \
  --confirm-reset-test-database
```

默认使用 1 / 3 / 5 / 10 / 20 个环境和 20 个确定性订单簿事件，生成结构化 JSON 报告；不访问交易所网络。

运行公开 REST API smoke test：

```bash
python scripts/probe_rest.py
```

该命令会访问真实交易所公开接口，并将结果写入本地 `data/probes/`。它不会使用 API Key 或执行交易。

验证 OKX `books` Canonical Adapter、序列连续性及公开交易规则：

```bash
python scripts/verify_okx_order_book.py --duration-seconds 15
```

该命令只访问公开行情接口，将容量受限的原始消息写入 `data/verification/`，并生成结构化 JSON 报告；不会创建或执行订单。

运行公开 WebSocket smoke test：

```bash
python scripts/probe_websocket.py
```

默认并发观察六家交易所 12 秒，并分别记录 Ticker、订单簿快照、增量、序列状态、心跳和数据时效性。Partial 或 Unsynced 结果不得用于交易分析。

获取并标准化六家交易所的实时 Ticker：

```bash
python scripts/normalize_tickers.py
```

标准化结果写入本地 `data/normalized/`，Decimal 在 JSON 中保存为字符串，缺失字段保存为 `null`。

记录所有方向的跨交易所毛价差：

```bash
python scripts/analyze_spreads.py
```

默认不假设未知手续费或再平衡成本，因此净收益为 `null`。只有显式提供完整成本参数时，工具才会生成标记为假设的净收益估算。

运行有界稳定性采集：

```bash
python scripts/run_stability_experiment.py
```

默认运行 300 秒；多交易所短时功能测试应显式使用 `--duration-seconds 60`。超过 300 秒的长期实验应作为独立进程执行，结束后再单独分析生成的 `summary.json`。脚本支持文件轮换、总容量限制和 `--log-level` 配置。

## 当前目录

```text
src/crypto_lab/   Python 源代码
tests/            自动化测试
docs/             项目设计与研究文档
data/             本地实验数据（运行数据不提交 Git）
```

## 项目文档

- [项目总体设计](docs/00-PROJECT-OVERVIEW.md)
- [Phase 0 开发计划](docs/01-PHASE-0-PLAN.md)
- [行情数据规范](docs/02-MARKET-DATA-SCHEMA.md)
- [开发规范](docs/AGENT.md)
- [Phase 1 开发计划](docs/06-PHASE-1-PLAN.md)
- [REST API 设计](docs/09-REST-API-DESIGN.md)
- [Phase 1 多环境性能基线](docs/14-PHASE-1-PERFORMANCE-BASELINE.md)
- [Phase 1 最终验收报告](docs/15-PHASE-1-ACCEPTANCE-REPORT.md)

候选交易所、依赖和接口行为尚待真实验证。未经验证的内容不得标记为已验证结果。

