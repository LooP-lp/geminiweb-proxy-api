<template>
  <div class="models-wrap">
    <h2 class="page-title">⚙️ 外部模型管理</h2>
    <p class="page-desc">配置第三方 OpenAI 兼容接口，替代硬编码的分流方式。</p>

    <div class="actions-bar">
      <button class="btn-primary" @click="addApi">➕ 添加 API 渠道</button>
    </div>

    <div v-if="apis.length === 0" class="empty-wrapper">
      <div class="empty-box">暂无自定义 API 渠道，请点击上方添加</div>
    </div>

    <div v-else class="api-scroll">
      <div class="api-list">
        <div v-for="(api, idx) in apis" :key="api.id || idx" class="api-card">
        <div class="api-card-header">
          <div class="api-title-group">
            <input
              v-model="api.name"
              class="input-inline name-input"
              placeholder="渠道名称 (例如: xinjianya)"
            />
          </div>
          <button class="btn-danger icon-btn" @click="removeApi(idx)" title="删除渠道">🗑</button>
        </div>

        <div class="api-card-body">
          <div class="form-group">
            <label>API URL (Base URL)</label>
            <input
              v-model="api.url"
              class="input-field"
              placeholder="https://api.openai.com/v1"
            />
          </div>

          <div class="form-group">
            <label>API Key</label>
            <input
              v-model="api.key"
              type="password"
              class="input-field"
              placeholder="sk-............................"
            />
          </div>

          <div class="form-group">
            <label>模型名称列表 (英文逗号分隔)</label>
            <textarea
              :value="Array.isArray(api.models) ? api.models.join(', ') : api.models"
              @input="updateModels(idx, ($event.target as HTMLTextAreaElement).value)"
              class="textarea-field"
              placeholder="deepseek-ai/deepseek-v4-pro, gpt-5.5, gpt-image-2-all"
              rows="3"
            ></textarea>
          </div>
        </div>
      </div>
    </div>
    </div>

    <div class="submit-bar" v-if="apis.length > 0">
      <button class="btn-primary save-btn" :disabled="loading" @click="saveApis">
        {{ loading ? '正在保存...' : '💾 保存所有渠道配置' }}
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getCustomApisAPI, saveCustomApisAPI } from '@/api'
import { useToastStore } from '@/stores/toast'
import type { CustomApiChannel } from '@/types'

const toast = useToastStore()
const apis = ref<CustomApiChannel[]>([])
const loading = ref(false)

onMounted(async () => {
  try {
    const res = await getCustomApisAPI()
    apis.value = res.data || []
  } catch (err: unknown) {
    toast.error(err instanceof Error ? err.message : '获取配置失败')
  }
})

function addApi() {
  apis.value.push({
    id: (Math.random().toString(36).substring(2)),
    name: '',
    url: '',
    key: '',
    models: []
  })
}

function removeApi(idx: number) {
  apis.value.splice(idx, 1)
}

function updateModels(idx: number, val: string) {
  apis.value[idx].models = val
    .split(',')
    .map(m => m.trim())
    .filter(m => m.length > 0)
}

async function saveApis() {
  for (const api of apis.value) {
    if (!api.name.trim()) {
      toast.error('渠道名称不能为空')
      return
    }
    if (!api.url.trim()) {
      toast.error(`渠道 [${api.name}] 的 API URL 不能为空`)
      return
    }
  }

  loading.value = true
  try {
    await saveCustomApisAPI(apis.value)
    toast.success('外部渠道配置已成功保存并实时生效！')
  } catch (err: unknown) {
    toast.error(err instanceof Error ? err.message : '保存失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.models-wrap {
  flex: 1;
  overflow: auto;
  padding: var(--sp-6);
}
.page-title {
  font-size: 1.5rem;
  font-weight: 700;
  background: linear-gradient(135deg, #a855f7, #6366f1);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  margin-bottom: var(--sp-1);
}
.page-desc {
  color: var(--muted);
  font-size: 0.875rem;
  margin-bottom: var(--sp-6);
}
.actions-bar {
  margin-bottom: var(--sp-4);
}
.empty-wrapper {
  background: var(--surface);
  border: 1px dashed var(--border);
  border-radius: var(--r-lg);
  padding: var(--sp-10);
  text-align: center;
}
.empty-box {
  color: var(--muted);
}
.api-scroll {
  overflow-x: auto;
  overflow-y: visible;
  padding-bottom: var(--sp-4);
  margin-bottom: var(--sp-6);
  scroll-snap-type: x mandatory;
  -webkit-overflow-scrolling: touch;
}
.api-list {
  display: flex;
  gap: var(--sp-4);
  min-width: min-content;
}
.api-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  overflow: hidden;
  box-shadow: var(--shadow-1);
  flex: 0 0 380px;
  scroll-snap-align: start;
}
.api-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: var(--sp-3) var(--sp-4);
  background: rgba(168, 85, 247, 0.04);
  border-bottom: 1px solid var(--border);
}
.input-inline {
  background: transparent;
  border: none;
  border-bottom: 1px dashed var(--border);
  color: var(--text);
  font-size: 1rem;
  font-weight: 600;
  padding: calc(var(--sp-1) * 0.5) var(--sp-1);
  outline: none;
  width: 280px;
}
.input-inline:focus {
  border-bottom-color: var(--blue);
}
.api-card-body {
  padding: var(--sp-4);
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--sp-3);
}
.form-group {
  display: flex;
  flex-direction: column;
  gap: calc(var(--sp-1) * 1.5);
}
.form-group label {
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--muted);
}
.input-field,
.textarea-field {
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  color: var(--text);
  padding: var(--sp-2) var(--sp-3);
  font-size: 0.9rem;
  outline: none;
  transition: border-color var(--t-normal);
}
.input-field:focus,
.textarea-field:focus {
  border-color: var(--blue);
}
.textarea-field {
  resize: vertical;
  font-family: monospace;
}
.icon-btn {
  padding: var(--sp-1) var(--sp-2);
  font-size: 0.9rem;
}
.submit-bar {
  display: flex;
  justify-content: flex-end;
}
.save-btn {
  min-width: 200px;
}
</style>
