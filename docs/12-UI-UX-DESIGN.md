# Crypto Lab — UI/UX Design Specification

## 0. 文档信息

| 属性 | 内容 |
|---|---|
| 文档名称 | Crypto Lab UI/UX Design Specification |
| 文件路径 | docs/12-UI-UX-DESIGN.md |
| 版本 | V1.2（Global UI Polish） |
| 对应阶段 | Phase 1 / Task 1.12 |
| 设计状态 | Accepted |
| 产品类型 | Personal Market Research & Paper Trading Platform |
| 主要平台 | Desktop Web Application |

修订记录：

- V1.0（2026-11-26）：项目负责人确认初始设计规范。
- V1.1（2026-11-26）：项目负责人确认 **Desktop Only 修订**——仅面向桌面浏览器，不进行移动端和平板适配；覆盖原文档中所有移动端及响应式降级要求（§1、§3.5、§7.2、§21、§25 相应更新，其余已确认设计及核心金融规则不变）。
- V1.2（2026-11-26）：统一非交易页容器、标题、卡片、表格和空状态；优化 Trading、Overview、Markets、Settings 的信息层级，并建立共享金融数据显示组件。保持 Desktop Only 与既有金融规则不变。

### 0.1 V1.2 全局精修补充

- Overview、Markets、Settings 使用最大宽度 1440px 的统一 PageContainer；桌面页面边距为 24～32px。
- 页面标题为 24px，正文默认 14px，表格 13px，辅助文字 12px；交易工作台允许为数据密度保留 12～13px 金融表格。
- 卡片圆角、边框、内边距、空状态与状态标识统一，避免渐变、玻璃拟态及无业务意义的动画。
- 金融展示使用等宽表格数字；单位采用次要文字样式，悬停可查看原始精度。显示格式化不得参与订单计算。
- Overview 明确区分总资产、可用、冻结、持仓市值、已实现与未实现盈亏及手续费；估值继续仅使用有效买一价。
- Markets 仅展示 Feed 实际支持的真实品种与行情，不生成虚假走势图或缺失数据。
- Settings 采用左侧分类导航与右侧内容；普通设置与系统诊断分离，内部标识收纳到技术详情。
- 账户默认执行延迟的服务端持久化尚未实现，界面必须如实说明；实际手续费由服务端决定，前端费率仅作为预览参考。

### 0.2 金融数字显示规范

- USDT 资产、可用/冻结资金、已实现/未实现盈亏默认显示 2 位小数并增加千位分隔符。
- 价格按品种 Tick Size 显示；持仓数量按品种精度显示；订单簿数量及累计数量默认最多 6 位小数。
- 24h 成交量与普通百分比默认 2 位小数；Spread 百分比自适应至最多 6 位；执行延迟显示整数毫秒。
- 极小非零手续费和数量使用自适应精度或小于阈值形式，不得显示为零。
- 正盈亏带 `+`，负盈亏为红色，零值使用中性色；金融数字统一使用 Tabular Numbers。
- 单位使用较小的次要文字；紧凑值悬停可查看原始完整精度，订单簿可切换紧凑/完整精度。
- 输入框保留实际交易精度。所有格式化仅在展示层执行，订单计算、API Contract、数据库与撮合继续使用原始 Decimal 值。

## 1. 产品定位

Crypto Lab 是一个基于真实市场数据和虚拟资金的个人金融研究与模拟交易平台。

核心目标：

- 学习金融交易知识。
- 理解真实市场运行机制。
- 进行模拟现货交易。
- 分析交易执行质量。
- 研究手续费、滑点及执行延迟。
- 为未来套利、历史回放及量化策略实验提供基础。

产品不是商业交易所，不涉及真实资金交易。

不提供充值、提现、真实交易账户绑定、营销活动及投资推荐。

Phase 1 仅面向桌面浏览器（Desktop Only）。

## 2. 已确认的 UI/UX 决策

| 项目 | 最终决定 |
|---|---|
| 整体风格 | Hybrid：专业交易终端 + Linear 极简设计 |
| 默认主题 | Dark |
| 品牌强调色 | Teal |
| 全局导航 | Top Navigation |
| 交易布局 | Resizable Panels |
| 默认语言 | 简体中文，保留必要英文术语 |
| 默认首页 | Trading |
| 学习辅助 | 静态金融术语 Tooltip |
| 下单确认 | 每次下单必须确认 |
| 涨跌颜色 | 国际惯例，绿涨红跌 |
| 订单簿及成交 | 同面板 Tab 切换 |
| 默认 K 线周期 | 1m |
| 布局保存 | 自动保存 |
| 环境管理 | 顶部环境选择器 |
| 延迟设置 | 账户默认值，下单时允许覆盖 |
| 设备范围 | Desktop Only，最小视口宽度 1280px |

