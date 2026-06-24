<template>
  <div class="console-wrap">
    <!-- Sessions Management -->
    <div class="card section-card">
      <div class="section-header">
        <h3>💬 会话管理</h3>
        <button class="btn-secondary" @click="loadSessions">刷新</button>
      </div>
      <p class="session-desc">
        系统自动识别不同对话线程，复用 Gemini 上下文。相同对话自动续接，不同对话互不干扰。
      </p>
      <div class="session-list">
        <EmptyState v-if="sessions.length === 0" icon="💬" title="暂无活跃会话" description="开始对话后会自动创建会话" />
        <div v-for="s in sessions" :key="s.session_id" class="session-item">
          <div class="session-info">
            <div class="session-fingerprint">{{ s.fingerprint }}</div>
            <div class="session-meta">
              {{ s.message_count }} 轮对话 | 最近使用: {{ formatTime(s.idle_seconds) }}前 | 创建于 {{ s.created_at }}
            </div>
          </div>
          <button class="btn-danger session-btn" @click="resetSession(s.session_id)">重置</button>
        </div>
      </div>
      <button v-if="sessions.length > 0" class="btn-danger reset-all-btn" @click="resetAllSessions">重置所有会话</button>
    </div>

    <!-- User Hourly Charts -->
    <div class="card section-card">
      <h3>📊 API 数据</h3>
      <div class="chart-grid">
        <div class="chart-col">
          <h4 class="chart-subtitle">24小时模型使用分布</h4>
          <div class="hourly-chart-wrap"><canvas ref="userModelBarChart" height="200"></canvas></div>
        </div>
        <div class="chart-col">
          <h4 class="chart-subtitle">24小时 Token 消耗</h4>
          <div class="hourly-chart-wrap"><canvas ref="userTokenLineChart" height="200"></canvas></div>
        </div>
      </div>
    </div>

    <!-- API Keys -->
    <div class="card section-card">
      <h3>🔑 我的 API Keys</h3>
      <div class="metric-row">
        <div class="k">接口地址</div>
        <div class="v">{{ baseUrl }}/v1</div>
      </div>
      <div class="api-key-list">
        <EmptyState v-if="apiKeys.length === 0" icon="🔑" title="暂无 API Key" description="创建一个 API Key 以开始使用" />
        <div v-for="k in apiKeys" :key="k.id" class="api-key-item">
          <div class="key-info">
            <div class="key-value">{{ k.api_key }}</div>
            <div class="key-note">{{ k.note || '无备注' }} | {{ k.created_at?.substring(0, 10) }}</div>
          </div>
          <span class="badge" :class="k.is_active ? 'badge-success' : 'badge-error'">{{ k.is_active ? '已启用' : '已禁用' }}</span>
          <div class="key-actions">
            <button class="btn-secondary key-btn" @click="toggleKey(k.id)">{{ k.is_active ? '禁用' : '启用' }}</button>
            <button class="btn-danger key-btn" @click="confirmDeleteKey(k.id)">删除</button>
          </div>
        </div>
      </div>
      <button class="create-key-btn" @click="showCreateKeyModal = true">+ 创建新的 API Key</button>
    </div>

    <!-- Models -->
    <div class="card section-card">
      <h3>🚀 可用模型</h3>
      <div class="model-list">
        <SkeletonLoader v-if="models.length === 0" height="32px" />
        <span v-for="m in models" :key="m" class="model-tag">{{ m }}</span>
      </div>
    </div>

    <!-- Rust Doc -->
    <div class="card section-card">
      <h3>🦀 Rust 对接文档</h3>
      <div class="rust-code">{{ rustCode }}</div>
    </div>

    <!-- Create Key Modal -->
    <ModalOverlay v-model="showCreateKeyModal" title="创建 API Key">
      <p class="modal-desc">请输入备注（可选），用于标识此 Key 的用途</p>
      <input type="text" v-model="newKeyNote" class="input-field" placeholder="例如: 开发测试" maxlength="200" @keypress.enter="createKey" />
      <template #actions>
        <button class="btn-secondary" @click="showCreateKeyModal = false">取消</button>
        <button class="btn-primary" :disabled="createKeyLoading" @click="createKey">{{ createKeyLoading ? '创建中...' : '创建' }}</button>
      </template>
    </ModalOverlay>

    <!-- Show Created Key Modal -->
    <ModalOverlay v-model="showKeyModal" title="API Key 已创建" :close-on-backdrop="false" :closable="false">
      <div class="key-warning">⚠️ 请立即复制并妥善保存，关闭此窗口后将无法再次查看！</div>
      <div class="key-display">{{ createdKey }}</div>
      <template #actions>
        <button class="btn-primary" @click="copyAndCloseKey">复制并关闭</button>
      </template>
    </ModalOverlay>

    <!-- Delete Key Modal -->
    <ModalOverlay v-model="showDeleteKeyModal" title="删除确认">
      <p class="modal-desc">确定要删除此 API Key 吗？此操作不可恢复。</p>
      <template #actions>
        <button class="btn-secondary" @click="showDeleteKeyModal = false">取消</button>
        <button class="btn-danger" :disabled="deleteKeyLoading" @click="deleteKey">{{ deleteKeyLoading ? '删除中...' : '确认删除' }}</button>
      </template>
    </ModalOverlay>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted, computed, nextTick, onActivated } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import { listApiKeysAPI, createApiKeyAPI, deleteApiKeyAPI, toggleApiKeyAPI, getModelsAPI, getUserHourlyStatsAPI, getSessionsAPI, resetSessionAPI, resetAllSessionsAPI } from '@/api'
