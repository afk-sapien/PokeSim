(() => {
  const $ = selector => document.querySelector(selector)
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp', '<': '&lt', '>': '&gt', '"': '&quot', "'": '&#39'}[char] + String.fromCharCode(59)))
  const page = document.body.dataset.page
  const currentId = document.body.dataset.adventure
  let csrf = ''
  let owner = false
  let adventures = []
  let busy = false
  let refreshing = false
  let participantsDirty = false
  const cardSignatures = new Map()
  let stoppedSignature = ''
  let participantSignature = ''
  const requests = new Map()
  const dateLabel = value => typeof value === 'number' ? new Date(value * 1000).toLocaleString() : String(value || '')
  const gameUrl = id => `/games/${encodeURIComponent(id)}/`
  const running = game => ['running', 'paused', 'held', 'waiting_for_trade'].includes(game.state)
  function notice(message, error = false) {
    $('#notice').textContent = message
    $('#notice').hidden = !message
    $('#notice').classList.toggle('error', error)
  }
  function permissions() {
    document.querySelectorAll('[data-owner]').forEach(element => { element.disabled = !owner || busy || element.hasAttribute('data-blocked') })
  }
  async function api(path, options = {}) {
    const response = await fetch(path, {cache: 'no-store', credentials: 'same-origin', ...options,
      headers: {...options.headers, ...(options.method && options.method !== 'GET' ? {'X-PokeSim-CSRF': csrf} : {})}})
    let data
    try { data = await response.json() } catch (_) { data = {} }
    if (!response.ok) {
      if (response.status === 401) { $('#signin').hidden = false
        $('#workspace').hidden = true }
      const detail = data.detail || data.error || `Request failed (${response.status})`
      throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail))
    }
    return data
  }
  async function write(path, body = {}, method = 'POST') {
    const signature = `${method}:${path}:${JSON.stringify(body)}`
    if (!requests.has(signature)) requests.set(signature, Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join(''))
    const data = await api(path, {method, headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(method === 'PATCH' ? body : {...body, request_id: requests.get(signature)})})
    requests.delete(signature)
    return data
  }
  async function act(operation) {
    if (busy) return
    busy = true
    permissions()
    try { notice('')
      document.querySelectorAll('.dialog-feedback').forEach(element => { element.textContent = '' })
      await operation()
      await refresh() } catch (error) { notice(error.message, true)
      const feedback = document.querySelector('dialog[open] .dialog-feedback')
      if (feedback) feedback.textContent = error.message }
    finally { busy = false
      permissions() }
  }
  function card(game) {
    const active = running(game)
    const transitional = ['starting', 'stopping', 'preparing', 'setting_up', 'recovering'].includes(game.state)
    const summary = game.summary || {}
    const activity = summary.message || summary.activity || summary.game?.location || summary.map || (active ? 'Adventure in progress' : 'Your saves are waiting here')
    const provenance = game.provenance?.trading_blocked ? `<p class="card-error">${esc(game.provenance.reason || 'Legacy trade history needs reconciliation before trading.')}</p>` : ''
    const failure = game.error ? `<p class="card-error">${esc(typeof game.error === 'string' ? game.error : JSON.stringify(game.error))}</p>` : ''
    return `<article class="adventure-card ${esc(game.version)}" data-adventure-id="${esc(game.id)}">${active ? `<div class="card-screen"><img src="${gameUrl(game.id)}frame.jpg" alt="${esc(game.name)} game screen" loading="lazy" width="160" height="144"></div>` : ''}<div class="card-banner"><span class="eyebrow">POKÉMON ${esc(game.version).toUpperCase()}</span><span class="state-pill">${esc(game.archived ? 'archived' : game.state || 'stopped')}</span></div><div class="card-body"><h2>${esc(game.name)}</h2><p>${esc(activity)}</p>${failure}${provenance}${game.archived ? '<p class="section-note">Archived adventures keep all their saves.</p>' : ''}<div class="card-actions"><a class="primary-button" href="${gameUrl(game.id)}">${active ? 'Open adventure' : 'View adventure'} ↗</a>${game.archived ? `<button data-action="restore" data-id="${esc(game.id)}" data-owner>Restore</button>` : `<button data-action="${active ? 'stop' : 'start'}" data-id="${esc(game.id)}" data-owner ${transitional ? 'disabled data-blocked' : ''}>${transitional ? esc(game.state) : active ? 'Save and stop' : 'Start'}</button><button data-action="settings" data-id="${esc(game.id)}" data-owner>Settings</button>${!active && !transitional ? `<button data-action="archive" data-id="${esc(game.id)}" data-owner>Archive</button>` : ''}`}</div></div></article>`
  }
  function renderAdventures() {
    const visible = adventures.filter(game => $('#show-archived').checked || !game.archived)
    const container = $('#adventure-list')
    const ids = new Set(visible.map(game => game.id))
    container.querySelectorAll('[data-adventure-id]').forEach(element => {
      if (!ids.has(element.dataset.adventureId)) { cardSignatures.delete(element.dataset.adventureId)
        element.remove() }
    })
    for (const game of visible) {
      const markup = card(game)
      if (cardSignatures.get(game.id) === markup) continue
      const previous = container.querySelector(`[data-adventure-id="${game.id}"]`)
      if (previous) previous.outerHTML = markup
      else container.insertAdjacentHTML('beforeend', markup)
      cardSignatures.set(game.id, markup)
    }
    $('#empty').hidden = Boolean(visible.length)
    $('#running-summary').textContent = `${adventures.filter(running).length} running · ${adventures.filter(game => !game.archived).length} adventures`
    if (page === 'stopped') {
      const game = adventures.find(item => item.id === currentId)
      $('#stopped-title').textContent = game?.name || 'Adventure unavailable'
      const stoppedMarkup = game ? card(game) : '<p>This adventure is not in the current library.</p>'
      if (stoppedSignature !== stoppedMarkup) { $('#stopped-card').innerHTML = stoppedMarkup
        stoppedSignature = stoppedMarkup }
      if (game && running(game)) location.replace(gameUrl(game.id))
    }
    permissions()
  }
  function fillAdventureSelect(selector) {
    const element = $(selector)
    const previous = element.value
    const choices = adventures.filter(game => !game.archived && running(game))
    const signature = JSON.stringify(choices.map(game => [game.id, game.name]))
    if (element.dataset.signature === signature) return
    element.dataset.signature = signature
    element.innerHTML = '<option value="">Select a running adventure</option>' + choices.map(game => `<option value="${esc(game.id)}">${esc(game.name)} (${esc(game.version)})</option>`).join('')
    if (choices.some(game => game.id === previous)) element.value = previous
    else if (previous) loadPokemon(selector.endsWith('left') ? 'left' : 'right')
  }
  function describeTrade(trade) {
    const left = adventures.find(game => game.id === trade.left_id)?.name || trade.left_id || trade.participants?.[0] || ''
    const right = adventures.find(game => game.id === trade.right_id)?.name || trade.right_id || trade.participants?.[1] || ''
    return `<div class="exchange"><strong>${esc(left)} ↔ ${esc(right)}</strong><span class="state-pill">${esc(trade.phase || trade.state || trade.status || 'Waiting')}</span><p>${esc(trade.message || trade.error || '')}</p>${trade.cancellable ? `<button data-trade-action="cancel" data-id="${esc(trade.id)}" data-owner>Cancel exchange</button>` : ''}${trade.phase === 'recovering' ? `<button data-trade-action="recover" data-id="${esc(trade.id)}" data-owner>Retry recovery</button>` : ''}</div>`
  }
  async function refreshTrades() {
    const data = await api('/api/v1/interactions')
    const selected = new Set((data.participants || []).map(item => typeof item === 'string' ? item : item.id))
    const signature = JSON.stringify([adventures.map(game => [game.id, game.name, game.state, game.archived]), [...selected], data.enabled])
    if (!participantsDirty && participantSignature !== signature) {
      $('#trading-enabled').checked = Boolean(data.enabled)
      $('#participants').innerHTML = adventures.filter(game => !game.archived).map(game => `<label class="participant inline-label"><input type="checkbox" name="participant" value="${esc(game.id)}" ${selected.has(game.id) ? 'checked' : ''} data-owner><span>${esc(game.name)} <small>${esc(game.version)} · ${esc(game.state)}</small></span></label>`).join('') || '<p>Create adventures in the Library to connect them.</p>'
      participantSignature = signature
    }
    const active = Array.isArray(data.active) ? data.active : data.active ? [data.active] : []
    $('#trade-active').innerHTML = active.length ? active.map(describeTrade).join('') : `<p>${esc(data.message || (data.enabled ? 'Waiting for a useful, eligible exchange.' : 'Automatic trading is off. You can choose an exchange below.'))}</p>`
    $('#trade-history').innerHTML = (data.history || []).length ? data.history.map(describeTrade).join('') : '<p>No exchanges yet.</p>'
    fillAdventureSelect('#trade-left')
    fillAdventureSelect('#trade-right')
    permissions()
  }
  async function loadPokemon(side) {
    const id = $(`#trade-${side}`).value
    const select = $(`#trade-${side}-key`)
    select.innerHTML = '<option value="">Loading Pokémon…</option>'
    if (!id) { select.innerHTML = '<option value="">Select an adventure first</option>'
      return }
    try {
      const data = await api(`/api/v1/adventures/${encodeURIComponent(id)}/trade-inventory`)
      if ($(`#trade-${side}`).value !== id) return
      const pokemon = (data.offers || []).filter(mon => mon.trade_key && !mon.locked)
      select.innerHTML = '<option value="">Select a Pokémon</option>' + pokemon.map(mon => `<option value="${esc(mon.trade_key)}">${esc(mon.nick || mon.name)} · Lv. ${esc(mon.level)} · ${mon.box ? `Box ${esc(mon.box)}` : 'Party'}</option>`).join('')
      if (!pokemon.length) select.innerHTML = '<option value="">No eligible trade offers available</option>'
    } catch (error) { select.innerHTML = '<option value="">Pokémon unavailable</option>'
      notice(error.message, true) }
  }
  async function refreshBackups() {
    const data = await api('/api/v1/backups')
    const backups = Array.isArray(data) ? data : data.backups || []
    $('#backups').innerHTML = backups.length ? backups.map(backup => `<p><a class="text-link" href="/api/v1/backups/${encodeURIComponent(backup.id)}/download">Download backup ${esc(dateLabel(backup.created_at) || backup.id)} ↗</a></p>`).join('') : '<p class="section-note">No backups yet.</p>'
  }
  async function refresh() {
    if (refreshing || $('#workspace').hidden) return
    refreshing = true
    try {
      const data = await api('/api/v1/adventures')
      adventures = data.adventures || []
      renderAdventures()
      if (page === 'trading') await refreshTrades()
      $('#connection').textContent = owner ? 'Owner' : 'Viewer'
    } catch (error) { $('#connection').textContent = 'Reconnecting'
      notice(error.message, true) }
    finally { refreshing = false }
  }
  async function openCreate() {
    await act(async () => {
      const data = await api('/api/v1/assets')
      $('#rom-select').innerHTML = '<option value="">Add a ROM below</option>' + (data.roms || []).map(rom => `<option value="${esc(rom.id)}">Pokémon ${esc(rom.version)} (${esc(rom.id.slice(0, 8))})</option>`).join('')
      if (data.roms?.length) $('#rom-select').value = data.roms[0].id
      $('#create-progress').textContent = ''
      $('#create-dialog').showModal()
      $('#new-name').focus()
    })
  }
  $('#new-adventure').onclick = openCreate
  $('#empty-create').onclick = openCreate
  $('#show-archived').onchange = renderAdventures
  document.querySelectorAll('[data-close]').forEach(button => { button.onclick = () => $(`#${button.dataset.close}`).close() })
  document.addEventListener('click', event => {
    const control = event.target.closest('[data-trade-action]')
    if (control && !control.disabled) act(async () => {
      await write(`/api/v1/interactions/${encodeURIComponent(control.dataset.id)}/${control.dataset.tradeAction}`)
      notice(control.dataset.tradeAction === 'recover' ? 'Recovery requested.' : 'Exchange cancellation requested.')
    })
    const button = event.target.closest('[data-action]')
    if (!button || button.disabled) return
    const game = adventures.find(item => item.id === button.dataset.id)
    if (!game) return
    if (button.dataset.action === 'settings') {
      $('#settings-id').value = game.id
      $('#settings-name').value = game.name
      $('#settings-speed').value = String(game.settings?.speed ?? 1)
      $('#settings-autostart').checked = Boolean(game.settings?.auto_start)
      for (const [field, setting] of [['league-rewards', 'league_rewards'], ['mew-event', 'mew_event']]) {
        const input = $(`#settings-${field}`)
        input.checked = Boolean(game.settings?.[setting])
        input.toggleAttribute('data-blocked', running(game))
        input.disabled = running(game)
      }
      $('#adventure-settings').showModal()
      return
    }
    act(async () => {
      if (button.dataset.action === 'restore') await write(`/api/v1/adventures/${encodeURIComponent(game.id)}`, {archived: false}, 'PATCH')
      else await write(`/api/v1/adventures/${encodeURIComponent(game.id)}/${button.dataset.action}`)
      notice(button.dataset.action === 'stop' ? 'Saving and stopping this adventure.' : 'Adventure updated.')
    })
  })
  $('#create-form').onsubmit = event => { event.preventDefault()
    act(async () => {
      let romId = $('#rom-select').value
      const file = $('#rom-file').files[0]
      if (file) { $('#create-progress').textContent = 'Checking and adding your ROM…'
        const rom = await api('/api/v1/assets/rom', {method: 'POST', headers: {'Content-Type': 'application/octet-stream'}, body: file})
        romId = rom.id }
      if (!romId) throw new Error('Select an existing ROM or add a ROM file.')
      $('#create-progress').textContent = 'Creating your adventure…'
      const startNow = $('#start-created').checked
      const result = await write('/api/v1/adventures', {name: $('#new-name').value.trim(), rom_id: romId, starter: $('#starter').value})
      const game = result.adventure || result
      $('#create-dialog').close()
      $('#create-form').reset()
      if (startNow) await write(`/api/v1/adventures/${encodeURIComponent(game.id)}/start`)
      notice('Adventure created. Its status will update as it gets ready.')
    }) }
  $('#adventure-settings-form').onsubmit = event => { event.preventDefault()
    act(async () => {
      const game = adventures.find(item => item.id === $('#settings-id').value)
      const rewards = game && !running(game) ? {league_rewards: $('#settings-league-rewards').checked, mew_event: $('#settings-mew-event').checked} : {}
      await write(`/api/v1/adventures/${encodeURIComponent($('#settings-id').value)}`, {name: $('#settings-name').value.trim(),
        settings: {speed: Number($('#settings-speed').value), auto_start: $('#settings-autostart').checked, ...rewards}}, 'PATCH')
      $('#adventure-settings').close()
      notice('Adventure settings saved.')
    }) }
  $('#participants-form').onchange = () => { participantsDirty = true }
  $('#participants-form').onsubmit = event => { event.preventDefault()
    act(async () => {
      await write('/api/v1/interactions', {enabled: $('#trading-enabled').checked,
        participants: [...document.querySelectorAll('[name="participant"]:checked')].map(input => input.value)}, 'PATCH')
      participantsDirty = false
      notice('Trading group saved.')
    }) }
  for (const side of ['left', 'right']) $(`#trade-${side}`).onchange = () => loadPokemon(side)
  $('#trade-form').onsubmit = event => { event.preventDefault()
    act(async () => {
      if ($('#trade-left').value === $('#trade-right').value) throw new Error('Choose two different adventures.')
      await write('/api/v1/interactions/trades', {left_id: $('#trade-left').value, right_id: $('#trade-right').value,
        left_key: $('#trade-left-key').value, right_key: $('#trade-right-key').value})
      notice('Cable Club exchange requested. Follow its progress above.')
    }) }
  $('#settings-form').onsubmit = event => { event.preventDefault()
    act(async () => { await write('/api/v1/settings', {max_running: Number($('#max-running').value)}, 'PATCH')
      notice('Application settings saved.') }) }
  $('#create-backup').onclick = () => act(async () => {
    notice('Saving adventures and creating a backup…')
    await write('/api/v1/backups')
    await refreshBackups()
    notice('Backup ready to download.')
  })
  $('#import-form').onsubmit = event => { event.preventDefault()
    act(async () => { notice('Checking and importing the archive…')
      await api('/api/v1/imports', {method: 'POST', headers: {'Content-Type': 'application/zip'}, body: $('#import-file').files[0]})
      $('#import-form').reset()
      notice('Import complete. Open the Library to see the adventure.') }) }
  $('#quit').onclick = () => act(async () => {
    await write('/api/v1/shutdown')
    notice('PokeSim is saving and closing. You can close this tab.')
    $('#workspace').hidden = true
  })
  async function enter() {
    const session = await api('/api/v1/session')
    csrf = session.csrf_token || ''
    owner = session.role === 'owner'
    $('#signin').hidden = true
    $('#workspace').hidden = false
    document.querySelectorAll('[data-view]').forEach(section => { section.hidden = section.dataset.view !== page })
    document.querySelector(`[data-nav="${page}"]`)?.setAttribute('aria-current', 'page')
    if (page === 'settings' && owner) {
      const settings = await api('/api/v1/settings')
      $('#max-running').value = settings.max_running
      await refreshBackups()
    }
    permissions()
    await refresh()
  }
  $('#signin-form').onsubmit = event => { event.preventDefault()
    act(async () => {
      await api('/api/v1/session', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({token: $('#owner-key').value})})
      $('#owner-key').value = ''
      await enter()
    }) }
  async function boot() {
    try {
      const fragment = new URLSearchParams(location.hash.slice(1))
      const token = fragment.get('token')
      if (token) {
        history.replaceState(null, '', location.pathname + location.search)
        await api('/api/v1/session', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({token})})
      }
      await enter()
    } catch (error) { $('#signin').hidden = false
      $('#workspace').hidden = true
      $('#connection').textContent = 'Sign in'
      if (location.hash || error.message.includes('failed')) notice(error.message, true) }
  }
  boot()
  setInterval(() => { if (!document.hidden && !busy) refresh() }, 3000)
})()
