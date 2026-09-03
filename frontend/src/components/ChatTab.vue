<template>
  <div class="chat-shell">
    <div class="chat-header">
      <span class="header-greeting">
        <svg class="header-icon" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
        <span class="greeting-text">{{ greeting }}</span>
      </span>
      <!-- Custom Model Picker Dropdown -->
      <div class="custom-dropdown" ref="dropdownEl">
        <button class="dropdown-trigger" @click.stop="toggleDropdown" :title="selectedModel">
          <span class="selected-text">{{ selectedModel }}</span>
          <svg class="dropdown-arrow-icon" :class="{ open: dropdownOpen }" xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
        </button>
        <Transition name="dropdown-fade">
          <div v-if="dropdownOpen" class="dropdown-menu">
            <div class="dropdown-scroll-area">
              <div v-for="([group, models]) in groupedModels" :key="group" class="dropdown-group">
                <div class="dropdown-group-label">{{ group }}</div>
                <div 
                  v-for="m in models" 
                  :key="m" 
                  class="dropdown-item" 
                  :class="{ active: selectedModel === m }" 
                  @click="selectModel(m)"
                >
                  {{ m }}
                </div>
              </div>
            </div>
          </div>
        </Transition>
      </div>
      <span class="badge token-badge" :class="tokenBadgeClass">{{ tokenBadgeText }}</span>
      <button class="btn-secondary btn-new-chat" @click="newChat">
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        <span>新对话</span>
      </button>
      <button class="btn-icon btn-history" @click="showHistory = !showHistory" title="历史记录">
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
        <span class="history-count" v-if="conversations.length > 0">{{ conversations.length }}</span>
      </button>
    </div>

    <!-- History Sidebar -->
    <Transition name="slide-fade">
      <div v-if="showHistory" class="history-sidebar">
        <div class="history-header">
          <span>历史记录</span>
          <button class="btn-icon" @click="showHistory = false">×</button>
        </div>
        <div class="history-list">
          <div v-if="conversations.length === 0" class="history-empty">暂无历史记录</div>
          <div
            v-for="(conv, idx) in conversations"
            :key="idx"
            class="history-item"
            :class="{ active: activeConversationIdx === idx }"
            @click="loadConversation(idx)"
          >
            <div class="history-item-title">{{ conv.title }}</div>
            <div class="history-item-time">{{ conv.time }}</div>
            <button class="history-delete-btn" @click.stop="deleteConversation(idx)" title="删除">×</button>
          </div>
        </div>
      </div>
    </Transition>

    <div class="chat-messages" ref="messagesEl" @scroll="handleMessagesScroll">
      <EmptyState v-if="messages.length === 0" title="开始新对话" description="输入消息与 AI 开始对话">
        <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
      </EmptyState>
      <div
        v-for="(msg, idx) in messages"
        :key="idx"
        class="msg"
        :class="msg.role"
        :data-msg-idx="idx"
      >
        <!-- User message -->
        <template v-if="msg.role === 'user'">
          <div v-if="msg.images?.length" class="msg-images">
            <img v-for="(src, i) in msg.images" :key="i" :src="src" class="msg-thumb" />
          </div>
          <span v-html="escapeHtml(msg.text)"></span>
          <span class="msg-time">{{ msg.time }}</span>
          <div class="msg-actions">
            <button @click="copyMsg(msg.text)">复制</button>
            <button @click="editMsg(idx)">编辑</button>
          </div>
        </template>

        <!-- Assistant message -->
        <template v-if="msg.role === 'assistant'">
          <div v-if="msg.thinking" class="thinking-block">
            <div class="thinking-toggle" :class="{ collapsed: !msg.thinkingOpen }" @click="msg.thinkingOpen = !msg.thinkingOpen">
              <span class="arrow"></span> 思考过程
            </div>
            <div class="thinking-content" :class="{ collapsed: !msg.thinkingOpen }" v-html="renderMd(msg.thinking)"></div>
          </div>
          <div v-html="renderMd(msg.reply)"></div>
          <div v-if="msg.streaming" class="assistant-stream-actions">
            <span class="inline-spinner"></span>
            <button class="jump-current-btn" @click="scrollToMessageTop(idx)" title="定位到本条消息顶部" aria-label="定位到本条消息顶部">↥</button>
          </div>
          <span v-else-if="msg.time" class="msg-time">{{ msg.time }}</span>
        </template>
      </div>
    </div>

    <div class="chat-input-area">
      <div class="prompt-bar">
        <span class="prompt-label">Prompt:</span>
        <select v-model="activePromptId" @change="onPromptChange" class="prompt-select">
          <option value="">(none)</option>
          <option v-for="p in prompts" :key="p.id" :value="p.id">{{ p.title || '(untitled)' }}</option>
        </select>
        <button class="btn-icon prompt-edit-btn" @click="showPromptEditor = true" title="管理 Prompt">+✎</button>
      </div>

      <div v-if="attachedImages.length" class="img-preview-area">
        <div v-for="(img, i) in attachedImages" :key="i" class="img-preview-item">
          <img :src="img.base64" alt="preview" />
          <button class="remove-img" @click="attachedImages.splice(i, 1)">×</button>
        </div>
      </div>

      <div class="chat-input-wrap">
        <button class="btn-icon attach-btn" @click="($refs.fileInput as HTMLInputElement).click()" title="上传图片">📎</button>
        <input ref="fileInput" type="file" accept="image/jpeg,image/png,image/gif,image/webp" multiple class="hidden-input" @change="handleFiles" />
        <textarea
          v-model="inputText"
          rows="1"
          placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
          @input="autoResize"
          @keydown="onKeydown"
          class="chat-textarea"
        ></textarea>
        <button class="send-btn" :disabled="isSending" @click="sendMessage" title="发送">➤</button>
      </div>
    </div>

    <!-- Prompt Editor Modal -->
    <ModalOverlay v-model="showPromptEditor" title="System Prompt 管理" width="520px">
      <div class="prompt-list">
        <div v-if="prompts.length === 0" class="prompt-empty">暂无 Prompt</div>
        <div v-for="p in prompts" :key="p.id" class="prompt-item">
          <span class="prompt-title" :class="{ active: p.is_active }" @click="selectPrompt(p)">{{ p.title || '(untitled)' }}</span>
          <button class="btn-icon prompt-delete-btn" @click="deletePrompt(p.id)" title="删除">🗑</button>
        </div>
      </div>
      <div class="prompt-divider"></div>
      <input v-model="promptTitle" class="input-field" placeholder="标题" />
      <textarea v-model="promptContent" class="input-field prompt-textarea" placeholder="System prompt 内容..."></textarea>
      <template #actions>
        <button class="btn-secondary" @click="showPromptEditor = false">取消</button>
        <button class="btn-primary" @click="savePrompt">保存</button>
      </template>
    </ModalOverlay>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, inject, nextTick } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import { getModelsAPI, getTokenStatusAPI, chatCompletionsAPI, resetChatAPI, listPromptsAPI, createPromptAPI, deletePromptAPI, activatePromptAPI } from '@/api'
