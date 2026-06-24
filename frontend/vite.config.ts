import { defineConfig, type ProxyOptions } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

const backend = 'http://localhost:7788'
const backendProxy: ProxyOptions = {
  target: backend,
  changeOrigin: true,
}
const adminApiProxy: ProxyOptions = {
  ...backendProxy,
  bypass(req) {
    if (req.method === 'GET' && (req.headers.accept || '').includes('text/html')) {
      return '/index.html'
    }
  },
}

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': resolve(__dirname, 'src'),
    },
  },
  build: {
    outDir: resolve(__dirname, '../dist'),
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/admin': adminApiProxy,
      '/v1': backendProxy,
      '/proxy_image': backendProxy,
      '/media': backendProxy,
      '/game': backendProxy,
      '/api': backendProxy,
    },
  },
})
