<template>
  <Teleport to="body">
    <div class="toast-container">
      <TransitionGroup name="toast-slide">
        <div
          v-for="t in toast.items"
          :key="t.id"
          class="toast-item"
          :class="t.type"
          @click="toast.remove(t.id)"
        >
          <span class="toast-icon">{{ iconMap[t.type] }}</span>
          <span class="toast-msg">{{ t.message }}</span>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { useToastStore } from '@/stores/toast'

const toast = useToastStore()

const iconMap: Record<string, string> = {
  success: '✓',
  error: '✕',
  info: 'ℹ',
  warning: '⚠',
}
</script>

<style scoped>
.toast-container {
  position: fixed;
  bottom: var(--sp-6);
  right: var(--sp-6);
  z-index: var(--z-toast, 2000);
  display: flex;
  flex-direction: column-reverse;
  gap: var(--sp-2);
  pointer-events: none;
}
.toast-item {
  pointer-events: auto;
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: var(--sp-3) var(--sp-5);
  border-radius: var(--r-md);
  font-size: var(--fs-md);
  font-weight: var(--fw-medium);
  box-shadow: var(--shadow-3);
  cursor: pointer;
  transition: all var(--t-normal);
  max-width: 380px;
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
}
.toast-item.success { background: var(--green-bg); color: var(--green-fg); border: 1px solid var(--green); }
.toast-item.error { background: var(--red-bg); color: var(--red-fg); border: 1px solid var(--red); }
.toast-item.info { background: var(--blue-bg); color: var(--blue); border: 1px solid var(--blue); }
.toast-item.warning { background: var(--yellow-bg); color: var(--yellow-fg); border: 1px solid var(--yellow); }
.toast-icon { font-weight: var(--fw-bold); font-size: var(--fs-lg); }
.toast-msg { flex: 1; line-height: var(--lh-normal); }
</style>
