// Your inbox: trade offers and answers, finished trades, control requests and new shares.
// Shown only to someone logged in to an account. The Library's adventure list carries the
// unread count, so this file adds no polling of its own and fetches items only when opened.
(() => {
  const $ = selector => document.querySelector(selector)
  const toggle = $('#inbox-open')
  const panel = $('#inbox-panel')
  if (!toggle || !panel) return
  const list = $('#inbox-list')
  const count = $('#inbox-count')
  const readAll = $('#inbox-read-all')
  const result = $('#inbox-result')
  let csrf = ''
  let unread = 0

  async function call(path, options = {}) {
    const response = await fetch(path, {cache: 'no-store', credentials: 'same-origin', ...options,
      headers: {'Content-Type': 'application/json', 'X-PokeSim-CSRF': csrf, ...(options.headers || {})}})
    let data
    try { data = await response.json() } catch (_) { data = {} }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`)
    return data
  }
  const markRead = body => call('/api/v1/inbox/read', {method: 'POST', body: JSON.stringify(body), keepalive: true})

  function showCount(value) {
    unread = Math.max(0, Number(value) || 0)
    count.textContent = unread > 99 ? '99+' : String(unread)
    count.hidden = unread === 0
    toggle.setAttribute('aria-label', unread ? `Inbox, ${unread} unread` : 'Inbox')
    readAll.disabled = unread === 0
  }

  // Only PokeSim paths become links. The server refuses anything else, and this keeps it so.
  const safeLink = link => typeof link === 'string' && link.startsWith('/') && !link.startsWith('//') && !link.includes('\\')

  function when(seconds) {
    const date = new Date(seconds * 1000)
    const today = new Date().toDateString() === date.toDateString()
    return today ? date.toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'})
      : date.toLocaleDateString([], {month: 'short', day: 'numeric'})
  }

  function render(items) {
    list.replaceChildren()
    if (!items.length) {
      const empty = document.createElement('li')
      empty.className = 'inbox-empty'
      empty.textContent = 'Nothing yet. Trade offers, finished trades, control requests and new shares show up here.'
      list.append(empty)
      return
    }
    for (const item of items) {
      const row = document.createElement('li')
      row.className = item.read ? 'inbox-item' : 'inbox-item is-unread'
      const body = document.createElement(safeLink(item.link) ? 'a' : 'p')
      body.className = 'inbox-body'
      if (body.tagName === 'A') {
        body.href = item.link
        body.addEventListener('click', () => {
          if (!item.read) markRead({ids: [item.id]}).catch(() => {})
        })
      }
      const text = document.createElement('span')
      text.className = 'inbox-text'
      text.textContent = item.text
      const time = document.createElement('time')
      time.className = 'micro'
      time.dateTime = new Date(item.created_at * 1000).toISOString()
      time.textContent = when(item.created_at)
      if (!item.read) {
        const flag = document.createElement('span')
        flag.className = 'inbox-flag'
        flag.textContent = 'Unread. '
        body.append(flag)
      }
      body.append(text, time)
      row.append(body)
      list.append(row)
    }
  }

  async function open() {
    panel.hidden = false
    toggle.setAttribute('aria-expanded', 'true')
    result.textContent = 'Loading'
    try {
      const data = await call('/api/v1/inbox')
      render(data.items || [])
      showCount(data.unread)
      result.textContent = ''
    } catch (error) { result.textContent = error.message }
  }
  function close(focus) {
    if (panel.hidden) return
    panel.hidden = true
    toggle.setAttribute('aria-expanded', 'false')
    if (focus) toggle.focus()
  }

  toggle.addEventListener('click', () => (panel.hidden ? open() : close(false)))
  readAll.addEventListener('click', async () => {
    try {
      await markRead({all: true})
      for (const row of list.querySelectorAll('.is-unread')) {
        row.classList.remove('is-unread')
        row.querySelector('.inbox-flag')?.remove()
      }
      showCount(0)
      result.textContent = 'All read'
    } catch (error) { result.textContent = error.message }
  })
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !panel.hidden) close(true)
  })
  document.addEventListener('click', event => {
    if (!panel.hidden && !panel.contains(event.target) && !toggle.contains(event.target)) close(false)
  })

  document.addEventListener('pokesim:session', event => {
    const session = event.detail || {}
    csrf = session.csrf_token || ''
    toggle.hidden = session.auth !== 'accounts' || !session.user || Boolean(session.user.placeholder)
  }, {once: true})
  // library.js hands over the unread count with every adventure list it reads.
  document.addEventListener('pokesim:inbox', event => {
    if (!toggle.hidden && event.detail) showCount(event.detail.unread)
  })
})()