import ModalOverlay from '@/components/ModalOverlay.vue'
import EmptyState from '@/components/EmptyState.vue'
import type { PromptItem } from '@/types'

const auth = useAuthStore()
const toast = useToastStore()
const openLightbox = inject<(url: string) => void>('openLightbox', () => {})

// History
const showHistory = ref(false)
const conversations = ref<Array<{ title: string; time: string; messages: DisplayMsg[]; chatHistory: Array<{ role: string; content: unknown }> }>>([])
const activeConversationIdx = ref(-1)

function getHistoryKey() {
  // Ensure we have a stable user key
  const userKey = auth.username || (auth.getApiKey() ? `key_${auth.getApiKey().slice(-8)}` : 'guest')
  return `yj_chat_history_${userKey}`
}

function saveConversation() {
  if (chatHistory.value.length === 0) return
  if (!auth.username && !auth.getApiKey()) return // Don't save if not authed
  const title = messages.value.find(m => m.role === 'user')?.text?.slice(0, 20) || '新对话'
  const now = new Date()
  const time = `${now.getHours().toString().padStart(2, '0')}:${now.getMinutes().toString().padStart(2, '0')}`
  const newConv = { title, time, messages: [...messages.value], chatHistory: [...chatHistory.value] }
  // Update existing or add new
  if (activeConversationIdx.value >= 0) {
    conversations.value[activeConversationIdx.value] = newConv
  } else {
    conversations.value.unshift(newConv)
    activeConversationIdx.value = 0
  }
  localStorage.setItem(getHistoryKey(), JSON.stringify(conversations.value))
}

function loadConversation(idx: number) {
  const conv = conversations.value[idx]
  if (!conv) return
  messages.value = [...conv.messages]
  chatHistory.value = [...conv.chatHistory]
  activeConversationIdx.value = idx
  showHistory.value = false
  nextTick(() => scrollToBottom(true))
}

function deleteConversation(idx: number) {
  conversations.value.splice(idx, 1)
  if (activeConversationIdx.value === idx) {
    activeConversationIdx.value = -1
    messages.value = []
    chatHistory.value = []
  } else if (activeConversationIdx.value > idx) {
    activeConversationIdx.value--
  }
  localStorage.setItem(getHistoryKey(), JSON.stringify(conversations.value))
}

let updateTokenTimer: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  await auth.fetchApiKey()
  loadHistory()
  window.addEventListener('beforeunload', saveConversation)
  document.addEventListener('click', onDocumentClick)

  try {
    const data = await getModelsAPI(auth.getApiKey())
    allModels.value = (data.data || []).map(m => m.id)
  } catch { /* models unavailable */ }
  updateTokenBadge()
  updateTokenTimer = setInterval(updateTokenBadge, 30000)
  loadPrompts()
})

onUnmounted(() => {
  saveConversation()
  window.removeEventListener('beforeunload', saveConversation)
  document.removeEventListener('click', onDocumentClick)
  if (updateTokenTimer) clearInterval(updateTokenTimer)
  if (loadHistoryTimer) clearTimeout(loadHistoryTimer)
})

let loadHistoryTimer: ReturnType<typeof setTimeout> | null = null
let loadHistoryRetries = 0

function loadHistory() {
  const key = getHistoryKey()
  if ((!key || key.endsWith('_guest')) && loadHistoryRetries < 20) {
    loadHistoryRetries++
    loadHistoryTimer = setTimeout(loadHistory, 300)
    return
  }
  const stored = localStorage.getItem(key)
  if (stored) {
    try { conversations.value = JSON.parse(stored) } catch { /* ignore */ }
  }
}

// Models
const allModels = ref<string[]>([])
const selectedModel = ref('gemini/gemini-3.8-flash')
const dropdownOpen = ref(false)
const dropdownEl = ref<HTMLElement | null>(null)

function toggleDropdown() {
  dropdownOpen.value = !dropdownOpen.value
}

function selectModel(model: string) {
  selectedModel.value = model
  dropdownOpen.value = false
}

// 点击外部关闭下拉菜单
function onDocumentClick(e: MouseEvent) {
  if (dropdownEl.value && !dropdownEl.value.contains(e.target as Node)) {
    dropdownOpen.value = false
  }
}

const groupedModels = computed(() => {
  const groups = new Map<string, string[]>()
  for (const model of allModels.value) {
    const slashIndex = model.indexOf('/')
    const group = slashIndex > 0 ? model.slice(0, slashIndex) : 'gemini'
    const existing = groups.get(group)
    if (existing) {
      existing.push(model)
    } else {
      groups.set(group, [model])
    }
  }
  return Array.from(groups.entries())
})

// Token badge
const tokenBadgeClass = ref('badge-warning')
const tokenBadgeText = ref('检查中...')
async function updateTokenBadge() {
  try {
    const data = await getTokenStatusAPI(auth.getApiKey())
    if (data.has_snlm0e) {
      tokenBadgeClass.value = 'badge-success'
      tokenBadgeText.value = `已刷新 ${data.total_refresh_count} 次`
    } else {
      tokenBadgeClass.value = 'badge-error'
      tokenBadgeText.value = 'Token 已失效'
    }
  } catch {
    tokenBadgeClass.value = 'badge-error'
    tokenBadgeText.value = '无法获取状态'
  }
}

