<template>
  <div class="admin-layout" :class="{ 'sidebar-collapsed': sidebarCollapsed }">
    <!-- Mobile Header Bar -->
    <header class="mobile-header">
      <div class="mobile-logo">
        <span class="logo-icon" style="width:22px; height:22px; display:inline-flex; align-items:center; justify-content:center;">
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" style="width:100%; height:100%;">
            <defs>
              <linearGradient id="yjLogoGradMobile" x1="0%" y1="0%" x2="100%" y2="100%">
                <stop offset="0%" stop-color="#a855f7" />
                <stop offset="50%" stop-color="#6366f1" />
                <stop offset="100%" stop-color="#ec4899" />
              </linearGradient>
            </defs>
            <path d="M4 4h2.5v11h5.5v2.5H4V4zm9 0h6.5a3.5 3.5 0 0 1 3.5 3.5v3a3.5 3.5 0 0 1-3.5 3.5H15.5v4H13V4zm2.5 2.5v4.5h4a1 1 0 0 0 1-1v-2.5a1 1 0 0 0-1-1h-4z" fill="url(#yjLogoGradMobile)"/>
          </svg>
        </span>
        <span class="logo-text">LooP API</span>
      </div>
      <div class="mobile-header-actions">
        <button class="mobile-action-btn" @click="theme.toggle()" :title="theme.isDark ? '浅色模式' : '深色模式'">
          <span v-if="theme.isDark">☀️</span>
          <span v-else>🌙</span>
        </button>
        <a href="/admin/logout" class="mobile-action-btn logout" title="退出登录">
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
        </a>
      </div>
    </header>

    <!-- Sidebar -->
    <aside class="sidebar" :class="{ collapsed: sidebarCollapsed }">
      <div class="sidebar-header">
        <div class="sidebar-logo">
          <span class="logo-icon" style="width:24px; height:24px; display:inline-flex; align-items:center; justify-content:center;">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" style="width:100%; height:100%;">
              <defs>
                <linearGradient id="yjLogoGradSidebar" x1="0%" y1="0%" x2="100%" y2="100%">
                  <stop offset="0%" stop-color="#a855f7" />
                  <stop offset="50%" stop-color="#6366f1" />
                  <stop offset="100%" stop-color="#ec4899" />
                </linearGradient>
              </defs>
              <path d="M4 4h2.5v11h5.5v2.5H4V4zm9 0h6.5a3.5 3.5 0 0 1 3.5 3.5v3a3.5 3.5 0 0 1-3.5 3.5H15.5v4H13V4zm2.5 2.5v4.5h4a1 1 0 0 0 1-1v-2.5a1 1 0 0 0-1-1h-4z" fill="url(#yjLogoGradSidebar)"/>
            </svg>
          </span>
          <span class="logo-text">LooP API</span>
        </div>
        <button class="collapse-btn" @click="sidebarCollapsed = !sidebarCollapsed" :title="sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'">
          <span class="collapse-icon">{{ sidebarCollapsed ? '»' : '«' }}</span>
        </button>
      </div>

      <nav class="sidebar-nav">
        <div
          v-for="item in navItems"
          v-show="item.key !== 'users' && item.key !== 'config' && item.key !== 'models' || auth.isAdmin"
          :key="item.key"
          class="nav-item"
          :class="{ active: activeTab === item.key }"
          @click="activeTab = item.key"
        >
          <span class="nav-icon">
            <template v-if="item.key === 'chat'">
              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
            </template>
            <template v-else-if="item.key === 'console'">
              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
            </template>
            <template v-else-if="item.key === 'games'">
              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 12h4M8 10v4"/><rect x="15" y="9" width="2" height="2" rx="1"/><rect x="18" y="9" width="2" height="2" rx="1"/><rect x="15" y="12" width="2" height="2" rx="1"/><rect x="18" y="12" width="2" height="2" rx="1"/></svg>
            </template>
            <template v-else-if="item.key === 'stats'">
              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
            </template>
            <template v-else-if="item.key === 'users'">
              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
            </template>
            <template v-else-if="item.key === 'models'">
              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/><path d="M6 8h4M6 12h4"/></svg>
            </template>
            <template v-else-if="item.key === 'config'">
              <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
            </template>
          </span>
          <span class="nav-label">{{ item.label }}</span>
          <span v-if="sidebarCollapsed" class="nav-tooltip">{{ item.label }}</span>
        </div>
      </nav>

      <div class="sidebar-footer">
        <button class="sidebar-action-btn" @click="theme.toggle()">
          <span class="footer-icon">
            <svg v-if="theme.isDark" xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>
            <svg v-else xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
          </span>
          <span class="footer-label">{{ theme.isDark ? '浅色模式' : '深色模式' }}</span>
        </button>
        <a href="/admin/logout" class="sidebar-action-link">
          <span class="footer-icon">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
          </span>
          <span class="footer-label">退出登录</span>
        </a>
      </div>
    </aside>

    <!-- Main Content -->
    <main class="main-content">
      <KeepAlive>
        <ChatTab v-show="activeTab === 'chat'" />
      </KeepAlive>
      <KeepAlive>
        <ConsoleTab v-show="activeTab === 'console'" />
      </KeepAlive>
      <KeepAlive>
        <StatsTab v-show="activeTab === 'stats'" />
      </KeepAlive>
      <UsersTab v-if="activeTab === 'users' && auth.isAdmin" />
      <ModelsTab v-if="activeTab === 'models' && auth.isAdmin" />
      <ConfigTab v-if="activeTab === 'config' && auth.isAdmin" />
      <KeepAlive>
        <GamesTab v-show="activeTab === 'games'" />
      </KeepAlive>
    </main>

    <!-- Mobile Bottom Navigation Tab Bar -->
    <nav class="mobile-nav">
      <div
        v-for="item in navItems"
        :key="item.key"
        v-show="item.key !== 'users' && item.key !== 'config' && item.key !== 'models' || auth.isAdmin"
        class="mobile-nav-item"
        :class="{ active: activeTab === item.key }"
        @click="activeTab = item.key"
      >
        <span class="mobile-nav-icon">
          <template v-if="item.key === 'chat'">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          </template>
          <template v-else-if="item.key === 'console'">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
          </template>
          <template v-else-if="item.key === 'games'">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="6" width="20" height="12" rx="2"/><path d="M6 12h4M8 10v4"/><rect x="15" y="9" width="2" height="2" rx="1"/><rect x="18" y="9" width="2" height="2" rx="1"/><rect x="15" y="12" width="2" height="2" rx="1"/><rect x="18" y="12" width="2" height="2" rx="1"/></svg>
          </template>
          <template v-else-if="item.key === 'stats'">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/></svg>
          </template>
          <template v-else-if="item.key === 'users'">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>
          </template>
          <template v-else-if="item.key === 'models'">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/><path d="M6 8h4M6 12h4"/></svg>
          </template>
          <template v-else-if="item.key === 'config'">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          </template>
        </span>
        <span class="mobile-nav-label">{{ item.label }}</span>
      </div>
    </nav>

    <!-- Image Lightbox -->
    <div class="img-lightbox" :class="{ active: lbShow }" @click="closeLightbox">
      <button class="lb-close" @click.stop="closeLightbox">&times;</button>
      <img :src="lbSrc" alt="" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, provide, onMounted, onUnmounted } from 'vue'
