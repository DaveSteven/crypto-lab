# Crypto Lab — 前端架构设计

## 0. 文档信息

| 属性 | 内容 |
|---|---|
| 文档版本 | V0.2 |
| 对应任务 | Phase 1 Task 1.12（Gate A 交付） |
| 状态 | Accepted（架构基线）/ 部分 Proposed（见 §10 差距） |
| 上游契约 | docs/09-REST-API-DESIGN.md、docs/10-REALTIME-SERVICE-DESIGN.md、ADR 0006/0007/0008 |
| 视觉与交互规范 | docs/12-UI-UX-DESIGN.md V1.1（Accepted） |

修订记录：

- V0.1（2026-11-26）：初始架构与接口调查（Task 1.12.1 旧划分）。
- V0.2（2026-11-26）：按已确认 UI/UX 规范 V1.1 与 Task 1.12 新划分全面修订——Desktop Only、Feature-based Architecture、API Capability Matrix、现状对照与剩余差距（含 ADR 0008 Proposed）。

## 1. 目标与边界

为 Phase 1 模拟交易系统定义前端技术架构、状态同步设计、接口能力矩阵与差距分析。

Desktop Only：仅支持桌面浏览器（最小视口 1280px），不实现移动端/平板布局。UI 布局、视觉与交互的权威来源是 docs/12；本文档不重复其内容。

前端只提交订单意图；成交价格、手续费与结果由服务端决定。不实现认证、公网部署或任何核心金融计算。

## 2. 技术选型（已安装版本为当前基线）

| 用途 | 选型 | 当前版本 |
|---|---|---|
| 包管理 | pnpm | 12.23 |
| 框架 | React + TypeScript | React 19.3 / TS 7.0 |
| 构建 | Vite | 8.3 |
| 样式 | Tailwind CSS | 4.3 |
| UI 组件 | shadcn/ui（基座已备：别名、cn、CSS 变量） | 随组件按需引入 |
| 图标 | Lucide React | 待 1.12.3（新划分）引入 |
| 服务端状态 | TanStack Query | 5.x |
| 客户端状态 | Zustand | 5.x |
| 路由 | React Router | 7.18 |
| 图表 | TradingView Lightweight Charts | 5.3 |
| 校验 | Zod | 5.x |
| 数值 | decimal.js | 4.x |
| 面板布局 | react-resizable-panels | 待 1.12.7 引入 |
| 实时通道 | 原生 WebSocket（crypto-lab.v1） | — |
| 单测 | Vitest + Testing Library | 5.1 |
| E2E | Playwright（Chromium） | 1.65 |

不引入功能重叠依赖；不提前安装后续阶段才需要的库。

## 3. 应用架构（Feature-based）

目标目录结构（docs/12 Instruction §5）：

```text
frontend/src/
├── app/            # 组合根：路由、Provider、Gateway 装配
├── pages/          # 路由页面（Trading / Overview / Markets / Settings）
├── features/       # 按领域组织：market / trading / account / workspace
│   └── <feature>/  # api.ts + store.ts + components/ + schema.ts
├── entities/       # 跨领域实体类型（canonical schemas）
└── shared/         # ui 基础组件、lib（format、decimal）、api 客户端核心
```

现状对照：当前代码为 `api/`（REST/WS/Sync 客户端，已稳定）、`state/`（stores）、`market/`、`pages/`、`realtime/`、`trading/`、`bootstrap/`。Task 1.12.3（新划分，Design System & App Shell）实施时迁移至上述 Feature 结构；迁移为机械性移动 + 路径更新，客户端层公共接口保持不变。

架构原则（与 V0.1 一致，继续有效）：

- REST 是权威快照来源，WebSocket 是通知通道；状态不一致以 REST Resync 收场。
- 契约类型全部由 Zod Schema 推导，不手写第二份 interface。
- 展示层不做核心金融计算；decimal.js 只做输入/展示换算，图表仅在展示边界转 Number。
- 单例 Gateway：每标签页一条 WS 连接绑定活动环境（ADR 0006/0007）。

## 4. REST / WebSocket 状态同步

V0.1 §4 的设计继续有效并已实现（`api/sync.ts`）：

