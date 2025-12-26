import { Link, Navigate, Route, Routes, useNavigate } from 'react-router-dom'
import { clearSession, loadSession } from './lib/auth'
import LoginPage from './pages/LoginPage'
import DevicesPage from './pages/DevicesPage'
import DeviceDetailPage from './pages/DeviceDetailPage'
import PoliciesPage from './pages/PoliciesPage'
import PolicyDetailPage from './pages/PolicyDetailPage'

function Shell({ children }: { children: React.ReactNode }) {
  const nav = useNavigate()
  const session = loadSession()

  return (
    <div style={{ fontFamily: 'system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial' }}>
      <header style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '12px 16px', borderBottom: '1px solid #e5e7eb' }}>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <strong>Baseliner</strong>
          <nav style={{ display: 'flex', gap: 12 }}>
            <Link to="/devices">Devices</Link>
            <Link to="/policies">Policies</Link>
          </nav>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {session ? (
            <span style={{ fontSize: 12, color: '#6b7280' }}>
              {session.apiBaseUrl}{session.tenantId ? ` • tenant ${session.tenantId}` : ''}
            </span>
          ) : null}
          <button
            onClick={() => {
              clearSession()
              nav('/login')
            }}
          >
            Logout
          </button>
        </div>
      </header>
      <main style={{ padding: 16 }}>{children}</main>
    </div>
  )
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const session = loadSession()
  if (!session) return <Navigate to="/login" replace />
  return <>{children}</>
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />

      <Route
        path="/"
        element={
          <RequireAuth>
            <Shell>
              <Navigate to="/devices" replace />
            </Shell>
          </RequireAuth>
        }
      />

      <Route
        path="/devices"
        element={
          <RequireAuth>
            <Shell>
              <DevicesPage />
            </Shell>
          </RequireAuth>
        }
      />

      <Route
        path="/devices/:deviceId"
        element={
          <RequireAuth>
            <Shell>
              <DeviceDetailPage />
            </Shell>
          </RequireAuth>
        }
      />

      <Route
        path="/policies"
        element={
          <RequireAuth>
            <Shell>
              <PoliciesPage />
            </Shell>
          </RequireAuth>
        }
      />

      <Route
        path="/policies/:policyId"
        element={
          <RequireAuth>
            <Shell>
              <PolicyDetailPage />
            </Shell>
          </RequireAuth>
        }
      />

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