import type { SessionItem } from '@/api'
import { drawUserModelBarChart, drawUserTokenLineChart, observeChartResize, watchDarkMode } from '@/composables/useCharts'
import ModalOverlay from '@/components/ModalOverlay.vue'
import EmptyState from '@/components/EmptyState.vue'
import SkeletonLoader from '@/components/SkeletonLoader.vue'
import type { ApiKeyItem } from '@/types'

const auth = useAuthStore()
const toast = useToastStore()
const baseUrl = computed(() => location.protocol + '//' + location.host)
const apiKeys = ref<ApiKeyItem[]>([])
const sessions = ref<SessionItem[]>([])
const models = ref<string[]>([])
const newKeyNote = ref('')
const createdKey = ref('')
const pendingDeleteKeyId = ref<number | null>(null)
const showCreateKeyModal = ref(false)
const showKeyModal = ref(false)
const showDeleteKeyModal = ref(false)
const createKeyLoading = ref(false)
const deleteKeyLoading = ref(false)
const userModelBarChart = ref<HTMLCanvasElement | null>(null)
const userTokenLineChart = ref<HTMLCanvasElement | null>(null)
let refreshTimer: ReturnType<typeof setInterval> | null = null
const cleanupFns: (() => void)[] = []

const rustCode = computed(() => {
  return `// Cargo.toml 依赖
// [dependencies]
// reqwest = { version = "0.12", features = ["json"] }
// serde = { version = "1", features = ["derive"] }
// serde_json = "1"
// tokio = { version = "1", features = ["full"] }

use serde::{Deserialize, Serialize};

#[derive(Serialize)]
struct ChatRequest { model: String, messages: Vec<Message>, stream: bool, }

#[derive(Serialize)]
struct Message { role: String, content: String, }

#[derive(Deserialize)]
struct ChatResponse { choices: Vec<Choice>, usage: Usage, }

#[derive(Deserialize)]
struct Choice { message: ResponseMessage, }

#[derive(Deserialize)]
struct ResponseMessage { content: String, }

#[derive(Deserialize)]
struct Usage { prompt_tokens: u32, completion_tokens: u32, total_tokens: u32, }

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
  let client = reqwest::Client::new();
  let request = ChatRequest {
    model: "gemini-3.5-flash".to_string(),
    messages: vec![Message { role: "user".to_string(), content: "你好".to_string() }],
    stream: false,
  };
  let response = client
    .post("${baseUrl.value}/v1/chat/completions")
    .header("Authorization", "Bearer sk-xxxxxxxxx")
    .json(&request)
    .send().await?
    .json::<ChatResponse>().await?;
  println!("回复: {}", response.choices[0].message.content);
  println!("Token 用量: {}", response.usage.total_tokens);
  Ok(())
}`
})

async function loadApiKeys() {
  try { apiKeys.value = (await listApiKeysAPI()).data || [] } catch { /* keys unavailable */ }
}

async function createKey() {
  createKeyLoading.value = true
  try {
    const result = await createApiKeyAPI(newKeyNote.value || '')
    if (result.success && result.data) {
      showCreateKeyModal.value = false
      createdKey.value = result.data.api_key
      showKeyModal.value = true
      loadApiKeys()
      toast.success('API Key 已创建')
    }
  } finally { createKeyLoading.value = false }
}