import { useAuthStore } from '@/stores/auth'
import { useThemeStore } from '@/stores/theme'
import ChatTab from '@/components/ChatTab.vue'
import ConsoleTab from '@/components/ConsoleTab.vue'
import StatsTab from '@/components/StatsTab.vue'
import UsersTab from '@/components/UsersTab.vue'
import ConfigTab from '@/components/ConfigTab.vue'
import GamesTab from '@/components/GamesTab.vue'
import ModelsTab from '@/components/ModelsTab.vue'

const auth = useAuthStore()
const theme = useThemeStore()

const activeTab = ref('chat')
const sidebarCollapsed = ref(false)

const navItems = [
  { key: 'chat', icon: '', label: '对话' },
  { key: 'console', icon: '', label: '控制台' },
  { key: 'games', icon: '', label: '游戏' },
  { key: 'stats', icon: '', label: '统计' },
  { key: 'users', icon: '', label: '用户' },
  { key: 'models', icon: '', label: '模型' },
  { key: 'config', icon: '', label: '配置' },
]

// Lightbox
const lbSrc = ref('')
const lbShow = ref(false)
function openLightbox(url: string) {
  lbSrc.value = url
  lbShow.value = true
  document.addEventListener('keydown', _lbKeyHandler)
}
function closeLightbox() {
  lbShow.value = false
  lbSrc.value = ''
  document.removeEventListener('keydown', _lbKeyHandler)
}
function _lbKeyHandler(e: KeyboardEvent) {
  if (e.key === 'Escape') closeLightbox()
}
provide('openLightbox', openLightbox)

