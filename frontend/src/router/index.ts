import { createRouter, createWebHistory } from 'vue-router'
import { defineComponent, h } from 'vue'

const LogoutRedirect = defineComponent({
  beforeCreate() {
    window.location.href = '/admin/logout'
  },
  render() {
    return h('div', '正在退出...')
  },
})

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/admin/login',
      name: 'login',
      component: () => import('@/views/LoginView.vue'),
    },
    {
      path: '/admin',
      name: 'admin',
      component: () => import('@/views/AdminView.vue'),
      meta: { requiresAuth: true },
    },
    {
      path: '/admin/logout',
      name: 'logout',
      component: LogoutRedirect,
    },
    {
      path: '/',
      redirect: '/admin',
    },
  ],
})

// Auth guard: check non-httponly session cookie before entering admin
router.beforeEach((to, from, next) => {
  if (to.meta.requiresAuth) {
    // admin_session is httponly, so we check admin_username instead
    const hasSession = document.cookie.match(/(?:^|;\s*)admin_username=/)
    if (!hasSession) {
      next('/admin/login')
      return
    }
  }
  next()
})

export default router