// Greeting
const greeting = computed(() => `${auth.greeting}，${auth.username}`)

// Chat
interface DisplayMsg {
  role: 'user' | 'assistant'
  text: string
  time: string
  images?: string[]
  reply: string
  thinking: string
  thinkingOpen: boolean
  streaming: boolean
}
const messages = ref<DisplayMsg[]>([])
const chatHistory = ref<Array<{ role: string; content: unknown }>>([])
const inputText = ref('')
const isSending = ref(false)
const messagesEl = ref<HTMLElement | null>(null)
const attachedImages = ref<Array<{ base64: string; mime: string; name: string }>>([])
const abortController = ref<AbortController | null>(null)
const autoFollowStream = ref(true)

function timeStr() {
  const d = new Date()
  return d.getHours().toString().padStart(2, '0') + ':' + d.getMinutes().toString().padStart(2, '0') + ':' + d.getSeconds().toString().padStart(2, '0')
}

function escapeHtml(t: string) {
  return t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>')
}

function proxyImgUrl(url: string) {
  if (!url) return url
  // Local media paths - pass through
  if (url.startsWith('/media/')) return url
  if (url.includes('/media/')) return url
  // Proxy all external URLs through the backend
  if (/^https?:\/\//.test(url)) {
    return '/proxy_image?url=' + encodeURIComponent(url)
  }
  return url
}

function renderMd(text: string): string {
  if (!text) return ''
  const imgMap: Array<{ alt: string; url: string; proxyUrl: string }> = []
  let s = text.replace(/!\[([^\]]*)\]\(([^)]+)\)/g, (_m, alt, url) => {
    const idx = imgMap.length
    imgMap.push({ alt: alt || 'image', url, proxyUrl: proxyImgUrl(url) })
    return `\u0000IMG${idx}\u0000`
  })
  s = s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  s = s.replace(/^###\s+(.+)$/gm, '<h3>$1</h3>')
  s = s.replace(/^##\s+(.+)$/gm, '<h2>$1</h2>')
  s = s.replace(/^#\s+(.+)$/gm, '<h1>$1</h1>')
  s = s.replace(/^>\s+(.+)$/gm, '<blockquote>$1</blockquote>')
  s = s.replace(/^---+$/gm, '<hr>')
  s = s.replace(/```([\s\S]*?)```/g, '<pre><code>$1</code></pre>')
  s = s.replace(/`([^`]+)`/g, '<code>$1</code>')
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>')
  s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
  s = s.replace(/\*(.+?)\*/g, '<em>$1</em>')
  s = s.replace(/\u0000IMG(\d+)\u0000/g, (_m, idx) => {
    const img = imgMap[parseInt(idx)]
    return `<div class="ai-img-wrap"><img class="ai-img" src="${img.proxyUrl}" alt="${escapeHtml(img.alt)}" onclick="window.__lb&&window.__lb('${img.proxyUrl.replace(/'/g, "\\'")}')" /><div class="ai-img-hint">点击查看详细图片</div></div>`
  })
  s = s.replace(/^[\s]*[-*]\s+\[ \]\s+(.+)$/gm, '<li class="task-item"><input type="checkbox" disabled> <span>$1</span></li>')
  s = s.replace(/^[\s]*[-*]\s+\[[xX]\]\s+(.+)$/gm, '<li class="task-item"><input type="checkbox" checked disabled> <span>$1</span></li>')
  s = s.replace(/^[\s]*[-*]\s+(.+)$/gm, '<li>$1</li>')
  s = s.replace(/^[\s]*\d+\.\s+(.+)$/gm, '<li data-ordered="true">$1</li>')
  s = s.replace(/((?:<li data-ordered="true">.*?<\/li>\s*)+)/gs, (_m, items) => `<ol>${items.replace(/ data-ordered="true"/g, '')}</ol>`)
  s = s.replace(/((?:<li(?: class="task-item")?>.*?<\/li>\s*)+)/gs, (block) => block.includes('task-item') ? `<ul class="task-list">${block}</ul>` : `<ul>${block}</ul>`)
  s = s.replace(/((?:\|.+\|\n)+(?:\|(?:\s*:?-+:?\s*\|)+\n(?:\|.*\|\n?)*)?)/g, (tableBlock) => {
    const lines = tableBlock.trim().split('\n').map(line => line.trim()).filter(Boolean)
    if (lines.length < 2) return tableBlock
    const separator = lines[1]
    if (!/^\|?(\s*:?-+:?\s*\|)+\s*$/.test(separator)) return tableBlock
    const parseRow = (line: string) => line.replace(/^\||\|$/g, '').split('|').map(cell => cell.trim())
    const headers = parseRow(lines[0])
    const bodyRows = lines.slice(2).map(parseRow)
    const thead = `<thead><tr>${headers.map(cell => `<th>${cell}</th>`).join('')}</tr></thead>`
    const tbody = `<tbody>${bodyRows.map(row => `<tr>${row.map(cell => `<td>${cell}</td>`).join('')}</tr>`).join('')}</tbody>`
    return `<div class="md-table-wrap"><table>${thead}${tbody}</table></div>`
  })
  s = s.replace(/\n/g, '<br>')
  s = s.replace(/<blockquote>(.*?)<\/blockquote>/gs, (_m, c) => '<blockquote>' + c.replace(/<br>/g, '') + '</blockquote>')
  s = s.replace(/<(h[1-3])>(.*?)<\/\1>/gs, (_m, tag, c) => `<${tag}>${String(c).replace(/<br>/g, '')}</${tag}>`)
  s = s.replace(/<hr><br>/g, '<hr>')
  s = s.replace(/<table>(.*?)<\/table><br>/gs, '<table>$1</table>')
  s = s.replace(/<\/div><br>/g, '</div>')
  s = s.replace(/<pre><code>(.*?)<\/code><\/pre>/gs, (_m, c) => '<pre><code>' + c.replace(/<br>/g, '\n') + '</code></pre>')
  return s
}

function isNearBottom(): boolean {
  if (!messagesEl.value) return true
  const el = messagesEl.value
  const distance = el.scrollHeight - el.scrollTop - el.clientHeight
  return distance <= 80
}

