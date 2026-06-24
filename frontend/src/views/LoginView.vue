<template>
  <div class="login-page">
    <!-- Animated background blobs -->
    <div class="bg-blob blob-1"></div>
    <div class="bg-blob blob-2"></div>
    <div class="bg-blob blob-3"></div>

    <div class="login-card">
      <div class="logo-wrap" style="width:64px; height:64px; margin:0 auto var(--sp-4) auto; display:flex; align-items:center; justify-content:center;">
        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" style="width:100%; height:100%; filter:drop-shadow(0 4px 12px rgba(168,85,247,0.4));">
          <defs>
            <linearGradient id="yjLogoGradLogin" x1="0%" y1="0%" x2="100%" y2="100%">
              <stop offset="0%" stop-color="#a855f7" />
              <stop offset="50%" stop-color="#6366f1" />
              <stop offset="100%" stop-color="#ec4899" />
            </linearGradient>
          </defs>
          <path d="M4 4h2.5v11h5.5v2.5H4V4zm9 0h6.5a3.5 3.5 0 0 1 3.5 3.5v3a3.5 3.5 0 0 1-3.5 3.5H15.5v4H13V4zm2.5 2.5v4.5h4a1 1 0 0 0 1-1v-2.5a1 1 0 0 0-1-1h-4z" fill="url(#yjLogoGradLogin)"/>
        </svg>
      </div>
      <h1>LooP API</h1>
      <p class="subtitle">请登录或注册以访问后台管理</p>

      <div class="tabs">
        <button class="tab" :class="{ active: tab === 'login' }" @click="tab = 'login'">登 录</button>
        <button class="tab" :class="{ active: tab === 'register' }" @click="tab = 'register'">注 册</button>
      </div>

      <Transition name="slide-fade" mode="out-in">
        <!-- Login Panel -->
        <form v-if="tab === 'login'" key="login" @submit.prevent="handleLogin" class="login-form">
          <div v-if="errorMsg" class="alert alert-error">{{ errorMsg }}</div>
          <div v-if="successMsg" class="alert alert-success">{{ successMsg }}</div>

          <div class="form-group">
            <label>用户名</label>
            <input v-model="loginForm.username" type="text" placeholder="请输入用户名" required autofocus class="input-field" />
          </div>
          <div class="form-group">
            <label>密码</label>
            <input v-model="loginForm.password" type="password" placeholder="请输入密码" required class="input-field" />
          </div>
          <button type="submit" class="btn-primary btn-block" :disabled="loginLoading">
            <span v-if="loginLoading" class="btn-spinner"></span>
            {{ loginLoading ? '登录中...' : '登 录' }}
          </button>
        </form>

        <!-- Register Panel -->
        <form v-else key="register" @submit.prevent="handleRegister" class="login-form">
          <div v-if="errorMsg" class="alert alert-error">{{ errorMsg }}</div>
          <div v-if="successMsg" class="alert alert-success">{{ successMsg }}</div>

          <div class="form-group">
            <label>用户名</label>
            <input v-model="regForm.username" type="text" placeholder="请输入用户名" required class="input-field" />
          </div>
          <div class="form-group">
            <label>邮箱</label>
            <input v-model="regForm.email" type="email" placeholder="请输入邮箱" required class="input-field" />
          </div>
          <div class="form-group">
            <label>密码</label>
            <input v-model="regForm.password" type="password" placeholder="请输入密码（至少6位）" required minlength="6" class="input-field" />
          </div>
          <div class="form-group">
            <label>验证码</label>
            <div class="code-row">
              <input v-model="regForm.code" type="text" placeholder="6位验证码" required maxlength="6" class="input-field" />
              <button type="button" class="btn-secondary code-btn" :disabled="countdown > 0" @click="handleSendCode">
                {{ countdown > 0 ? countdown + 's' : '发送验证码' }}
              </button>
            </div>
          </div>
          <button type="submit" class="btn-primary btn-block" :disabled="regLoading">
            <span v-if="regLoading" class="btn-spinner"></span>
            {{ regLoading ? '注册中...' : '注 册' }}
          </button>
        </form>
      </Transition>

      <div class="ip-info">
        <img src="https://ping0.cc/img1" alt="IP Info" loading="lazy" @error="($event.target as HTMLImageElement).parentElement!.style.display='none'" />
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive, onUnmounted } from 'vue'
import { loginAPI, registerAPI, sendCodeAPI } from '@/api'
const tab = ref<'login' | 'register'>('login')
const errorMsg = ref('')
const successMsg = ref('')
const loginLoading = ref(false)
const regLoading = ref(false)
const countdown = ref(0)
let countdownTimer: ReturnType<typeof setInterval> | null = null

const loginForm = reactive({ username: '', password: '' })
const regForm = reactive({ username: '', password: '', email: '', code: '' })

function clearMessages() {
  errorMsg.value = ''
  successMsg.value = ''
}

