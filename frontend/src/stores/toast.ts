import { defineStore } from 'pinia'
import { ref } from 'vue'

export interface ToastItem {
  id: number
  message: string
  type: 'success' | 'error' | 'info' | 'warning'
  duration: number
}

let nextId = 0

export const useToastStore = defineStore('toast', () => {
  const items = ref<ToastItem[]>([])

  function remove(id: number) {
    items.value = items.value.filter((t) => t.id !== id)
  }

  function add(message: string, type: ToastItem['type'] = 'info', duration = 3000) {
    const id = nextId++
    items.value = [...items.value, { id, message, type, duration }]
    if (duration > 0) {
      setTimeout(() => remove(id), duration)
    }
  }

  function success(message: string, duration?: number) { add(message, 'success', duration) }
  function error(message: string, duration?: number) { add(message, 'error', duration ?? 5000) }
  function info(message: string, duration?: number) { add(message, 'info', duration) }
  function warning(message: string, duration?: number) { add(message, 'warning', duration) }

  return { items, add, remove, success, error, info, warning }
})