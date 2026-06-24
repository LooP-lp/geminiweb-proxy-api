// ==================== 常量 & 配置 ====================
const COLS = 12;
const ROWS = 20;
const PIECES = 'ILJOTSZ';
const API_BASE_URL = '/api/game';
let currentUsername = null;

// Listen for username from parent page (GamesTab.vue)
window.addEventListener('message', function (event) {
  if (event.data && event.data.type === 'set-username') {
    currentUsername = event.data.username;
    // Reload leaderboard with the username
    renderLeaderboard().then(fitGameToViewport);
  }
});

// ==================== 自适应缩放 ====================
function fitGameToViewport() {
  var container = document.querySelector('.game-container');
  if (!container) return;

  // Reset transform to measure natural size
  container.style.transform = '';

  var naturalW = container.scrollWidth;
  var naturalH = container.scrollHeight;

  var margin = 12;
  var availW = window.innerWidth - margin * 2;
  var availH = window.innerHeight - margin * 2;

  var scale = Math.min(1, availW / naturalW, availH / naturalH);

  if (scale < 1) {
    container.style.transformOrigin = 'center center';
    container.style.transform = 'scale(' + scale + ')';
  } else {
    container.style.transform = '';
  }
}

// Fit on load and resize
window.addEventListener('load', fitGameToViewport);
window.addEventListener('resize', fitGameToViewport);

const THEME_COLORS = {
  retro:  [null, '#FF0D72', '#0DC2FF', '#0DFF72', '#F538FF', '#FF8E0D', '#FFE138', '#3877FF'],
  neon:   [null, '#FF0055', '#00FFFF', '#39FF14', '#FF00FF', '#FF6600', '#FFFF00', '#4400FF'],
  modern: [null, '#FF2D2D', '#FF6B4A', '#FF9E3D', '#FFD23D', '#FF4A6E', '#FF7EB3', '#CC1D1D'],
};

const THEME_CONFIG = {
  retro:  { dropInterval: 800, label: 'Retro' },
  neon:   { dropInterval: 500, label: 'Neon' },
  modern: { dropInterval: 300, label: 'Modern' },
};

const RANK_ICONS = ['🥇', '🥈', '🥉'];

// ==================== DOM 引用 ====================
const $ = id => document.getElementById(id);
const canvas       = $('tetris');
const ctx          = canvas.getContext('2d');
const nextCanvas   = $('next-piece');
const nextCtx      = nextCanvas.getContext('2d');
const scoreEl      = $('score');
const overlay      = $('overlay');
const modeSelect   = $('mode-select');
const muteBtn      = $('mute-btn');
const startScreen  = $('start-screen');
const startBtn     = $('start-btn');

ctx.scale(20, 20);
nextCtx.scale(20, 20);

// ==================== 音频 ====================
const audioCtx = new (window.AudioContext || window.webkitAudioContext)();

function playTone(freq, type, duration, vol = 0.1) {
  if (game.isMuted) return;
  try {
    if (audioCtx.state === 'suspended') audioCtx.resume();
    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(freq, audioCtx.currentTime);
    gain.gain.setValueAtTime(vol, audioCtx.currentTime);
    gain.gain.exponentialRampToValueAtTime(0.0001, audioCtx.currentTime + duration);
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start();
    osc.stop(audioCtx.currentTime + duration);
  } catch (e) {}
}

// ==================== 工具函数 ====================
function createMatrix(w, h) {
  const matrix = [];
  while (h--) matrix.push(new Array(w).fill(0));
  return matrix;
}

function createPiece(type) {
  switch (type) {
    case 'I': return [[0,1,0,0],[0,1,0,0],[0,1,0,0],[0,1,0,0]];
    case 'L': return [[0,2,0],[0,2,0],[0,2,2]];
    case 'J': return [[0,3,0],[0,3,0],[3,3,0]];
    case 'O': return [[4,4],[4,4]];
    case 'Z': return [[5,5,0],[0,5,5],[0,0,0]];
    case 'S': return [[0,6,6],[6,6,0],[0,0,0]];
    case 'T': return [[0,7,0],[7,7,7],[0,0,0]];
  }
}