以上为项目负责人已确认的设计决策。

未经确认不得改变。

## 3. Design Principles

### 3.1 Professional

保持专业金融交易终端的信息密度、数据精度及操作效率。

### 3.2 Minimal

参考 Linear 的视觉设计：

- 扁平化面板。
- 清晰视觉层级。
- 克制的颜色。
- 紧凑但可读的排版。
- 统一组件规范。

不使用玻璃拟态、复杂渐变、大面积阴影及无意义动画。

### 3.3 Data Integrity

所有正式展示的行情、成交、资产、持仓及盈亏必须具有真实数据依据。

禁止：

- 伪造行情。
- 随机生成收益曲线。
- 使用 Mock 数据掩盖接口异常。
- 将历史行情显示为当前实时行情。
- 将预估成交结果显示为实际成交结果。

### 3.4 Learning-oriented

在必要的专业术语旁提供静态 Tooltip。

不引入 AI、LLM 或自动投资建议。

### 3.5 Desktop Only

仅面向桌面浏览器，不为移动端和平板做专门适配。

- 保持专业金融交易终端的信息密度。
- 不为了移动端适配牺牲桌面布局。
- 不引入移动端专用导航、Drawer 或 Touch Gesture 组件。
- 不重复维护桌面端及移动端组件。
- 保留键盘操作及基本 Accessibility 支持。

## 4. Design System

### 4.1 Dark Theme Tokens

| Token | Value |
|---|---|
| background.canvas | #101418 |
| background.surface | #181E25 |
| background.elevated | #202832 |
| border.default | #303943 |
| border.strong | #45505C |
| text.primary | #E8EDF2 |
| text.secondary | #94A3B8 |
| text.muted | #64748B |
| brand.primary | #2DD4BF |
| brand.hover | #5EEAD4 |
| semantic.positive | #22C55E |
| semantic.negative | #EF4444 |
| semantic.warning | #F59E0B |
| semantic.info | #60A5FA |
| semantic.neutral | #94A3B8 |
| action.buy | #15803D |
| action.sell | #B91C1C |

所有颜色通过 CSS Variables 和 Semantic Tokens 管理。

禁止在业务组件中大量硬编码颜色。

品牌色仅用于：

- 当前选中状态。
- 全局主要操作。
- Focus Ring。
- 品牌标识。
- 非涨跌性质的重点数据。

不得将品牌色与盈利颜色混淆。

### 4.2 Market Color

采用国际金融市场颜色惯例：

- 上涨：绿色。
- 下跌：红色。
- 买入：绿色。
- 卖出：红色。
- 中性：灰色。

颜色不能作为唯一状态识别方式。

同时使用文字、正负号、方向图标及状态说明。

### 4.3 Typography

| 类型 | 字体 |
|---|---|
| 中文 | Noto Sans SC |
| 英文 | Inter |
| 数字 | Tabular Numbers |
| ID / 调试信息 | Monospace |

推荐使用本地字体资源及系统字体回退，避免运行时依赖外部字体 CDN。

### 4.4 Font Scale

| 使用场景 | 字号 |
|---|---:|
| 状态栏、辅助信息 | 11px |
| 紧凑表格、次要数据 | 12px |
| 常规正文、数据 | 13px |
| 表单及常规标题 | 14px |
| 面板标题 | 16px |
| 重要数据 | 20px |
| 最新行情价格 | 24px |

金融数字使用 font-variant-numeric: tabular-nums。

表格中的价格、金额、数量默认右对齐。

### 4.5 Spacing

采用 4px 基础间距系统。

可用间距：

4 / 8 / 12 / 16 / 20 / 24 / 32px。

交易终端面板之间优先使用紧凑间距。

### 4.6 Border Radius

| 组件 | 圆角 |
|---|---:|
| 交易面板 | 4px |
| 按钮 | 6px |
| 输入框 | 6px |
| Tooltip | 6px |
| Dialog | 8px |
| Drawer | 8px 或无外侧圆角 |

### 4.7 Component Dimensions

