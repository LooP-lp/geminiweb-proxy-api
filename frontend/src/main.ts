import './style.css'
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)

app.mount('#root')

// Initialize theme after pinia is ready
import { useThemeStore } from './stores/theme'
const theme = useThemeStore()
theme.init()
