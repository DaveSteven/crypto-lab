import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { AppLayout } from './AppLayout'

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={['/trading']}>
      <AppLayout />
    </MemoryRouter>,
  )
}

test('renders top navigation with the trading entry and paper trading identity', () => {
  renderLayout()
  expect(screen.getByRole('navigation', { name: '主导航' })).toBeVisible()
  expect(screen.getByRole('link', { name: '交易' })).toBeVisible()
  expect(screen.getByText('Paper Trading')).toBeVisible()
})

test('marks the active route with brand styling', () => {
  renderLayout()
  const active = screen.getByRole('link', { name: '交易' })
  expect(active).toHaveAttribute('aria-current', 'page')
})