function randomPiece() {
  return createPiece(PIECES[PIECES.length * Math.random() | 0]);
}

// ==================== 游戏核心状态 ====================
const game = {
  arena:      createMatrix(COLS, ROWS),
  player:     { pos: { x: 0, y: 0 }, matrix: null, score: 0 },
  nextPiece:  null,
  colors:     [...THEME_COLORS.retro],
  mode:       'retro',
  dropInterval: 800,
  dropCounter:  0,
  lastTime:    0,
  animationId: null,
  paused:      false,
  isGameOver:  false,
  isMuted:     false,
  isStarted:   false,
  particles:   [],
};

function canPlay() {
  return game.isStarted && !game.isGameOver && !game.paused;
}

// ==================== 碰撞 & 合并 ====================
function collide(arena, player) {
  const [m, o] = [player.matrix, player.pos];
  for (let y = 0; y < m.length; ++y) {
    for (let x = 0; x < m[y].length; ++x) {
      if (m[y][x] !== 0 && (arena[y + o.y] && arena[y + o.y][x + o.x]) !== 0) return true;
    }
  }
  return false;
}

function merge(arena, player) {
  player.matrix.forEach((row, y) => {
    row.forEach((value, x) => {
      if (value !== 0) arena[y + player.pos.y][x + player.pos.x] = value;
    });
  });
  playTone(150, 'sine', 0.1, 0.2);
}

// ==================== 旋转 ====================
function rotate(matrix, dir) {
  for (let y = 0; y < matrix.length; ++y) {
    for (let x = 0; x < y; ++x) {
      [matrix[x][y], matrix[y][x]] = [matrix[y][x], matrix[x][y]];
    }
  }
  if (dir > 0) matrix.forEach(row => row.reverse());
  else matrix.reverse();
}

// ==================== 玩家操作 ====================
function playerDrop() {
  if (!canPlay()) return;
  game.player.pos.y++;
  if (collide(game.arena, game.player)) {
    game.player.pos.y--;
    merge(game.arena, game.player);
    playerReset();
    arenaSweep();
    updateScore();
  }
  game.dropCounter = 0;
}

function playerHardDrop() {
  if (!canPlay()) return;
  while (!collide(game.arena, game.player)) game.player.pos.y++;
  game.player.pos.y--;
  merge(game.arena, game.player);
  playerReset();
  arenaSweep();
  updateScore();
  game.dropCounter = 0;
}

function playerMove(dir) {
  if (!canPlay()) return;
  game.player.pos.x += dir;
  if (collide(game.arena, game.player)) game.player.pos.x -= dir;
}

function playerRotate(dir) {
  if (!canPlay()) return;
  const pos = game.player.pos.x;
  let offset = 1;
  rotate(game.player.matrix, dir);
  while (collide(game.arena, game.player)) {
    game.player.pos.x += offset;
    offset = -(offset + (offset > 0 ? 1 : -1));
    if (offset > game.player.matrix[0].length) {
      rotate(game.player.matrix, -dir);
      game.player.pos.x = pos;
      return;
    }
  }
}

function playerReset() {
  if (game.isGameOver || !game.isStarted) return;
  game.player.matrix = game.nextPiece === null ? randomPiece() : game.nextPiece;
  game.nextPiece = randomPiece();
  game.player.pos.y = 0;
  game.player.pos.x = (game.arena[0].length / 2 | 0) - (game.player.matrix[0].length / 2 | 0);
  if (collide(game.arena, game.player)) gameOver();
}

