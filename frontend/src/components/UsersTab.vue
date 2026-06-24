<template>
  <div class="users-wrap">
    <h2 class="page-title">👥 用户管理</h2>

    <!-- User List -->
    <div v-if="!selectedUserId">
      <EmptyState v-if="users.length === 0 && !error403" icon="👥" title="暂无用户" />
      <div v-if="error403" class="permission-denied">需要管理员权限</div>
      <div v-for="u in users" :key="u.id" class="user-card" @click="selectedUserId = u.id">
        <div class="user-info">
          <div class="user-name">
            {{ u.username }}
            <span v-if="u.is_admin" class="badge badge-success admin-badge">管理员</span>
          </div>
          <div class="user-meta">
            <span>ID: {{ u.id }}</span>
            <span>{{ u.email || '-' }}</span>
            <span>Keys: {{ u.key_count }}</span>
            <span>请求: {{ u.total_requests }}</span>
            <span>Tokens: {{ u.total_tokens }}</span>
            <span v-if="u.created_at">注册: {{ u.created_at.substring(0, 10) }}</span>
          </div>
        </div>
        <div class="user-actions">
          <button class="btn-secondary action-btn" @click.stop="toggleAdmin(u.id)">{{ u.is_admin ? '取消管理员' : '设为管理员' }}</button>
          <button class="btn-danger action-btn" @click.stop="confirmDeleteUser(u.id, u.username)">🗑</button>
        </div>
      </div>
    </div>

    <!-- User Detail -->
    <div v-if="selectedUserId && userDetail">
      <button class="btn-secondary back-btn" @click="selectedUserId = null; userDetail = null">← 返回用户列表</button>
      <div class="user-detail-panel">
        <h3 class="detail-title">
          {{ userDetail.username }}
          <span class="detail-id">(ID: {{ userDetail.id }})</span>
          <span v-if="userDetail.is_admin" class="badge badge-success">管理员</span>
        </h3>
        <div class="detail-grid">
          <div class="detail-item"><div class="detail-label">邮箱</div><div class="detail-value">{{ userDetail.email || '-' }}</div></div>
          <div class="detail-item"><div class="detail-label">角色</div><div class="detail-value">{{ userDetail.is_admin ? '管理员' : '普通用户' }}</div></div>
          <div class="detail-item"><div class="detail-label">注册时间</div><div class="detail-value">{{ userDetail.created_at || '-' }}</div></div>
          <div class="detail-item"><div class="detail-label">API Keys</div><div class="detail-value">{{ userDetail.api_keys?.length || 0 }}</div></div>
          <div class="detail-item"><div class="detail-label">总请求数</div><div class="detail-value">{{ userDetail.stats?.total_requests || 0 }}</div></div>
          <div class="detail-item"><div class="detail-label">总 Tokens</div><div class="detail-value">{{ userDetail.stats?.total_tokens || 0 }}</div></div>
          <div class="detail-item"><div class="detail-label">Prompt Tokens</div><div class="detail-value">{{ userDetail.stats?.total_prompt_tokens || 0 }}</div></div>
          <div class="detail-item"><div class="detail-label">Completion Tokens</div><div class="detail-value">{{ userDetail.stats?.total_completion_tokens || 0 }}</div></div>
        </div>

        <template v-if="userDetail.stats?.requests_by_model && Object.keys(userDetail.stats.requests_by_model).length">
          <h4 class="sub-title">模型使用分布</h4>
          <div v-for="(count, model) in userDetail.stats.requests_by_model" :key="model" class="model-row">
            <span>{{ model }}</span>
            <span class="model-count">{{ count }}</span>
          </div>
        </template>

        <template v-if="userDetail.api_keys?.length">
          <h4 class="sub-title">API Keys</h4>
          <div v-for="k in userDetail.api_keys" :key="k.api_key" class="user-key-row">
            <span class="key-mono">{{ k.api_key }}</span>
            <span class="key-note">{{ k.note || '' }}</span>
            <span class="badge" :class="k.is_active ? 'badge-success' : 'badge-error'">{{ k.is_active ? '活跃' : '禁用' }}</span>
          </div>
        </template>
      </div>
    </div>

    <!-- Delete User Modal -->
    <ModalOverlay v-model="showDeleteModal" title="删除用户">
      <p class="modal-desc">确定要删除用户 <strong>{{ pendingDeleteName }}</strong> 及其所有数据吗？此操作不可恢复。</p>
      <template #actions>
        <button class="btn-secondary" @click="showDeleteModal = false">取消</button>
        <button class="btn-danger" :disabled="deleteLoading" @click="deleteUser">{{ deleteLoading ? '删除中...' : '确认删除' }}</button>
      </template>
    </ModalOverlay>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { listUsersAPI, getUserDetailAPI, deleteUserAPI, toggleAdminAPI } from '@/api'
