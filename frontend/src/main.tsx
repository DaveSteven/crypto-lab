import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AppLayout from './App'
import { MarketPage } from './pages/MarketPage'
import { TradingPage } from './pages/TradingPage'
import { OrdersPage } from './pages/OrdersPage'
import { ExecutionsPage } from './pages/ExecutionsPage'
import { AccountPage } from './pages/AccountPage'
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
            <Route path="/" element={<MarketPage />} />
            <Route path="/market" element={<MarketPage />} />
            <Route path="/trading" element={<TradingPage />} />
            <Route path="/orders" element={<OrdersPage />} />
            <Route path="/executions" element={<ExecutionsPage />} />
            <Route path="/account" element={<AccountPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
