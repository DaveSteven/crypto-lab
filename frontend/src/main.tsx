import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AppLayout } from './app/AppLayout'
import { OverviewPage } from './features/account/OverviewPage'
import { TradingWorkspace } from './features/workspace/TradingWorkspace'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false, staleTime: 5_000 },
  },
})

// docs/12 §5.1: root redirects to /trading; Markets route arrives with
// Task 1.12.11 (no Coming Soon pages).
createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          <Route element={<AppLayout />}>
            <Route path="/" element={<Navigate to="/trading" replace />} />
            <Route path="/trading" element={<TradingWorkspace />} />
            <Route path="/overview" element={<OverviewPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
