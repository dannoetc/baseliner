import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiBaseUrl } from '../lib/config'
import { saveSession } from '../lib/auth'

export default function LoginPage() {
  const nav = useNavigate()
  const [baseUrl, setBaseUrl] = useState<string>(() => {
    return localStorage.getItem('baseliner.apiBaseUrl') || apiBaseUrl()
  })
  const [adminKey, setAdminKey] = useState<string>(() => localStorage.getItem('baseliner.adminKey') || '')
  const [tenantId, setTenantId] = useState<string>(() => localStorage.getItem('baseliner.tenantId') || '')
  const [status, setStatus] = useState<string>('')
  const [busy, setBusy] = useState(false)

  async function verify() {
    setBusy(true)
    setStatus('Checking /api/v1/admin/whoami...')
    try {
      // Call directly so we can validate before saving
      const headers = new Headers()
      headers.set('X-Admin-Key', adminKey)
      if (tenantId.trim()) headers.set('X-Tenant-ID', tenantId.trim())
      const resp = await fetch(baseUrl.replace(/\/$/, '') + '/api/v1/admin/whoami', { headers })
      const text = await resp.text()
      if (!resp.ok) {
        throw new Error(text || `HTTP ${resp.status}`)
      }
      saveSession({ apiBaseUrl: baseUrl.replace(/\/$/, ''), adminKey, tenantId: tenantId.trim() || undefined })
      setStatus('OK')
      nav('/devices')
    } catch (e: any) {
      setStatus(`Login failed: ${e?.message || String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ maxWidth: 560, margin: '0 auto' }}>
      <h1 style={{ fontSize: 24, marginBottom: 8 }}>Baseliner UI</h1>
      <p style={{ color: '#6b7280', marginTop: 0 }}>
        This MVP UI uses your admin key directly from the browser (sent as <code>X-Admin-Key</code>). Use TLS.
      </p>

      <div style={{ display: 'grid', gap: 12, marginTop: 16 }}>
        <label>
          <div>API Base URL</div>
          <input
            style={{ width: '100%', padding: 8 }}
            value={baseUrl}
            onChange={(e) => setBaseUrl(e.target.value)}
            placeholder="http://localhost:8000"
          />
        </label>

        <label>
          <div>Admin Key</div>
          <input
            style={{ width: '100%', padding: 8 }}
            value={adminKey}
            onChange={(e) => setAdminKey(e.target.value)}
            placeholder="change-me-too"
          />
        </label>

        <label>
          <div>Tenant ID (optional)</div>
          <input
            style={{ width: '100%', padding: 8 }}
            value={tenantId}
            onChange={(e) => setTenantId(e.target.value)}
            placeholder="<uuid>"
          />
          <div style={{ fontSize: 12, color: '#6b7280' }}>
            Only needed for superadmin keys when you want to operate on a specific tenant.
          </div>
        </label>

        <button disabled={busy || !baseUrl || !adminKey} onClick={verify} style={{ padding: '10px 12px' }}>
          {busy ? 'Checking…' : 'Login'}
        </button>

        {status ? <pre style={{ whiteSpace: 'pre-wrap', margin: 0 }}>{status}</pre> : null}
      </div>
    </div>
  )
}