| 组件 | 默认尺寸 |
|---|---:|
| Top Navigation | 48px |
| Market Header | 64px |
| Status Bar | 24px |
| Table Row | 32px |
| Compact Table Row | 26px |
| Input | 36px |
| Button | 36px |
| Compact Button | 28px |
| Panel Header | 36px |

### 4.8 Animation

普通交互动画控制在100～180ms。

禁止：

- 每次行情变化触发复杂过渡。
- 高频价格变化导致布局移动。
- K线更新时重新播放完整动画。
- 大面积闪烁效果。

支持 prefers-reduced-motion。

### 4.9 Theme

Phase 1 默认实现完整 Dark Theme。

保留 Light Theme Token 扩展能力。

未完成浅色主题前，不展示不可用的主题切换入口。

## 5. Information Architecture

### 5.1 Phase 1 页面

| 页面 | 路由 |
|---|---|
| Trading | /trading |
| Overview | /overview |
| Markets | /markets |
| Settings | /settings |

根路径 / 默认重定向至 /trading。

### 5.2 后续页面

- /arbitrage
- /replay
- /strategies
- /analytics

后续功能未完成前不展示对应导航入口。

不创建无实际功能的 Coming Soon 页面。

## 6. Global Application Shell

### 6.1 Top Navigation

左侧：

- Crypto Lab 品牌。
- 概览。
- 交易。
- 市场。

右侧：

- 当前模拟环境选择器。
- 当前账户选择器（仅在需要时展示）。
- Paper Trading 标识。
- WebSocket 连接状态。
- 设置入口。

全局导航不占用额外侧边栏空间。

### 6.2 Paper Trading Identity

交易页面必须明确区分：

- 真实市场行情。
- 虚拟资金。
- 模拟成交。

全局保留稳定、克制的模拟交易标识。

### 6.3 Status Bar

底部状态栏显示：

- Exchange Feed 状态。
- 当前数据质量。
- 最近行情接收时间或 Event Age。
- Browser WebSocket 状态。
- 账户同步状态。
- 当前显示时区。

不得将 Event Age、心跳 RTT 或 Scheduler Lag 描述为真实交易所成交延迟。

## 7. Trading Workspace

### 7.1 Layout

页面采用：

Top Navigation
→ Market Header
→ Three-column Trading Workspace
→ Account Activity Panel
→ Status Bar。

三栏区域：

- 左：Candlestick Chart。
- 中：Order Book / Market Trades。
- 右：Order Entry。

底部：

- Open Orders。
- Order History。
- Executions。
- Balances。
- Positions。

### 7.2 Default Layout

默认主区域宽度：

| Panel | Width |
|---|---:|
| Candlestick Chart | 54% |
| Order Book | 21% |
| Order Entry | 25% |

默认底部 Activity Panel 占可用工作区高度的28%。

建议桌面端最小宽度：

- Chart：420px。
- Order Book：240px。
- Order Entry：280px。

最小支持浏览器视口宽度为 1280px；低于最小支持宽度时显示简洁的桌面端使用提示，不实现窄屏降级布局，不产生页面级横向滚动。

### 7.3 Resizable Panels

建议使用 react-resizable-panels 或等价方案。

支持：

- 横向调整三栏宽度。
- 纵向调整底部面板高度。
- 折叠允许折叠的辅助面板。
- 恢复默认布局。
- 自动保存布局。
- 浏览器刷新后恢复。

限制：

- Phase 1 不支持自由拖拽重排。
- 不支持任意新增面板。
- 不支持复杂多工作区系统。

LocalStorage 中保存带版本号的布局配置。

布局损坏或版本不兼容时恢复默认值。

面板分隔线应具备明确的拖动反馈及键盘操作能力。

## 8. Market Header

展示：

- 交易对选择器。
- Exchange。
- Market Type。
- Latest Price。
- 24H Change。
- 24H High。
- 24H Low。
- 24H Volume。
- Market Quality。

初始交易对：

- BTC/USDT。
- ETH/USDT。

初始交易所：

- OKX。

初始市场：

- Spot。

所有统计指标以实际后端 Contract 为准。

后端未提供的数据使用 --，不得构造数值。

## 9. Candlestick Chart

### 9.1 Chart Library

使用 TradingView Lightweight Charts。

不得自行从零实现完整 K 线图渲染引擎。

### 9.2 Default Configuration

