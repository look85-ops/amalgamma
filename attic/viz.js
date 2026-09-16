const COLS = { bg: '#0a0a0f', fg: '#8a5cf5', fg2: '#44aa88', text: '#ddd8d0', dim: '#555' }
let w, h, ctx, state = null, pulses = [], words = [], mood = 'neutral', frame = 0

function resize () {
  w = innerWidth
  h = 180
  const c = document.getElementById('viz')
  if (c) { c.width = w; c.height = h; ctx = c.getContext('2d') }
}

function init () {
  const d = document.createElement('div')
  d.style.cssText = 'position:relative;margin:0 -1.5rem;overflow:hidden'
  d.innerHTML = '<canvas id="viz"></canvas>'
  document.querySelector('.footer').before(d)
  resize()
  fetch('state.json')
    .then(r => r.json())
    .then(s => {
      state = s
      pulses = Array.from({ length: 60 }, (_, i) => ({ x: i * 10, y: 0 }))
      const t = s._agent_temp || 0.85
      const e = s._exploration_factor || 0.5
      pulses.forEach(p => { p.y = 50 - (t * 40); p.y2 = 50 - (e * 40) })
      words = (s._inquiry_threads || []).map(q => {
        const text = q.replace(/^[0-9. ]+/, '').slice(0, 40)
        return { text: text, x: Math.random() * w, y: Math.random() * h, vx: (Math.random() - 0.5) * 0.3, vy: (Math.random() - 0.5) * 0.3, size: 12 + Math.random() * 8 }
      })
      const ev = s._evaluation || ''
      mood = ev === 'интересно' ? 'curious' : ev === 'странно' ? 'strange' : 'calm'
      anim()
    })
  window.addEventListener('resize', resize)
}

function anim () {
  frame++
  ctx.clearRect(0, 0, w, h)
  if (state) {
    const t = state._agent_temp || 0.85
    const e = state._exploration_factor || 0.5
    const cyc = state.cycle || 0
    pulses.shift()
    pulses.push({ x: pulses.length ? pulses[pulses.length - 1].x + 10 : 0, y: 50 - (t * 40), y2: 50 - (e * 40) })
    ctx.beginPath()
    ctx.strokeStyle = COLS.fg
    ctx.lineWidth = 1.5
    pulses.forEach((p, i) => { i ? ctx.lineTo(p.x, p.y) : ctx.moveTo(p.x, p.y) })
    ctx.stroke()
    ctx.beginPath()
    ctx.strokeStyle = COLS.fg2
    ctx.lineWidth = 1
    pulses.forEach((p, i) => { i ? ctx.lineTo(p.x, p.y2) : ctx.moveTo(p.x, p.y2) })
    ctx.stroke()
    ctx.fillStyle = COLS.dim
    ctx.font = '10px monospace'
    ctx.fillText('temp. ' + t.toFixed(2), 10, 12)
    ctx.fillStyle = COLS.fg2
    ctx.fillText('explr. ' + e.toFixed(2), 10, 24)
    ctx.fillStyle = COLS.dim
    ctx.font = '10px monospace'
    ctx.textAlign = 'right'
    ctx.fillText('cycle ' + cyc, w - 10, 12)
    const ec = mood === 'curious' ? COLS.fg2 : mood === 'strange' ? COLS.fg : COLS.dim
    ctx.fillStyle = ec
    ctx.fillText(state._evaluation || '', w - 10, 24)
    words.forEach(wd => {
      wd.x += wd.vx; wd.y += wd.vy
      if (wd.x < 0 || wd.x > w) wd.vx *= -1
      if (wd.y < 0 || wd.y > h) wd.vy *= -1
      ctx.fillStyle = 'rgba(221,216,208,' + (0.15 + Math.sin(frame * 0.02 + words.indexOf(wd)) * 0.1) + ')'
      ctx.font = wd.size + 'px Georgia'
      ctx.textAlign = 'center'
      ctx.fillText(wd.text, wd.x, wd.y)
    })
  }
  requestAnimationFrame(anim)
}

window.addEventListener('DOMContentLoaded', init)
