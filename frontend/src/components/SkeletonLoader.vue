<template>
  <div class="skeleton-loader" :style="{ width, height }" />
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  width?: string
  height?: string
}>(), {
  width: '100%',
  height: '20px',
})
</script>

<style scoped>
.skeleton-loader {
  background: var(--surface-2);
  border-radius: var(--r-md);
  animation: skeleton-pulse 1.5s ease-in-out infinite;
}
@keyframes skeleton-pulse {
  0% { opacity: 1; }
  50% { opacity: .4; }
  100% { opacity: 1; }
}
</style>
