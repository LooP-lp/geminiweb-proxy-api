
import type { HourlyStat } from '@/types'

const CHART_COLORS = ['#4285f4','#ea4335','#fbbc04','#34a853','#ff6d01','#46bdc6','#7b1fa2','#e91e63','#00bcd4','#8bc34a']

function formatNum(n: number): string {
  if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'K'
  return n.toString()
}

function isDarkMode(): boolean {
  return document.documentElement.getAttribute('data-theme') === 'dark'
}

/**
 * Observe a canvas parent's size and call `redraw` on resize.
 * Skips redraw when parent width is 0 (tab hidden via v-show).
 * Returns a disconnect function for cleanup in onUnmounted.
 */
export function observeChartResize(canvas: HTMLCanvasElement, redraw: () => void): () => void {
  const parent = canvas.parentElement
  if (!parent) return () => {}
  let skipNext = false
  const ro = new ResizeObserver(() => {
    // Skip redraws when element is hidden (width=0 from v-show)
    const rect = parent.getBoundingClientRect()
    if (rect.width < 10) {
      skipNext = true
      return
    }
    // If we previously skipped (element was hidden), redraw now that it's visible
    if (skipNext) {
      skipNext = false
      redraw()
      return
    }
    redraw()
  })
  ro.observe(parent)
  return () => ro.disconnect()
}

/**
 * Watch dark-mode changes and trigger redraw.
 * Returns a cleanup function.
 */
export function watchDarkMode(redraw: () => void): () => void {
  const observer = new MutationObserver(() => { redraw() })
  observer.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme'],
  })
  return () => observer.disconnect()
}

export function drawUserModelBarChart(canvas: HTMLCanvasElement, hourlyData: HourlyStat[]) {
  const dpr = window.devicePixelRatio || 1
  const rect = canvas.parentElement!.getBoundingClientRect()
  let W = rect.width; if (W < 100) W = 100
  const H = 200
  // Skip drawing when parent is hidden (v-show: display:none)
  if (rect.width < 1) return
  canvas.width = W * dpr; canvas.height = H * dpr
  canvas.style.width = '100%'; canvas.style.height = H + 'px'
  const ctx = canvas.getContext('2d')!; ctx.scale(dpr, dpr)

  const now = new Date(); const curHour = now.getHours()
  const models: Record<string, Record<number, number>> = {}
  const hours: number[] = []
  for (let i = 0; i < 24; i++) { hours.push((curHour - 23 + i + 24) % 24) }
  hourlyData.forEach((d: HourlyStat) => {
    if (!models[d.model]) models[d.model] = {}
    models[d.model][d.hour] = d.requests
  })
  const modelNames = Object.keys(models)
  if (modelNames.length === 0) {
    ctx.clearRect(0, 0, W, H); ctx.fillStyle = isDarkMode() ? '#9aa0a6' : '#5f6368'; ctx.font = '13px sans-serif'
    ctx.textAlign = 'center'; ctx.fillText('暂无数据', W / 2, H / 2); return
  }

  let maxVal = 0
  for (let hi = 0; hi < 24; hi++) {
    let total = 0; modelNames.forEach(m => { total += (models[m][hours[hi]] || 0) })
    if (total > maxVal) maxVal = total
  }
  if (maxVal === 0) maxVal = 1

  const padL = 50, padR = 10, padT = 10, padB = 55
  const cW = W - padL - padR, cH = H - padT - padB
  const dark = isDarkMode()
  const gridColor = dark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)'
  const textColor = dark ? '#9aa0a6' : '#5f6368'

  ctx.clearRect(0, 0, W, H); ctx.strokeStyle = gridColor; ctx.lineWidth = 1
  for (let g = 0; g <= 4; g++) {
    const gy = padT + cH - (cH * g / 4)
    ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(padL + cW, gy); ctx.stroke()
    ctx.fillStyle = textColor; ctx.font = '11px sans-serif'; ctx.textAlign = 'right'
    ctx.fillText(Math.round(maxVal * g / 4).toString(), padL - 6, gy + 4)
  }

  ctx.textAlign = 'center'; ctx.font = '10px sans-serif'
  const barW = cW / 24
  for (let xi = 0; xi < 24; xi++) {
    if (xi % 3 === 0) ctx.fillText(hours[xi].toString().padStart(2, '0') + ':00', padL + barW * xi + barW / 2, H - 6)
  }

  for (let bi = 0; bi < 24; bi++) {
    let bottomY = padT + cH
    for (let mi = 0; mi < modelNames.length; mi++) {
      const val = models[modelNames[mi]][hours[bi]] || 0
      if (val === 0) continue
      const bH = cH * val / maxVal; bottomY -= bH
      ctx.fillStyle = CHART_COLORS[mi % CHART_COLORS.length]
      ctx.fillRect(padL + barW * bi + 2, bottomY, barW - 4, bH)
    }
  }

  let lx = padL, ly = H - 30
  modelNames.forEach((m, idx) => {
    ctx.fillStyle = CHART_COLORS[idx % CHART_COLORS.length]
    ctx.fillRect(lx, ly, 10, 10)
    ctx.fillStyle = textColor; ctx.font = '10px sans-serif'; ctx.textAlign = 'left'
    const short = m.length > 15 ? m.substring(0, 15) + '...' : m
    ctx.fillText(short, lx + 14, ly + 9)
    lx += ctx.measureText(short).width + 24
    if (lx > W - 60) { lx = padL; ly -= 14 }
  })
}

