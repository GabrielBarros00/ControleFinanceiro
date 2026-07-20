import { render, screen } from '@testing-library/react'
import { expect, test } from 'vitest'
import App from './App'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: false,
    },
  },
})

test('renders app component and shows loading state', () => {
  render(
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  )
  
  // App starts with loading state
  expect(screen.getByText(/Carregando sua sessão/i)).toBeInTheDocument()
})
