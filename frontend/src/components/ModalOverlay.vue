<template>
  <Transition name="fade">
    <div v-if="modelValue" class="modal-overlay" @click.self="handleBackdropClick">
      <Transition name="slide-up" appear>
        <div v-if="modelValue" class="modal-panel" :style="{ maxWidth: width }">
          <div v-if="title" class="modal-header">
            <h3 class="modal-title">{{ title }}</h3>
            <button v-if="closable" class="modal-close" @click="close">&times;</button>
          </div>
          <div class="modal-body">
            <slot />
          </div>
          <div v-if="$slots.actions" class="modal-actions">
            <slot name="actions" />
          </div>
        </div>
      </Transition>
    </div>
  </Transition>
</template>

<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'

const props = withDefaults(defineProps<{
  modelValue: boolean
  title?: string
  width?: string
  closable?: boolean
  closeOnBackdrop?: boolean
}>(), {
  title: '',
  width: '420px',
  closable: true,
  closeOnBackdrop: true,
})

const emit = defineEmits<{
  'update:modelValue': [value: boolean]
}>()

function close() {
  emit('update:modelValue', false)
}

function handleBackdropClick() {
  if (props.closeOnBackdrop) close()
}

function onKey(e: KeyboardEvent) {
  if (e.key === 'Escape' && props.modelValue && props.closable) close()
}

onMounted(() => document.addEventListener('keydown', onKey))
onUnmounted(() => document.removeEventListener('keydown', onKey))
</script>

<style scoped>
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,.45);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: var(--z-modal, 1500);
  padding: var(--sp-5);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
}
.modal-panel {
  background: var(--surface);
  border-radius: var(--r-lg);
  padding: var(--sp-6);
  width: 90%;
  box-shadow: var(--shadow-5);
  max-height: 85vh;
  overflow-y: auto;
}
.modal-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--sp-4);
}
.modal-title {
  font-size: var(--fs-xl);
  font-weight: var(--fw-semibold);
  color: var(--text);
  margin: 0;
}
.modal-close {
  width: 32px; height: 32px;
  border-radius: var(--r-full);
  border: none; background: transparent;
  color: var(--muted); font-size: 20px;
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  transition: all var(--t-normal);
}
.modal-close:hover { background: var(--surface-2); color: var(--text); }
.modal-body {
  color: var(--text-2);
  font-size: var(--fs-md);
  line-height: var(--lh-relaxed);
}
.modal-actions {
  display: flex;
  gap: var(--sp-3);
  justify-content: flex-end;
  margin-top: var(--sp-5);
}
</style>
