# Crypto Lab — Phase 1 最终验收报告

- 日期：2026-11-26
- 范围：Task 1.1～1.13
- 状态：**Accepted / Completed**（项目负责人于 2026-11-26 确认）
- Phase 0-B：Pending（独立长期研究，不因 Phase 1 验收而改变）

## 1. 验收结论

Phase 1 已完成只使用虚拟资金的现货模拟交易系统：真实公开行情接入、规范化市场状态、订单簿驱动撮合、限价单 TRADE_THROUGH、执行延迟、原子结算、PostgreSQL 持久化、REST/WebSocket 服务、React 前端及本地 Docker Compose 部署均已实施。

可自动验证的 Task 1.13 项目全部通过。项目负责人已确认 Task 1.13 及 Phase 1 验收，状态正式更新为 Accepted / Completed。Phase 0-B 保持独立 Pending，未被本结论替代。

## 2. 功能链路

| 范围 | 验收证据 | 结果 |
|---|---|---|
| 行情 | OKX 公开 Ticker / Trade / Order Book / Candle Adapter；时效性、序列、断线和重同步测试 | Pass |
| 市价单 | 多档撮合、VWAP、滑点、预算内部分成交、剩余取消 | Pass |
| 限价单 | Marketable Limit + GTC；TRADE_THROUGH；Maker/Taker；部分成交及取消 | Pass |
| 延迟 | ManualClock、多预设、延迟期间价格变化/取消、禁止未来行情 | Pass |
| 一致性 | 串行事件、内存 UoW、失败回滚、幂等、确定性 ID 和重放 | Pass |
| 账户/持仓 | Ledger 权威余额、Fill History 权威成交、Portfolio 增量更新及重建 | Pass |
| REST | 环境、账户、余额、订单、取消、成交、持仓、PnL、快照和幂等写入 | Pass |
| WebSocket | 订阅、心跳、背压、Replay/Resync、事务后发布、市场及交易事件 | Pass |
| 前端 | Market、下单、订单/成交、账户/持仓、环境隔离、断线恢复和错误态 | Pass |
| 部署 | ARM64 Multi-stage 镜像、迁移门禁、Readiness、Nginx REST/WS、Named Volume、备份恢复 | Pass |

## 3. 自动化结果

| 验证 | 结果 |
|---|---:|
| Python + PostgreSQL 完整回归 | **353 passed** |
| Ruff | **Pass** |
| Frontend Vitest | **129 passed / 26 files** |
| TypeScript + Vite Production Build | **Pass** |
| Playwright Chromium E2E | **13 passed** |
| Docker Compose Build / Up / Health | **Pass** |
| REST 经 Nginx | **201 / 200** |
| WebSocket 经 Nginx | **`crypto-lab.v1`, `session.ready`** |
| Backend 重启后数据保留 | **Pass** |
| `pg_dump` 备份恢复演练 | **Pass** |

E2E 使用真实 FastAPI、PostgreSQL、Dispatcher、Scheduler、撮合、WebSocket 和 React 应用，行情为不访问外网的确定性测试 Feed。覆盖下单确认、成交与余额变化、挂单/取消、行情失效与恢复、环境切换隔离、刷新恢复和断线重连。

## 4. 安全边界

代码和依赖复核未发现交易所私有下单/撤单接口、API Key、Secret、Passphrase、钱包或真实资产转移集成。外部网络仅限于交易所公开市场数据：

- OKX Public / Business WebSocket 的 books、trades 和 candles。
- OKX 公开 market ticker / history-candles REST。
- Phase 0 六家交易所公开 Ticker REST。

前端下单和取消只写入本地 FastAPI/PostgreSQL 模拟环境。系统不连接真实交易账户，不需要交易权限。

## 5. 性能基线

详细结果见 [`14-PHASE-1-PERFORMANCE-BASELINE.md`](14-PHASE-1-PERFORMANCE-BASELINE.md)。

- 1 / 3 / 5 / 10 / 20 环境的订单簿平均耗时分别为 4.586 / 13.813 / 27.416 / 52.842 / 106.467ms。
- 所有规模的成交、余额、持仓、流动性和事件顺序业务指纹一致。
- Dispatcher Error 为 0，Scheduler Lag 为预期的 25ms。
- 结果确认近似线性成本；Phase 1 保留环境隔离和路径依赖流动性语义，不引入未验证并行优化。

## 6. 已知限制与技术债

1. 订单簿处理成本随活跃环境数近似线性增长；真实高频行情 + 多环境可能产生 Feed 积压。
2. Phase 1 为本机单进程、单 Worker、内存 Event Hub；数据库提交后、WebSocket 发布前进程退出可丢失通知，客户端通过 REST Resync 恢复。
3. 公开市场数据无法提供真实排队位置或模拟订单的市场冲击；TRADE_THROUGH 是保守近似。
4. 前端仅完成 Chromium 自动 E2E；Safari / Firefox / Edge、读屏器、颜色对比度和 200% 缩放未完成人工验收。
5. 前端生产主 JS Chunk 约 743kB（gzip 约 234kB），尚未代码分割。
6. 前端真实高频订单簿下的长时间渲染稳定性未完成专项实验。
7. Phase 0-B 的24小时长期稳定性、延迟统计和套利机会研究仍为 Pending，不得由 Phase 1 短时验收替代。

## 7. 部署验收

ADR-0009 已实施。实测证据：

- PostgreSQL 16、独立 Alembic migrate task、单 Worker Backend、Nginx Frontend 全部 Healthy。
- 宿主机只暴露 `127.0.0.1:8080`（验收时使用隔离端口 18080）；Backend 8642 和 PostgreSQL 5432 只在 Compose 网络内可达。
- Nginx 经过 REST 创建/读取及 WebSocket Subprotocol 握手验证。
- Backend 重启后环境仍可读取。
- 备份后新增标记数据，执行恢复后该标记返回 404，证明已回到备份时点。
- 验收完成后专用容器、测试数据卷和临时数据库均已删除。

## 8. Git 与验收门禁

Task 1.13 主要提交：

- `d36457c feat(deploy): add local Docker Compose stack`
- `6277753 test(performance): add Phase 1 scalability baseline`

项目负责人已明确确认。验收状态同步通过文档检查后创建独立本地 Commit，不自动 Push。