// Fix lightbox: set window.__lb so onclick="this.__lb&&this.__lb(...)" works
onMounted(() => {
  window.__lb = openLightbox
  auth.initFromCookies()
  auth.fetchApiKey()
})

onUnmounted(() => {
  delete window.__lb
})
</script>

<!-- Declare global type for lightbox -->
<script lang="ts">
declare global {
  interface Window {
    __lb?: (url: string) => void
  }
}
</script>

<style scoped>
.admin-layout { display: flex; min-height: 100vh; overflow: hidden; }

/* ===== Sidebar ===== */
.sidebar {
  width: 260px;
  background: var(--surface);
  height: 100vh;
  position: fixed;
  left: 0; top: 0;
  display: flex;
  flex-direction: column;
  border-right: 1px solid var(--border);
  z-index: var(--z-fixed, 300);
  transition: width var(--t-slow), background var(--t-normal), border-color var(--t-normal);
  overflow: hidden;
}
.sidebar.collapsed { width: 68px; }

/* Sci-fi glass sidebar in dark mode */
[data-theme="dark"] .sidebar {
  background: rgba(14,14,30,.92);
  backdrop-filter: blur(14px);-webkit-backdrop-filter: blur(14px);
  border-right: 1px solid rgba(110,168,254,.12);
  box-shadow: 1px 0 30px rgba(110,168,254,.04);
}
[data-theme="dark"] .sidebar::before {
  content:'';position:absolute;inset:0;
  background:linear-gradient(180deg,rgba(110,168,254,.03) 0%,transparent 30%,rgba(168,85,247,.02) 100%);
  pointer-events:none;
}

/* Header */
.sidebar-header {
  padding: var(--sp-5) var(--sp-4);
  border-bottom: 1px solid var(--border);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
  min-height: 64px;
}
.sidebar-logo {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  overflow: hidden;
  white-space: nowrap;
}
.logo-icon { font-size: 24px; flex-shrink: 0; }
.logo-text {
  font-size: var(--fs-xl);
  font-weight: var(--fw-bold);
  color: var(--text);
  transition: opacity var(--t-normal);
}
.sidebar.collapsed .logo-text { opacity: 0; width: 0; }

.collapse-btn {
  width: 28px; height: 28px;
  border-radius: var(--r-sm);
  border: 1px solid var(--border);
  background: var(--surface-2);
  color: var(--muted);
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  flex-shrink: 0;
  transition: all var(--t-normal);
  font-size: var(--fs-md);
}
.collapse-btn:hover { color: var(--text); border-color: var(--blue); }