async function handleLogin() {
  clearMessages()
  loginLoading.value = true
  try {
    const result = await loginAPI({ username: loginForm.username, password: loginForm.password })
    if (result.success) {
      window.location.href = '/admin'
    } else {
      errorMsg.value = result.message || '登录失败'
    }
  } catch (err: unknown) {
    errorMsg.value = '网络错误: ' + (err instanceof Error ? err.message : String(err))
  } finally {
    loginLoading.value = false
  }
}

async function handleSendCode() {
  clearMessages()
  if (!regForm.email || !regForm.email.includes('@')) {
    errorMsg.value = '请输入有效邮箱'
    return
  }
  countdown.value = 60
  countdownTimer = setInterval(() => {
    countdown.value--
    if (countdown.value <= 0) {
      if (countdownTimer) clearInterval(countdownTimer)
    }
  }, 1000)

  try {
    const result = await sendCodeAPI({ email: regForm.email })
    if (result.success) {
      successMsg.value = result.message
    } else {
      errorMsg.value = result.message
      if (countdownTimer) clearInterval(countdownTimer)
      countdown.value = 0
    }
  } catch (err: unknown) {
    errorMsg.value = '发送失败: ' + (err instanceof Error ? err.message : String(err))
    if (countdownTimer) clearInterval(countdownTimer)
    countdown.value = 0
  }
}

async function handleRegister() {
  clearMessages()
  regLoading.value = true
  try {
    const result = await registerAPI({
      username: regForm.username,
      password: regForm.password,
      email: regForm.email,
      code: regForm.code,
    })
    if (result.success) {
      successMsg.value = result.message
      if (countdownTimer) clearInterval(countdownTimer)
      redirectTimer = setTimeout(() => { tab.value = 'login' }, 1500)
    } else {
      errorMsg.value = result.message || '注册失败'
    }
  } catch (err: unknown) {
    errorMsg.value = '网络错误: ' + (err instanceof Error ? err.message : String(err))
  } finally {
    regLoading.value = false
  }
}

let redirectTimer: ReturnType<typeof setTimeout> | null = null
onUnmounted(() => {
  if (countdownTimer) clearInterval(countdownTimer)
  if (redirectTimer) clearTimeout(redirectTimer)
})
</script>