function copyAndCloseKey() {
  navigator.clipboard.writeText(createdKey.value).then(() => {
    showKeyModal.value = false
    toast.success('已复制到剪贴板')
  }).catch(() => {
    // Fallback for non-HTTPS or older browsers
    const ta = document.createElement('textarea')
    ta.value = createdKey.value
    ta.style.position = 'fixed'
    ta.style.left = '-9999px'
    ta.tabIndex = -1
    document.body.appendChild(ta)
    ta.focus()
    ta.select()
    try { document.execCommand('copy') } catch { /* ignore */ }
    document.body.removeChild(ta)
    showKeyModal.value = false
    toast.success('已复制到剪贴板')
  })
}

async function toggleKey(keyId: number) {
  try {
    const result = await toggleApiKeyAPI(keyId)
    if (result.success) { loadApiKeys(); toast.success('操作成功') }
  } catch { toast.error('操作失败') }
}

async function loadSessions() {
  try {
    const result = await getSessionsAPI()
    sessions.value = result.sessions
  } catch (e) {
    console.error('加载会话失败:', e)
  }
}

async function resetSession(sessionId: string) {
  try {
    const result = await resetSessionAPI(sessionId)
    if (result.success) {
      toast.success('会话已重置')
      loadSessions()
    } else {
      toast.error(result.message || '重置失败')
    }
  } catch {
    toast.error('重置失败')
  }
}

async function resetAllSessions() {
  if (!confirm('确定要重置所有会话吗？')) return
  try {
    const result = await resetAllSessionsAPI()
    if (result.success) {
      toast.success(result.message || '所有会话已重置')
      loadSessions()
    } else {
      toast.error(result.message || '重置失败')
    }
  } catch {
    toast.error('重置失败')
  }
}