/* Nav */
.sidebar-nav { flex: 1; padding: var(--sp-3) var(--sp-2); overflow-y: auto; }
.nav-item {
  display: flex;
  align-items: center;
  padding: var(--sp-3) var(--sp-4);
  cursor: pointer;
  color: var(--muted);
  font-size: var(--fs-md);
  font-weight: var(--fw-medium);
  border-radius: var(--r-xl);
  margin: 2px 0;
  transition: all var(--t-normal);
  position: relative;
  overflow: hidden;
  white-space: nowrap;
}
.nav-item::before {
  content: '';
  position: absolute;
  left: 0; top: 50%;
  transform: translateY(-50%);
  width: 3px; height: 0;
  background: var(--blue);
  border-radius: 0 2px 2px 0;
  transition: height var(--t-normal);
}
.nav-item:hover { color: var(--text); background: var(--blue-bg); }
.nav-item.active { color: var(--blue); background: var(--blue-bg); }
.nav-item.active::before { height: 20px; }
.nav-icon { margin-right: var(--sp-4); font-size: 20px; flex-shrink: 0; opacity: .85; }
.nav-label { transition: opacity var(--t-normal); }
.sidebar.collapsed .nav-label { opacity: 0; width: 0; }
.sidebar.collapsed .nav-icon { margin-right: 0; }
.sidebar.collapsed .nav-item { justify-content: center; padding: var(--sp-3); }

/* Tooltip for collapsed state */
.nav-tooltip {
  display: none;
  position: absolute;
  left: 100%;
  top: 50%;
  transform: translateY(-50%);
  margin-left: 8px;
  background: var(--surface-2);
  color: var(--text);
  padding: var(--sp-1) var(--sp-3);
  border-radius: var(--r-sm);
  font-size: var(--fs-base);
  white-space: nowrap;
  box-shadow: var(--shadow-3);
  z-index: 10;
  pointer-events: none;
}
.sidebar.collapsed .nav-item:hover .nav-tooltip { display: block; }

/* Footer */
.sidebar-footer {
  padding: var(--sp-3) var(--sp-2);
  border-top: 1px solid var(--border);
}
.footer-link {
  color: var(--muted);
  text-decoration: none;
  font-size: var(--fs-base);
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  border-radius: var(--r-xl);
  transition: all var(--t-normal);
  margin: 2px 0;
  overflow: hidden;
  white-space: nowrap;
}
.footer-link:hover { color: var(--text); background: var(--blue-bg); }
.footer-icon { font-size: 18px; flex-shrink: 0; }
.footer-label { transition: opacity var(--t-normal); }
.sidebar.collapsed .footer-label { opacity: 0; width: 0; }
.sidebar.collapsed .footer-link { justify-content: center; padding: var(--sp-3); }

/* ===== Main Content ===== */
.main-content {
  margin-left: 260px;
  flex: 1;
  height: 100vh;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  background: var(--bg);
  transition: margin-left var(--t-slow), background var(--t-normal);
}
.admin-layout.sidebar-collapsed .main-content { margin-left: 68px; }

/* ===== Lightbox ===== */
.img-lightbox {
  position: fixed; inset: 0;
  background: rgba(0,0,0,.8);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  z-index: var(--z-lightbox, 3000);
  display: flex; align-items: center; justify-content: center;
  opacity: 0; pointer-events: none;
  transition: opacity var(--t-normal);
}
.img-lightbox.active { opacity: 1; pointer-events: auto; }
.img-lightbox img {
  max-width: 92vw; max-height: 88vh;
  border-radius: var(--r-md);
  box-shadow: var(--shadow-5);
  object-fit: contain;
}
.lb-close {
  position: absolute; top: 16px; right: 20px;
  width: 40px; height: 40px;
  border-radius: var(--r-full);
  background: rgba(255,255,255,.15);
  color: #fff;
  border: none;
  font-size: 24px;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: background var(--t-normal);
}
.lb-close:hover { background: rgba(255,255,255,.3); }