- 默认周期：1m。
- 默认初始历史数据：300根。
- 支持按需分页。
- 显示 OHLC。
- 显示 Volume。
- 显示 Last Price Line。
- 显示 Crosshair。
- 支持滚轮缩放。
- 支持拖动。
- 支持全屏。
- 支持返回实时位置。

### 9.3 Supported Intervals

- 1m
- 5m
- 15m
- 1h
- 4h
- 1d

所有周期必须具备真实历史及实时数据能力。

UTC 周期边界由 Canonical Candle 定义。

本地时区转换只影响展示，不改变 K 线身份或周期边界。

### 9.4 REST / WebSocket Merge

使用以下复合身份：

- exchange_id
- instrument_id
- interval
- open_ts_ms

处理规则：

- REST 加载历史 K 线。
- WebSocket 更新当前 Candle。
- 同身份数据进行合并。
- 已闭合 Candle 不得被迟到的未闭合事件覆盖。
- 重复数据不得产生重复 K 线。
- 切换品种或周期时隔离旧订阅及迟到响应。
- 断线后通过 REST 查询补齐缺失区间。
- 无法补齐的区间明确标记数据缺失。
- 不生成虚假的零成交量 K 线。

初始化时必须处理历史查询与实时消息之间的竞争，避免丢失或覆盖更新。

### 9.5 Multi-interval Subscription

根据前端实际订阅动态管理上游 Candle Channel。

建议：

- 相同交易对及周期复用订阅。
- 使用引用计数或等价机制管理订阅生命周期。
- 限制上游订阅数量。
- 不为每个浏览器连接建立独立交易所连接。
- 断线恢复时重新订阅有效频道。

具体后端变更需同步更新 ADR、REST / WebSocket Contract 和测试。

### 9.6 Personal Trade Markers

支持在 K 线图显示当前模拟账户的实际成交标记。

- Buy Marker。
- Sell Marker。
- 成交时间。
- 成交均价或实际成交价。
- 成交数量。
- 关联 Order ID。

同一订单多档成交或多个部分成交时，可进行视觉聚合，但详情必须可追溯至实际 Fill。

不得使用挂单时间代替成交时间。

### 9.7 Future Enhancements

当前限价挂单价格线作为可选增强。

以下功能不属于 Phase 1 强制范围：

- MA / EMA。
- RSI。
- MACD。
- 自定义画线工具。
- 多图表联动。
- 高级指标编辑器。

## 10. Order Book Panel

采用 Tab 切换：

- 订单簿。
- 最新成交。

默认显示订单簿。

### 10.1 Order Book

展示：

- Ask Price。
- Ask Quantity。
- Bid Price。
- Bid Quantity。
- Best Ask。
- Best Bid。
- Spread。
- 累计深度背景条。

默认展示真实市场订单簿。

不得将真实市场深度描述为保证可以获得的模拟成交数量。

模拟环境已消耗的流动性可能影响实际模拟成交结果。

点击订单簿价格时，可将价格填入限价单输入框，但不得自动下单。

### 10.2 Market Trades

展示：

- 成交时间。
- 价格。
- 数量。
- 主动成交方向。

明确区分：

- 最新成交：真实市场 Trade。
- 成交记录：当前用户的模拟 Fill。

最新成交列表使用有界内存。

高频更新不得导致整个 Trading Workspace 重新渲染。

## 11. Order Entry

### 11.1 Supported Orders

Phase 1：

- Market Buy。
- Market Sell。
- GTC Limit Buy。
- GTC Limit Sell。

不提供：

- 杠杆。
- 合约。
- 保证金。
- 真实交易。
- 未实现的高级条件单。

### 11.2 Form Fields

公共字段：

- Buy / Sell。
- Market / Limit。
- Quantity。
- Available Balance。
- Allocation Percentage。
- Execution Latency。

限价单额外字段：

- Limit Price。

市价买单：

- 明确显示最大资金预算。
- 预算包含适用手续费。
- 显示实际接口要求的数量及预算字段。

百分比快捷选择：

25% / 50% / 75% / 100%。

使用 decimal.js 或等价 Decimal 工具处理表单计算及精度。

禁止通过 JavaScript 浮点运算承担权威金融计算。

### 11.3 Execution Latency

账户具有默认模拟执行延迟。

下单时允许修改本次订单延迟。

候选预设：

- 0ms。
- 50ms。
- 100ms。
- 250ms。
- 500ms。
- 1000ms。
- Custom（后端支持时）。