function handleMessagesScroll() {
  autoFollowStream.value = isNearBottom()
}

function scrollToBottom(force: boolean = false) {
  if (!force && !autoFollowStream.value) return
  requestAnimationFrame(() => {
    if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight
  })
}

function scrollToMessageTop(idx: number) {
  requestAnimationFrame(() => {
    const container = messagesEl.value
    if (!container) return
    const target = container.querySelector(`[data-msg-idx="${idx}"]`) as HTMLElement | null
    if (!target) return
    container.scrollTop = Math.max(0, target.offsetTop - 8)
  })
}

function newChat() {
  if (isSending.value) return
  saveConversation() // Save current before clearing
  messages.value = []
  chatHistory.value = []
  activeConversationIdx.value = -1
  const oldSessionId = auth.getChatSessionId()
  auth.resetChatSessionId()
  resetChatAPI(auth.getApiKey(), oldSessionId).catch(() => {})
  toast.info('已开始新对话')
}

function handleFiles(e: Event) {
  const files = (e.target as HTMLInputElement).files
  if (!files) return
  for (let i = 0; i < files.length; i++) {
    const file = files[i]
    if (!file.type.startsWith('image/')) continue
    const reader = new FileReader()
    reader.onload = (ev) => {
      attachedImages.value.push({ base64: ev.target!.result as string, mime: file.type, name: file.name })
    }
    reader.readAsDataURL(file)
  }
  ;(e.target as HTMLInputElement).value = ''
}

function autoResize(e: Event) {
  const el = e.target as HTMLTextAreaElement
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 120) + 'px'
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMessage()
  }
}

function parseThinkingChunk(
  c: string,
  inThinkTag: number,
  thinkingContent: string,
): { content: string; thinking: string; done: boolean; tagIdx: number } {
  const thinkPairs = [
    { open: '<thinking>', close: '</thinking>' },
    { open: '««', close: '»»' },
    { open: '<reasoning>', close: '</reasoning>' },
    { open: '<reason>', close: '</reason>' },
    { open: '<reflect>', close: '</reflect>' },
    { open: '<reflection>', close: '</reflection>' },
    { open: '<thought>', close: '</thought>' },
  ]
  let thinking = thinkingContent
  let done = false
  let tagIdx = inThinkTag
  let content = ''

  for (let ti = 0; ti < thinkPairs.length; ti++) {
    const pair = thinkPairs[ti]
    const hasOpen = c.indexOf(pair.open) > -1
    const hasClose = c.indexOf(pair.close) > -1
    if (hasOpen || tagIdx === ti) {
      tagIdx = ti
      if (hasOpen) c = c.split(pair.open)[1] || ''
      if (hasClose) {
        const beforeClose = c.split(pair.close)[0] || ''
        const afterClose = c.substring(c.indexOf(pair.close) + pair.close.length)
        thinking += beforeClose
        if (afterClose) content = afterClose
        done = true
        tagIdx = -1
      } else {
        thinking += c
        c = ''
      }
      return { content, thinking, done, tagIdx }
    }
  }
  // 不在任何 think 标签内
  if (thinking && !done) done = true
  return { content: c, thinking, done, tagIdx }
}

// Replaces the inline think-tag parsing block in SSE handler
function processContentDelta(
  deltaContent: string,
  thinkingContent: string,
  inThinkTag: number,
): { replyContent: string; thinkingContent: string; thinkingDone: boolean; inThinkTag: number } {
  const result = parseThinkingChunk(deltaContent, inThinkTag, thinkingContent)
  return {
    replyContent: result.content,
    thinkingContent: result.thinking,
    thinkingDone: result.done,
    inThinkTag: result.tagIdx,
  }
}

	async function sendMessage() {
  if (isSending.value) return
  const text = inputText.value.trim()
  if (!text && attachedImages.value.length === 0) return

  isSending.value = true
  let content: unknown = text
  const imgSrcs: string[] = []
  if (attachedImages.value.length > 0) {
    content = []
    if (text) (content as Array<Record<string, unknown>>).push({ type: 'text', text })
    attachedImages.value.forEach(img => {
      imgSrcs.push(img.base64)
      ;(content as Array<Record<string, unknown>>).push({ type: 'image_url', image_url: { url: img.base64 } })
    })
  }

  messages.value.push({ role: 'user', text, time: timeStr(), images: imgSrcs, reply: '', thinking: '', thinkingOpen: true, streaming: false })
  inputText.value = ''
  attachedImages.value = []
  chatHistory.value.push({ role: 'user', content })

  const systemPrompt = getActivePromptContent()
  const messagesToSend = systemPrompt
    ? [{ role: 'system', content: systemPrompt }, ...chatHistory.value]
    : chatHistory.value.slice()

const replyMsg: DisplayMsg = { role: 'assistant', text: '', time: '', reply: '', thinking: '', thinkingOpen: false, streaming: true }
messages.value.push(replyMsg)
// 必须获取 Vue 代理后的响应式引用，否则后续修改 replyMsg.reply 等属性
// 修改的是原始普通对象而非 Vue Proxy，不会触发 UI 更新
const replyMsgReactive = messages.value[messages.value.length - 1]
autoFollowStream.value = true
scrollToBottom(true)

  try {
    const model = selectedModel.value || 'gemini-3.8-flash'
    const sessionId = auth.getChatSessionId()
    abortController.value = new AbortController()
    const resp = await chatCompletionsAPI(auth.getApiKey(), { model, messages: messagesToSend, stream: true }, sessionId, abortController.value.signal)
    if (!resp.ok) {
      let errText = `请求失败 (HTTP ${resp.status})`
      try { const errJson = await resp.json(); errText = errJson.detail || errJson.error || JSON.stringify(errJson) } catch { /* ignore parse error */ }
      replyMsgReactive.reply = '错误: ' + errText
      replyMsgReactive.streaming = false
      replyMsgReactive.time = timeStr()
      isSending.value = false
      return
    }

        let replyContent = ''
        let thinkingContent = ''
        let thinkingDone = false
        let inThinkTag = -1

    const reader = resp.body!.getReader()
    const decoder = new TextDecoder()
    let sseBuffer = ''

    try {
      while (true) {
        const result = await reader.read()
        if (result.done) break
        sseBuffer += decoder.decode(result.value, { stream: true })
        const lines = sseBuffer.split('\n')
        sseBuffer = lines.pop() || ''
        for (const line of lines) {
          const trimmed = line.trim()
          if (!trimmed.startsWith('data: ')) continue
          const dataStr = trimmed.substring(6)
          if (dataStr === '[DONE]') continue
          try {
            const data = JSON.parse(dataStr)
            const delta = data.choices?.[0]?.delta
            if (!delta) continue

            // 服务器已将 thinking 标签解析为 reasoning_content
            // 直接累积即可，无需客户端重复解析
            if (delta.reasoning_content) {
              thinkingContent += delta.reasoning_content
              // 思考过程中保持 thinkingOpen = true
              replyMsgReactive.thinkingOpen = true
            }
            if (delta.reasoning) {
              thinkingContent += delta.reasoning
              replyMsgReactive.thinkingOpen = true
            }

            if (delta.content) {
              if (thinkingContent) {
                if (thinkingContent && !thinkingDone) thinkingDone = true
                replyContent += delta.content
              } else {
                const processed = processContentDelta(delta.content, thinkingContent, inThinkTag)
                replyContent += processed.replyContent
                thinkingContent = processed.thinkingContent
                thinkingDone = processed.thinkingDone
                inThinkTag = processed.inThinkTag
              }
            }

            replyMsgReactive.reply = replyContent
            replyMsgReactive.thinking = thinkingContent

            // 思考块 UI 控制：
            // - 思考进行中（有 thinkingContent 且 thinkingDone=false）：保持展开
            // - 思考已完成（thinkingDone=true）：折叠
            // - 无思考内容：不受影响
            if (thinkingContent) {
              replyMsgReactive.thinkingOpen = !thinkingDone
            }

            scrollToBottom()
          } catch { /* skip unparseable SSE line */ }
        }
      }

      replyMsgReactive.streaming = false
      replyMsgReactive.time = timeStr()
      // 流结束后确保思考块折叠
      if (thinkingContent) {
        replyMsgReactive.thinkingOpen = false
      }
      chatHistory.value.push({ role: 'assistant', content: replyContent })
      saveConversation() // Auto-save after assistant reply
    } finally {
      reader.releaseLock()
      abortController.value = null
    }
  } catch (e: unknown) {
    replyMsgReactive.reply = '请求失败: ' + (e instanceof Error ? e.message : String(e))
    replyMsgReactive.streaming = false
    replyMsgReactive.time = timeStr()
  } finally {
    isSending.value = false
  }
}