<style scoped>
/* ===== Login page — always uses dark cosmic gradient ===== */
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--sp-5);
  background: linear-gradient(135deg, #0f0c29 0%, #1a1a3e 30%, #24243e 60%, #302b63 100%);
  position: relative;
  overflow: hidden;
}
[data-theme="dark"] .login-page {
  background:
    radial-gradient(ellipse at 20% 40%,rgba(110,60,254,.10) 0%,transparent 55%),
    radial-gradient(ellipse at 80% 20%,rgba(14,165,233,.07) 0%,transparent 50%),
    radial-gradient(ellipse at 50% 85%,rgba(168,85,247,.06) 0%,transparent 50%),
    linear-gradient(135deg, #070714 0%, #0f0c29 30%, #1a1040 60%, #302b63 100%);
}

/* Animated background blobs */
.bg-blob {
  position: absolute;
  border-radius: 50%;
  filter: blur(80px);
  opacity: .35;
  animation: float-blob 12s ease-in-out infinite;
}
.blob-1 {
  width: 400px; height: 400px;
  background: radial-gradient(circle, #667eea, transparent 70%);
  top: -10%; left: -5%;
  animation-delay: 0s;
}
.blob-2 {
  width: 350px; height: 350px;
  background: radial-gradient(circle, #764ba2, transparent 70%);
  bottom: -10%; right: -5%;
  animation-delay: -4s;
}
.blob-3 {
  width: 250px; height: 250px;
  background: radial-gradient(circle, #4facfe, transparent 70%);
  top: 40%; right: 20%;
  animation-delay: -8s;
}
@keyframes float-blob {
  0%, 100% { transform: translate(0, 0) scale(1); }
  33% { transform: translate(30px, -20px) scale(1.05); }
  66% { transform: translate(-20px, 20px) scale(.95); }
}

/* Glass card — uses design tokens */
.login-card {
  background: var(--glass-bg);
  backdrop-filter: blur(var(--glass-blur));
  -webkit-backdrop-filter: blur(var(--glass-blur));
  border: 1px solid var(--glass-border);
  border-radius: var(--r-2xl);
  padding: var(--sp-8) var(--sp-6);
  width: 100%; max-width: 420px;
  box-shadow: var(--glass-shadow);
  position: relative; z-index: 1;
}

/* Logo & title */
.logo {
  text-align: center;
  margin-bottom: var(--sp-4);
  font-size: 52px;
  filter: drop-shadow(0 4px 12px rgba(0,0,0,.3));
}
h1 {
  color: #fff;
  margin-bottom: var(--sp-2);
  font-size: var(--fs-3xl);
  text-align: center;
  font-weight: var(--fw-bold);
  text-shadow: 0 2px 8px rgba(0,0,0,.3);
}
.subtitle {
  color: rgba(255,255,255,.7);
  margin-bottom: var(--sp-5);
  font-size: var(--fs-md);
  text-align: center;
}

/* Tabs */
.tabs {
  display: flex;
  background: rgba(255,255,255,.08);
  border-radius: var(--r-2xl);
  padding: 3px;
  margin-bottom: var(--sp-5);
}
.tab {
  flex: 1;
  text-align: center;
  padding: var(--sp-3) var(--sp-4);
  cursor: pointer;
  font-size: var(--fs-md);
  font-weight: var(--fw-medium);
  color: rgba(255,255,255,.6);
  border: none;
  background: transparent;
  border-radius: var(--r-xl);
  transition: all var(--t-normal);
}
.tab.active {
  color: #fff;
  background: rgba(255,255,255,.15);
  box-shadow: 0 2px 8px rgba(0,0,0,.15);
}
.tab:hover:not(.active) {
  color: rgba(255,255,255,.85);
}

/* Form */
.login-form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}
.form-group { display: flex; flex-direction: column; gap: var(--sp-2); }
.form-group label {
  font-size: var(--fs-base);
  font-weight: var(--fw-medium);
  color: rgba(255,255,255,.85);
}
.form-group .input-field {
  background: rgba(255,255,255,.1);
  border: 1px solid rgba(255,255,255,.15);
  color: #fff;
  border-radius: var(--r-md);
  padding: var(--sp-3) var(--sp-4);
  font-size: var(--fs-md);
  transition: all var(--t-normal);
}
.form-group .input-field::placeholder { color: rgba(255,255,255,.4); }
.form-group .input-field:focus {
  outline: none;
  border-color: rgba(255,255,255,.35);
  background: rgba(255,255,255,.14);
  box-shadow: 0 0 0 3px rgba(102,126,234,.25);
}
[data-theme="dark"] .form-group .input-field:focus {
  border-color: rgba(110,168,254,.4);
  box-shadow: 0 0 0 3px rgba(110,168,254,.2);
}

/* Buttons */
.btn-block { width: 100%; padding: var(--sp-4) var(--sp-6); font-size: var(--fs-lg); }
.btn-primary {
  background: var(--gradient-primary);
  color: white;
  border: none;
  border-radius: var(--r-2xl);
  font-weight: var(--fw-semibold);
  cursor: pointer;
  transition: all var(--t-normal);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: var(--sp-2);
}
.btn-primary:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(102,126,234,.4);
}
[data-theme="dark"] .btn-primary:hover {
  box-shadow: 0 8px 24px rgba(110,168,254,.3), 0 0 30px rgba(168,85,247,.15);
}
.btn-primary:disabled {
  opacity: .6;
  cursor: not-allowed;
  transform: none;
  box-shadow: none;
}
.btn-spinner {
  width: 16px; height: 16px;
  border: 2px solid rgba(255,255,255,.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin .6s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

.btn-secondary {
  background: rgba(255,255,255,.1);
  color: rgba(255,255,255,.8);
  border: 1px solid rgba(255,255,255,.15);
  border-radius: var(--r-md);
  cursor: pointer;
  transition: all var(--t-normal);
}
.btn-secondary:hover { background: rgba(255,255,255,.18); }
.btn-secondary:disabled { opacity: .5; cursor: not-allowed; }

.code-row { display: flex; gap: var(--sp-2); }
.code-row .input-field { flex: 1; }
.code-btn {
  padding: var(--sp-3) var(--sp-4);
  font-size: var(--fs-base);
  white-space: nowrap;
  flex-shrink: 0;
}

/* Alerts — use design tokens */
.alert {
  padding: var(--sp-3) var(--sp-4);
  border-radius: var(--r-md);
  font-size: var(--fs-base);
  line-height: var(--lh-normal);
}
.alert-error {
  background: var(--red-bg);
  border: 1px solid var(--red);
  color: var(--red-fg);
}
.alert-success {
  background: var(--green-bg);
  border: 1px solid var(--green);
  color: var(--green-fg);
}

/* IP info */
.ip-info {
  margin-top: var(--sp-5);
  border-radius: var(--r-md);
  overflow: hidden;
  border: 1px solid rgba(255,255,255,.1);
}
.ip-info img { width: 100%; height: auto; display: block; }

/* Slide-fade transition */
.slide-fade-enter-active { transition: all .25s ease-out; }
.slide-fade-leave-active { transition: all .15s ease-in; }
.slide-fade-enter-from { opacity: 0; transform: translateX(12px); }
.slide-fade-leave-to { opacity: 0; transform: translateX(-12px); }

/* Responsive */
@media (max-width: 480px) {
  .login-card { padding: var(--sp-6) var(--sp-4); }
}
</style>