修改单笔订单延迟不自动改变账户默认设置。

账户默认值的持久化方式及支持字段以实际后端能力为准。

### 11.4 Order Preview

下单前必须显示确认预览。

展示：

- 当前模拟环境。
- 当前账户。
- 交易品种。
- 买卖方向。
- 订单类型。
- 订单数量。
- 限价或参考报价。
- 最大资金预算。
- 预估手续费。
- 预估成交金额。
- 模拟执行延迟。

预估 VWAP 和 Slippage 仅在具有可靠计算依据时展示。

优先使用后端提供的预估能力。

若当前接口不支持完整预估，可显示明确标记的本地参考估算，但不得将其视为实际撮合结果。

### 11.5 Submission Flow

填写订单
→ 客户端基础校验
→ 展示确认 Dialog
→ 用户确认
→ 调用 REST
→ 接收服务端订单结果
→ WebSocket 实时更新
→ 必要时 REST Resync。

必须满足：

- 每笔订单均经过确认。
- 不提供关闭下单确认的设置。
- 请求进行期间禁用重复提交。
- 使用 REST 幂等机制。
- 请求超时时不得直接生成新订单身份盲目重试。
- 服务端确认之前不得伪造成功订单。
- 服务端接受订单不等于订单已经成交。
- 最终状态由后端决定。

### 11.6 Market Buy Budget

严格遵循已确认的后端规则：

- 预算内部分成交。
- 剩余未成交数量取消。
- 剩余冻结资金释放。
- 不自动追加账户资金。
- 不允许透支。

GTC Limit Order 不得错误套用市价单剩余自动取消规则。

### 11.7 Unavailable Market

行情不可用、账户状态未同步或必要数据缺失时，禁用依赖这些数据的新订单提交。

明确说明禁用原因。

取消订单仍应允许通过可用 REST 服务发起，不应因行情 Feed 失效而被无条件禁止。

## 12. Account Activity Panel

默认 Tab：

当前委托。

支持：

- 当前委托。
- 历史订单。
- 成交记录。
- 资产余额。
- 持仓盈亏。

### 12.1 Open Orders

候选字段：

- 创建时间。
- 交易对。
- 方向。
- 类型。
- 限价。
- 委托数量。
- 已成交数量。
- 剩余数量。
- 状态。
- 取消操作。

支持取消单笔订单。

Phase 1 不强制实现批量取消，除非现有 REST Contract 已支持。

### 12.2 Order History

展示完整订单生命周期。

支持按实际接口能力进行：

- 时间筛选。
- 交易对筛选。
- 订单状态筛选。
- 买卖方向筛选。
- 分页。

### 12.3 Executions

展示：

- 成交时间。
- 成交价格。
- 数量。
- 成交金额。
- Maker / Taker。
- 手续费。
- Order ID。
- Fill ID。

支持打开 Execution Detail Drawer。

### 12.4 Balances

展示：

- Asset。
- Total。
- Available。
- Locked。

余额以 Account Ledger 对外提供的权威投影为准。

### 12.5 Positions

展示：

- Asset / Instrument。
- Quantity。
- Average Cost。
- Current Valuation Price。
- Market Value。
- Realized PnL。
- Unrealized PnL。

是否支持相关字段以实际后端 Contract 为准。

已平仓资产不得继续显示为有效非零持仓。

行情失效时，不将过期估值显示为当前实时估值。

## 13. Order Status Design

中文展示映射：

| Logical Status | 中文 |
|---|---|
| PENDING_EXECUTION | 等待执行 |
| OPEN / RESTING | 挂单中 |
| PARTIALLY_FILLED | 部分成交 |
| FILLED | 全部成交 |
| CANCELLED | 已取消 |
| REJECTED | 已拒绝 |

以上为 UI 逻辑状态。

实际枚举以现有后端为准。

对于部分成交后取消的订单，应同时展示：

- 最终订单状态。
- 已成交数量。
- 已取消剩余数量。

不得仅显示已取消而隐藏历史成交。

## 14. Execution Detail Drawer

支持从订单记录或成交记录打开详情。

### 14.1 Basic Information

- Order ID。
- Fill ID。
- Exchange。
- Instrument。
- Side。
- Order Type。
- Quantity。
- Status。
- Time。

### 14.2 Execution Analysis

在后端数据支持的情况下展示：

