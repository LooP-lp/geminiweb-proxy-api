<template>
  <div class="stats-wrap">
    <div class="toolbar">
      <button class="btn-secondary" @click="loadStats">🔄 刷新数据</button>
      <button v-if="auth.isAdmin" class="btn-secondary" @click="refreshToken">🔁 刷新 Token</button>
    </div>

    <div class="stats-grid">
      <div class="stat-card"><div class="stat-label">总请求数</div><div class="stat-value">{{ stats.total_requests || '-' }}</div><div class="stat-sub">今日 {{ stats.today_requests || 0 }}</div></div>
      <div class="stat-card"><div class="stat-label">总 Token</div><div class="stat-value">{{ formatNum(stats.total_tokens || 0) }}</div><div class="stat-sub">今日 {{ formatNum(stats.today_tokens || 0) }}</div></div>
      <div class="stat-card"><div class="stat-label">Prompt Tokens</div><div class="stat-value">{{ formatNum(stats.total_prompt_tokens || 0) }}</div></div>
      <div class="stat-card"><div class="stat-label">Completion</div><div class="stat-value">{{ formatNum(stats.total_completion_tokens || 0) }}</div></div>
    </div>

    <div class="stats-grid">
      <div class="stat-card"><div class="stat-label">运行时间</div><div class="stat-value stat-sm">{{ stats.uptime || '-' }}</div></div>
      <div class="stat-card"><div class="stat-label">刷新次数</div><div class="stat-value">{{ stats.token_refresh_count ?? '-' }}</div></div>
      <div class="stat-card"><div class="stat-label">后台刷新</div><div class="stat-value stat-sm">{{ stats.background_refresh_enabled ? '开启' : '关闭' }}</div></div>
      <div class="stat-card"><div class="stat-label">Client</div><div class="stat-value stat-sm" :class="stats.client_active ? 'clr-ok' : 'clr-err'">{{ stats.client_active ? '在线' : '离线' }}</div></div>
    </div>

    <div class="card section-card">
      <h3>📊 模型使用分布</h3>
      <EmptyState v-if="!modelKeys.length" icon="📊" title="暂无数据" description="暂无模型使用数据" />
      <div v-for="(k, idx) in modelKeys" :key="k" class="model-bar">
        <div class="model-bar-name">{{ k }}</div>
        <div class="bar-bg"><div class="bar-fill" :style="{ width: modelBarWidth(k) + '%', background: chartColors[idx % chartColors.length] }">{{ stats.requests_by_model?.[k] ?? 0 }}</div></div>
      </div>
    </div>

    <div class="chart-row">
      <div class="card section-card section-flat">
        <h3>📈 24小时请求趋势</h3>
        <div class="hourly-chart-wrap"><canvas ref="hourlyReqsChart" height="180"></canvas></div>
      </div>
      <div class="card section-card section-flat">
        <h3>📈 24小时Token使用趋势</h3>
        <div class="hourly-chart-wrap"><canvas ref="hourlyTokensChart" height="180"></canvas></div>
      </div>
    </div>

    <div class="card section-card">
      <h3>📝 运行信息</h3>
      <div class="metric-list">
        <div class="metric-row"><div class="k">Token 自动刷新</div><div class="v">{{ stats.auto_refresh_enabled ? '开启' : '关闭' }}</div></div>
        <div class="metric-row"><div class="k">后台定时刷新</div><div class="v">{{ stats.background_refresh_enabled ? '开启' : '关闭' }}</div></div>
        <div class="metric-row"><div class="k">当前模型数量</div><div class="v">{{ modelKeys.length }}</div></div>
        <div class="metric-row"><div class="k">更新时间</div><div class="v">{{ updatedAt }}</div></div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, onActivated } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useToastStore } from '@/stores/toast'
import { getStatsAPI, getHourlyStatsAPI, refreshTokenAPI } from '@/api'
import { drawHourlyChart, observeChartResize, watchDarkMode } from '@/composables/useCharts'
import EmptyState from '@/components/EmptyState.vue'
import type { StatsData } from '@/types'

const auth = useAuthStore()
const toast = useToastStore()
const stats = ref<Partial<StatsData>>({})
const updatedAt = ref('')
const hourlyReqsChart = ref<HTMLCanvasElement | null>(null)
const hourlyTokensChart = ref<HTMLCanvasElement | null>(null)
const chartColors = ['#4285f4','#ea4335','#fbbc04','#34a853','#ff6d01','#46bdc6','#7b1fa2','#e91e63','#00bcd4','#8bc34a']
let refreshTimer: ReturnType<typeof setInterval> | null = null
const cleanupFns: (() => void)[] = []

const modelKeys = computed(() => {
  const rby = stats.value.requests_by_model || {}
  return Object.keys(rby).sort((a, b) => rby[b] - rby[a])
})

