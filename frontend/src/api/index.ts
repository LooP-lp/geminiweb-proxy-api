import type { CustomApiChannel } from '@/types'

const BASE = ''

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const resp = await fetch(BASE + url, {
    credentials: 'same-origin',
    ...options,
  })
  if (resp.status === 401) {
    throw new Error('未登录')
  }
  return resp.json()
}

// Generic list/data responses
interface ListResponse<T> { data: T[] }
interface SuccessResponse { success: boolean; message: string }
interface DetailResponse<T> { data: T }

// ===== Auth =====
export function loginAPI(data: { username: string; password: string }) {
  return fetch(BASE + '/admin/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify(data),
  }).then(r => r.json()) as Promise<import('@/types').AuthResponse>
}

export function registerAPI(data: {
  username: string
  password: string
  email: string
  code: string
}) {
  return fetch(BASE + '/admin/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify(data),
  }).then(r => r.json()) as Promise<import('@/types').AuthResponse>
}

export function sendCodeAPI(data: { email: string }) {
  return fetch(BASE + '/admin/send-code', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'same-origin',
    body: JSON.stringify(data),
  }).then(r => r.json()) as Promise<import('@/types').AuthResponse>
}

// ===== Current Key =====
export function getCurrentKeyAPI() {
  return fetch(BASE + '/admin/current-key', { credentials: 'same-origin' })
    .then(r => r.json()) as Promise<{ api_key: string }>
}

// ===== Models =====
export function getModelsAPI(apiKey: string) {
  return fetch(BASE + '/v1/models', {
    headers: { Authorization: 'Bearer ' + apiKey },
  }).then(r => r.json()) as Promise<import('@/types').ModelsResponse>
}

// ===== Token Status =====
export function getTokenStatusAPI(apiKey: string) {
  return fetch(BASE + '/v1/token/status', {
    headers: { Authorization: 'Bearer ' + apiKey },
  }).then(r => r.json()) as Promise<import('@/types').TokenStatus>
}

export function refreshTokenAPI(apiKey: string) {
  return fetch(BASE + '/v1/token/refresh', {
    method: 'POST',
    headers: { Authorization: 'Bearer ' + apiKey },
  }).then(r => r.json()) as Promise<SuccessResponse>
}

export function resetClientAPI(apiKey: string) {
  return fetch(BASE + '/v1/client/reset', {
    method: 'POST',
    headers: { Authorization: 'Bearer ' + apiKey },
  }).then(r => r.json()) as Promise<SuccessResponse>
}

// ===== Stats =====
export function getStatsAPI() {
  return request<import('@/types').StatsData>('/admin/stats')
}

export function getHourlyStatsAPI() {
  return request<{ data: import('@/types').HourlyStat[] }>('/admin/hourly-stats')
}

export function getUserHourlyStatsAPI() {
  return request<{ data: import('@/types').HourlyStat[] }>('/admin/user-hourly-stats')
}

// ===== API Keys =====
export function listApiKeysAPI() {
  return request<any>('/admin/api-keys').then(res => {
    if (Array.isArray(res)) return { data: res }
    return res
  }) as Promise<ListResponse<import('@/types').ApiKeyItem>>
}

export function createApiKeyAPI(note: string) {
  return request<import('@/types').CreateKeyResponse>('/admin/api-keys', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ note }),
  })
}

export function deleteApiKeyAPI(keyId: number) {
  return request<SuccessResponse>(`/admin/api-keys/${keyId}`, { method: 'DELETE' })
}

export function toggleApiKeyAPI(keyId: number) {
  return request<import('@/types').ToggleKeyResponse>(`/admin/api-keys/${keyId}/toggle`, { method: 'POST' })
}

// ===== Users =====
export function listUsersAPI() {
  return request<ListResponse<import('@/types').UserItem>>('/admin/users')
}

export function getUserDetailAPI(userId: number) {
  return request<DetailResponse<import('@/types').UserDetail>>(`/admin/users/${userId}`)
}

export function deleteUserAPI(userId: number) {
  return request<SuccessResponse>(`/admin/users/${userId}`, { method: 'DELETE' })
}

export function toggleAdminAPI(userId: number) {
  return request<SuccessResponse>(`/admin/users/${userId}/toggle-admin`, { method: 'POST' })
}

// ===== Config =====
export function getConfigAPI() {
  return request<import('@/types').ConfigData>('/admin/config')
}

export function saveConfigAPI(data: import('@/types').SaveConfigRequest) {
  return request<import('@/types').SaveConfigResponse>('/admin/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}

// ===== Custom APIs =====
export function getCustomApisAPI() {
  return request<{ data: CustomApiChannel[] }>('/admin/custom-apis')
}

export function saveCustomApisAPI(apis: unknown[]) {
  return request<SuccessResponse>('/admin/custom-apis', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ apis }),
  })
}

// ===== Prompts =====
export function listPromptsAPI(ptype: string) {
  return request<{ data: import('@/types').PromptItem[] }>(`/admin/prompts/${ptype}`)
}

export function createPromptAPI(ptype: string, title: string, content: string) {
  return request<SuccessResponse>(`/admin/prompts/${ptype}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title, content }),
  })
}

export function deletePromptAPI(ptype: string, promptId: number) {
  return request<SuccessResponse>(`/admin/prompts/${ptype}/${promptId}`, { method: 'DELETE' })
}

export function activatePromptAPI(ptype: string, promptId: number) {
  return request<SuccessResponse>(`/admin/prompts/${ptype}/${promptId}/activate`, { method: 'POST' })
}

// ===== Chat (SSE) =====
export function chatCompletionsAPI(
  apiKey: string,
  body: { model: string; messages: unknown[]; stream: boolean },
  sessionId: string = '',
  signal?: AbortSignal,
): Promise<Response> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    Authorization: 'Bearer ' + apiKey,
  }
  if (sessionId) {
    headers['X-Session-Id'] = sessionId
  }
  return fetch(BASE + '/v1/chat/completions', {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
    signal,
  })
}

export function resetChatAPI(apiKey: string, sessionId: string = '') {
  const headers: Record<string, string> = {
    Authorization: 'Bearer ' + apiKey,
  }
  if (sessionId) {
    headers['X-Session-Id'] = sessionId
  }
  return fetch(BASE + '/v1/client/reset', {
    method: 'POST',
    headers,
  })
}

// ===== Session Management =====
export interface SessionItem {
  session_id: string
  fingerprint: string
  message_count: number
  created_at: string
  last_used: string
  age_seconds: number
  idle_seconds: number
}

export function getSessionsAPI() {
  return request<{ sessions: SessionItem[] }>('/admin/sessions')
}

export function resetSessionAPI(sessionId: string) {
  return request<SuccessResponse>(`/admin/sessions/${sessionId}/reset`, {
    method: 'POST',
  })
}

export function resetAllSessionsAPI() {
  return request<SuccessResponse>('/admin/sessions/reset-all', {
    method: 'POST',
  })
}