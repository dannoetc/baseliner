export function apiBaseUrl(): string {
  const runtime = window.__BASELINER__?.API_BASE_URL
  const env = (import.meta as any).env?.VITE_API_BASE_URL
  return (runtime || env || '/api').replace(/\/$/, '')
}

export const STORAGE_KEYS = {
  apiBaseUrl: 'baseliner.apiBaseUrl',
  adminKey: 'baseliner.adminKey',
  tenantId: 'baseliner.tenantId'
}
