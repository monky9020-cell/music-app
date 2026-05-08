<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Music Recommender</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{background:#0a0a0a;color:#fff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;min-height:100vh;display:flex;flex-direction:column;align-items:center;padding:32px 16px}

  .app{width:100%;max-width:720px}

  /* Header */
  .header{display:flex;align-items:center;gap:12px;margin-bottom:36px}
  .logo-circle{width:36px;height:36px;background:#1db954;border-radius:50%;display:flex;align-items:center;justify-content:center;flex-shrink:0}
  .logo-circle svg{width:18px;height:18px;fill:#000}
  .header h1{font-size:20px;font-weight:600;letter-spacing:-0.3px}
  .header span{font-size:14px;color:#a0a0a0;margin-left:4px;font-weight:400}

  /* Search form */
  .form-card{background:#111;border:1px solid #222;border-radius:16px;padding:24px;margin-bottom:28px}
  .form-label{font-size:11px;color:#737373;text-transform:uppercase;letter-spacing:1px;margin-bottom:8px;display:block}
  .input-row{display:flex;gap:12px;margin-bottom:16px}
  .input-wrap{flex:1;position:relative}
  .input-wrap svg{position:absolute;left:12px;top:50%;transform:translateY(-50%);width:16px;height:16px;stroke:#555;fill:none;pointer-events:none}
  .input-wrap input{width:100%;background:#1a1a1a;border:1px solid #2a2a2a;border-radius:10px;padding:11px 14px 11px 38px;color:#fff;font-size:14px;outline:none;transition:border-color .15s}
  .input-wrap input:focus{border-color:#1db954}
  .input-wrap input::placeholder{color:#555}
  .artist-wrap input{padding-left:14px}
  .btn-search{width:100%;background:#1db954;color:#000;border:none;border-radius:50px;padding:13px;font-size:14px;font-weight:600;cursor:pointer;display:flex;align-items:center;justify-content:center;gap:8px;transition:background .15s;letter-spacing:0.2px}
  .btn-search:hover{background:#1ed760}
  .btn-search:disabled{background:#333;color:#666;cursor:not-allowed}
  .btn-search svg{width:16px;height:16px;fill:currentColor}


  /* Barra de progreso */
  .progress-bar{display:none;margin-top:16px;background:#1a1a1a;border-radius:50px;height:3px;overflow:hidden}
  .progress-bar.visible{display:block}
  .progress-fill{height:100%;background:#1db954;border-radius:50px;width:0%;transition:width .4s ease}
  .progress-steps{display:none;margin-top:10px;font-size:12px;color:#737373;text-align:center}
  .progress-steps.visible{display:block}
  /* Status */
  .status{text-align:center;padding:12px;font-size:13px;color:#a0a0a0;display:none}
  .status.visible{display:block}
  .dot-anim::after{content:'...';animation:dots 1.2s infinite}
  @keyframes dots{0%{content:'.'}33%{content:'..'}66%{content:'...'}}

  /* Results */
  .results-header{display:flex;align-items:baseline;gap:8px;margin-bottom:16px}
  .results-header h2{font-size:13px;text-transform:uppercase;letter-spacing:1px;color:#737373;font-weight:500}
  .results-header span{font-size:13px;color:#a0a0a0}

  .result-card{background:#111;border:1px solid #1e1e1e;border-radius:12px;padding:14px 16px;margin-bottom:10px;display:flex;align-items:center;gap:14px;transition:background .15s,border-color .15s}
  .result-card:hover{background:#161616;border-color:#2a2a2a}

  .result-num{font-size:13px;color:#555;width:18px;text-align:center;flex-shrink:0;font-variant-numeric:tabular-nums}
  .result-bar{width:3px;height:34px;border-radius:2px;flex-shrink:0}
  .result-bar.playing{background:#1db954}
  .result-bar.idle{background:#2a2a2a}

  .result-info{flex:1;min-width:0}
  .result-title{font-size:14px;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;color:#fff}
  .result-sub{font-size:12px;color:#737373;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .similar-tag{color:#1db954}

  .result-dur{font-size:12px;color:#555;flex-shrink:0;font-variant-numeric:tabular-nums}

  .btn-radio{background:none;border:1px solid #2a2a2a;border-radius:50px;padding:5px 12px;color:#737373;font-size:12px;cursor:pointer;display:flex;align-items:center;gap:5px;flex-shrink:0;transition:all .15s;white-space:nowrap}
  .btn-radio:hover{border-color:#1db954;color:#1db954}
  .btn-radio svg{width:12px;height:12px;fill:currentColor}

  .btn-yt{background:none;border:none;color:#555;cursor:pointer;flex-shrink:0;padding:6px;border-radius:6px;display:flex;align-items:center;transition:color .15s}
  .btn-yt:hover{color:#fff}
  .btn-yt svg{width:20px;height:20px;fill:currentColor}

  /* Error */
  .error-box{background:#1a0a0a;border:1px solid #3a1a1a;border-radius:10px;padding:14px 16px;color:#ff6b6b;font-size:13px;margin-bottom:16px;display:none}
  .error-box.visible{display:block}

  /* Empty */
  .empty{text-align:center;padding:48px 0;color:#555;font-size:14px;display:none}
  .empty.visible{display:block}

  /* Breadcrumb */
  .breadcrumb{display:flex;align-items:center;gap:6px;margin-bottom:20px;flex-wrap:wrap;display:none}
  .breadcrumb.visible{display:flex}
  .crumb{font-size:12px;color:#555;cursor:pointer;transition:color .15s}
  .crumb:hover{color:#a0a0a0}
  .crumb.active{color:#a0a0a0}
  .crumb-sep{font-size:12px;color:#333}
</style>
</head>
<body>

<div class="app">

  <!-- Header -->
  <div class="header">
    <div class="logo-circle">
      <svg viewBox="0 0 24 24"><path d="M12 3v10.55A4 4 0 1 0 14 17V7h4V3h-6z"/></svg>
    </div>
    <h1>Music Recommender <span>via Last.fm + YouTube</span></h1>
  </div>

  <!-- Breadcrumb de navegación radio -->
  <div class="breadcrumb" id="breadcrumb"></div>

  <!-- Formulario -->
  <div class="form-card">
    <label class="form-label">Canción o URL de YouTube</label>
    <div class="input-row">
      <div class="input-wrap" style="flex:2">
        <svg viewBox="0 0 24 24" stroke-width="2"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>
        <input type="text" id="query" placeholder="https://youtube.com/watch?v=... o nombre de canción" autocomplete="off">
      </div>
      <div class="input-wrap artist-wrap" style="flex:1">
        <input type="text" id="artist" placeholder="Artista (opcional si pegaste URL)" autocomplete="off">
      </div>
    </div>
    <button class="btn-search" id="btn-search" onclick="doSearch()">
      <svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8zm-1-5h2v2h-2zm0-8h2v6h-2z"/></svg>
      Buscar recomendaciones
    </button>
  </div>

  <!-- Barra de progreso -->
  <div class="progress-bar" id="progress-bar">
    <div class="progress-fill" id="progress-fill"></div>
  </div>
  <div class="progress-steps" id="progress-steps"></div>

  <!-- Estado de carga -->
  <div class="status" id="status"></div>

  <!-- Error -->
  <div class="error-box" id="error-box"></div>

  <!-- Resultados -->
  <div id="results-section" style="display:none">
    <div class="results-header">
      <h2>Recomendaciones</h2>
      <span id="results-subtitle"></span>
    </div>
    <div id="results-list"></div>
  </div>

  <!-- Empty -->
  <div class="empty" id="empty">No se encontraron resultados. Intenta con otro artista.</div>

</div>

<script>
const BAR_COLORS = ['playing','idle','idle','idle','idle']
let searchHistory = []

const STEPS = [
  [10,  'Analizando la canción...'],
  [25,  'Consultando Last.fm...'],
  [50,  'Buscando artistas similares...'],
  [70,  'Buscando en YouTube...'],
  [85,  'Filtrando resultados...'],
  [95,  'Casi listo...'],
]
let progressTimer = null
let stepIdx = 0

function setStatus(msg) {
  const el = document.getElementById('status')
  el.innerHTML = msg
  el.className = msg ? 'status visible' : 'status'
}

function startProgress() {
  const bar   = document.getElementById('progress-bar')
  const fill  = document.getElementById('progress-fill')
  const steps = document.getElementById('progress-steps')
  bar.className   = 'progress-bar visible'
  steps.className = 'progress-steps visible'
  stepIdx = 0
  fill.style.width = '0%'
  steps.textContent = STEPS[0][1]

  progressTimer = setInterval(() => {
    if (stepIdx < STEPS.length - 1) stepIdx++
    const [pct, label] = STEPS[stepIdx]
    fill.style.width   = pct + '%'
    steps.textContent  = label
  }, 1800)
}

function stopProgress(success) {
  clearInterval(progressTimer)
  const bar   = document.getElementById('progress-bar')
  const fill  = document.getElementById('progress-fill')
  const steps = document.getElementById('progress-steps')
  if (success) {
    fill.style.width    = '100%'
    fill.style.background = '#1db954'
    steps.textContent   = 'Listo.'
  }
  setTimeout(() => {
    bar.className   = 'progress-bar'
    steps.className = 'progress-steps'
    fill.style.width = '0%'
    fill.style.background = '#1db954'
  }, 800)
}

function setError(msg) {
  const el = document.getElementById('error-box')
  el.textContent = msg
  el.className = msg ? 'error-box visible' : 'error-box'
}

function setLoading(on) {
  const btn = document.getElementById('btn-search')
  btn.disabled = on
  btn.innerHTML = on
    ? '<span class="dot-anim">Buscando</span>'
    : '<svg viewBox="0 0 24 24" style="width:16px;height:16px;fill:currentColor"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zm0 18a8 8 0 1 1 8-8 8 8 0 0 1-8 8zm-1-5h2v2h-2zm0-8h2v6h-2z"/></svg> Buscar recomendaciones'
}

function updateBreadcrumb() {
  const bc = document.getElementById('breadcrumb')
  if (searchHistory.length <= 1) { bc.className = 'breadcrumb'; return }
  bc.className = 'breadcrumb visible'
  bc.innerHTML = searchHistory.map((h, i) => {
    const isLast = i === searchHistory.length - 1
    const crumb = `<span class="crumb ${isLast ? 'active' : ''}" ${!isLast ? `onclick="jumpTo(${i})"` : ''}>${h.artist}</span>`
    return i < searchHistory.length - 1 ? crumb + '<span class="crumb-sep">›</span>' : crumb
  }).join('')
}

function jumpTo(idx) {
  searchHistory = searchHistory.slice(0, idx + 1)
  const h = searchHistory[idx]
  document.getElementById('query').value  = h.query
  document.getElementById('artist').value = h.artist
  updateBreadcrumb()
  doSearch(true)
}

async function doSearch(fromHistory = false) {
  const query  = document.getElementById('query').value.trim()
  const artist = document.getElementById('artist').value.trim()
  if (!query) { setError('Ingresa una canción o URL de YouTube'); return }

  setError('')
  setLoading(true)
  document.getElementById('results-section').style.display = 'none'
  document.getElementById('empty').className = 'empty'
  setStatus('')
  startProgress()

  try {
    const resp = await fetch('/search', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({query, artist})
    })
    const data = await resp.json()

    stopProgress(true)
    setStatus('')
    setLoading(false)

    if (data.error) { setError(data.error); return }

    if (!fromHistory) {
      searchHistory.push({query, artist: data.artist || artist || query})
      updateBreadcrumb()
    }

    renderResults(data)
  } catch(e) {
    stopProgress(false)
    setStatus('')
    setLoading(false)
    setError('Error de conexión. ¿Está corriendo el servidor?')
  }
}

let lastResults = []

function renderResults(data) {
  lastResults = data.results || []
  const section  = document.getElementById('results-section')
  const list     = document.getElementById('results-list')
  const subtitle = document.getElementById('results-subtitle')
  const empty    = document.getElementById('empty')

  if (!data.results || data.results.length === 0) {
    empty.className = 'empty visible'
    section.style.display = 'none'
    return
  }

  subtitle.textContent = `similar a ${data.artist}`
  list.innerHTML = ''

  data.results.forEach((r, i) => {
    const card = document.createElement('div')
    card.className = 'result-card'
    card.dataset.idx = i
    card.innerHTML = `
      <span class="result-num">${i + 1}</span>
      <div class="result-bar ${i === 0 ? 'playing' : 'idle'}"></div>
      <div class="result-info">
        <div class="result-title" title="${esc(r.title)}">${esc(r.title)}</div>
        <div class="result-sub">${esc(r.channel)} · <span class="similar-tag">similar a ${esc(r.target_artist)}</span></div>
      </div>
      <span class="result-dur">${r.duration}</span>
      <button class="btn-radio" data-idx="${i}">
        <svg viewBox="0 0 24 24"><path d="M12 2a10 10 0 1 0 10 10A10 10 0 0 0 12 2zM6.27 17.73A8 8 0 1 1 17.73 6.27 8 8 0 0 1 6.27 17.73zm5.73-3.73a2 2 0 1 1-2-2 2 2 0 0 1 2 2zm0-5.27V7a5 5 0 0 1 5 5h-2a3 3 0 0 0-3-3zm0 2.17V9a3 3 0 0 1 3 3h-2a1 1 0 0 0-1-1z"/></svg>
        Radio
      </button>
      <button class="btn-yt" onclick="openYT('${esc(r.url)}')" title="Abrir en YouTube">
        <svg viewBox="0 0 24 24"><path d="M21.8 8s-.2-1.4-.8-2c-.8-.8-1.6-.8-2-.9C16.6 5 12 5 12 5s-4.6 0-7 .1c-.4.1-1.2.1-2 .9-.6.6-.8 2-.8 2S2 9.6 2 11.2v1.5c0 1.6.2 3.2.2 3.2s.2 1.4.8 2c.8.8 1.8.8 2.3.9C6.8 19 12 19 12 19s4.6 0 7-.2c.4-.1 1.2-.1 2-.9.6-.6.8-2 .8-2s.2-1.6.2-3.2v-1.5C22 9.6 21.8 8 21.8 8zM10 15V9l5.2 3-5.2 3z"/></svg>
      </button>
    `
    // Event listeners para botones Radio
    card.querySelector('.btn-radio').addEventListener('click', function() {
      radioFrom(parseInt(this.dataset.idx))
    })
    list.appendChild(card)
  })

  section.style.display = 'block'
}

function radioFrom(idx) {
  const r = lastResults[idx]
  if (!r) return
  document.getElementById('query').value  = r.title
  document.getElementById('artist').value = r.target_artist
  window.scrollTo({top: 0, behavior: 'smooth'})
  doSearch()
}

function openYT(url) {
  window.open(url, '_blank')
}

function esc(str) {
  return String(str)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;')
}

// Enter para buscar
document.getElementById('query').addEventListener('keydown', e => {
  if (e.key === 'Enter') doSearch()
})
document.getElementById('artist').addEventListener('keydown', e => {
  if (e.key === 'Enter') doSearch()
})
</script>
</body>
</html>