// ==================== 行消除 & 粒子 ====================
function arenaSweep() {
  let rowCount = 1;
  const clearedRows = [];
  const clearedColors = [];
  outer: for (let y = game.arena.length - 1; y > 0; --y) {
    for (let x = 0; x < game.arena[y].length; ++x) {
      if (game.arena[y][x] === 0) continue outer;
    }
    clearedRows.push(y);
    clearedColors.push([...game.arena[y]]);
    const row = game.arena.splice(y, 1)[0].fill(0);
    game.arena.unshift(row);
    ++y;
    game.player.score += rowCount * 10;
    rowCount *= 2;
  }
  if (clearedRows.length > 0) {
    createExplosion(clearedRows, clearedColors);
    playTone(600, 'square', 0.2, 0.15);
  }
}

function createExplosion(rows, rowColors) {
  rows.forEach((y, rowIdx) => {
    const cellColors = rowColors[rowIdx];
    for (let x = 0; x < game.arena[0].length; x++) {
      const colorValue = cellColors[x];
      const particleColor = colorValue ? game.colors[colorValue] : '#FFF';
      for (let i = 0; i < 10; i++) {
        const angle = Math.random() * Math.PI * 2;
        const speed = Math.random() * 0.6 + 0.1;
        game.particles.push({
          x: x + 0.5, y: y + 0.5,
          vx: Math.cos(angle) * speed,
          vy: Math.sin(angle) * speed,
          life: 1.0,
          color: particleColor,
          size: Math.random() * 0.2 + 0.08,
        });
      }
    }
  });
}

function drawParticles() {
  for (let i = game.particles.length - 1; i >= 0; i--) {
    const p = game.particles[i];
    p.x += p.vx;
    p.y += p.vy;
    p.vy += 0.005;
    p.life -= 0.015;
    if (p.life <= 0) {
      game.particles.splice(i, 1);
    } else {
      ctx.globalAlpha = p.life;
      ctx.fillStyle = p.color;
      const s = p.size || 0.1;
      ctx.fillRect(p.x - s / 2, p.y - s / 2, s, s);
      ctx.globalAlpha = 1;
    }
  }
}

// ==================== 绘制 ====================
function draw() {
  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  drawMatrix(game.arena, { x: 0, y: 0 }, ctx);
  if (!game.isGameOver && game.isStarted) {
    drawMatrix(game.player.matrix, game.player.pos, ctx);
  }
  drawParticles();
  drawNext();
}

function drawMatrix(matrix, offset, c) {
  matrix.forEach((row, y) => {
    row.forEach((value, x) => {
      if (value !== 0) {
        c.fillStyle = game.colors[value];
        c.fillRect(x + offset.x, y + offset.y, 1, 1);
        c.lineWidth = 0.05;
        c.strokeStyle = 'white';
        c.strokeRect(x + offset.x, y + offset.y, 1, 1);
      }
    });
  });
}

function drawNext() {
  nextCtx.fillStyle = '#333';
  nextCtx.fillRect(0, 0, nextCanvas.width, nextCanvas.height);
  if (!game.nextPiece) return;
  const size = game.nextPiece.length;
  const ox = (nextCanvas.width / 20 - size) / 2;
  const oy = (nextCanvas.height / 20 - size) / 2;
  drawMatrix(game.nextPiece, { x: ox, y: oy }, nextCtx);
}

// ==================== 得分 & 历史记录 ====================
function updateScore() {
  scoreEl.innerText = game.player.score;
}

function saveScore() {
  if (game.player.score > 0) {
    sendScoreToBackend(game.player.score, game.mode);
  }
  renderLeaderboard().then(fitGameToViewport);
}

function expandHistoryPanel(mode) {
  ['retro', 'neon', 'modern'].forEach(m => {
    const body  = $('history-' + m);
    const arrow = $('arrow-' + m);
    if (m === mode) {
      body.classList.remove('collapsed');
      arrow.textContent = '▼';
    } else {
      body.classList.add('collapsed');
      arrow.textContent = '▶';
    }
  });
}

