<template>
  <div class="games-tab">
    <div class="game-grid">
      <div
        class="game-card"
        :class="{ active: selectedGame === 'tetris' }"
        @click="selectedGame = 'tetris'"
      >
        <div class="game-card-icon">
          <svg xmlns="http://www.w3.org/2000/svg" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <rect x="3" y="3" width="7" height="7" rx="1"/>
            <rect x="14" y="3" width="7" height="7" rx="1"/>
            <rect x="3" y="14" width="7" height="7" rx="1"/>
            <rect x="14" y="14" width="7" height="7" rx="1"/>
          </svg>
        </div>
        <div class="game-card-info">
          <div class="game-card-name">俄罗斯方块</div>
          <div class="game-card-desc">经典 Tetris 游戏，三种难度模式<span class="game-card-author"> — by:bigegg</span></div>
        </div>
        <div class="game-card-arrow">→</div>
      </div>
    </div>

    <div v-if="selectedGame === 'tetris'" class="game-frame-wrapper">
      <iframe
        ref="gameIframe"
        src="/game/tetris/"
        class="game-iframe"
        @load="onIframeLoad"
        title="俄罗斯方块"
        scrolling="no"
      ></iframe>
    </div>

    <div v-else class="game-placeholder">
      <p>选择一个游戏开始</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useAuthStore } from '@/stores/auth'

const auth = useAuthStore()
const selectedGame = ref('')
const gameIframe = ref<HTMLIFrameElement | null>(null)

function onIframeLoad() {
  // Send username to the game via postMessage
  const iframe = gameIframe.value
  if (iframe && iframe.contentWindow) {
    iframe.contentWindow.postMessage(
      { type: 'set-username', username: auth.username },
      '*'
    )
  }
}
</script>

<style scoped>
.games-tab {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
}

.game-grid {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-5) var(--sp-5) 0;
}

.game-card {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  padding: var(--sp-5);
  border-radius: var(--r-xl);
  background: var(--surface);
  border: 1px solid var(--border);
  cursor: pointer;
  transition: all var(--t-normal);
  user-select: none;
}

.game-card:hover {
  border-color: var(--blue);
  background: var(--blue-bg);
  transform: translateY(-1px);
}

.game-card.active {
  border-color: var(--blue);
  background: var(--blue-bg);
}

.game-card-icon {
  color: var(--blue);
  flex-shrink: 0;
  opacity: 0.9;
}

.game-card-info {
  flex: 1;
  min-width: 0;
}

.game-card-name {
  font-size: var(--fs-lg);
  font-weight: var(--fw-bold);
  color: var(--text);
  margin-bottom: 2px;
}

.game-card-desc {
  font-size: var(--fs-base);
  color: var(--muted);
}

.game-card-author {
  color: var(--blue);
  font-weight: var(--fw-medium);
  opacity: 0.85;
}

.game-card-arrow {
  color: var(--muted);
  font-size: var(--fs-lg);
  flex-shrink: 0;
  transition: transform var(--t-normal);
}

.game-card.active .game-card-arrow,
.game-card:hover .game-card-arrow {
  transform: translateX(4px);
  color: var(--blue);
}

.game-frame-wrapper {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  padding: var(--sp-3);
  position: relative;
  min-height: 0;
}

.game-iframe {
  width: 100%;
  height: 100%;
  max-width: 100%;
  max-height: 100%;
  border: 1px solid var(--border);
  border-radius: var(--r-xl);
  background: transparent;
}

.game-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--muted);
  font-size: var(--fs-md);
}

[data-theme="dark"] .game-card {
  background: rgba(14, 14, 30, 0.6);
  border-color: rgba(110, 168, 254, 0.1);
}

[data-theme="dark"] .game-card:hover,
[data-theme="dark"] .game-card.active {
  background: rgba(110, 168, 254, 0.08);
  border-color: rgba(110, 168, 254, 0.25);
}

@media (max-width: 900px) {
  .game-grid {
    padding: var(--sp-3) var(--sp-3) 0;
  }
  .game-frame-wrapper {
    padding: var(--sp-2);
  }
}
</style>
