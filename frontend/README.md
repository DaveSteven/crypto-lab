# Crypto Lab 前端

Phase 1 Task 1.12 前端应用（React + TypeScript + Vite + Tailwind CSS）。

架构设计见 `../docs/11-FRONTEND-DESIGN.md`；REST/WS 契约见 `../docs/09`、`../docs/10`。

## 常用命令

```bash
pnpm install        # 安装依赖
pnpm dev            # 开发服务器（/api 与 /health 代理到 127.0.0.1:8000）
pnpm test           # Vitest 单元测试
pnpm lint           # oxlint
pnpm build          # 生产构建（含 tsc 类型检查）
pnpm e2e            # Playwright E2E（需先 pnpm exec playwright install）
```

## 边界

- 本地模拟交易前端：只提交订单意图，成交价格、手续费与结果由后端决定。
- 后端默认仅绑定 127.0.0.1，开发代理不产生 CORS 暴露。
- 所有页面固定展示模拟交易声明。