window.toggleHistoryPanel = function (mode) {
  const body  = $('history-' + mode);
  const arrow = $('arrow-' + mode);
  body.classList.toggle('collapsed');
  arrow.textContent = body.classList.contains('collapsed') ? '▶' : '▼';
};



// ==================== 主题 ====================
function applyTheme(mode) {
  game.mode = mode;
  game.colors = [...THEME_COLORS[mode]];
  game.dropInterval = THEME_CONFIG[mode].dropInterval;
  document.body.setAttribute('data-theme', mode);
}

// ==================== 游戏流程 ====================
function gameOver() {
  if (game.isGameOver) return;
  game.isGameOver = true;
  modeSelect.disabled = false;
  playTone(100, 'sawtooth', 0.8, 0.2);
  overlay.classList.remove('hidden');
  cancelAnimationFrame(game.animationId);
  saveScore();
  draw();
}

function togglePause() {
  if (!overlay.classList.contains('hidden') || game.isGameOver || !game.isStarted) return;
  game.paused = !game.paused;
  if (!game.paused) {
    game.lastTime = performance.now();
    update();
  } else {
    cancelAnimationFrame(game.animationId);
    ctx.fillStyle = 'rgba(0,0,0,0.5)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#fff';
    ctx.font = '1px Arial';
    ctx.textAlign = 'center';
    ctx.fillText('PAUSED', game.arena[0].length / 2, game.arena.length / 2);
  }
}

function clearArena() {
  game.arena.forEach(row => row.fill(0));
}

function saveCurrentScore() {
  if (game.player.score > 0) {
    const history = JSON.parse(localStorage.getItem(getHistoryKey(game.mode)) || '[]');
    history.push({ score: game.player.score, time: new Date().toLocaleString() });
    localStorage.setItem(getHistoryKey(game.mode), JSON.stringify(history));
  }
}

function resetGameState() {
  clearArena();
  game.player.score = 0;
  game.paused = false;
  game.isGameOver = false;
  game.particles = [];
  game.dropCounter = 0;
  updateScore();
}

window.resetGame = function () {
  if (game.player.score > 0 && !game.isGameOver) saveCurrentScore();
  resetGameState();
  modeSelect.disabled = true;
  overlay.classList.add('hidden');
  playerReset();
  renderLeaderboard().then(fitGameToViewport);
  expandHistoryPanel(game.mode);
  update();
};

window.backToStart = function () {
  if (game.player.score > 0 && !game.isGameOver) saveCurrentScore();
  resetGameState();
  game.isStarted = false;
  game.nextPiece = null;
  modeSelect.disabled = false;
  overlay.classList.add('hidden');
  startScreen.classList.remove('hidden');
  renderLeaderboard().then(fitGameToViewport);

  ctx.fillStyle = '#000';
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  nextCtx.fillStyle = '#333';
  nextCtx.fillRect(0, 0, nextCanvas.width, nextCanvas.height);
};

// ==================== 主循环 ====================
function update(time = 0) {
  if (game.paused || game.isGameOver || !game.isStarted) return;
  const deltaTime = time - game.lastTime;
  game.lastTime = time;
  game.dropCounter += deltaTime;
  if (game.dropCounter > game.dropInterval) playerDrop();
  draw();
  game.animationId = requestAnimationFrame(update);
}

// ==================== 事件绑定 ====================
modeSelect.addEventListener('change', e => {
  if (game.isStarted && !game.isGameOver) {
    modeSelect.value = game.mode;
    return;
  }
  applyTheme(e.target.value);
});

muteBtn.addEventListener('click', () => {
  game.isMuted = !game.isMuted;
  muteBtn.textContent = game.isMuted ? '🔇' : '🔊';
  muteBtn.classList.toggle('muted', game.isMuted);
});

