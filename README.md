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