import { useToastStore } from '@/stores/toast'
import ModalOverlay from '@/components/ModalOverlay.vue'
import EmptyState from '@/components/EmptyState.vue'
import type { UserItem, UserDetail } from '@/types'

const toast = useToastStore()
const users = ref<UserItem[]>([])
const selectedUserId = ref<number | null>(null)
const userDetail = ref<UserDetail | null>(null)
const error403 = ref(false)
const showDeleteModal = ref(false)
const pendingDeleteId = ref<number | null>(null)
const pendingDeleteName = ref('')
const deleteLoading = ref(false)

async function loadUsers() {
  error403.value = false
  try {
    const data = await listUsersAPI()
    users.value = data.data || []
  } catch (e: unknown) {
    if (e instanceof Error && e.message.includes('403')) error403.value = true
  }
}

watch(selectedUserId, async (id) => {
  if (!id) return
  try {
    const data = await getUserDetailAPI(id)
    userDetail.value = data.data
  } catch { /* detail unavailable */ }
}, { immediate: false })

async function toggleAdmin(userId: number) {
  try {
    const result = await toggleAdminAPI(userId)
    if (result.success) { loadUsers(); toast.success('操作成功') }
  } catch { toast.error('操作失败') }
}

function confirmDeleteUser(userId: number, username: string) {
  pendingDeleteId.value = userId
  pendingDeleteName.value = username
  showDeleteModal.value = true
}

async function deleteUser() {
  if (!pendingDeleteId.value) return
  deleteLoading.value = true
  try {
    await deleteUserAPI(pendingDeleteId.value)
    showDeleteModal.value = false
    loadUsers()
    toast.success('用户已删除')
  } catch {
    toast.error('删除失败')
  } finally {
    deleteLoading.value = false
    pendingDeleteId.value = null
  }
}

loadUsers()
</script>

<style scoped>
.users-wrap { flex: 1; overflow-y: auto; padding: var(--sp-5); }
.page-title { font-size: var(--fs-2xl); margin-bottom: var(--sp-5); font-weight: var(--fw-semibold); }

.user-card {
  display: flex; align-items: center; justify-content: space-between;
  padding: var(--sp-4) var(--sp-5);
  background: var(--surface-2);
  border-radius: var(--r-md);
  margin-bottom: var(--sp-2);
  cursor: pointer;
  transition: all var(--t-normal);
}
.user-card:hover { box-shadow: var(--shadow-2); }
.user-info { flex: 1; }
.user-name { font-size: var(--fs-lg); font-weight: var(--fw-semibold); color: var(--text); }
.admin-badge { margin-left: var(--sp-2); }
.user-meta { font-size: var(--fs-sm); color: var(--muted); margin-top: var(--sp-1); display: flex; gap: var(--sp-3); flex-wrap: wrap; }
.user-actions { display: flex; gap: var(--sp-2); align-items: center; }
.action-btn { padding: var(--sp-2) var(--sp-3); font-size: var(--fs-sm); }

.permission-denied { color: var(--muted); text-align: center; padding: var(--sp-10); }

/* Detail */
.back-btn { margin-bottom: var(--sp-3); }
.user-detail-panel { background: var(--surface-2); border-radius: var(--r-lg); padding: var(--sp-6); margin-top: var(--sp-4); }
.detail-title { margin: 0 0 var(--sp-4) 0; font-size: var(--fs-xl); }
.detail-id { font-size: var(--fs-md); color: var(--muted); font-weight: var(--fw-normal); }
.detail-grid { display: grid; grid-template-columns: 1fr 1fr; gap: var(--sp-3); margin-bottom: var(--sp-4); }
.detail-item { background: var(--surface); padding: var(--sp-3) var(--sp-4); border-radius: var(--r-md); }
.detail-label { font-size: var(--fs-sm); color: var(--muted); margin-bottom: var(--sp-1); }
.detail-value { font-size: var(--fs-lg); font-weight: var(--fw-semibold); color: var(--text); }
.sub-title { margin: var(--sp-4) 0 var(--sp-2); font-size: var(--fs-md); }
.model-row { display: flex; justify-content: space-between; padding: var(--sp-1) 0; font-size: var(--fs-base); }
.model-count { color: var(--blue); }
.user-key-row { display: flex; align-items: center; gap: var(--sp-2); padding: var(--sp-2) 0; border-bottom: 1px solid var(--border); font-size: var(--fs-base); }
.user-key-row:last-child { border-bottom: none; }
.key-mono { font-family: 'SF Mono', monospace; color: var(--blue); }
.key-note { color: var(--muted); font-size: var(--fs-xs); }

.modal-desc { font-size: var(--fs-md); color: var(--muted); line-height: var(--lh-relaxed); }
</style>