1. WS 连接 → session.ready → 订阅（自动 resume_from 游标）。
2. 交易事件先缓冲；REST Snapshot（state_version V）到达后丢弃 `<= V` 的缓冲事件。
3. 按 `(state_version, event_index)` 排序应用，event_id 去重。
4. 之后实时应用；`delivery_sequence` 缺口或 `stream_id` 变更 → 全量 Resync；`stream_sequence` 缺口正常不处理。

补充（docs/12 §18 三态模型映射）：

- Connection State → 连接徽标（connecting/online/resync/offline 已实现）。
- Market Data State → quality 徽标 + 下单闸门（已实现）。
- Account Sync State → LOADING/SYNCED/RESYNCING/ERROR 待 1.12.9（新划分）在 Activity Panel 呈现。

环境切换（docs/12 §17.5）：Gateway 按 `env:account` 键重建连接并重置 trading/market store（已实现幂等 start）；TanStack Query 缓存按环境 key 前缀隔离（1.12.11 实施时落地）。

## 5. Candle 同步（实现状态）

已实现（`market/candles.ts` + `pages/MarketPage`）：

- 复合键 `(instrument, interval, open_ts)` 合并；已闭合 K 线不被未闭合覆盖；REST 页面对其时间戳权威；升序、5000 根上限。
- REST 历史 seed + WS upsert；分页 `before` 游标；resync 后 `after` 拉取缺口。

待实现（新划分 1.12.6 收尾）：

- 初始化竞争处理：历史请求与实时消息竞态（当前以 seedCandles 合并缓解，需加请求代次标记隔离迟到响应）。
- Volume 副图、Last Price Line、成交标记（§9.6）。
- 缺失区间无法补齐时的显式"数据缺失"标记。
- 多周期实时订阅（ADR 0008，后端前置）。

## 6. API Capability Matrix

以实际源码与契约为准（2026-11-26）。S=Supported / P=Partially Supported / N=Not Supported。

| Feature | Endpoint / Topic | Status | Gap | Required Change |
|---|---|---|---|---|
| Environment List | GET /api/v1/environments | N | 无列表端点 | 可选新增（现用本地会话持久化） |
| Environment Creation | POST /environments | S | — | — |
| Environment Switching | 本地会话 + Gateway | S | Query 缓存隔离未落地 | 1.12.11 前端实现 |
| Account List | GET /accounts | S | — | — |
| Account Default Latency | — | N | 后端无账户级默认延迟字段；仅订单级 latency_preset | 最小扩展：paper_accounts 增加 default_latency 列 + 创建/更新参数；或 Phase 1 前端记住上次选择（本地偏好） |
| Account Snapshot | GET /accounts/{id} | S | — | — |
| Full Snapshot | GET /snapshot | S | — | — |
| Balances | GET + WS `balances` | S | — | — |
| Positions | GET + WS `positions` | P | 无当前估值价格/市值（§12.5） | 前端以 ticker × quantity 显示参考估值并明确标注；或后端后续提供估值端点 |
| Orders | GET + WS `orders` | S | 游标分页未实现（limit ≤ 200） | 按 docs/09 当前限制记录 |
| Order Submission | POST /orders | S | 订单预估不存在（见 Order Preview） | — |
| Order Cancellation | POST /orders/{id}/cancel | S | — | — |
| Executions | GET + WS `executions` | S | Maker/Taker 标记未入库 | 后端执行记录补 taker/maker 字段（Task 1.12 前后端对齐时评估） |
| Execution Details | GET /executions/{id} | S | 滑点分析字段未持久化 | Execution Detail Drawer 仅展示已存在字段（§14.2 "后端数据支持的情况下"） |
| Market Rules | — | N | 无 REST 端点 | 前端静态配置（OKX:DOCUMENTED:SPOT:V1 同源），标注 Documented |
| Ticker | WS `market.ticker` | S | 无 REST 快照端点 | 首屏空窗可接受；可选增强 GET /market/ticker |
| Order Book | WS `market.order_book` | S | 无 depth 订阅过滤（推送合并后全量） | 前端切片 top-N |
| Market Trades | WS `market.trade` | S | 有界列表前端实现 | — |
| Market Quality | WS `market.quality` | S | — | — |
| Historical Candles | GET /market/candles | S | — | — |
| Realtime Candles | WS `market.candle` | P | 仅常驻周期实时推送 | ADR 0008（Proposed） |
| Multi-interval Subscription | — | P | 静态周期列表，非动态引用计数 | ADR 0008 实施 |
| Order Preview | — | N | 无后端预估 API | 预估手续费 = 数量×限价/参考价×费率（本地参考估算，明确标注）；预估成交金额同法；VWAP/Slippage 不展示 |
| state_version | Snapshot + WS 事件 | S | — | — |
| Replay | resume_from | S | — | — |
| REST Resync | snapshot + sync 层 | S | — | — |

