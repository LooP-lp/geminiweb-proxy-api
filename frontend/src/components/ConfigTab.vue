<template>
  <div class="config-wrap">
    <div class="card config-card">
      <div class="config-header">
        <h2 class="config-title">⚙️ 配置管理</h2>
        <span class="badge" :class="tokenBadgeClass">{{ tokenBadgeText }}</span>
      </div>

      <div class="info-box">
        <strong>获取方法：</strong><br>
        1. 打开 <a href="https://gemini.google.com" target="_blank">gemini.google.com</a> 并登录<br>
        2. F12 → 网络 → 发送内容到聊天 → 点击任意请求 → Copy 请求头内完整cookie
      </div>

      <form @submit.prevent="saveConfig">
        <div class="section">
          <div class="section-title">🔑 Cookie 配置</div>
          <div class="form-group">
            <label>完整 Cookie <span class="required">*</span></label>
            <textarea v-model="form.FULL_COOKIE" rows="6" placeholder="粘贴从浏览器复制的完整 Cookie 字符串..." required @input="onCookieInput" class="input-field"></textarea>
            <div v-if="parsedCookieFields.length" class="parsed-info">
              <h4>✔ 已解析的字段：</h4>
              <div v-for="f in parsedCookieFields" :key="f.name" class="parsed-item">{{ f.name }}: <span>{{ f.value }}</span></div>
            </div>
          </div>
        </div>

        <div class="section">
          <div class="section-title">🎯 模型 ID 配置 <span class="optional">(可选，如果模型切换失效请更新)</span></div>
          <div class="info-box">
            <strong>获取方法：</strong>F12 → Network → 在 Gemini 中切换模型发送消息 → 找到请求头 <code>x-goog-ext-525001261-jspb</code> → 复制整个数组值粘贴到下方输入框
          </div>
          <div class="form-group">
            <label>快速解析 <span class="optional">(粘贴请求头数组自动提取 ID)</span></label>
            <input v-model="modelIdParser" placeholder='粘贴如: [1,null,null,null,"56fdd199312815e2",null,null,0,[4],null,null,2]' @input="onModelIdParse" class="input-field" />
            <div v-if="parsedModelId" class="parsed-info">
              <h4>✔ 已提取的模型 ID：</h4>
              <div class="parsed-item">提取到的 ID: <span class="model-id-value">{{ parsedModelId }}</span></div>
              <div class="fill-btns">
                <button v-for="t in ['flash','pro','lite']" :key="t" type="button" class="btn-secondary fill-btn" @click="fillModelId(t)">{{ t === 'flash' ? '填入极速版' : t === 'pro' ? '填入Pro版' : '填入Lite版' }}</button>
              </div>
            </div>
          </div>
          <div class="form-group">
            <label>极速版 (Flash) ID</label>
            <input v-model="form.MODEL_ID_FLASH" placeholder="56fdd199312815e2" class="input-field" />
          </div>
          <div class="form-group">
            <label>Pro 版 ID</label>
            <input v-model="form.MODEL_ID_PRO" placeholder="e6fa609c3fa255c0" class="input-field" />
          </div>
          <div class="form-group">
            <label>Lite 版 ID</label>
            <input v-model="form.MODEL_ID_LITE" placeholder="8c46e95b1a07cecc" class="input-field" />
          </div>
        </div>

        <button type="submit" class="btn-primary btn-save" :disabled="saving">{{ saving ? '保存中...' : '💾 保存配置' }}</button>
      </form>

      <div v-if="statusMsg.text" class="status-msg" :class="statusMsg.type" v-html="statusMsg.text"></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onMounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import { getConfigAPI, saveConfigAPI, getTokenStatusAPI } from '@/api'

const auth = useAuthStore()
const toast = useToastStore()

const form = reactive({
  FULL_COOKIE: '',
  MODEL_ID_FLASH: '',
  MODEL_ID_PRO: '',
  MODEL_ID_LITE: '',
})
const modelIdParser = ref('')
const parsedModelId = ref('')
const parsedCookieFields = ref<Array<{ name: string; value: string }>>([])
const saving = ref(false)
const statusMsg = reactive({ text: '', type: '' })
const tokenBadgeClass = ref('badge-warning')
const tokenBadgeText = ref('检查中...')

const cookieFieldMap: Record<string, string> = {
  '__Secure-1PSID': 'SECURE_1PSID',
  '__Secure-1PSIDTS': 'SECURE_1PSIDTS',
  'SAPISID': 'SAPISID',
  '__Secure-1PAPISID': 'SAPISID',
  'SID': 'SID',
  'HSID': 'HSID',
  'SSID': 'SSID',
  'APISID': 'APISID',
}

const cookieNameDisplay: Record<string, string> = {
  'SECURE_1PSID': '__Secure-1PSID',
  'SECURE_1PSIDTS': '__Secure-1PSIDTS',
  'SAPISID': 'SAPISID',
  'SID': 'SID',
  'HSID': 'HSID',
  'SSID': 'SSID',
  'APISID': 'APISID',
}

function parseCookie(str: string): Record<string, string> {
  const result: Record<string, string> = {}
  if (!str) return result
  str.split(';').forEach(item => {
    const t = item.trim()
    const eq = t.indexOf('=')
    if (eq > 0) {
      const k = t.substring(0, eq).trim()
      const v = t.substring(eq + 1).trim()
      if (cookieFieldMap[k]) result[cookieFieldMap[k]] = v
    }
  })
  return result
}

function onCookieInput() {
  const parsed = parseCookie(form.FULL_COOKIE)
  parsedCookieFields.value = []
  for (const key in cookieNameDisplay) {
    if (parsed[key]) {
      const sv = parsed[key].length > 30 ? parsed[key].substring(0, 30) + '...' : parsed[key]
      parsedCookieFields.value.push({ name: cookieNameDisplay[key], value: sv })
    }
  }
}