function copyMsg(text: string) {
  navigator.clipboard.writeText(text).then(() => toast.success('已复制')).catch(() => toast.error('复制失败'))
}

function editMsg(idx: number) {
  const msg = messages.value[idx]
  if (!msg) return
  // Position-based sync: slice both arrays at the same index
  messages.value = messages.value.slice(0, idx)
  chatHistory.value = chatHistory.value.slice(0, idx)
  inputText.value = msg.text
}

// Prompts
const prompts = ref<PromptItem[]>([])
const activePromptId = ref<number | string>('')
const showPromptEditor = ref(false)
const promptTitle = ref('')
const promptContent = ref('')

async function loadPrompts() {
  try {
    const data = await listPromptsAPI('prompt')
    prompts.value = data.data || []
    const active = prompts.value.find(p => p.is_active)
    activePromptId.value = active ? active.id : ''
  } catch { /* prompts unavailable */ }
}

function onPromptChange() {
  const val = activePromptId.value
  const id = typeof val === 'string' ? parseInt(val) : val
  activatePromptAPI('prompt', id || 0).catch(() => {})
}

function selectPrompt(p: PromptItem) {
  promptTitle.value = p.title
  promptContent.value = p.content
  activePromptId.value = p.id
  activatePromptAPI('prompt', p.id).catch(() => {})
}

async function savePrompt() {
  if (!promptContent.value.trim()) { toast.warning('Prompt 内容不能为空'); return }
  try {
    await createPromptAPI('prompt', promptTitle.value, promptContent.value)
    showPromptEditor.value = false
    toast.success('Prompt 已保存')
    loadPrompts()
  } catch (e) {
    toast.error('保存失败')
  }
}

async function deletePrompt(id: number) {
  try {
    await deletePromptAPI('prompt', id)
    showPromptEditor.value = false
    toast.success('已删除')
    loadPrompts()
  } catch {
    toast.error('删除失败')
  }
}

function getActivePromptContent(): string {
  const val = activePromptId.value
  const id = typeof val === 'string' ? parseInt(val) : val
  const p = prompts.value.find(x => x.id === id)
  return p ? p.content : ''
}
</script>

<style scoped>
.chat-shell { display: flex; flex-direction: column; flex: 1; min-height: 0; height: 100%; overflow: hidden; background: var(--bg); }

