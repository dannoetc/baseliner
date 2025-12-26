import { loadSession } from './auth'

export type ApiError = {
  status: number
  detail: any
}

async function parseJsonSafe(resp: Response): Promise<any> {
  const text = await resp.text()
  if (!text) return null
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const s = loadSession()
  if (!s) throw new Error('Not logged in')

  const headers = new Headers(init?.headers || {})
  headers.set('X-Admin-Key', s.adminKey)
  if (s.tenantId) headers.set('X-Tenant-ID', s.tenantId)
  headers.set('Accept', 'application/json')
  if (init?.body && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const url = s.apiBaseUrl.replace(/\/$/, '') + path
  const resp = await fetch(url, { ...init, headers })

  if (!resp.ok) {
    const detail = await parseJsonSafe(resp)
    const err: ApiError = { status: resp.status, detail }
    throw err
  }

  return (await parseJsonSafe(resp)) as T
}

// Convenience helpers
export const api = {
  whoami: () => apiFetch<any>('/api/v1/admin/whoami'),
  listDevices: (params: Record<string, any> = {}) => {
    const qs = new URLSearchParams()
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null || v === '') continue
      qs.set(k, String(v))
    }
    return apiFetch<any>(`/api/v1/admin/devices?${qs.toString()}`)
  },
  deviceDebug: (deviceId: string) => apiFetch<any>(`/api/v1/admin/devices/${deviceId}/debug`),
  listPolicies: (params: Record<string, any> = {}) => {
    const qs = new URLSearchParams()
    for (const [k, v] of Object.entries(params)) {
      if (v === undefined || v === null || v === '') continue
      qs.set(k, String(v))
    }
    return apiFetch<any>(`/api/v1/admin/policies?${qs.toString()}`)
  },
  getPolicy: (policyId: string) => apiFetch<any>(`/api/v1/admin/policies/${policyId}`),
  upsertPolicy: (payload: any) => apiFetch<any>('/api/v1/admin/policies', { method: 'POST', body: JSON.stringify(payload) })
}
