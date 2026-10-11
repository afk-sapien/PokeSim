(() => {
  const meta = name => typeof document === 'undefined' ? '' : document.querySelector?.(`meta[name="${name}"]`)?.content || ''
  const base = meta('pokesim-base')
  const adventureId = meta('pokesim-adventure')
  // The library stamps the portraits this adventure shows, so a stamped portrait is kept for a year.
  const spriteVersion = meta('pokesim-sprites') || 'rom-portraits-1'
  const sprite = dex => `${base}/sprites/${Number(dex) || 0}.png?v=${encodeURIComponent(spriteVersion)}`
  let csrf = ''
  let sessionRequest = null
  const url = path => {
    if (!path.startsWith('/') || path.startsWith('//') || path.includes('..')) throw new Error('Expected an absolute game route')
    return base + path
  }
  async function session() {
    if (!sessionRequest) sessionRequest = fetch('/api/v1/session', {cache: 'no-store', credentials: 'same-origin'})
      .then(async response => {
        if (!response.ok) throw new Error('Could not connect to PokeSim. Try again in a moment.')
        const data = await response.json()
        csrf = data.csrf_token || ''
        return data
      }).catch(error => { sessionRequest = null
        throw error })
    return sessionRequest
  }
  async function request(target, options = {}, retried = false) {
    const method = (options.method || 'GET').toUpperCase()
    if (!base || ['GET', 'HEAD', 'OPTIONS'].includes(method)) return fetch(target, options)
    await session()
    const sentCsrf = csrf
    const response = await fetch(target, {...options, credentials: 'same-origin', headers: {...options.headers, 'X-PokeSim-CSRF': sentCsrf}})
    if (!retried && response.status === 403) {
      let data = {}
      try { data = await response.clone().json() } catch (_) {}
      if (data.code === 'csrf_expired' || data.detail === 'Reload this page before making changes') {
        if (csrf === sentCsrf) sessionRequest = null
        return request(target, options, true)
      }
    }
    return response
  }
  const gameFetch = (path, options = {}) => request(url(path), options)
  const setSpeed = speed => base && adventureId
    ? request(`/api/v1/adventures/${encodeURIComponent(adventureId)}`, {
      method: 'PATCH', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({settings: {speed}}),
    })
    : gameFetch('/api/control', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action: 'speed', value: speed}),
    })
  // The last data a page drew, kept per adventure in IndexedDB so a reload can paint it at
  // once while fresh data loads. Only for display: anything that acts waits for the server.
  // Storage can be missing, blocked or full, and then pages simply wait as before.
  const SAVED = 'pokesim-saved'
  const SAVED_SHAPE = 1
  let savedStore = null
  function saved() {
    if (!savedStore) savedStore = new Promise((resolve, reject) => {
      const open = globalThis.indexedDB.open(SAVED, 1)
      open.onupgradeneeded = () => open.result.createObjectStore('pages')
      open.onsuccess = () => resolve(open.result)
      open.onerror = () => reject(open.error)
      open.onblocked = () => reject(new Error('blocked'))
    })
    return savedStore
  }
  const savedKey = name => `${adventureId || base || 'local'}:${name}`
  async function recall(name) {
    try {
      const db = await saved()
      const row = await new Promise((resolve, reject) => {
        const read = db.transaction('pages').objectStore('pages').get(savedKey(name))
        read.onsuccess = () => resolve(read.result)
        read.onerror = () => reject(read.error)
      })
      return row?.shape === SAVED_SHAPE ? row.data : null
    } catch (_) { return null }
  }
  async function remember(name, data) {
    try {
      const db = await saved()
      const write = db.transaction('pages', 'readwrite')
      write.objectStore('pages').put({shape: SAVED_SHAPE, saved: Date.now(), data}, savedKey(name))
      await new Promise(resolve => { write.oncomplete = write.onerror = write.onabort = resolve })
    } catch (_) {}
  }
  globalThis.PokeSim = {base, adventureId, spriteVersion, sprite, recall, remember, url, fetch: gameFetch, api: request, session, setSpeed}
  if (!base || !adventureId) return
  document.addEventListener('DOMContentLoaded', async () => {
    const switcher = document.querySelector('#adventure-switcher')
    if (!switcher) return
    switcher.onchange = () => {
      const page = location.pathname.slice(base.length)
      const next = ['/', '/pc', '/pokedex', '/journal', '/journal/stats', '/stats', '/stats/pokemon', '/stats/items', '/trading'].includes(page) ? page : '/'
      location.href = `/games/${encodeURIComponent(switcher.value)}${next}`
    }
    try {
      const response = await fetch('/api/v1/adventures', {cache: 'no-store'})
      if (!response.ok) return
      const {adventures} = await response.json()
      switcher.replaceChildren(...adventures.filter(game => !game.archived || game.id === adventureId).map(game => {
        const option = document.createElement('option')
        option.value = game.id
        option.textContent = `${game.name} (${game.version})`
        option.selected = game.id === adventureId
        return option
      }))
    } catch (_) { switcher.title = 'Adventure list is reconnecting' }
  })
})()