- Submission Reference Price。
- Execution Reference Price。
- VWAP。
- Order Book Slippage。
- Execution Price Drift。
- Total Slippage。
- Fee。
- Fee Rate。
- Maker / Taker。
- 实际各档 Fill。

滑点与手续费分开显示。

不得重复计算已经包含于成交价格中的滑点成本。

### 14.3 Latency Analysis

展示：

- Configured Latency。
- Scheduled Execution Time。
- Actual Execution Time。
- Scheduler Lag。
- Actual Simulated Delay。

明确：

Actual Simulated Delay 不等于真实交易所网络延迟。

### 14.4 Learning Tooltips

对专业指标提供统一静态解释。

例如：

- Spread。
- VWAP。
- Slippage。
- Maker。
- Taker。
- PnL。
- Liquidity。
- Scheduler Lag。
- TRADE_THROUGH。

Tooltip 支持鼠标悬停和键盘聚焦。

## 15. Overview Page

目标：

展示当前模拟账户资产及基础交易成果。

候选模块：

- 总资产。
- 可用资金。
- 冻结资金。
- 已实现盈亏。
- 未实现盈亏。
- 累计手续费。
- 资产分布。
- 当前持仓。
- 最近模拟成交。

账户资产估值应明确：

- 估值币种。
- 数据时间。
- 是否存在无法估值的资产。

未具备可靠历史快照数据之前，不实现虚假的账户收益曲线。

以下高级统计延后：

- Sharpe Ratio。
- Maximum Drawdown。
- Win Rate。
- 风险分析。
- 策略收益对比。

## 16. Markets Page

第一版只展示实际已接入市场。

字段：

- Instrument。
- Exchange。
- Latest Price。
- 24H Change。
- 24H Volume。
- Data Quality。

支持：

- 搜索。
- 基础排序。
- 点击交易对进入 Trading 页面。

不展示不存在的数据源或不可用交易所。

## 17. Settings Page

### 17.1 Simulation Environment

- 查看已有模拟环境。
- 创建模拟环境。
- 修改允许修改的环境信息。
- 切换当前环境。

是否支持删除或重置由现有 REST Contract 决定。

具有破坏性的操作必须单独确认。

### 17.2 Account Settings

- 当前模拟账户。
- 虚拟初始资金配置（后端支持时）。
- 默认执行延迟。
- 可读取的手续费配置。
- 其他已实现的实验参数。

不得直接修改已结算历史流水或成交记录。

### 17.3 Workspace Settings

- 恢复默认面板布局。
- 本地布局偏好。
- 显示时区。
- 其他已实现的展示设置。

### 17.4 System Status

- API 状态。
- WebSocket 状态。
- Exchange Feed 状态。
- Market Quality。
- 当前配置的行情品种及周期。
- 可读取的 Scheduler 配置。

### 17.5 Environment Switching

切换环境时：

- 取消旧环境订阅。
- 清理旧环境实时状态。
- 隔离查询缓存。
- 加载目标环境权威快照。
- 建立目标环境 WebSocket 订阅。
- 完成状态同步后恢复交易操作。

不得将旧环境订单、余额及持仓短暂显示到新环境。

## 18. Realtime UX

分别维护：

### Connection State

- CONNECTING。
- CONNECTED。
- RECONNECTING。
- DISCONNECTED。

### Market Data State

- VALID。
- STALE。
- SYNCING。
- UNAVAILABLE。

### Account Sync State

- LOADING。
- SYNCED。
- RESYNCING。
- ERROR。

以上为前端候选展示模型，需映射至实际 Contract。

### 18.1 Reconnect

- 使用带退避的自动重连。
- 按实际协议恢复订阅。
- 使用 stream_id 和有效 Replay 游标。
- 无法恢复时执行 REST Resync。
- Resync 完成前不将旧账户状态视为最新状态。

### 18.2 Data Quality

行情失效时：

- 保留可明确标记的历史数据。
- 显示失效或延迟状态。
- 禁止依赖失效行情的新交易操作。
- 不切换至伪造数据。

### 18.3 Sequence Handling

按照已确认 WebSocket Contract：

- 正常 stream_sequence 缺口不代表数据丢失。
- 使用实际 delivery_sequence 检测传输连续性。
- event_id 用于业务事件去重。
- state_version 用于业务快照一致性。

具体恢复策略以实际协议为准。

## 19. State Management

### TanStack Query

负责 REST 服务端数据：