export function drawUserTokenLineChart(canvas: HTMLCanvasElement, hourlyData: HourlyStat[]) {
  const dpr = window.devicePixelRatio || 1
  const rect = canvas.parentElement!.getBoundingClientRect()
  let W = rect.width; if (W < 100) W = 100
  const H = 200
  // Skip drawing when parent is hidden (v-show: display:none)
  if (rect.width < 1) return
  canvas.width = W * dpr; canvas.height = H * dpr
  canvas.style.width = '100%'; canvas.style.height = H + 'px'
  const ctx = canvas.getContext('2d')!; ctx.scale(dpr, dpr)

  const now = new Date(); const curHour = now.getHours()
  const labels: string[] = []; const values: number[] = []
  for (let i = 0; i < 24; i++) {
    const h = (curHour - 23 + i + 24) % 24
    labels.push(h.toString().padStart(2, '0') + ':00')
    let total = 0
    for (let j = 0; j < hourlyData.length; j++) { if (hourlyData[j].hour === h) total += hourlyData[j].total_tokens }
    values.push(total)
  }

  if (Math.max(...values) === 0) {
    ctx.clearRect(0, 0, W, H); ctx.fillStyle = isDarkMode() ? '#9aa0a6' : '#5f6368'; ctx.font = '13px sans-serif'
    ctx.textAlign = 'center'; ctx.fillText('暂无数据', W / 2, H / 2); return
  }
  drawLineChart(ctx, W, H, labels, values, '#34a853', '#0d904f')
}

export function drawHourlyChart(canvas: HTMLCanvasElement, hourlyData: HourlyStat[], field: keyof HourlyStat, lineColor: string, fillColor: string) {
  const dpr = window.devicePixelRatio || 1
  const rect = canvas.parentElement!.getBoundingClientRect()
  let W = rect.width; if (W < 100) W = 100
  const H = 160
  // Skip drawing when parent is hidden (v-show: display:none)
  if (rect.width < 1) return
  canvas.width = W * dpr; canvas.height = H * dpr
  canvas.style.width = '100%'; canvas.style.height = H + 'px'
  const ctx = canvas.getContext('2d')!; ctx.scale(dpr, dpr)

  const now = new Date(); const curHour = now.getHours()
  const labels: string[] = []; const values: number[] = []
  for (let i = 0; i < 24; i++) {
    const h = (curHour - 23 + i + 24) % 24
    labels.push(h.toString().padStart(2, '0') + ':00')
    const found = hourlyData.find((d: HourlyStat) => d.hour === h)
    values.push(Number(found ? found[field] : 0))
  }
  drawLineChart(ctx, W, H, labels, values, lineColor, fillColor)
}

function drawLineChart(ctx: CanvasRenderingContext2D, W: number, H: number, labels: string[], values: number[], lineColor: string, fillColor: string) {
  let maxVal = Math.max(...values); if (maxVal === 0) maxVal = 1
  const padL = 60, padR = 10, padT = 10, padB = 30
  const cW = W - padL - padR, cH = H - padT - padB
  const dark = isDarkMode()
  const gridColor = dark ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.06)'
  const textColor = dark ? '#9aa0a6' : '#5f6368'

  ctx.clearRect(0, 0, W, H)
  ctx.strokeStyle = gridColor; ctx.lineWidth = 1
  for (let g = 0; g <= 4; g++) {
    const gy = padT + cH - (cH * g / 4)
    ctx.beginPath(); ctx.moveTo(padL, gy); ctx.lineTo(padL + cW, gy); ctx.stroke()
    ctx.fillStyle = textColor; ctx.font = '11px sans-serif'; ctx.textAlign = 'right'
    ctx.fillText(formatNum(Math.round(maxVal * g / 4)), padL - 6, gy + 4)
  }
  ctx.textAlign = 'center'; ctx.font = '10px sans-serif'
  for (let xi = 0; xi < 24; xi += 3) {
    const xx = padL + (cW * xi / 23)
    ctx.fillText(labels[xi], xx, H - 4)
  }
  ctx.beginPath()
  for (let li = 0; li < 24; li++) {
    const lx = padL + (cW * li / 23)
    const ly = padT + cH - (cH * values[li] / maxVal)
    if (li === 0) ctx.moveTo(lx, ly); else ctx.lineTo(lx, ly)
  }
  ctx.strokeStyle = lineColor; ctx.lineWidth = 2; ctx.stroke()
  ctx.lineTo(padL + cW, padT + cH); ctx.lineTo(padL, padT + cH); ctx.closePath()
  ctx.fillStyle = fillColor + '22'; ctx.fill()
  for (let di = 0; di < 24; di++) {
    if (values[di] > 0) {
      const dx = padL + (cW * di / 23)
      const dy = padT + cH - (cH * values[di] / maxVal)
      ctx.beginPath(); ctx.arc(dx, dy, 3, 0, 6.2832)
      ctx.fillStyle = lineColor; ctx.fill()
    }
  }
}
