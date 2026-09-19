(() => {
  const meta = name => typeof document === 'undefined' ? '' : document.querySelector?.(`meta[name="${name}"]`)?.content || ''
  const base = meta('pokesim-base')
  const adventureId = meta('pokesim-adventure')
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
  async function gameFetch(path, options = {}, retried = false) {
    const method = (options.method || 'GET').toUpperCase()
    if (!base || ['GET', 'HEAD', 'OPTIONS'].includes(method)) return fetch(url(path), options)
    await session()
    const sentCsrf = csrf
    const response = await fetch(url(path), {...options, credentials: 'same-origin', headers: {...options.headers, 'X-PokeSim-CSRF': sentCsrf}})
    if (!retried && response.status === 403) {
      let data = {}
      try { data = await response.clone().json() } catch (_) {}
      if (data.code === 'csrf_expired' || data.detail === 'Reload this page before making changes') {
        if (csrf === sentCsrf) sessionRequest = null
        return gameFetch(path, options, true)
      }
    }
    return response
  }
  globalThis.PokeSim = {base, adventureId, url, fetch: gameFetch, session}
  if (!base || !adventureId) return
  document.addEventListener('DOMContentLoaded', async () => {
    const switcher = document.querySelector('#adventure-switcher')
    if (!switcher) return
    switcher.onchange = () => {
      const page = location.pathname.slice(base.length)
      const next = ['/', '/pc', '/pokedex', '/journal', '/trading'].includes(page) ? page : '/'
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
