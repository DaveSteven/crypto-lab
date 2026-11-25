# Crypto Lab

Crypto Lab 是一个基于真实虚拟货币市场数据、使用虚拟资金进行交易和量化研究的个人实验平台。

当前处于 **Phase 0 — 技术可行性验证**。本阶段只验证公开市场数据的采集、标准化、质量检测和跨交易所价差分析，不连接真实交易账户或钱包，也不执行真实交易。

## 环境要求

- Python 3.12
- Git

本机可能安装了其他 Python 版本，请显式使用 `python3.12`。

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

运行公开 REST API smoke test：

```bash
python scripts/probe_rest.py
```

该命令会访问真实交易所公开接口，并将结果写入本地 `data/probes/`。它不会使用 API Key 或执行交易。

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

候选交易所、依赖和接口行为尚待真实验证。未经验证的内容不得标记为已验证结果。

