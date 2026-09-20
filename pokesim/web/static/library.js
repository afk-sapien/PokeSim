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
  let connecting = false
  let closing = false
  let sessionPending = null
  let appSettingsDirty = false
  let notifyDirty = false
  let notifyAdventuresSignature = ''
  // Checkbox choices on the Notifications page, kept apart from the markup that shows them.
  const notify = {categories: {}, adventures: {}}
  const cardSignatures = new Map()
  let stoppedSignature = ''
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
  async function initializeSession() {
    if (!sessionPending) sessionPending = api('/api/v1/session').then(session => {
      csrf = session.csrf_token || ''
      owner = session.role === 'owner'
      permissions()
    }).finally(() => { sessionPending = null })
    return sessionPending
  }
  async function api(path, options = {}, retried = false) {
    const response = await fetch(path, {cache: 'no-store', credentials: 'same-origin', ...options,
      headers: {...options.headers, ...(options.method && options.method !== 'GET' ? {'X-PokeSim-CSRF': csrf} : {})}})
    let data
    try { data = await response.json() } catch (_) { data = {} }
    if (!response.ok) {
      const detail = data.detail || data.error || `Request failed (${response.status})`
      const expired = response.status === 401 || (response.status === 403 && (data.code === 'csrf_expired' || detail === 'Reload this page before making changes'))
      if (expired && path !== '/api/v1/session' && !retried) {
        await initializeSession()
        return api(path, options, true)
      }
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
    const wins = summary.league_rewards?.wins
    const league = Number.isInteger(wins) ? `<p class="section-note">${wins.toLocaleString()} League ${wins === 1 ? 'win' : 'wins'}</p>` : ''
    const provenance = game.provenance?.trading_blocked ? `<p class="card-error">${esc(game.provenance.reason || 'Legacy trade history needs reconciliation before trading.')}</p>` : ''
    const stalled = active && summary.stalled ? '<p class="card-error">Stuck? No progress for a while. Open the adventure to see its objective.</p>' : ''
    const failure = game.error ? `<p class="card-error">${esc(typeof game.error === 'string' ? game.error : JSON.stringify(game.error))}</p>` : ''
    return `<article class="adventure-card ${esc(game.version)}" data-adventure-id="${esc(game.id)}">${active ? `<div class="card-screen"><img src="${gameUrl(game.id)}frame.jpg" alt="${esc(game.name)} game screen" loading="lazy" width="160" height="144"></div>` : ''}<div class="card-banner"><span class="eyebrow">POKÉMON ${esc(game.version).toUpperCase()}</span><span class="state-pill">${esc(game.archived ? 'archived' : game.state || 'stopped')}</span></div><div class="card-body"><h2>${esc(game.name)}</h2><p>${esc(activity)}</p>${league}${stalled}${failure}${provenance}${game.archived ? '<p class="section-note">Archived adventures keep all their saves.</p>' : ''}<div class="card-actions"><a class="primary-button" href="${gameUrl(game.id)}">${active ? 'Open adventure' : 'View adventure'} ↗</a>${game.archived ? `<button data-action="restore" data-id="${esc(game.id)}" data-owner>Restore</button>` : `<button data-action="${active ? 'stop' : 'start'}" data-id="${esc(game.id)}" data-owner ${transitional ? 'disabled data-blocked' : ''}>${transitional ? esc(game.state) : active ? 'Save and stop' : 'Start'}</button><button data-action="settings" data-id="${esc(game.id)}" data-owner>Settings</button>${!active && !transitional ? `<button data-action="archive" data-id="${esc(game.id)}" data-owner>Archive</button>` : ''}`}</div></div></article>`
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
  function tradePhase(trade) {
    if (trade.decision === 'ABORT' || trade.error || ['recovering', 'aborting', 'aborted'].includes(trade.phase)) {
      return trade.decision === 'COMMIT' ? 'Finishing the exchange safely' : 'Getting ready to try again'
    }
    const labels = {
      proposed: 'Getting ready', preparing: 'Heading to the Cable Club',
      connecting: 'Connecting the games', trading: 'Exchanging Pokémon',
      saving: 'Saving progress', leaving: 'Leaving the Cable Club',
      resuming: 'Returning to the adventure', returning: 'Returning to the adventure',
      verifying: 'Checking both saves', staging: 'Checking both saves',
      committed: 'Saving the exchange', applying: 'Saving the exchange',
      releasing: 'Returning to the adventure', completed: 'Trade completed'
    }
    return labels[trade.phase || trade.state || trade.status] || 'Getting ready'
  }
  function tradePartner(id, mon, completed, failed) {
    const game = adventures.find(item => item.id === id)
    const title = game ? `<a href="${gameUrl(id)}trading">${esc(game.name)} ↗</a>` : 'Adventure unavailable'
    const label = completed ? 'Received' : failed ? 'Planned to receive' : 'Receiving'
    const dex = Number.isInteger(mon?.dex) && mon.dex >= 1 && mon.dex <= 151 ? mon.dex : null
    const sprite = dex && game ? `<img src="${gameUrl(id)}sprites/${dex}.png" alt="" width="64" height="64" loading="lazy">`
      : '<span class="exchange-placeholder" aria-hidden="true">?</span>'
    const name = mon?.name ? esc(mon.name) : 'Pokémon details unavailable'
    const nickname = mon?.nickname && mon.nickname.toLowerCase() !== mon.name?.toLowerCase()
      ? `<p class="exchange-nickname">“${esc(mon.nickname)}”</p>` : ''
    const level = Number.isInteger(mon?.level) && mon.level >= 1 && mon.level <= 100 ? ` · Lv. ${mon.level}` : ''
    const evolution = completed && mon?.evolved_from?.name
      ? `<p class="exchange-evolution">✦ ${esc(mon.evolved_from.name)} → ${name}</p>` : ''
    return `<section class="exchange-partner"><h3>${title}</h3><div class="exchange-pokemon">${sprite}<div><p class="eyebrow">${label}${level}</p><strong>${name}</strong>${nickname}${evolution}</div></div></section>`
  }
  function describeTrade(trade, completed = false) {
    const leftId = trade.left_id || trade.participants?.[0] || trade.plan?.left_id
    const rightId = trade.right_id || trade.participants?.[1] || trade.plan?.right_id
    const left = adventures.find(game => game.id === leftId)?.name || 'First adventure'
    const right = adventures.find(game => game.id === rightId)?.name || 'Second adventure'
    const failed = trade.phase === 'aborted'
    const time = (completed || failed) && trade.updated_at ? `<p class="section-note">${esc(dateLabel(trade.updated_at))}</p>` : ''
    const reason = failed ? `<p>${esc(trade.failure_reason || 'The exchange could not finish safely.')}</p>` : ''
    const label = failed ? 'Trade did not complete' : completed ? 'Trade completed' : tradePhase(trade)
    const display = trade.display || {}
    const pair = failed ? `<strong>${esc(left)} ↔ ${esc(right)}</strong>`
      : `<div class="exchange-pair">${tradePartner(leftId, display[leftId]?.received, completed, failed)}<span class="exchange-arrow" aria-hidden="true">⇄</span>${tradePartner(rightId, display[rightId]?.received, completed, failed)}</div>`
    return `<article class="exchange${completed ? ' exchange-completed' : ''}"><header class="exchange-heading"><span class="state-pill">${esc(label)}</span>${time}</header>${pair}${reason}</article>`
  }
  async function refreshTrades() {
    const data = await api('/api/v1/interactions')
    const count = new Set((data.participants || []).map(item => typeof item === 'string' ? item : item.id)).size
    $('#trading-status').textContent = data.attention?.message || (count >= 2 ? `${count} adventures can trade automatically.`
      : 'Trades begin when two eligible adventures are running and have a useful exchange.')
    const active = (Array.isArray(data.active) ? data.active : data.active ? [data.active] : [])
      .filter(trade => !['completed', 'aborted'].includes(trade.phase))
    $('#trade-active-section').hidden = !active.length
    const retrying = /retry|attention|recover/i.test(data.message || '')
    $('#trade-active').innerHTML = active.length ? active.map(trade => describeTrade(trade)).join('')
      : `<p>${data.attention ? 'No exchange is in progress. Automatic trading will try again.' : retrying ? 'Trading is waiting to try again. Your adventures will reconnect automatically.' : 'Waiting for a useful exchange. Your adventures keep playing in the meantime.'}</p>`
    const completed = (data.history || []).filter(trade => trade.phase === 'completed' && trade.decision !== 'ABORT').slice(0, 20)
    $('#trade-history-count').textContent = `${completed.length}${completed.length === 20 ? '+' : ''} recent ${completed.length === 1 ? 'exchange' : 'exchanges'}`
    $('#trade-history').innerHTML = completed.length ? completed.map(trade => describeTrade(trade, true)).join('') : '<p>No completed trades yet.</p>'
    const failures = data.recent_failures || []
    $('#trade-failures-section').hidden = !failures.length
    $('#trade-failures').innerHTML = failures.map(trade => describeTrade(trade)).join('')
  }
  async function refreshBackups() {
    const data = await api('/api/v1/backups')
    const backups = Array.isArray(data) ? data : data.backups || []
    $('#backups').innerHTML = backups.length ? backups.map(backup => `<p><a class="text-link" href="/api/v1/backups/${encodeURIComponent(backup.id)}/download">Download backup ${esc(dateLabel(backup.created_at) || backup.id)} ↗</a></p>`).join('') : '<p class="section-note">No backups yet.</p>'
  }
  function randomTopic() {
    const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
    return 'pokesim-' + Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => alphabet[byte % alphabet.length]).join('')
  }
  function notifyChoice(kind, key, label, detail, checked) {
    return `<label class="inline-label"><input type="checkbox" data-notify="${kind}" data-key="${esc(key)}" ${checked ? 'checked' : ''} data-owner><span>${esc(label)}${detail ? `<small>${esc(detail)}</small>` : ''}</span></label>`
  }
  function renderSubscribe() {
    const server = $('#notify-server').value.trim().replace(/\/+$/, '')
    const topic = $('#notify-topic').value.trim()
    const valid = /^https?:\/\/[^\s/]+/.test(server) && /^[A-Za-z0-9_-]{1,64}$/.test(topic)
    $('#notify-subscribe').innerHTML = valid ? `<a class="text-link" href="${esc(`${server}/${topic}`)}" target="_blank" rel="noreferrer">${esc(`${server}/${topic}`)} ↗</a>`
      : 'Choose a topic to see its address.'
  }
  function renderNotifyAdventures() {
    // New adventures notify until they are turned off, so a missing choice counts as on.
    const markup = adventures.filter(game => !game.archived).map(game => notifyChoice('adventures', game.id, game.name, '', notify.adventures[game.id] !== false)).join('')
      || '<p class="section-note">Adventures appear here once you create them.</p>'
    if (markup === notifyAdventuresSignature) return
    notifyAdventuresSignature = markup
    $('#notify-adventures').innerHTML = markup
    permissions()
  }
  function renderNotifications(data) {
    $('#notify-enabled').checked = Boolean(data.enabled)
    $('#notify-server').value = data.server || 'https://ntfy.sh'
    $('#notify-topic').value = data.topic || ''
    $('#notify-priority').value = String(Math.max(2, data.min_priority ?? 2))
    $('#notify-token').value = ''
    $('#notify-token').placeholder = data.token_set ? 'A token is saved. Leave blank to keep it.' : ''
    $('#notify-clear-token').checked = false
    $('#notify-clear-row').hidden = !data.token_set
    $('#notify-token-note').textContent = data.source === 'environment'
      ? 'These values come from the NTFY_* environment settings. Saving here replaces them.'
      : 'Only needed for a protected topic or a private server.'
    const categories = data.categories || []
    notify.categories = Object.fromEntries(categories.map(row => [row.key, Boolean(row.enabled)]))
    notify.adventures = Object.fromEntries((data.adventures || []).map(row => [row.id, Boolean(row.enabled)]))
    $('#notify-categories').innerHTML = categories.map(row => notifyChoice('categories', row.key, row.label, row.detail, row.enabled)).join('')
    notifyAdventuresSignature = ''
    renderSubscribe()
    renderNotifyAdventures()
    notifyDirty = false
    permissions()
  }
  function notifyDestination() {
    const token = $('#notify-clear-token').checked ? {token: ''} : $('#notify-token').value ? {token: $('#notify-token').value} : {}
    return {server: $('#notify-server').value.trim(), topic: $('#notify-topic').value.trim(), ...token}
  }
  async function refresh() {
    if (refreshing || $('#workspace').hidden) return
    refreshing = true
    try {
      const data = await api('/api/v1/adventures')
      adventures = data.adventures || []
      renderAdventures()
      if (page === 'notifications') renderNotifyAdventures()
      if (page === 'trading') await refreshTrades()
      $('#connection').textContent = 'Connected'
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
    const button = event.target.closest('[data-action]')
    if (!button || button.disabled) return
    const game = adventures.find(item => item.id === button.dataset.id)
    if (!game) return
    if (button.dataset.action === 'settings') {
      $('#settings-id').value = game.id
      $('#settings-name').value = game.name
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
        settings: {auto_start: $('#settings-autostart').checked, ...rewards}}, 'PATCH')
      $('#adventure-settings').close()
      notice('Adventure settings saved.')
    }) }
  $('#settings-form').oninput = () => { appSettingsDirty = true }
  $('#settings-form').onchange = () => { appSettingsDirty = true }
  $('#settings-form').onsubmit = event => { event.preventDefault()
    act(async () => { const result = await write('/api/v1/settings', {max_running: Number($('#max-running').value), speed: Number($('#simulation-speed').value)}, 'PATCH')
      notice(result.pace_pending?.length ? 'Settings saved. The pace will apply to reconnecting adventures automatically.' : 'Application settings saved.') }) }
  $('#notify-form').oninput = () => { notifyDirty = true
    renderSubscribe() }
  $('#notify-form').onchange = event => { notifyDirty = true
    const input = event?.target
    if (input?.dataset?.notify) notify[input.dataset.notify][input.dataset.key] = Boolean(input.checked) }
  $('#notify-generate').onclick = () => { $('#notify-topic').value = randomTopic()
    notifyDirty = true
    renderSubscribe() }
  $('#notify-form').onsubmit = event => { event.preventDefault()
    act(async () => {
      const known = new Set(adventures.map(game => game.id))
      const result = await write('/api/v1/notifications', {enabled: $('#notify-enabled').checked, ...notifyDestination(),
        min_priority: Number($('#notify-priority').value), categories: notify.categories,
        adventures: Object.fromEntries(Object.entries(notify.adventures).filter(([id]) => known.has(id)))}, 'PATCH')
      renderNotifications(result)
      $('#notify-result').textContent = ''
      notice(result.pending?.length ? 'Notifications saved. Reconnecting adventures will pick them up automatically.' : 'Notifications saved. They apply to running adventures right away.')
    }) }
  $('#notify-test').onclick = () => act(async () => {
    $('#notify-result').textContent = 'Sending…'
    try {
      const result = await write('/api/v1/notifications/test', notifyDestination())
      $('#notify-result').textContent = result.ok ? 'ntfy accepted the test. Check your phone.' : `ntfy did not accept it: ${result.error}`
    } catch (error) { $('#notify-result').textContent = ''
      throw error }
  })
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
    closing = true
    notice('PokeSim is saving and closing. You can close this tab.')
    $('#workspace').hidden = true
  })
  async function enter() {
    await initializeSession()
    $('#workspace').hidden = false
    document.querySelectorAll('[data-view]').forEach(section => { section.hidden = section.dataset.view !== page })
    document.querySelector(`[data-nav="${page}"]`)?.setAttribute('aria-current', 'page')
    if (page === 'settings' && owner) {
      const settings = await api('/api/v1/settings')
      if (!appSettingsDirty) {
        $('#max-running').value = settings.max_running
        $('#simulation-speed').value = String(settings.speed ?? 1)
      }
      await refreshBackups()
    }
    if (page === 'notifications' && owner && !notifyDirty) renderNotifications(await api('/api/v1/notifications'))
    permissions()
    await refresh()
  }
  async function boot() {
    if (connecting || closing) return
    connecting = true
    try {
      notice('')
      await enter()
    } catch (error) { $('#workspace').hidden = true
      $('#connection').textContent = 'Reconnecting'
      notice(error.message, true) }
    finally { connecting = false }
  }
  boot()
  setInterval(() => {
    if (!document.hidden && !busy && !closing) {
      if ($('#workspace').hidden) boot()
      else refresh()
    }
  }, 3000)
})()
