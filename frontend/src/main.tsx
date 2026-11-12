import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { lazy, StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import { createBrowserRouter, Navigate, RouterProvider } from 'react-router'
import Layout from './components/Layout'
import { AuthGate, MeProvider } from './lib/auth'
import { DomainProvider } from './lib/domain'
import { domainQueryKeyHash } from './lib/domainStore'
import './index.css'

// Screens load on demand: the process map's graph libraries stay off the Overview.
const Overview = lazy(() => import('./pages/Overview'))
const Process = lazy(() => import('./pages/Process'))
const Knowledge = lazy(() => import('./pages/Knowledge'))
const Investigate = lazy(() => import('./pages/Investigate'))
const Actions = lazy(() => import('./pages/Actions'))
const Watch = lazy(() => import('./pages/Watch'))
const Explore = lazy(() => import('./pages/Explore'))
const Models = lazy(() => import('./pages/Models'))
const Observability = lazy(() => import('./pages/Observability'))
const Users = lazy(() => import('./pages/Users'))

const queryClient = new QueryClient({
  defaultOptions: {
    // Every cache entry belongs to the active domain pack (see lib/domain).
    queries: { staleTime: 30_000, refetchOnWindowFocus: false, retry: 1, queryKeyHashFn: domainQueryKeyHash },
  },
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
      { path: 'explore', element: <Suspense><Explore /></Suspense> },
      { path: 'models', element: <Suspense><Models /></Suspense> },
      { path: 'observability', element: <Suspense><Observability /></Suspense> },
      { path: 'users', element: <Suspense><Users /></Suspense> },
      { path: '*', element: <Navigate to="/watch" replace /> },
    ],
  },
])

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <AuthGate>
        <DomainProvider>
          {(domain) => (
            // Keyed on the pack: switching remounts the app, so no screen keeps another pack's state.
            <MeProvider key={domain}>
              <RouterProvider router={router} />
            </MeProvider>
          )}
        </DomainProvider>
      </AuthGate>
    </QueryClientProvider>
  </StrictMode>,
)
