import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AppLayout from './App'
import { PlaceholderPage } from './pages/PlaceholderPage'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 5_000 },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppLayout />}>
            <Route
              path="/"
              element={
                <PlaceholderPage
                  title="行情"
                  description="Market 页面将在 Task 1.12.5 实现（Lightweight Charts）。"
                />
              }
            />
            <Route
              path="/market"
              element={
                <PlaceholderPage
                  title="行情"
                  description="Market 页面将在 Task 1.12.5 实现（Lightweight Charts）。"
                />
              }
            />
            <Route
              path="/trading"
              element={
                <PlaceholderPage
                  title="交易"
                  description="下单意图表单将在 Task 1.12.6 实现。前端只提交订单意图，成交价格与结果由服务端决定。"
                />
              }
            />
            <Route
              path="/orders"
              element={
                <PlaceholderPage title="订单" description="订单列表与取消将在 Task 1.12.6 实现。" />
              }
            />
            <Route
              path="/executions"
              element={
                <PlaceholderPage title="成交" description="成交记录将在 Task 1.12.6 实现。" />
              }
            />
            <Route
              path="/account"
              element={
                <PlaceholderPage
                  title="账户"
                  description="余额与持仓将在 Task 1.12.6 实现。"
                />
              }
            />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