function modelBarWidth(k: string) {
  const rby = stats.value.requests_by_model || {}
  const maxVal = Math.max(...Object.values(rby) as number[], 1)
  return ((rby[k] || 0) / maxVal) * 100
}

function formatNum(n: number): string {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return n.toString()
}

async function loadStats() {
  try { const s = await getStatsAPI(); stats.value = s; updatedAt.value = new Date().toLocaleString() } catch { /* n/a */ }
  try {
    const hData = await getHourlyStatsAPI()
    const hourly = hData.data || []
    if (hourlyReqsChart.value) drawHourlyChart(hourlyReqsChart.value, hourly, 'requests', '#1a73e8', '#4285f4')
    if (hourlyTokensChart.value) drawHourlyChart(hourlyTokensChart.value, hourly, 'total_tokens', '#34a853', '#0d904f')
  } catch { /* n/a */ }
}

async function refreshToken() {
  try { await refreshTokenAPI(auth.getApiKey()); toast.success('Token 刷新成功'); loadStats() }
  catch { toast.error('Token 刷新失败') }
}

onMounted(() => {
  loadStats()
  refreshTimer = setInterval(loadStats, 10000)
  if (hourlyReqsChart.value) {
    cleanupFns.push(observeChartResize(hourlyReqsChart.value, loadStats))
    cleanupFns.push(watchDarkMode(loadStats))
  }
  if (hourlyTokensChart.value) {
    cleanupFns.push(observeChartResize(hourlyTokensChart.value, loadStats))
  }
})

// 当组件从 KeepAlive 激活时，确保图表正确渲染
onActivated(() => {
  nextTick(() => {
    loadStats()
  })
})

onUnmounted(() => {
  if (refreshTimer) clearInterval(refreshTimer)
  cleanupFns.forEach(fn => fn())
})
</script>

<style scoped>
.stats-wrap { flex: 1; overflow-y: auto; padding: var(--sp-5); }
.toolbar { display: flex; flex-wrap: wrap; gap: var(--sp-2); margin-bottom: var(--sp-5); }
.stats-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: var(--sp-4); margin-bottom: var(--sp-4); }
.stat-card { background: var(--surface); border: 1px solid var(--border); border-radius: var(--r-lg); padding: var(--sp-4); box-shadow: var(--shadow-1); transition: background var(--t-normal), border-color var(--t-normal); }
.stat-label { font-size: var(--fs-sm); color: var(--muted); margin-bottom: var(--sp-2); font-weight: var(--fw-medium); }
.stat-value { font-size: var(--fs-3xl); font-weight: var(--fw-medium); color: var(--text); }
.stat-sm { font-size: var(--fs-xl); }
.stat-sub { margin-top: var(--sp-2); font-size: var(--fs-sm); color: var(--muted); }
.clr-ok { color: var(--green-fg); }
.clr-err { color: var(--red-fg); }
.section-card { margin-bottom: var(--sp-5); }
.section-card h3 { font-size: var(--fs-lg); font-weight: var(--fw-semibold); margin-bottom: var(--sp-4); }
.section-flat { margin-bottom: 0; }
.model-bar { display: flex; align-items: center; gap: var(--sp-3); margin: var(--sp-2) 0; }
.model-bar-name { width: 180px; font-size: var(--fs-base); color: var(--text); text-align: right; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar-bg { flex: 1; height: 20px; background: var(--surface-2); border-radius: var(--r-md); overflow: hidden; }
.bar-fill { height: 100%; border-radius: var(--r-md); transition: width var(--t-slow); display: flex; align-items: center; justify-content: flex-end; padding-right: var(--sp-2); font-size: var(--fs-xs); color: #fff; min-width: 24px; }
.chart-row { display: flex; gap: var(--sp-4); margin-bottom: var(--sp-5); }
.hourly-chart-wrap { background: var(--surface-2); border: 1px solid var(--border); border-radius: var(--r-md); padding: var(--sp-4); margin-top: var(--sp-2); }
.hourly-chart-wrap canvas { width: 100%; height: 180px; display: block; }
.metric-list { display: grid; grid-template-columns: repeat(2,minmax(0,1fr)); gap: var(--sp-3); }
.metric-row { background: var(--surface-2); border-radius: var(--r-md); padding: var(--sp-3) var(--sp-4); display: flex; justify-content: space-between; gap: var(--sp-3); align-items: center; }
.metric-row .k { font-size: var(--fs-base); color: var(--muted); }
.metric-row .v { font-size: var(--fs-base); color: var(--text); font-weight: var(--fw-medium); text-align: right; word-break: break-all; }

@media (max-width: 1100px) {
  .stats-grid { grid-template-columns: repeat(2,1fr); }
  .metric-list { grid-template-columns: 1fr; }
  .chart-row { flex-direction: column; }
}
@media (max-width: 900px) {
  .stats-grid { grid-template-columns: 1fr; }
  .model-bar-name { width: 100px; }
}
</style>