## 7. Backend Gap Handling（Instruction §7 对应）

1. **Candle 多周期**：ADR 0008（Proposed）。实施前过渡策略：`CRYPTO_LAB_FEED_CANDLE_INTERVALS=1m,5m,15m,1h,4h,1d` 全量常驻（本地带宽可接受），六周期即具备实时能力；ADR 0008 作为带宽优化后续实施。
2. **Account Default Latency**：后端无此字段。最小扩展建议：`paper_accounts.default_latency_preset` 可空列 + 设置页更新端点；Phase 1 允许前端以"上次使用"本地偏好替代并明确标注。需负责人确认采用哪种。
3. **Order Preview**：无后端预估。确认 Dialog 展示本地参考估算（费率 × 名义额），标注"本地参考估算，非实际撮合结果"；VWAP/Slippage 不展示（docs/12 §11.4 允许）。
4. **Overview 估值**：持仓估值 = ticker.last/中间价 × 数量，标注估值币种 USDT 与数据时间；无历史快照前不实现收益曲线；无法估值的资产明确列出。
5. **Executions Maker/Taker**：后端执行记录无该字段 → Drawer 不展示该行（"后端数据支持的情况下"），或后端补充字段（建议后续 Task 评估）。

## 8. 金融精度

API Decimal 字符串保留精度；Zod 校验响应结构；decimal.js 承担输入换算（如 25%/50% 快捷计算须以 Decimal 实现）；图表边界才转 Number；原始字符串不被覆盖；数量遵循静态 Market Rules 配置。

## 9. Testing Strategy

- **Unit（Vitest）**：Decimal 处理、表单校验、状态映射、Candle 合并、序列处理、事件去重、布局配置持久化——已覆盖核心部分，随新模块补充。
- **Component（RTL）**：Order Entry / Preview / 状态 / 取消 / 连接状态 / 质量 / Empty-Error / Term Tooltip——已有基础，按 docs/12 补充确认 Dialog 与 Tooltip。
- **Integration**：REST Snapshot + WS 更新（已实现层测试）、Reconnect/Replay/Resync/State Version（已覆盖）、Environment Switching、周期切换、分页、重复/迟到事件（1.12.6 补充）。
- **E2E（Playwright）**：真实后端 + 独立测试库 + 关闭 Feed；已覆盖引导/下单意图/订单表/账户/会话恢复；补充确认流程、成交与余额变化、行情失效禁用、布局持久化。**运行须知：本机系统代理会拦截 Playwright 的就绪探测，须以 `env -u HTTP_PROXY -u HTTPS_PROXY` 运行**（已验证）。
- **桌面验收矩阵**：1280×720 / 1440×900 / 1920×1080 / 2560×1440（docs/12 §21.1）；不要求移动端 E2E。

## 10. 差距清单（现行有效）

| 编号 | 内容 | 状态 |
|---|---|---|
| G1 | 多周期推送 | 已解决（静态列表）；动态订阅 → ADR 0008 Proposed |
| G2/G3 | executions/positions 推送 | 已解决 |
| G4 | 订单簿 depth 过滤 | 前端切片（可接受） |
| G5 | 环境列表端点 | 本地会话替代；可选增强 |
| G6 | instrument 元数据端点 | 前端静态配置（Documented） |
| G7 | 行情快照端点 | 可选增强 |
| G8 | 游标分页 | 按 docs/09 限制记录 |
| G9 | 账户默认延迟字段 | 最小扩展方案待负责人确认（§7.2） |
| G10 | 订单预估 API | 本地参考估算替代（§7.3） |
| G11 | 执行记录 Maker/Taker 字段 | Drawer 暂不展示；后续评估 |

## 11. 已确认事项

1. Phase 1 不进行容器化部署（2026-11-26）。
2. 后端默认端口 8642（2026-11-26）。
3. Desktop Only，最小视口 1280px（2026-11-26，UI/UX V1.1）。
4. E2E 运行须剥离系统代理环境变量（2026-11-26，已验证）。
