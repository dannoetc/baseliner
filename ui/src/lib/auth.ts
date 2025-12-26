import { STORAGE_KEYS } from './config'

export type Session = {
  apiBaseUrl: string
  adminKey: string
  tenantId?: string
}

export function loadSession(): Session | null {
  const apiBaseUrl = localStorage.getItem(STORAGE_KEYS.apiBaseUrl) || ''
  const adminKey = localStorage.getItem(STORAGE_KEYS.adminKey) || ''
  const tenantId = localStorage.getItem(STORAGE_KEYS.tenantId) || ''

  if (!apiBaseUrl || !adminKey) return null
  return { apiBaseUrl, adminKey, tenantId: tenantId || undefined }
}

export function saveSession(s: Session) {
  localStorage.setItem(STORAGE_KEYS.apiBaseUrl, s.apiBaseUrl)
  localStorage.setItem(STORAGE_KEYS.adminKey, s.adminKey)
  if (s.tenantId) localStorage.setItem(STORAGE_KEYS.tenantId, s.tenantId)
  else localStorage.removeItem(STORAGE_KEYS.tenantId)
}

export function clearSession() {
  localStorage.removeItem(STORAGE_KEYS.apiBaseUrl)
  localStorage.removeItem(STORAGE_KEYS.adminKey)
  localStorage.removeItem(STORAGE_KEYS.tenantId)
}