- Environments。
- Accounts。
- Balances。
- Positions。
- Orders。
- Executions。
- Historical Candles。

### Zustand

负责客户端状态及必要的实时状态：

- 当前环境及账户。
- 当前交易对。
- 当前 Candle 周期。
- 工作区偏好。
- WebSocket 生命周期。
- 高频市场视图。

避免在多个 Store 中重复维护同一个权威订单或余额状态。

必须明确 REST Cache 与 WebSocket 更新之间的状态所有权。

## 20. Performance

要求：

- 高频行情与 React 渲染频率分离。
- Chart 使用增量更新。
- 避免每条 Candle 消息重新创建图表。
- 避免 Ticker 更新导致整个页面渲染。
- 使用细粒度 Store Selector。
- 订单簿使用稳定行结构。
- 最新成交及历史缓存有界。
- 大型列表按需分页或虚拟化。
- 组件卸载时释放订阅、Timer 和事件监听。

不得在前端重复实现交易撮合引擎。

## 21. Viewport & Device Requirements

- 仅支持桌面浏览器；不实现移动端和平板专用布局。
- 最小支持浏览器视口宽度：1280px；最小建议视口高度：720px。
- 保持桌面端三栏交易工作台布局。
- 支持桌面浏览器窗口缩放、面板拖动调整尺寸、布局自动保存及恢复。
- 不实现窄屏单栏交易页面。
- 低于最小支持宽度时，显示简洁的桌面端使用提示。
- 以上尺寸均指 CSS Viewport Pixels，而非设备物理分辨率。

### 21.1 Desktop Acceptance Matrix

至少验证以下浏览器视口尺寸：

- 1280 × 720
- 1440 × 900
- 1920 × 1080
- 2560 × 1440

主要浏览器：

- Chrome
- Safari
- Edge
- Firefox

优先保证 macOS Chrome 和 Safari 的体验。

## 22. Loading / Empty / Error

每个核心模块必须具备：

- Loading。
- Empty。
- Error。
- Stale / Reconnecting（适用时）。

空状态应说明当前没有数据或订单。

错误状态应提供实际可执行的恢复操作。

不使用随机数据作为错误状态的替代品。

## 23. Accessibility

- 支持键盘操作。
- Dialog 正确管理 Focus。
- Tooltip 支持键盘聚焦。
- 输入框具有 Label。
- 错误信息与对应字段关联。
- 图标按钮具有可访问名称。
- 关键状态不只通过颜色表达。
- 文字及主要交互元素满足适当的对比度。
- Resizable Panel 支持键盘调整。

## 24. Financial Safety Boundary

Crypto Lab 仅使用虚拟资金。

禁止引入：

- 真实交易 API Key。
- 钱包授权。
- 充值及提现。
- 真正的订单执行接口。
- 自动投资建议。
- 未授权的 AI 或 LLM 服务。

不得因前端便利性修改已确认的后端金融计算规则。

## 25. UI Acceptance Criteria

- 默认进入 Trading。
- Dark Theme 与 Teal Design System 一致。
- 顶部导航符合规范。
- 三栏面板支持调整尺寸。
- 布局自动保存及恢复。
- 订单簿与最新成交通过 Tab 切换。
- 六种 Candle 周期均可真实更新。
- 历史 Candle 支持分页及断线补齐。
- 所有下单操作均需要确认。
- 市价单及限价单正确映射现有后端。
- 账户默认延迟可在下单时覆盖。
- 订单状态实时更新。
- 可取消有效订单。
- 余额、成交、持仓状态一致。
- 支持成交详情及术语 Tooltip。
- 环境切换不存在数据泄漏。
- 行情失效状态明确。
- REST / WebSocket 恢复正确。
- 不存在伪造业务数据。
- 核心页面通过 Desktop Acceptance Matrix 验证（§21.1）。
- 完整后端回归及前端测试通过。

## 26. Change Control

本文件记录已确认的 UI/UX 设计原则。

实际工程实现允许根据后端接口、浏览器兼容性及组件能力调整技术细节。

涉及以下事项必须重新获得项目负责人确认：

- 产品导航结构。
- 核心页面布局。
- 默认主题及视觉体系。
- 下单确认规则。
- 核心金融交互规则。
- 模拟环境及账户隔离规则。
- 后端业务 Contract 的不兼容变更。

普通组件实现及非破坏性技术细节由 Agent 自主决定，并记录必要的技术取舍。