function formatTime(seconds: number): string {
  if (seconds < 60) return `${seconds}秒`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}分钟`
  const hours = Math.floor(minutes / 60)
  return `${hours}小时`
}

function confirmDeleteKey(keyId: number) {
  pendingDeleteKeyId.value = keyId
  showDeleteKeyModal.value = true
}

async function deleteKey() {
  if (!pendingDeleteKeyId.value) return
  deleteKeyLoading.value = true
  try {
    const result = await deleteApiKeyAPI(pendingDeleteKeyId.value)
    if (result.success) { showDeleteKeyModal.value = false; loadApiKeys(); toast.success('已删除') }
  } finally { deleteKeyLoading.value = false; pendingDeleteKeyId.value = null }
}

async function loadConsoleData() {
  try {
    const mdata = await getModelsAPI(auth.getApiKey())
    models.value = (mdata.data || []).map(m => m.id)
  } catch { /* models unavailable */ }
  try {
    const hData = await getUserHourlyStatsAPI()
    const hourly = hData.data || []
    if (userModelBarChart.value) drawUserModelBarChart(userModelBarChart.value, hourly)
    if (userTokenLineChart.value) drawUserTokenLineChart(userTokenLineChart.value, hourly)
  } catch { /* hourly stats unavailable */ }
}

onMounted(() => {
  loadApiKeys()
  loadSessions()
  loadConsoleData()
  refreshTimer = setInterval(() => {
    loadConsoleData()
    loadSessions()
  }, 10000)

  // Set up ResizeObserver + dark-mode watcher for charts
  if (userModelBarChart.value) {
    cleanupFns.push(observeChartResize(userModelBarChart.value, loadConsoleData))
    cleanupFns.push(watchDarkMode(loadConsoleData))
  }
  if (userTokenLineChart.value) {
    cleanupFns.push(observeChartResize(userTokenLineChart.value, loadConsoleData))
  }
})

// 当组件从 KeepAlive 激活时，确保图表正确渲染
onActivated(() => {
  nextTick(() => {
    loadConsoleData()
  })
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  cleanupFns.forEach(fn => fn())
})
</script>

<style scoped>
.console-wrap { flex: 1; overflow-y: auto; padding: var(--sp-5); }
.section-card { margin-bottom: var(--sp-5); }
.section-card h3 { font-size: var(--fs-lg); font-weight: var(--fw-semibold); margin-bottom: var(--sp-4); color: var(--text); }
.section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--sp-4); }
.section-header h3 { margin-bottom: 0; }

/* Session Management */
.session-desc {
  font-size: var(--fs-sm);
  color: var(--muted);
  margin-bottom: var(--sp-4);
  line-height: 1.5;
}
.session-list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  margin-bottom: var(--sp-4);
}
.session-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
}
.session-info {
  flex: 1;
  min-width: 0;
}
.session-fingerprint {
  font-size: var(--fs-base);
  font-weight: var(--fw-medium);
  color: var(--text);
  margin-bottom: var(--sp-1);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.session-meta {
  font-size: var(--fs-sm);
  color: var(--muted);
}
.session-btn {
  padding: var(--sp-2) var(--sp-3);
  font-size: var(--fs-sm);
  flex-shrink: 0;
}
.reset-all-btn {
  width: 100%;
}

/* Charts */
.chart-grid { display: flex; gap: var(--sp-4); }
.chart-col { flex: 1; min-width: 0; }
.chart-subtitle { font-size: var(--fs-base); color: var(--muted); margin-bottom: var(--sp-3); }
.hourly-chart-wrap {
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: var(--sp-4);
  margin-top: var(--sp-2);
}
.hourly-chart-wrap canvas { width: 100%; height: 180px; display: block; }

/* API Keys */
.metric-row {
  background: var(--surface-2);
  border-radius: var(--r-md);
  padding: var(--sp-3) var(--sp-4);
  display: flex; justify-content: space-between; gap: var(--sp-3);
  align-items: center;
  margin-bottom: var(--sp-3);
}
.metric-row .k { font-size: var(--fs-base); color: var(--muted); }
.metric-row .v { font-size: var(--fs-base); color: var(--text); font-weight: var(--fw-medium); text-align: right; word-break: break-all; }

.api-key-list { margin-top: var(--sp-3); }
.api-key-item {
  display: flex; align-items: center; justify-content: space-between;
  padding: var(--sp-3) var(--sp-4);
  background: var(--surface-2);
  border-radius: var(--r-md);
  margin-bottom: var(--sp-2);
}
.api-key-item .key-info { flex: 1; }
.api-key-item .key-value { font-family: 'SF Mono', monospace; font-size: var(--fs-base); color: var(--text); }
.api-key-item .key-note { font-size: var(--fs-sm); color: var(--muted); margin-top: var(--sp-1); }
.api-key-item .key-actions { display: flex; gap: var(--sp-2); }
.key-btn { padding: var(--sp-2) var(--sp-3); font-size: var(--fs-sm); }

.create-key-btn {
  display: flex; align-items: center; justify-content: center; gap: var(--sp-2);
  padding: var(--sp-3) var(--sp-5);
  border: 2px dashed var(--border);
  border-radius: var(--r-md);
  background: none; width: 100%;
  cursor: pointer; color: var(--muted);
  font-size: var(--fs-md);
  transition: all var(--t-normal);
  margin-top: var(--sp-3);
}
.create-key-btn:hover { border-color: var(--blue); color: var(--blue); }

/* Models */
.model-list { margin-top: var(--sp-2); }
.model-tag {
  display: inline-block;
  background: var(--surface-2);
  color: var(--text);
  padding: var(--sp-2) var(--sp-4);
  border-radius: var(--r-xl);
  font-size: var(--fs-sm);
  margin: var(--sp-1);
  font-weight: var(--fw-medium);
}

/* Rust code */
.rust-code {
  background: var(--code-bg);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  padding: var(--sp-4);
  font-family: 'SF Mono', Consolas, monospace;
  font-size: var(--fs-sm);
  color: var(--text);
  overflow-x: auto;
  white-space: pre;
  line-height: var(--lh-relaxed);
  max-height: 400px;
  overflow-y: auto;
}

/* Modal content */
.modal-desc { font-size: var(--fs-md); color: var(--muted); margin-bottom: var(--sp-4); }
.key-warning {
  background: var(--yellow-bg);
  border: 1px solid var(--yellow);
  border-radius: var(--r-md);
  padding: var(--sp-3);
  font-size: var(--fs-base);
  color: var(--yellow-fg);
  margin-bottom: var(--sp-3);
}
.key-display {
  font-family: 'SF Mono', monospace;
  font-size: var(--fs-md);
  background: var(--surface-2);
  padding: var(--sp-4);
  border-radius: var(--r-md);
  color: var(--blue);
  word-break: break-all;
  margin: var(--sp-3) 0;
}

@media (max-width: 900px) {
  .chart-grid { flex-direction: column; }
}
</style>
