import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy, StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router'
import Layout from './components/Layout'
import { ActingUserProvider } from './lib/actingUser'
import './index.css'

// Screens load on demand: the process map's graph libraries stay off the Overview.
const Overview = lazy(() => import('./pages/Overview'))
const Process = lazy(() => import('./pages/Process'))
const Knowledge = lazy(() => import('./pages/Knowledge'))
const Investigate = lazy(() => import('./pages/Investigate'))
const Actions = lazy(() => import('./pages/Actions'))
const Watch = lazy(() => import('./pages/Watch'))

const queryClient = new QueryClient({
  defaultOptions: { queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: 1 } },
})

const router = createBrowserRouter([
  {
    element: <Layout />,
    children: [
      { index: true, element: <Navigate to="/watch" replace /> },
      { path: 'watch', element: <Suspense><Watch /></Suspense> },
      { path: 'overview', element: <Suspense><Overview /></Suspense> },
      { path: 'process', element: <Suspense><Process /></Suspense> },
      { path: 'knowledge', element: <Suspense><Knowledge /></Suspense> },
      { path: 'investigate', element: <Suspense><Investigate /></Suspense> },
      { path: 'actions', element: <Suspense><Actions /></Suspense> },
      { path: '*', element: <Navigate to="/watch" replace /> },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <ActingUserProvider>
        <RouterProvider router={router} />
      </ActingUserProvider>
    </QueryClientProvider>
  </StrictMode>,
)
