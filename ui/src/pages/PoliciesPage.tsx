import { useQuery } from '@tanstack/react-query'
import { Link, useNavigate } from 'react-router-dom'
import { api } from '../lib/api'

export default function PoliciesPage() {
  const nav = useNavigate()
  const q = useQuery({
    queryKey: ['policies'],
    queryFn: () => api.listPolicies({ limit: 200, offset: 0, include_inactive: true })
  })

  if (q.isLoading) return <div>Loading…</div>
  if (q.isError) return <pre>{JSON.stringify(q.error, null, 2)}</pre>

  const items: any[] = q.data?.items || []

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Policies</h2>
      <p style={{ color: '#6b7280', marginTop: 0 }}>
        Create/edit happens via <code>POST /api/v1/admin/policies</code>.
      </p>

      <button
        onClick={() => nav('/policies/new')}
        style={{ padding: '8px 10px', marginBottom: 12 }}
      >
        New policy
      </button>

      <table style={{ width: '100%', borderCollapse: 'collapse' }}>
        <thead>
          <tr style={{ textAlign: 'left', borderBottom: '1px solid #e5e7eb' }}>
            <th style={{ padding: 8 }}>Name</th>
            <th style={{ padding: 8 }}>Active</th>
            <th style={{ padding: 8 }}>Updated</th>
          </tr>
        </thead>
        <tbody>
          {items.map((p) => (
            <tr key={p.id} style={{ borderBottom: '1px solid #f3f4f6' }}>
              <td style={{ padding: 8 }}>
                <Link to={`/policies/${p.id}`}>{p.name}</Link>
              </td>
              <td style={{ padding: 8 }}>{String(!!p.is_active)}</td>
              <td style={{ padding: 8 }}>{p.updated_at ? new Date(p.updated_at).toLocaleString() : ''}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
