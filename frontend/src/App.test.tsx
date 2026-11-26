import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import AppLayout from './App'

function renderLayout() {
  return render(
    <MemoryRouter initialEntries={['/market']}>
      <AppLayout />
    </MemoryRouter>,
  )
}

test('renders navigation and the simulation disclaimer', () => {
  renderLayout()
  expect(screen.getByRole('navigation')).toBeVisible()
  expect(screen.getByText('模拟交易声明', { exact: false })).toBeVisible()
})

test('marks the active route', () => {
  renderLayout()
  const active = screen.getByRole('link', { name: '行情' })
  expect(active).toHaveClass('bg-accent')
})