/* Header */
.chat-header {
  padding: var(--sp-3) var(--sp-4);
  border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: var(--sp-3);
  background: var(--surface);
  transition: background var(--t-normal), border-color var(--t-normal);
  flex-wrap: wrap;
}
.header-greeting {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-weight: var(--fw-semibold);
  font-size: var(--fs-md);
  white-space: nowrap;
}
.greeting-text {
  max-width: 140px; 
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* Custom Dropdown Component */
.custom-dropdown {
  position: relative;
  display: inline-block;
}
.dropdown-trigger {
  background: var(--surface-2);
  color: var(--text);
  border: 1px solid var(--border);
  padding: var(--sp-2) var(--sp-4);
  font-size: var(--fs-base);
  font-weight: var(--fw-medium);
  cursor: pointer;
  border-radius: var(--r-xl);
  outline: none;
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  max-width: 220px;
  transition: border-color var(--t-normal), box-shadow var(--t-normal);
}
.dropdown-trigger:hover {
  border-color: var(--blue);
}
.selected-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dropdown-arrow-icon {
  flex-shrink: 0;
  transition: transform var(--t-normal);
  color: var(--muted);
}
.dropdown-arrow-icon.open {
  transform: rotate(180deg);
}
.dropdown-menu {
  position: absolute;
  top: calc(100% + var(--sp-1));
  left: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-xl);
  box-shadow: var(--shadow-lg);
  z-index: 100;
  min-width: 260px;
  max-width: 320px;
  overflow: hidden;
}
.dropdown-scroll-area {
  max-height: 280px;
  overflow-y: auto;
  padding: var(--sp-2) 0;
}
.dropdown-group {
  padding: var(--sp-1) 0;
}
.dropdown-group-label {
  font-size: var(--fs-xs);
  font-weight: var(--fw-bold);
  text-transform: uppercase;
  color: var(--muted);
  padding: var(--sp-1) var(--sp-3);
  letter-spacing: 0.5px;
}
.dropdown-item {
  padding: var(--sp-2) var(--sp-3);
  font-size: var(--fs-base);
  color: var(--text);
  cursor: pointer;
  transition: background var(--t-fast), color var(--t-fast);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.dropdown-item:hover {
  background: var(--hover-bg);
  color: var(--blue);
}
.dropdown-item.active {
  background: rgba(110, 168, 254, 0.15);
  color: var(--blue);
  font-weight: var(--fw-semibold);
}

/* Transitions */
.dropdown-fade-enter-active,
.dropdown-fade-leave-active {
  transition: opacity 0.15s ease, transform 0.15s cubic-bezier(0, 0, 0.2, 1);
}
.dropdown-fade-enter-from,
.dropdown-fade-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

.token-badge {
  white-space: nowrap;
  font-variant-numeric: tabular-nums;
  max-width: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.btn-history {
  position: relative;
  border: 1px solid var(--blue);
  background: rgba(110, 168, 254, 0.15);
  color: var(--blue);
  padding: 4px 10px;
  border-radius: var(--r-xl);
  font-size: var(--fs-base);
  font-weight: var(--fw-semibold);
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: all var(--t-normal);
  box-shadow: 0 0 0 0 rgba(110, 168, 254, 0);
}
.btn-history:hover {
  background: rgba(110, 168, 254, 0.25);
  box-shadow: 0 0 12px rgba(110, 168, 254, 0.35);
  transform: translateY(-1px);
}
.history-count {
  background: var(--blue);
  color: #fff;
  border-radius: var(--r-full);
  padding: 0 5px;
  font-size: 10px;
  font-weight: var(--fw-bold);
  min-width: 16px;
  text-align: center;
  line-height: 16px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.2);
}
.btn-new-chat {
  margin-left: auto;
  font-size: var(--fs-base);
  padding: var(--sp-1) var(--sp-3);
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
}

/* History Sidebar */
.history-sidebar {
  position: fixed;
  top: 0;
  right: 0;
  width: 280px;
  height: 100vh;
  background: var(--surface);
  border-left: 1px solid var(--border);
  z-index: var(--z-fixed, 300);
  display: flex;
  flex-direction: column;
  box-shadow: var(--shadow-3);
}
.history-header {
  padding: var(--sp-4);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: var(--fw-semibold);
  font-size: var(--fs-md);
}
.history-list {
  flex: 1;
  overflow-y: auto;
  padding: var(--sp-2);
}
.history-empty {
  color: var(--muted);
  text-align: center;
  padding: var(--sp-5);
  font-size: var(--fs-base);
}
.history-item {
  padding: var(--sp-3);
  border-radius: var(--r-xl);
  cursor: pointer;
  margin-bottom: var(--sp-1);
  transition: background var(--t-fast);
  position: relative;
  border: 1px solid transparent;
}
.history-item:hover { background: var(--hover-bg); }
.history-item.active {
  background: rgba(110, 168, 254, 0.1);
  border-color: var(--blue);
}
.history-item-title {
  font-size: var(--fs-base);
  font-weight: var(--fw-medium);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  padding-right: var(--sp-5);
}
.history-item-time {
  font-size: var(--fs-xs);
  color: var(--muted);
  margin-top: var(--sp-1);
}
.history-delete-btn {
  position: absolute;
  top: var(--sp-2);
  right: var(--sp-2);
  background: none;
  border: none;
  color: var(--muted);
  cursor: pointer;
  font-size: var(--fs-md);
  padding: var(--sp-1);
  border-radius: var(--r-sm);
  transition: color var(--t-fast), background var(--t-fast);
}
.history-delete-btn:hover { color: var(--red); background: var(--hover-bg); }

/* Slide transition */
.slide-fade-enter-active { transition: transform 0.2s ease, opacity 0.2s ease; }
.slide-fade-leave-active { transition: transform 0.2s ease, opacity 0.2s ease; }
.slide-fade-enter-from, .slide-fade-leave-to { transform: translateX(20px); opacity: 0; }

@media (max-width: 600px) {
  .chat-header {
    padding: var(--sp-2) var(--sp-3);
    gap: calc(var(--sp-1) * 1.5);
    flex-wrap: nowrap;
    overflow-x: auto;
  }
  .greeting-text {
    max-width: 60px;
  }
  .model-select {
    max-width: 110px;
    font-size: var(--fs-sm);
    padding: calc(var(--sp-1) * 1.5) var(--sp-4) calc(var(--sp-1) * 1.5) var(--sp-2);
  }
  .token-badge {
    font-size: var(--fs-xs);
    padding: 2px 4px;
    max-width: 90px;
  }
  .btn-new-chat span {
    display: none;
  }
}

/* Messages */
.chat-messages {
  flex: 1; min-height: 0; overflow-y: auto;
  padding: var(--sp-5);
  display: flex; flex-direction: column; gap: var(--sp-3);
}
.msg {
  max-width: 85%;
  padding: var(--sp-3) var(--sp-4);
  border-radius: var(--r-2xl);
  font-size: var(--fs-md);
  line-height: var(--lh-relaxed);
  position: relative;
  word-wrap: break-word;
  white-space: pre-wrap;
}
.msg .msg-time { font-size: var(--fs-xs); margin-top: var(--sp-2); opacity: .65; display: block; }

.msg.user {
  align-self: flex-end;
  background: var(--blue);
  color: #fff;
  border-bottom-right-radius: var(--r-xs);
}
.msg.user .msg-time { color: rgba(255,255,255,.7); }
.msg.user .msg-actions { display: flex; gap: var(--sp-2); margin-top: var(--sp-2); }
.msg.user .msg-actions button {
  background: rgba(255,255,255,.15);
  color: rgba(255,255,255,.8);
  border: none;
  padding: var(--sp-1) var(--sp-3);
  border-radius: var(--r-sm);
  font-size: var(--fs-xs);
  cursor: pointer;
  transition: all var(--t-normal);
}
.msg.user .msg-actions button:hover { background: rgba(255,255,255,.3); color: #fff; }

.msg.assistant {
  align-self: flex-start;
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border);
  border-bottom-left-radius: var(--r-xs);
}
.msg.assistant .inline-spinner {
  display: inline-block;
  width: 14px; height: 14px;
  border-radius: 50%;
  background: conic-gradient(#4285f4 0 25%, #ea4335 25% 50%, #fbbc04 50% 75%, #34a853 75% 100%);
  -webkit-mask: radial-gradient(farthest-side, transparent calc(100% - 2.5px), #000 calc(100% - 2.5px));
  mask: radial-gradient(farthest-side, transparent calc(100% - 2.5px), #000 calc(100% - 2.5px));
  animation: spin .8s linear infinite;
  vertical-align: middle;
  margin-left: var(--sp-2);
}
.msg.assistant .assistant-stream-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-top: var(--sp-2);
}
.msg.assistant .jump-current-btn {
  background: var(--surface-2);
  color: var(--muted);
  border: 1px solid var(--border);
  padding: var(--sp-1) var(--sp-2);
  border-radius: var(--r-xl);
  font-size: var(--fs-xs);
  cursor: pointer;
  transition: all var(--t-normal);
}
.msg.assistant .jump-current-btn:hover {
  color: var(--blue);
  border-color: var(--blue);
}
.msg.assistant :deep(pre) {
  background: var(--bg);
  padding: var(--sp-3);
  border-radius: var(--r-sm);
  overflow-x: auto;
  margin: var(--sp-2) 0;
  font-size: var(--fs-base);
  border: 1px solid var(--border);
}
.msg.assistant :deep(code) { font-family: 'SF Mono', Consolas, monospace; font-size: var(--fs-base); }
.msg.assistant :deep(code:not(pre code)) { background: var(--surface-2); padding: 2px 5px; border-radius: var(--r-xs); }
.msg.assistant :deep(h1), .msg.assistant :deep(h2), .msg.assistant :deep(h3) {
  line-height: 1.3;
  margin: var(--sp-3) 0 var(--sp-2);
  font-weight: var(--fw-semibold);
}
.msg.assistant :deep(h1) { font-size: calc(var(--fs-md) + 6px); }
.msg.assistant :deep(h2) { font-size: calc(var(--fs-md) + 3px); }
.msg.assistant :deep(h3) { font-size: var(--fs-md); }
.msg.assistant :deep(a) {
  color: var(--blue);
  text-decoration: underline;
  word-break: break-all;
}
.msg.assistant :deep(blockquote) {
  margin: var(--sp-2) 0;
  padding: var(--sp-2) var(--sp-3);
  border-left: 3px solid var(--blue);
  background: var(--surface-2);
  color: var(--muted);
  border-radius: 0 var(--r-sm) var(--r-sm) 0;
}
.msg.assistant :deep(hr) {
  border: none;
  border-top: 1px solid var(--border);
  margin: var(--sp-3) 0;
}
.msg.assistant :deep(ul), .msg.assistant :deep(ol) { padding-left: var(--sp-5); margin: var(--sp-2) 0; }
.msg.assistant :deep(li) { margin: var(--sp-1) 0; }
.msg.assistant :deep(.task-list) {
  list-style: none;
  padding-left: 0;
}
.msg.assistant :deep(.task-item) {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-2);
}
.msg.assistant :deep(.task-item input[type="checkbox"]) {
  margin-top: 0.2em;
  accent-color: var(--blue);
}
.msg.assistant :deep(strong) { color: var(--blue); }
.msg.assistant :deep(em) { color: var(--green); }
.msg.assistant :deep(.md-table-wrap) {
  width: 100%;
  overflow-x: auto;
  margin: var(--sp-3) 0;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
}
.msg.assistant :deep(table) {
  width: 100%;
  min-width: 420px;
  border-collapse: collapse;
  background: var(--surface);
}
.msg.assistant :deep(th),
.msg.assistant :deep(td) {
  padding: var(--sp-2) var(--sp-3);
  border-bottom: 1px solid var(--border);
  text-align: left;
  vertical-align: top;
}
.msg.assistant :deep(th) {
  background: var(--surface-2);
  font-weight: var(--fw-semibold);
}
.msg.assistant :deep(tr:last-child td) {
  border-bottom: none;
}
.msg.assistant :deep(.ai-img-wrap) {
  margin: var(--sp-2) 0;
  border-radius: var(--r-md);
  overflow: hidden;
  display: inline-flex;
  flex-direction: column;
  width: min(100%, 720px);
  max-width: 100%;
  background: var(--surface-2);
  border: 1px solid var(--border);
}
.msg.assistant :deep(.ai-img-wrap .ai-img) {
  width: 100%;
  max-width: 100%;
  max-height: min(70vh, 960px);
  border-radius: var(--r-md);
  cursor: pointer;
  display: block;
  transition: transform var(--t-normal), box-shadow var(--t-normal);
  object-fit: contain;
  background: var(--bg);
}
.msg.assistant :deep(.ai-img-wrap .ai-img:hover) { transform: scale(1.02); box-shadow: var(--shadow-3); }
.msg.assistant :deep(.ai-img-wrap .ai-img-hint) {
  font-size: var(--fs-xs);
  color: var(--muted);
  cursor: pointer;
  margin-top: 2px;
  padding: var(--sp-2) var(--sp-3);
}

/* Thinking block */
.thinking-block {
  margin-bottom: var(--sp-2);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  overflow: hidden;
  background: var(--surface-2);
}
.thinking-toggle {
  display: flex; align-items: center; gap: var(--sp-2);
  padding: var(--sp-2) var(--sp-3);
  cursor: pointer;
  font-size: var(--fs-base);
  color: var(--muted);
  user-select: none;
  transition: background var(--t-normal);
}
.thinking-toggle:hover { background: var(--hover-bg); }
.thinking-toggle .arrow {
  display: inline-block;
  width: 0; height: 0;
  border-left: 5px solid transparent;
  border-right: 5px solid transparent;
  border-top: 6px solid var(--muted);
  transition: transform var(--t-normal);
}
.thinking-toggle.collapsed .arrow { transform: rotate(-90deg); }
.thinking-content {
  padding: var(--sp-2) var(--sp-3);
  font-size: var(--fs-base);
  color: var(--muted);
  line-height: var(--lh-relaxed);
  max-height: 400px;
  overflow-y: auto;
  border-top: 1px solid var(--border);
  transition: max-height 0.4s cubic-bezier(.2,0,0,1), padding 0.4s cubic-bezier(.2,0,0,1);
}
.thinking-content.collapsed { max-height: 0; padding: 0 var(--sp-3); border-top: none; overflow: hidden; }

@keyframes spin { to { transform: rotate(360deg); } }

/* User message images */
.msg-images { margin-bottom: var(--sp-2); }
.msg-thumb {
  max-width: 80px; max-height: 80px;
  border-radius: var(--r-sm);
  margin-right: var(--sp-1);
}

/* Input area */
.chat-input-area {
  padding: var(--sp-3) var(--sp-5);
  border-top: 1px solid var(--border);
  background: var(--surface);
  transition: background var(--t-normal), border-color var(--t-normal);
}
.prompt-bar {
  display: flex; align-items: center; gap: var(--sp-2);
  padding: 0 0 var(--sp-2) 0;
  flex-wrap: wrap;
}
.prompt-label { font-size: var(--fs-xs); color: var(--muted); }
.prompt-select {
  background: var(--surface-2);
  color: var(--text);
  border: 1px solid var(--border);
  padding: var(--sp-1) var(--sp-2);
  font-size: var(--fs-base);
  border-radius: var(--r-xl);
  outline: none;
  cursor: pointer;
  max-width: 200px;
}
.prompt-select:hover { border-color: var(--blue); }
.btn-icon {
  background: none;
  border: 1px dashed var(--border);
  padding: var(--sp-1) var(--sp-3);
  border-radius: var(--r-xl);
  font-size: var(--fs-xs);
  color: var(--muted);
  cursor: pointer;
  transition: all var(--t-normal);
}
.btn-icon:hover { border-color: var(--blue); color: var(--blue); }
.prompt-edit-btn { border-style: dashed; }

.img-preview-area { display: flex; gap: var(--sp-2); padding: 0 0 var(--sp-2) 0; flex-wrap: wrap; }
.img-preview-item {
  position: relative;
  width: 56px; height: 56px;
  border-radius: var(--r-md);
  overflow: hidden;
  border: 1px solid var(--border);
  background: var(--surface);
}
.img-preview-item img { width: 100%; height: 100%; object-fit: cover; }
.img-preview-item .remove-img {
  position: absolute; top: 2px; right: 2px;
  background: rgba(0,0,0,.6);
  color: #fff;
  border: none;
  width: 18px; height: 18px;
  border-radius: var(--r-full);
  font-size: var(--fs-base);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
}

.chat-input-wrap {
  display: flex; align-items: flex-end; gap: var(--sp-2);
  background: var(--input-bg);
  border: 1px solid var(--border);
  border-radius: var(--r-2xl);
  padding: var(--sp-2) var(--sp-3);
  transition: border-color var(--t-normal), box-shadow var(--t-normal);
}
.chat-input-wrap:focus-within { border-color: var(--blue); box-shadow: var(--shadow-glow); }
.attach-btn { border: none; font-size: 20px; padding: var(--sp-2); border-radius: var(--r-full); }
.hidden-input { display: none; }
.chat-textarea {
  flex: 1;
  background: transparent;
  border: none;
  color: var(--text);
  font-size: var(--fs-md);
  resize: none;
  outline: none;
  max-height: 120px;
  min-height: 24px;
  line-height: var(--lh-normal);
  font-family: inherit;
}
.send-btn {
  background: var(--blue);
  border: none;
  color: #fff;
  width: 36px; height: 36px;
  border-radius: var(--r-full);
  cursor: pointer;
  font-size: var(--fs-lg);
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  transition: all var(--t-normal);
}
.send-btn:hover { background: var(--blue-2); transform: scale(1.05); }
.send-btn:disabled { opacity: .4; cursor: not-allowed; transform: none; }
[data-theme="dark"] .send-btn:hover { box-shadow: 0 0 14px rgba(110,168,254,.30); }
[data-theme="dark"] .chat-input-wrap:focus-within {
  box-shadow: var(--shadow-glow),0 0 18px rgba(110,168,254,.08);
}
[data-theme="dark"] .msg.assistant {
  backdrop-filter:blur(6px);-webkit-backdrop-filter:blur(6px);
}

/* Prompt editor modal content */
.prompt-list { margin-bottom: var(--sp-3); }
.prompt-empty { color: var(--muted); font-size: var(--fs-base); text-align: center; padding: var(--sp-4) 0; }
.prompt-item {
  display: flex; align-items: center; gap: var(--sp-2);
  padding: var(--sp-2) 0;
  border-bottom: 1px solid var(--border);
}
.prompt-title {
  flex: 1;
  font-size: var(--fs-base);
  cursor: pointer;
  color: var(--muted);
  transition: color var(--t-normal);
}
.prompt-title.active { color: var(--blue); font-weight: var(--fw-semibold); }
.prompt-title:hover { color: var(--text); }
.prompt-delete-btn { border: none; font-size: var(--fs-lg); padding: var(--sp-1); }
.prompt-divider { border: none; border-top: 1px solid var(--border); margin: var(--sp-4) 0; }
.prompt-textarea { min-height: 200px; margin-top: var(--sp-3); font-family: 'SF Mono', Consolas, monospace; font-size: var(--fs-base); resize: vertical; }
</style>