function parseModelIdInput(input: string): string | null {
  try {
    const arr = JSON.parse(input)
    if (Array.isArray(arr) && arr.length > 4 && typeof arr[4] === 'string') return arr[4]
  } catch { /* not JSON */ }
  const match = input.match(/["']([a-f0-9]{16})["']/i)
  if (match) return match[1]
  return null
}

function onModelIdParse() {
  const mid = parseModelIdInput(modelIdParser.value)
  parsedModelId.value = mid || ''
}

function fillModelId(type: string) {
  const map: Record<string, keyof typeof form> = { flash: 'MODEL_ID_FLASH', pro: 'MODEL_ID_PRO', lite: 'MODEL_ID_LITE' }
  form[map[type]] = parsedModelId.value
}

async function saveConfig() {
  saving.value = true
  statusMsg.text = ''
  statusMsg.type = ''

  const data = {
    FULL_COOKIE: form.FULL_COOKIE.trim(),
    MODEL_IDS: {
      flash: form.MODEL_ID_FLASH || '',
      pro: form.MODEL_ID_PRO || '',
      lite: form.MODEL_ID_LITE || '',
    },
  }

  try {
    const result = await saveConfigAPI(data)
    if (result.success) {
      statusMsg.text = '✔ ' + result.message.replace(/</g, '&lt;').replace(/>/g, '&gt;') + '<br><br>配置已生效，无需重启服务！'
      statusMsg.type = 'success'
      toast.success('配置已保存')
    } else {
      statusMsg.type = 'error'
      statusMsg.text = '✘ ' + (result.message || '').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    }
    updateTokenBadge()
  } catch (err: unknown) {
    statusMsg.type = 'error'
    statusMsg.text = '保存失败: ' + ((err instanceof Error ? err.message : String(err)) || '').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  } finally {
    saving.value = false
  }
}

async function updateTokenBadge() {
  try {
    const data = await getTokenStatusAPI(auth.getApiKey())
    if (data.has_snlm0e) {
      tokenBadgeClass.value = 'badge-success'
      tokenBadgeText.value = `Token 有效 | 已刷新 ${data.total_refresh_count} 次`
    } else {
      tokenBadgeClass.value = 'badge-error'
      tokenBadgeText.value = 'Token 已失效'
    }
  } catch {
    tokenBadgeClass.value = 'badge-error'
    tokenBadgeText.value = '无法获取状态'
  }
}

onMounted(async () => {
  updateTokenBadge()
  try {
    const config = await getConfigAPI()
    if (config.FULL_COOKIE) { form.FULL_COOKIE = config.FULL_COOKIE; onCookieInput() }
    if (config.MODEL_IDS) {
      form.MODEL_ID_FLASH = config.MODEL_IDS.flash || ''
      form.MODEL_ID_PRO = config.MODEL_IDS.pro || ''
      form.MODEL_ID_LITE = config.MODEL_IDS.lite || ''
    }
  } catch { /* config unavailable */ }
})
</script>

<style scoped>
.config-wrap { flex: 1; overflow-y: auto; padding: var(--sp-5); }
.config-card { max-width: 900px; margin: 0 auto; }
.config-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: var(--sp-5); }
.config-title { font-size: var(--fs-2xl); font-weight: var(--fw-semibold); margin: 0; }

.section { margin-bottom: var(--sp-7); }
.section-title { font-size: var(--fs-lg); font-weight: var(--fw-semibold); color: var(--text); margin-bottom: var(--sp-4); padding-bottom: var(--sp-3); border-bottom: 1px solid var(--border); }
.form-group { margin-bottom: var(--sp-4); }
.form-group label { display: block; font-size: var(--fs-base); font-weight: var(--fw-medium); color: var(--muted); margin-bottom: var(--sp-2); }
.form-group textarea { min-height: 80px; resize: vertical; }

.info-box { background: var(--surface-2); border-radius: var(--r-md); padding: var(--sp-4); margin-bottom: var(--sp-5); font-size: var(--fs-base); color: var(--muted); line-height: var(--lh-relaxed); }
.info-box code { background: var(--surface); padding: 2px 6px; border-radius: var(--r-xs); color: var(--blue); }
.info-box a { color: var(--blue); }

.required { color: var(--red); }
.optional { color: var(--muted); font-size: var(--fs-sm); }

.parsed-info { background: var(--surface-2); border-radius: var(--r-md); padding: var(--sp-4); margin-top: var(--sp-4); font-size: var(--fs-sm); }
.parsed-info h4 { color: var(--green); margin-bottom: var(--sp-2); }
.parsed-item { margin: var(--sp-1) 0; color: var(--muted); }
.parsed-item span { color: var(--green); font-family: 'SF Mono', monospace; }
.model-id-value { color: var(--green); font-family: 'SF Mono', monospace; }

.fill-btns { margin-top: var(--sp-3); display: flex; gap: var(--sp-2); }
.fill-btn { padding: var(--sp-1) var(--sp-3); font-size: var(--fs-sm); }

.btn-save { width: 100%; margin-top: var(--sp-5); padding: var(--sp-3) var(--sp-6); font-size: var(--fs-md); }

.status-msg { margin-top: var(--sp-4); padding: var(--sp-4); border-radius: var(--r-md); font-size: var(--fs-md); }
.status-msg.success { background: var(--green-bg); border: 1px solid var(--green); color: var(--green-fg); }
.status-msg.error { background: var(--red-bg); border: 1px solid var(--red); color: var(--red-fg); }
</style>