startBtn.addEventListener('click', () => {
  if (audioCtx.state === 'suspended') audioCtx.resume();
  startScreen.classList.add('hidden');
  game.isStarted = true;
  modeSelect.disabled = true;
  applyTheme(modeSelect.value);
  expandHistoryPanel(game.mode);
  playerReset();
  updateScore();
  update();
  setTimeout(fitGameToViewport, 100);
});

document.addEventListener('keydown', event => {
  if (!game.isStarted) return;
  if (event.keyCode === 27) togglePause();
  if (event.keyCode === 82) window.resetGame();
  if (game.paused || game.isGameOver) return;
  switch (event.keyCode) {
    case 37: playerMove(-1); break;
    case 39: playerMove(1);  break;
    case 40: playerDrop();   break;
    case 81: playerRotate(-1); break;
    case 87: playerRotate(1);  break;
    case 32: playerHardDrop(); break;
  }
});

// ==================== API / 得分上报 ====================
function getUsername() {
  return currentUsername || localStorage.getItem('tetris_username') || '匿名';
}

function saveLocalScore(score, mode) {
  const key = 'tetris_local_' + mode;
  const history = JSON.parse(localStorage.getItem(key) || '[]');
  history.push({ score: score, time: new Date().toLocaleString() });
  history.sort((a, b) => b.score - a.score);
  localStorage.setItem(key, JSON.stringify(history.slice(0, 20)));
}

async function sendScoreToBackend(score, mode, timestamp = new Date().toISOString()) {
  if (score <= 0) return;
  const username = getUsername();

  // Always save locally
  saveLocalScore(score, mode);

  try {
    const response = await fetch(`${API_BASE_URL}/score`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, score, mode, timestamp }),
    });
    if (!response.ok) console.warn('得分同步失败:', response.status);
  } catch (error) {
    console.warn('得分同步失败:', error);
  }
}

async function fetchLeaderboard(mode) {
  try {
    const response = await fetch(`${API_BASE_URL}/score?mode=${encodeURIComponent(mode)}&limit=10`);
    if (response.ok) return await response.json();
  } catch (e) {
    console.warn('排行榜获取失败:', e);
  }
  return [];
}

async function renderLeaderboard() {
  for (const mode of ['retro', 'neon', 'modern']) {
    const listEl = $('list-' + mode);
    if (!listEl) continue;

    const entries = await fetchLeaderboard(mode);
    const localKey = 'tetris_local_' + mode;
    const localHistory = JSON.parse(localStorage.getItem(localKey) || '[]');
    const username = getUsername();

    // Show "我的最高分" at top if user has local scores
    let html = '';
    const myBest = localHistory.length > 0 ? localHistory[0].score : 0;
    if (myBest > 0) {
      const myEntries = localHistory.slice(0, 3);
      html += '<div class="history-section-title">我的记录</div>';
      myEntries.forEach((h, i) => {
        const icon = i < 3 ? `<span class="rank-icon rank-${i + 1}">${RANK_ICONS[i]}</span>` : `<span class="rank-icon rank-other">${i + 1}</span>`;
        html += `<div class="history-item">${icon}<span class="history-score">${h.score}分</span><small class="history-time">${h.time}</small></div>`;
      });
    }

    if (entries.length > 0) {
      html += '<div class="history-section-title">排行榜</div>';
      entries.forEach((h, i) => {
        const icon = i < 3 ? `<span class="rank-icon rank-${i + 1}">${RANK_ICONS[i]}</span>` : `<span class="rank-icon rank-other">${i + 1}</span>`;
        const isMe = h.username === username;
        html += `<div class="history-item${isMe ? ' is-me' : ''}">${icon}<span class="history-score">${h.score}分</span><small class="history-time">${isMe ? '👤 ' : ''}${h.username}</small></div>`;
      });
    }

    if (!html) {
      html = '<div class="history-empty">暂无记录</div>';
    }
    listEl.innerHTML = html;
  }
}

// ==================== 初始化 ====================
applyTheme('retro');
renderLeaderboard().then(fitGameToViewport);
