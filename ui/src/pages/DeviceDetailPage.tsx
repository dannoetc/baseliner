import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { api } from '../lib/api'

export default function DeviceDetailPage() {
  const { deviceId } = useParams()
  const q = useQuery({
    queryKey: ['deviceDebug', deviceId],
    enabled: !!deviceId,
    queryFn: () => api.deviceDebug(deviceId!)
  })

  if (q.isLoading) return <div>Loading…</div>
  if (q.isError) return <pre>{JSON.stringify(q.error, null, 2)}</pre>

  const data = q.data

  return (
    <div>
      <h2 style={{ marginTop: 0 }}>Device</h2>
      <p style={{ color: '#6b7280', marginTop: 0 }}>
        This page uses <code>GET /api/v1/admin/devices/{deviceId ?? '{id}'}/debug</code>.
      </p>

      <h3>Summary</h3>
      <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(data.device, null, 2)}</pre>

      <h3>Assignments</h3>
      <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(data.assignments, null, 2)}</pre>

      <h3>Effective policy</h3>
      <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(data.effective_policy, null, 2)}</pre>

      <h3>Last run</h3>
      <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(data.last_run, null, 2)}</pre>

      <h3>Last run items</h3>
      <pre style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(data.last_run_items, null, 2)}</pre>
    </div>
  )
}
