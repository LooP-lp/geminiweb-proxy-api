<template>
  <div class="empty-state">
    <div class="empty-icon">{{ icon }}</div>
    <div class="empty-title">{{ title }}</div>
    <div v-if="description" class="empty-desc">{{ description }}</div>
    <slot />
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  icon?: string
  title: string
  description?: string
}>(), {
  icon: '📭',
})
</script>

<style scoped>
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--sp-10) var(--sp-5);
  text-align: center;
}
.empty-icon {
  font-size: 48px;
  margin-bottom: var(--sp-4);
  opacity: .6;
}
.empty-title {
  font-size: var(--fs-lg);
  font-weight: var(--fw-medium);
  color: var(--muted);
  margin-bottom: var(--sp-2);
}
.empty-desc {
  font-size: var(--fs-base);
  color: var(--muted);
  max-width: 320px;
  line-height: var(--lh-relaxed);
}
</style>
