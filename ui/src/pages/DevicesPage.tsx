import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { api } from '../lib/api'

function fmt(ts?: string | null) {
  if (!ts) return ''
  try {
    return new Date(ts).toLocaleString()
  } catch {
    return ts
  }
}

export default function DevicesPage() {
  const q = useQuery({
    queryKey: ['devices'],
    queryFn: () => api.listDevices({ limit: 100, offset: 0, include_health: true })
  })

  if (q.isLoading) return <div>Loading…</div>
  if (q.isError) return <pre>{JSON.stringify(q.error, null, 2)}</pre>

  const items: any[] = q.data?.items || []

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Devices</h2>
      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ textAlign: 'left', borderBottom: '1px solid #e5e7eb' }}>
            <th style={{ padding: 8 }}>Hostname</th>
            <th style={{ padding: 8 }}>OS</th>
            <th style={{ padding: 8 }}>Status</th>
            <th style={{ padding: 8 }}>Last seen</th>
            <th style={{ padding: 8 }}>Health</th>
          </tr>
        </thead>
        <tbody>
          {items.map((d) => (
            <tr key={d.id} style={{ borderBottom: '1px solid #f3f4f6' }}>
              <td style={{ padding: 8 }}>
                <Link to={`/devices/${d.id}`}>{d.hostname || d.device_key || d.id}</Link>
              </td>
              <td style={{ padding: 8 }}>{[d.os, d.os_version].filter(Boolean).join(' ')}</td>
              <td style={{ padding: 8 }}>{d.status}</td>
              <td style={{ padding: 8 }}>{fmt(d.last_seen_at)}</td>
              <td style={{ padding: 8 }}>{d.health?.status || d.health || ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ marginTop: 12, color: '#6b7280', fontSize: 12 }}>
        Showing {items.length} devices (limit=100)
      </div>
    </div>
  )
}
