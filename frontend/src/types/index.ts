// ===== API Response Types =====
export interface LoginRequest {
  username: string
  password: string
}

export interface RegisterRequest {
  username: string
  password: string
  email: string
  code: string
}

export interface SendCodeRequest {
  email: string
}

export interface AuthResponse {
  success: boolean
  message: string
  is_admin?: boolean
}

export interface ModelItem {
  id: string
  object: string
  created: number
  owned_by: string
}

export interface ModelsResponse {
  object: string
  data: ModelItem[]
}

export interface ApiKeyItem {
  id: number
  api_key: string
  note: string
  is_active: boolean
  created_at: string
  user_id?: number
}

export interface CreateKeyResponse {
  success: boolean
  data?: ApiKeyItem & { api_key: string }
  message?: string
}

export interface ToggleKeyResponse {
  success: boolean
  is_active?: boolean
  message?: string
}

export interface StatsData {
  total_requests: number
  total_tokens: number
  total_prompt_tokens: number
  total_completion_tokens: number
  requests_by_model: Record<string, number>
  uptime: string
  token_refresh_count: number
  background_refresh_enabled: boolean
  client_active: boolean
  auto_refresh_enabled: boolean
  today_requests?: number
  today_tokens?: number
  recent_24h_requests?: number
  total_errors?: number
  session_stats?: {
    active_sessions: number
    session_ttl: number
    fingerprint_depth: number
  }
}

export interface HourlyStat {
  hour: number
  requests: number
  total_tokens: number
  model: string
}

export interface UserItem {
  id: number
  username: string
  email: string
  is_admin: boolean
  key_count: number
  total_requests: number
  total_tokens: number
  created_at: string
}

export interface UserDetail {
  id: number
  username: string
  email: string
  is_admin: boolean
  created_at: string
  api_keys: Array<{ api_key: string; note: string; is_active: boolean }>
  stats: {
    total_requests: number
    total_tokens: number
    total_prompt_tokens: number
    total_completion_tokens: number
    requests_by_model: Record<string, number>
  }
}

export interface ConfigData {
  SNLM0E: string
  SECURE_1PSID: string
  SECURE_1PSIDTS: string
  SAPISID: string
  SID: string
  HSID: string
  SSID: string
  APISID: string
  PUSH_ID: string
  FULL_COOKIE: string
  MODELS: string[]
  MODEL_IDS: {
    flash: string
    pro: string
    thinking: string
    lite?: string
  }
}

export interface SaveConfigRequest {
  FULL_COOKIE: string
  MODEL_IDS: {
    flash: string
    pro: string
    thinking?: string
    lite?: string
  }
}

export interface SaveConfigResponse {
  success: boolean
  message: string
  need_restart?: boolean
}

export interface PromptItem {
  id: number
  title: string
  content: string
  is_active: boolean
  ptype: string
}

export interface TokenStatus {
  auto_refresh_enabled: boolean
  background_refresh_enabled: boolean
  refresh_interval_range: string
  last_refresh_seconds_ago: number
  total_refresh_count: number
  has_snlm0e: boolean
  has_push_id: boolean
  client_active: boolean
}

export interface ChatMessage {
  role: 'user' | 'assistant' | 'system' | 'tool'
  content: string | Array<Record<string, unknown>>
  name?: string
  tool_call_id?: string
  tool_calls?: unknown[]
}

export interface ChatCompletionDelta {
  role?: string
  content?: string
  reasoning_content?: string
  reasoning?: string
}

export interface ChatCompletionChunk {
  id: string
  object: string
  created: number
  model: string
  choices: Array<{
    index: number
    delta: ChatCompletionDelta
    finish_reason: string | null
  }>
}

export interface CustomApiChannel {
  id: string
  name: string
  url: string
  key: string
  models: string[]
}
