import { defineStore } from 'pinia'
import { getCurrentKeyAPI } from '@/api'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    username: '',
    isAdmin: false,
    apiKey: '',
  }),
  getters: {
    greeting(): string {
      const h = new Date().getHours()
      if (h < 6) return '夜深了'
      if (h < 12) return '早上好'
      if (h < 14) return '中午好'
      if (h < 18) return '下午好'
      return '晚上好'
    },
  },
  actions: {
    initFromCookies() {
      const getCookie = (name: string) => {
        const match = document.cookie.match(new RegExp('(?:^|;\\s*)' + name + '=([^;]*)'))
        return match ? decodeURIComponent(match[1]) : ''
      }
      this.username = getCookie('admin_username') || '用户'
      this.isAdmin = getCookie('admin_is_admin') === '1'
    },
    async fetchApiKey() {
      try {
        const data = await getCurrentKeyAPI()
        if (data && data.api_key) {
          this.apiKey = data.api_key
          localStorage.setItem('admin_api_key', data.api_key)
          return
        }
      } catch {
        /* fall through */
      }
      const stored = localStorage.getItem('admin_api_key') || ''
      this.apiKey = stored
    },
    getApiKey(): string {
      const current = this.apiKey
      if (current) return current
      const stored = localStorage.getItem('admin_api_key') || ''
      if (stored) {
        this.apiKey = stored
        return stored
      }
      return ''
    },
    getChatSessionId(): string {
      let sid = sessionStorage.getItem('chat_session_id')
      if (!sid) {
        sid = crypto.randomUUID()
        sessionStorage.setItem('chat_session_id', sid)
      }
      return sid
    },
    resetChatSessionId(): string {
      sessionStorage.removeItem('chat_session_id')
      return this.getChatSessionId()
    },
  },
})