/* ===== Mobile responsive ===== */
.mobile-header {
  display: none;
  height: 56px;
  padding: 0 var(--sp-4);
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  align-items: center;
  justify-content: space-between;
  position: fixed;
  top: 0; left: 0; right: 0;
  z-index: var(--z-fixed);
}
.mobile-logo {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-weight: var(--fw-bold);
  color: var(--text);
}
.mobile-logo .logo-icon {
  color: var(--blue);
  display: flex;
  align-items: center;
}
.mobile-header-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-1);
}
.mobile-action-btn {
  background: none;
  border: none;
  width: 36px;
  height: 36px;
  border-radius: var(--r-full);
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
  cursor: pointer;
  font-size: var(--fs-xl);
  transition: background var(--t-normal), color var(--t-normal);
}
.mobile-action-btn:hover {
  background: var(--hover-bg);
  color: var(--text);
}
.mobile-action-btn.logout {
  color: var(--red);
}
.mobile-action-btn.logout:hover {
  background: var(--red-bg);
  color: var(--red-2);
}

.mobile-nav {
  display: none;
  position: fixed;
  bottom: 0; left: 0; right: 0;
  height: 60px;
  background: var(--surface);
  border-top: 1px solid var(--border);
  z-index: var(--z-fixed);
  grid-template-columns: repeat(auto-fit, minmax(0, 1fr));
  padding: 0 var(--sp-2);
  box-shadow: 0 -2px 10px rgba(0,0,0,.04);
}
.mobile-nav-item {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--sp-1);
  color: var(--muted);
  cursor: pointer;
  transition: color var(--t-normal);
  position: relative;
}
.mobile-nav-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform var(--t-normal);
}
.mobile-nav-item:hover .mobile-nav-icon {
  transform: translateY(-1px);
}
.mobile-nav-label {
  font-size: var(--fs-xs);
  font-weight: var(--fw-medium);
}
.mobile-nav-item.active {
  color: var(--blue);
}

/* Sidebar buttons styling */
.sidebar-action-btn {
  width: 100%;
  background: none;
  border: none;
  color: var(--muted);
  font-size: var(--fs-base);
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  border-radius: var(--r-xl);
  transition: all var(--t-normal);
  margin: 2px 0;
  cursor: pointer;
  text-align: left;
  font-family: inherit;
}
.sidebar-action-btn:hover { color: var(--text); background: var(--blue-bg); }
.sidebar-action-btn .footer-icon { display: flex; align-items: center; color: var(--muted); }
.sidebar-action-btn:hover .footer-icon { color: var(--text); }
.sidebar .sidebar-action-btn { justify-content: flex-start; }
.sidebar.collapsed .sidebar-action-btn { justify-content: center; padding: var(--sp-3); }
.sidebar.collapsed .sidebar-action-btn .footer-label { opacity: 0; width: 0; display: none; }

.sidebar-action-link {
  color: var(--muted);
  text-decoration: none;
  font-size: var(--fs-base);
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-3) var(--sp-4);
  border-radius: var(--r-xl);
  transition: all var(--t-normal);
  margin: 2px 0;
  overflow: hidden;
  white-space: nowrap;
}
.sidebar-action-link:hover { color: var(--text); background: var(--blue-bg); }
.sidebar-action-link .footer-icon { display: flex; align-items: center; }
.sidebar.collapsed .sidebar-action-link { justify-content: center; padding: var(--sp-3); }
.sidebar.collapsed .sidebar-action-link .footer-label { opacity: 0; width: 0; display: none; }

[data-theme="dark"] .mobile-header,
[data-theme="dark"] .mobile-nav {
  background: rgba(14,14,30,.92);
  backdrop-filter: blur(14px);-webkit-backdrop-filter: blur(14px);
  border-color: rgba(110,168,254,.12);
}

@media (max-width: 900px) {
  .mobile-header { display: flex; }
  .mobile-nav { display: grid; }
  .sidebar { display: none; }
  .main-content {
    margin-left: 0 !important;
    padding-top: 56px;
    padding-bottom: 60px;
    height: calc(100vh - 56px - 60px);
    overflow: hidden;
  }
  .main-content > * {
    height: 100%;
    width: 100%;
  }
  .admin-layout.sidebar-collapsed .main-content { margin-left: 0 !important; }
  .collapse-btn { display: none; }
}
</style>
