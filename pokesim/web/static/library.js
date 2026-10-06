(() => {
  const $ = selector => document.querySelector(selector)
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp', '<': '&lt', '>': '&gt', '"': '&quot', "'": '&#39'}[char] + String.fromCharCode(59)))
  const page = document.body.dataset.page
  const connection = (label, offline) => {
    $('#status').textContent = label
    $('#connection').classList.toggle('is-offline', offline)
  }
  const currentId = document.body.dataset.adventure
  // Trade portraits are cartridge art (56px and under) or 96px installed packs.
  // Scale each by the largest whole number that fits its plate so pixels stay square.
  document.addEventListener('load', event => {
    const img = event.target
    const frame = img?.tagName === 'IMG' ? img.closest('.plate') : null
    if (!frame || !img.naturalWidth) return
    const scale = Math.max(1, Math.floor(frame.clientWidth / Math.max(img.naturalWidth, img.naturalHeight)))
    img.style.width = `${img.naturalWidth * scale}px`
    img.style.height = `${img.naturalHeight * scale}px`
  }, true)
  let csrf = ''
  let owner = false
  let adventures = []
  let busy = false
  let refreshing = false
  let connecting = false
  let closing = false
  let sessionPending = null
  let notifyDirty = false
  let notifyData = {integrations: [], categories: [], integration_defaults: {}}
  let notifyIntegration = null
  let notifySecretChanged = false
  let notifySecretCleared = false
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
    if (notifyIntegration) renderNotifyProvider()
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
    const {download, ...fetchOptions} = options
    const response = await fetch(path, {cache: 'no-store', credentials: 'same-origin', ...fetchOptions,
      headers: {...options.headers, ...(options.method && options.method !== 'GET' ? {'X-PokeSim-CSRF': csrf} : {})}})
    if (response.ok && download) return response
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
  async function downloadSave(game) {
    notice(`Preparing ${game.name}'s save…`)
    const response = await api(`${gameUrl(game.id)}api/export-save`, {method: 'POST', download: true})
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1] || 'pokesim.sav'
    document.body.append(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 60000)
    notice('Save downloaded. Load it with the matching game ROM in your emulator.')
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
  function resourceLabels(game) {
    const usage = game.resources
    const off = !running(game) && ['stopped', 'archived', 'failed'].includes(game.state)
    return {
      cpu: Number.isFinite(usage?.cpu_percent) ? `${usage.cpu_percent.toFixed(1)}%` : off ? 'Not running' : usage?.cpu_percent === null ? 'Measuring…' : 'Unavailable',
      speed: off ? 'Not running' : Number.isFinite(usage?.observed_speed) ? `${usage.observed_speed.toFixed(1)}×` : usage?.speed_status === 'measuring' ? 'Measuring…' : 'Unavailable',
      memory: Number.isFinite(usage?.memory_bytes) ? `${Math.round(usage.memory_bytes / 1048576).toLocaleString()} MiB` : off ? 'Not running' : 'Unavailable'
    }
  }
  function updateResources(container, game) {
    if (!container) return
    for (const [key, value] of Object.entries(resourceLabels(game))) {
      const node = container.querySelector(`[data-usage="${key}"]`)
      if (node) {
        if (node.textContent !== value) node.textContent = value
        node.classList.toggle('is-pending', ['Measuring…', 'Unavailable', 'Not running'].includes(value))
      }
    }
  }
  function card(game) {
    const active = running(game)
    const transitional = ['starting', 'stopping', 'preparing', 'setting_up', 'recovering'].includes(game.state)
    const summary = game.summary || {}
    const activity = summary.message || summary.activity || summary.game?.location || summary.map || (active ? 'Adventure in progress' : 'Your saves are waiting here')
    const wins = summary.league_rewards?.wins
    const league = Number.isInteger(wins) ? `<p class="card-stat micro">${wins.toLocaleString()} League ${wins === 1 ? 'win' : 'wins'}</p>` : ''
    const recent = (summary.recent_activity || []).slice(0, 3)
    const log = recent.length ? `<section class="card-log" aria-label="Recent activity"><h3 class="micro">Recent activity</h3><ol>${recent.map(row => `<li><time datetime="${esc(new Date(row.time * 1000).toISOString())}">${esc(new Date(row.time * 1000).toLocaleTimeString([], {hour: '2-digit', minute: '2-digit'}))}</time><span>${esc(row.message)}</span></li>`).join('')}</ol></section>` : ''
    const resources = '<dl class="card-resources" aria-label="Resource usage" aria-live="off"><div><dt title="100% CPU means one fully used processor core">CPU (1 core)</dt><dd data-usage="cpu">Measuring…</dd></div><div><dt title="Resident memory for this simulation, excluding the shared library process">Memory</dt><dd data-usage="memory">Measuring…</dd></div><div><dt title="Simulated seconds per real second, measured over the latest health-check interval">Actual speed</dt><dd data-usage="speed">Measuring…</dd></div></dl>'
    const provenance = game.provenance?.trading_blocked ? `<p class="card-error">${esc(game.provenance.reason || 'Legacy trade history needs reconciliation before trading.')}</p>` : ''
    const stalled = active && summary.stalled ? '<p class="card-error">Stuck? No progress for a while. Open the adventure to see its objective.</p>' : ''
    const failure = game.error ? `<p class="card-error">${esc(typeof game.error === 'string' ? game.error : JSON.stringify(game.error))}</p>` : ''
    const lamp = game.archived ? '' : failure || game.state === 'error' ? 'crit' : transitional || (active && summary.stalled) ? 'warn' : active ? 'ok' : ''
    const download = `<button class="key" data-action="download-save" data-id="${esc(game.id)}" data-owner ${!active ? 'disabled data-blocked title="Start this adventure to download its save"' : 'title="Download a .sav file for another emulator"'}>Download Save</button>`
    const screen = active
      ? `<div class="card-screen"><img src="${gameUrl(game.id)}frame.jpg" alt="${esc(game.name)} game screen" loading="lazy" width="160" height="144"></div>`
      : `<div class="card-screen card-screen--off"><span class="micro">${game.archived ? 'Archived' : 'Saved · not running'}</span></div>`
    return `<article class="adventure-card ${esc(game.version)}" data-adventure-id="${esc(game.id)}"><header class="card-banner"><span class="micro">POKÉMON ${esc(game.version).toUpperCase()}</span><span class="tag state-pill"><i class="lamp"${lamp ? ` data-on="${lamp}"` : ''} aria-hidden="true"></i>${esc(game.archived ? 'archived' : game.state || 'stopped')}</span></header>${screen}<div class="card-body"><h2>${esc(game.name)}</h2><p class="card-activity">${esc(activity)}</p>${league}${resources}${log}${stalled}${failure}${provenance}${game.archived ? '<p class="card-note">Archived adventures keep all their saves.</p>' : ''}</div><div class="card-actions"><a class="key key--primary" href="${gameUrl(game.id)}">${active ? 'Open adventure' : 'View adventure'}</a>${game.archived ? `<button class="key" data-action="restore" data-id="${esc(game.id)}" data-owner>Restore</button>` : `<button class="key" data-action="${active ? 'stop' : 'start'}" data-id="${esc(game.id)}" data-owner ${transitional ? 'disabled data-blocked' : ''}>${transitional ? esc(game.state) : active ? 'Save and stop' : 'Start'}</button><button class="key" data-action="settings" data-id="${esc(game.id)}" data-owner>Settings</button>${!active && !transitional ? `<button class="key" data-action="archive" data-id="${esc(game.id)}" data-owner>Archive</button>` : ''}`}${download}</div></article>`
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
      if (cardSignatures.get(game.id) === markup) {
        updateResources(container.querySelector(`[data-adventure-id="${game.id}"]`), game)
        continue
      }
      const previous = container.querySelector(`[data-adventure-id="${game.id}"]`)
      if (previous) previous.outerHTML = markup
      else container.insertAdjacentHTML('beforeend', markup)
      cardSignatures.set(game.id, markup)
      updateResources(container.querySelector(`[data-adventure-id="${game.id}"]`), game)
    }
    $('#empty').hidden = Boolean(visible.length)
    const kept = adventures.filter(game => !game.archived).length
    $('#running-summary').textContent = `${adventures.filter(running).length} running · ${kept} ${kept === 1 ? 'adventure' : 'adventures'}`
    if (page === 'stopped') {
      const game = adventures.find(item => item.id === currentId)
      $('#stopped-title').textContent = game?.name || 'Adventure unavailable'
      const stoppedMarkup = game ? card(game) : '<p>This adventure is not in the current library.</p>'
      if (stoppedSignature !== stoppedMarkup) { $('#stopped-card').innerHTML = stoppedMarkup
        stoppedSignature = stoppedMarkup }
      if (game) updateResources($('#stopped-card'), game)
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
    const dex = Number.isInteger(mon?.dex) && mon.dex >= 1 && mon.dex <= 251 ? mon.dex : null
    const sprite = dex && game ? `<div class="plate plate--trade"><img src="${gameUrl(id)}sprites/${dex}.png?v=rom-portraits-1" alt="" loading="lazy"></div>`
      : '<div class="plate plate--trade exchange-placeholder" aria-hidden="true"><span class="plate-num">?</span></div>'
    const name = mon?.name ? esc(mon.name) : 'Pokémon details unavailable'
    const nickname = mon?.nickname && mon.nickname.toLowerCase() !== mon.name?.toLowerCase()
      ? `<p class="exchange-nickname">“${esc(mon.nickname)}”</p>` : ''
    const level = Number.isInteger(mon?.level) && mon.level >= 1 && mon.level <= 100 ? ` · Lv. ${mon.level}` : ''
    const evolution = completed && mon?.evolved_from?.name
      ? `<p class="exchange-evolution">✦ ${esc(mon.evolved_from.name)} → ${name}</p>` : ''
    return `<section class="exchange-partner"><h3>${title}</h3><div class="exchange-pokemon">${sprite}<div class="exchange-text"><p class="micro">${label}${level}</p><strong>${name}</strong>${nickname}${evolution}</div></div></section>`
  }
  function describeTrade(trade, completed = false) {
    const leftId = trade.left_id || trade.participants?.[0] || trade.plan?.left_id
    const rightId = trade.right_id || trade.participants?.[1] || trade.plan?.right_id
    const left = adventures.find(game => game.id === leftId)?.name || 'First adventure'
    const right = adventures.find(game => game.id === rightId)?.name || 'Second adventure'
    const failed = trade.phase === 'aborted'
    const time = (completed || failed) && trade.updated_at ? `<p class="micro">${esc(dateLabel(trade.updated_at))}</p>` : ''
    const reason = failed ? `<p class="exchange-reason">${esc(trade.failure_reason || 'The exchange could not finish safely.')}</p>` : ''
    const label = failed ? 'Trade did not complete' : completed ? 'Trade completed' : tradePhase(trade)
    const display = trade.display || {}
    const pair = failed ? `<strong class="exchange-failed">${esc(left)} ↔ ${esc(right)}</strong>`
      : `<div class="exchange-pair">${tradePartner(leftId, display[leftId]?.received, completed, failed)}<span class="exchange-arrow" aria-hidden="true">⇄</span>${tradePartner(rightId, display[rightId]?.received, completed, failed)}</div>`
    return `<article class="exchange${completed ? ' exchange-completed' : ''}"><header class="exchange-heading"><span class="tag state-pill${failed ? ' tag--crit' : ''}">${esc(label)}</span>${time}</header>${pair}${reason}</article>`
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
  let savedBackups = []
  let backupPage = 0
  let backupToDelete = null
  const backupPageSize = 5
  function renderBackups() {
    backupPage = Math.max(0, Math.min(backupPage, Math.ceil(savedBackups.length / backupPageSize) - 1))
    const start = backupPage * backupPageSize
    const visible = savedBackups.slice(start, start + backupPageSize)
    $('#backups').innerHTML = visible.length ? visible.map(backup => `<div class="backup-row"><div><strong>${esc(dateLabel(backup.created_at))}</strong><p class="note">${(backup.size_bytes / 1048576).toFixed(1)} MiB</p></div><div class="backup-row-actions"><a class="key" href="/api/v1/backups/${encodeURIComponent(backup.id)}/download" download>Download</a><button type="button" class="key" data-load-backup="${esc(backup.id)}" data-owner>Load</button><button type="button" class="key key--danger" data-delete-backup="${esc(backup.id)}" data-owner>Delete</button></div></div>`).join('') : '<p class="section-note">No backups yet. Create one here or load a backup ZIP.</p>'
    $('#backup-summary').textContent = savedBackups.length ? `${savedBackups.length} ${savedBackups.length === 1 ? 'backup' : 'backups'} · ${(savedBackups.reduce((total, backup) => total + backup.size_bytes, 0) / 1048576).toFixed(1)} MiB stored` : ''
    $('#backup-pagination').hidden = savedBackups.length <= backupPageSize
    $('#backup-page-label').textContent = `${start + 1}–${start + visible.length} of ${savedBackups.length}`
    $('#backup-previous').disabled = backupPage === 0
    $('#backup-next').disabled = start + backupPageSize >= savedBackups.length
    $('#backups').querySelectorAll('[data-load-backup]').forEach(button => { button.onclick = () => act(() => openBackup(button.dataset.loadBackup)) })
    $('#backups').querySelectorAll('[data-delete-backup]').forEach(button => { button.onclick = () => {
      backupToDelete = savedBackups.find(backup => backup.id === button.dataset.deleteBackup)
      $('#backup-delete-description').textContent = `Delete the backup from ${dateLabel(backupToDelete.created_at)} (${(backupToDelete.size_bytes / 1048576).toFixed(1)} MiB)?`
      $('#backup-delete-dialog .dialog-feedback').textContent = ''
      $('#backup-delete-dialog').showModal()
      $('#backup-delete-cancel').focus()
    } })
    permissions()
  }
  async function refreshBackups() {
    const data = await api('/api/v1/backups')
    savedBackups = Array.isArray(data) ? data : data.backups || []
    renderBackups()
  }
  $('#backup-previous').onclick = () => { backupPage -= 1
    renderBackups() }
  $('#backup-next').onclick = () => { backupPage += 1
    renderBackups() }
  $('#backup-delete-form').onsubmit = event => {
    event.preventDefault()
    act(async () => {
      await write(`/api/v1/backups/${encodeURIComponent(backupToDelete.id)}`, {}, 'DELETE')
      $('#backup-delete-dialog').close()
      backupToDelete = null
      await refreshBackups()
      notice('Backup deleted. Your adventures are unchanged.')
      $('#create-backup').focus()
    })
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
    if (!notifyIntegration) return
    // New adventures notify until they are turned off, so a missing choice counts as on.
    const markup = adventures.filter(game => !game.archived).map(game => notifyChoice('adventures', game.id, game.name, '', notify.adventures[game.id] ?? $('#notify-include-new').checked)).join('')
      || '<p class="section-note">Adventures appear here once you create them.</p>'
    if (markup === notifyAdventuresSignature) return
    notifyAdventuresSignature = markup
    $('#notify-adventures').innerHTML = markup
    permissions()
  }
  const providerLabel = provider => ({ntfy: 'ntfy', discord: 'Discord', telegram: 'Telegram'}[provider] || provider)
  const integrationUrl = id => '/api/v1/notifications/integrations' + (id ? '/' + encodeURIComponent(id) : '')
  function renderNotifications(data) {
    notifyData = data
    $('#notify-enabled').checked = Boolean(data.enabled)
    $('#notify-delivery-state').textContent = data.enabled ? 'Delivery is on for enabled integrations.' : 'Delivery is paused for all integrations.'
    $('#notify-integrations').innerHTML = (data.integrations || []).map(row => {
      const categories = Object.values(row.categories || {}).filter(Boolean).length
      const games = Object.values(row.adventures || {}).filter(Boolean).length
      const scope = row.include_new_adventures ? `${games} adventure${games === 1 ? '' : 's'}, plus new adventures` : `${games} selected adventure${games === 1 ? '' : 's'}`
      return `<article class="panel integration-card"><div><p class="micro">${esc(providerLabel(row.provider))} · ${row.enabled ? 'Enabled' : 'Disabled'}</p><h2 class="legend legend--ink">${esc(row.name)}</h2><p class="note">${categories} event type${categories === 1 ? '' : 's'} · ${esc(scope)}</p></div><div class="integration-card-actions"><button type="button" class="key" data-integration-action="edit" data-id="${esc(row.id)}" data-owner>Edit</button><button type="button" class="key" data-integration-action="test" data-id="${esc(row.id)}" data-owner>Test</button><button type="button" class="key" data-integration-action="toggle" data-id="${esc(row.id)}" data-owner>${row.enabled ? 'Disable' : 'Enable'}</button></div><p class="form-result" data-integration-result="${esc(row.id)}" role="status"></p></article>`
    }).join('') || '<div class="panel empty-state"><h2 class="legend legend--ink">No integrations yet</h2><p>Add a Discord channel, Telegram chat or ntfy topic. You can add several of each.</p></div>'
    permissions()
  }
  function renderNotifyProvider() {
    const provider = $('#notify-provider').value
    $('#notify-provider').disabled = Boolean(notifyIntegration?.id) || !owner || busy
    for (const name of ['ntfy', 'discord', 'telegram']) {
      const panel = $('#notify-' + name)
      panel.hidden = name !== provider
      for (const input of panel.querySelectorAll('input, button')) input.disabled = name !== provider || !owner || busy
    }
    const field = {ntfy: 'notify-token', discord: 'notify-discord-webhook', telegram: 'notify-telegram-token'}[provider]
    const saved = notifyIntegration?.[{ntfy: 'token_set', discord: 'discord_webhook_set', telegram: 'telegram_token_set'}[provider]]
    const kept = saved && !notifySecretChanged && !notifySecretCleared
    $('#' + field).closest('label').hidden = Boolean(kept)
    $('#notify-change-secret').hidden = !kept
    $('#notify-remove-token').hidden = provider !== 'ntfy' || !kept
    $('#notify-credential-note').textContent = kept ? 'Credential saved. Replacing it is optional.'
      : notifySecretCleared ? 'The saved access token will be removed when you save.' : ''
    $('#notify-change-secret').textContent = provider === 'discord' ? 'Replace webhook URL' : 'Replace token'
  }
  function openIntegration(row = null) {
    notifyIntegration = row || {provider: 'discord', name: '', enabled: true, include_new_adventures: true,
      categories: notifyData.integration_defaults || {}, adventures: {}}
    notifyDirty = true
    notifySecretChanged = false
    notifySecretCleared = false
    $('#integration-heading').textContent = row ? 'Edit integration' : 'Add integration'
    $('#notify-name').value = notifyIntegration.name
    $('#notify-provider').value = notifyIntegration.provider
    $('#notify-integration-enabled').checked = notifyIntegration.enabled
    $('#notify-include-new').checked = notifyIntegration.include_new_adventures
    $('#notify-server').value = notifyIntegration.server || 'https://ntfy.sh'
    $('#notify-topic').value = notifyIntegration.topic || ''
    $('#notify-telegram-chat').value = notifyIntegration.telegram_chat_id || ''
    for (const id of ['notify-token', 'notify-discord-webhook', 'notify-telegram-token']) $('#' + id).value = ''
    $('#notify-priority').value = String(notifyIntegration.min_priority ?? 2)
    notify.categories = {...notifyIntegration.categories}
    notify.adventures = {...notifyIntegration.adventures}
    $('#notify-categories').innerHTML = (notifyData.categories || []).map(row => notifyChoice('categories', row.key, row.label, row.detail, notify.categories[row.key])).join('')
    notifyAdventuresSignature = ''
    renderNotifyAdventures()
    renderSubscribe()
    $('#notify-delete').hidden = !row
    $('#notify-delete-confirm').hidden = true
    $('#notify-result').textContent = ''
    permissions()
    $('#integration-dialog').showModal()
  }
  function notifyDestination() {
    const provider = $('#notify-provider').value
    if (provider === 'discord') {
      const value = $('#notify-discord-webhook').value.trim()
      return {provider, ...(value || !notifyIntegration?.id ? {discord_webhook: value} : {})}
    }
    if (provider === 'telegram') {
      const value = $('#notify-telegram-token').value.trim()
      return {provider, telegram_chat_id: $('#notify-telegram-chat').value.trim(),
        ...(value || !notifyIntegration?.id ? {telegram_token: value} : {})}
    }
    const token = notifySecretCleared || (!notifyIntegration?.id && !$('#notify-token').value) ? {token: ''} : $('#notify-token').value ? {token: $('#notify-token').value} : {}
    return {provider, server: $('#notify-server').value.trim(), topic: $('#notify-topic').value.trim(), ...token}
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
      connection('Connected', false)
    } catch (error) { connection('Reconnecting…', true)
      notice(error.message, true) }
    finally { refreshing = false }
  }
  function randomizeAdventure() {
    const starts = ['Sleepy', 'Cozy', 'Chaotic', 'Lucky', 'Wobbly', 'Daring', 'Mighty', 'Tiny',
      'Sneaky', 'Sunny', 'Moonlit', 'Wandering', 'Bouncy', 'Curious', 'Mischievous', 'Snacktime',
      'Weekend', 'Midnight', 'Daydream', 'Unexpected']
    const endings = ['Safari', 'Expedition', 'Detour', 'Victory Lap', 'Gym Tour', 'Road Trip',
      'Adventure', 'Quest', 'Marathon', 'Ramble', 'Rivalry', 'Field Trip', 'Badge Hunt',
      'Grand Tour', 'Training Camp', 'Cave Club', 'Picnic', 'Escape', 'Homecoming', 'Stroll']
    const reserved = new Set(adventures.map(game => game.name.trim().toLowerCase()))
    reserved.add($('#new-name').value.trim().toLowerCase())
    const choices = starts.flatMap(start => endings.map(ending => `${start} ${ending}`))
      .filter(name => !reserved.has(name.toLowerCase()))
    let name = choices[Math.floor(Math.random() * choices.length)]
    if (!name) {
      let number = 1
      while (reserved.has(`kanto adventure ${number}`)) number += 1
      name = `Kanto Adventure ${number}`
    }
    $('#new-name').value = name
  }
  $('#random-adventure').onclick = randomizeAdventure
  function randomizeTrainer(field, other) {
    const names = (document.body.dataset.trainerNames || '').split(',').filter(Boolean)
    const current = $(field).value.toUpperCase()
    const reserved = $(other).value.toUpperCase()
    const choices = names.filter(name => name !== current && name !== reserved)
    if (choices.length) $(field).value = choices[Math.floor(Math.random() * choices.length)]
  }
  $('#random-trainer').onclick = () => randomizeTrainer('#new-trainer', '#new-rival')
  $('#random-rival').onclick = () => randomizeTrainer('#new-rival', '#new-trainer')
  function updateStarters() {
    const version = $('#rom-select').selectedOptions[0]?.dataset.version
    const johto = ['gold', 'silver', 'crystal'].includes(version)
    const choices = !version || $('#rom-file').files.length ? ['bulbasaur', 'charmander', 'squirtle', 'chikorita', 'cyndaquil', 'totodile'] : johto ? ['chikorita', 'cyndaquil', 'totodile'] : ['bulbasaur', 'charmander', 'squirtle']
    const previous = $('#starter').value
    $('#starter').innerHTML = '<option value="random">Surprise me</option>' + choices.map(name => `<option value="${name}">${name[0].toUpperCase() + name.slice(1)}</option>`).join('')
    $('#starter').value = choices.includes(previous) ? previous : 'random'
  }
  $('#rom-select').onchange = updateStarters
  $('#rom-file').onchange = updateStarters
  async function openCreate() {
    await act(async () => {
      const data = await api('/api/v1/assets')
      $('#rom-select').innerHTML = '<option value="">Add a ROM below</option>' + (data.roms || []).map(rom => `<option value="${esc(rom.id)}" data-version="${esc(rom.version)}">Pokémon ${esc(rom.version)} (${esc(rom.id.slice(0, 8))})</option>`).join('')
      if (data.roms?.length) $('#rom-select').value = data.roms[0].id
      updateStarters()
      if (!$('#new-name').value.trim()) randomizeAdventure()
      if (!$('#new-trainer').value) randomizeTrainer('#new-trainer', '#new-rival')
      if (!$('#new-rival').value) randomizeTrainer('#new-rival', '#new-trainer')
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
      const speed = String(game.settings?.speed ?? 1)
      const speedInput = $('#settings-speed')
      speedInput.value = speed
      if (!speedInput.value) {
        speedInput.add(new Option(`${speed}×`, speed))
        speedInput.value = speed
      }
      $('#settings-autostart').checked = Boolean(game.settings?.auto_start)
      const johto = ['gold', 'silver', 'crystal'].includes(game.version)
      for (const [field, setting] of [['league-rewards', 'league_rewards'], ['mew-event', 'mew_event']]) {
        const input = $(`#settings-${field}`)
        input.checked = Boolean(game.settings?.[setting])
        input.toggleAttribute('data-blocked', running(game))
        input.disabled = running(game)
      }
      $('#settings-celebi-label').hidden = game.version !== 'crystal'
      $('#settings-celebi-note').hidden = game.version !== 'crystal'
      $('#settings-celebi-event').checked = Boolean(game.settings?.celebi_event)
      $('#settings-celebi-event').disabled = running(game) || game.version !== 'crystal'
      $('#settings-celebi-event').toggleAttribute('data-blocked', running(game) || game.version !== 'crystal')
      $('#settings-legendary-steps').value = game.settings?.legendary_return_steps ?? 1000000
      $('#settings-legendary-steps').disabled = running(game)
      for (const [field, setting, fallback] of [['event-steps', 'event_return_steps', 100000], ['mew-steps', 'mew_return_steps', 1000000], ['fossil-preference', 'fossil_preference', 'auto'], ['dojo-preference', 'dojo_preference', 'auto']]) {
        const input = $(`#settings-${field}`)
        input.value = game.settings?.[setting] ?? fallback
        input.disabled = running(game)
      }
      for (const field of ['legendary-steps', 'event-steps', 'fossil-preference', 'dojo-preference']) {
        const input = $(`#settings-${field}`)
        input.closest('label').hidden = johto
        input.disabled = johto || running(game)
      }
      $('#adventure-settings').showModal()
      return
    }
    if (button.dataset.action === 'download-save') {
      act(() => downloadSave(game))
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
      const result = await write('/api/v1/adventures', {name: $('#new-name').value.trim(), rom_id: romId, starter: $('#starter').value,
        trainer_name: $('#new-trainer').value.trim().toUpperCase(), rival_name: $('#new-rival').value.trim().toUpperCase()})
      const game = result.adventure || result
      $('#create-dialog').close()
      $('#create-form').reset()
      if (startNow) await write(`/api/v1/adventures/${encodeURIComponent(game.id)}/start`)
      notice('Adventure created. Its status will update as it gets ready.')
    }) }
  $('#adventure-settings-form').onsubmit = event => { event.preventDefault()
    act(async () => {
      const game = adventures.find(item => item.id === $('#settings-id').value)
      const rewards = game && !running(game) ? {league_rewards: $('#settings-league-rewards').checked, mew_event: $('#settings-mew-event').checked, celebi_event: $('#settings-celebi-event').checked, legendary_return_steps: Number($('#settings-legendary-steps').value), event_return_steps: Number($('#settings-event-steps').value), mew_return_steps: Number($('#settings-mew-steps').value), fossil_preference: $('#settings-fossil-preference').value, dojo_preference: $('#settings-dojo-preference').value} : {}
      if (['gold', 'silver', 'crystal'].includes(game?.version)) {
        for (const field of ['legendary_return_steps', 'event_return_steps', 'fossil_preference', 'dojo_preference']) delete rewards[field]
      }
      const result = await write(`/api/v1/adventures/${encodeURIComponent($('#settings-id').value)}`, {name: $('#settings-name').value.trim(),
        settings: {auto_start: $('#settings-autostart').checked, speed: Number($('#settings-speed').value), ...rewards}}, 'PATCH')
      $('#adventure-settings').close()
      notice(result.pace_pending ? 'Settings saved. The speed will apply when this adventure reconnects.' : 'Adventure settings saved.')
    }) }
  $('#notify-add').onclick = () => openIntegration()
  $('#notify-enabled').onchange = () => act(async () => {
    try {
      renderNotifications(await write('/api/v1/notifications', {enabled: $('#notify-enabled').checked}, 'PATCH'))
    } catch (error) {
      $('#notify-enabled').checked = Boolean(notifyData.enabled)
      throw error
    }
  })
  $('#notify-integrations').onclick = event => {
    const button = event.target.closest('[data-integration-action]')
    if (!button || busy) return
    const row = notifyData.integrations.find(row => row.id === button.dataset.id)
    if (!row) return
    if (button.dataset.integrationAction === 'edit') return openIntegration(row)
    act(async () => {
      if (button.dataset.integrationAction === 'toggle') {
        renderNotifications(await write(integrationUrl(row.id), {enabled: !row.enabled}, 'PATCH'))
      } else {
        const result = await write(integrationUrl(row.id) + '/test', {})
        $(`[data-integration-result="${row.id}"]`).textContent = result.ok ? 'Test accepted. Check your destination.' : `Test failed: ${result.error}`
      }
    })
  }
  $('#notify-form').oninput = event => {
    if (event.target?.id === 'notify-token' && event.target.value) {
      notifySecretCleared = false
      notifySecretChanged = true
      renderNotifyProvider()
    }
    renderSubscribe()
  }
  $('#notify-form').onchange = event => {
    const input = event?.target
    if (input?.dataset?.notify) notify[input.dataset.notify][input.dataset.key] = Boolean(input.checked)
  }
  $('#notify-provider').onchange = () => {
    notifySecretChanged = false
    notifySecretCleared = false
    for (const id of ['notify-token', 'notify-discord-webhook', 'notify-telegram-token']) $('#' + id).value = ''
    renderNotifyProvider()
  }
  $('#notify-include-new').onchange = () => {
    for (const input of $('#notify-adventures').querySelectorAll('input[data-notify="adventures"]')) notify.adventures[input.dataset.key] = input.checked
    notifyAdventuresSignature = ''
    renderNotifyAdventures() }
  $('#notify-change-secret').onclick = () => { notifySecretChanged = true
    renderNotifyProvider() }
  $('#notify-remove-token').onclick = () => { notifySecretCleared = true
    $('#notify-token').value = ''
    renderNotifyProvider() }
  $('#notify-generate').onclick = () => { $('#notify-topic').value = randomTopic()
    renderSubscribe() }
  $('#notify-form').onsubmit = event => { event.preventDefault()
    act(async () => {
      const known = new Set(adventures.map(game => game.id))
      const choices = Object.fromEntries(adventures.filter(game => !game.archived).map(game => [game.id, notify.adventures[game.id] ?? $('#notify-include-new').checked]))
      for (const [id, on] of Object.entries(notify.adventures)) if (known.has(id)) choices[id] = on
      const result = await write(integrationUrl(notifyIntegration.id), {
        name: $('#notify-name').value.trim(), enabled: $('#notify-integration-enabled').checked,
        ...notifyDestination(), min_priority: Number($('#notify-priority').value), categories: notify.categories,
        include_new_adventures: $('#notify-include-new').checked, adventures: choices,
      }, notifyIntegration.id ? 'PATCH' : 'POST')
      $('#integration-dialog').close()
      renderNotifications(result)
      notice(result.pending?.length ? 'Integration saved. Reconnecting adventures will pick it up automatically.' : 'Integration saved.')
    })
  }
  $('#notify-test').onclick = () => act(async () => {
    $('#notify-result').textContent = 'Sending…'
    const url = notifyIntegration.id ? integrationUrl(notifyIntegration.id) + '/test' : '/api/v1/notifications/test'
    const result = await write(url, notifyDestination())
    $('#notify-result').textContent = result.ok ? 'Test accepted. Check your destination.' : `Test failed: ${result.error}`
  })
  $('#notify-delete').onclick = () => { $('#notify-delete-confirm').hidden = false }
  $('#notify-delete-cancel').onclick = () => { $('#notify-delete-confirm').hidden = true }
  $('#notify-delete-yes').onclick = () => act(async () => {
    const result = await write(integrationUrl(notifyIntegration.id), {}, 'DELETE')
    $('#integration-dialog').close()
    renderNotifications(result)
    notice('Integration deleted.')
  })
  $('#integration-dialog').onclose = () => {
    for (const id of ['notify-token', 'notify-discord-webhook', 'notify-telegram-token']) $('#' + id).value = ''
    notifyIntegration = null
    notifyDirty = false
    permissions()
  }
  $('#create-backup').onclick = () => act(async () => {
    notice('Saving adventures and creating a backup…')
    backupPage = 0
    await write('/api/v1/backups')
    await refreshBackups()
    notice('Backup ready to download.')
  })
  $('#import-form').onsubmit = event => { event.preventDefault()
    act(async () => { notice('Checking and importing the archive…')
      await api('/api/v1/imports', {method: 'POST', headers: {'Content-Type': 'application/zip'}, body: $('#import-file').files[0]})
      $('#import-form').reset()
      notice('Import complete. Open the Library to see the adventure.') }) }
  const nicknameKinds = ['prefixes', 'suffixes', 'names']
  const nicknameFields = [...nicknameKinds, ...nicknameKinds.map(kind => 'excluded-' + kind)]
  const nicknameParts = id => [...new Set($(id).value.split(/[,\n]/).map(word => word.trim().toUpperCase()).filter(Boolean))]
  let nicknameSettings = {}
  function nicknamePreview() {
    const catalog = nicknameSettings.nickname_catalog || {}
    const read = kind => nicknameParts('#nickname-' + kind)
    const excluded = kind => new Set(read('excluded-' + kind))
    const names = new Set([...(catalog.names || []), ...read('names')])
    for (const prefix of [...(catalog.prefixes || []), ...read('prefixes')].filter(word => !excluded('prefixes').has(word))) {
      for (const suffix of [...(catalog.suffixes || []), ...read('suffixes')].filter(word => !excluded('suffixes').has(word))) {
        if ((prefix + suffix).length <= 10) names.add(prefix + suffix)
      }
    }
    for (const name of excluded('names')) names.delete(name)
    $('#nickname-preview').textContent = `${names.size.toLocaleString()} available names with these choices.`
    nicknameKinds.forEach(kind => {
      const blocked = excluded(kind)
      const choices = $('#nickname-default-' + kind).querySelectorAll('input')
      choices.forEach(input => { input.checked = !blocked.has(input.value) })
      $('#nickname-count-' + kind).textContent = `(${[...choices].filter(input => input.checked).length}/${choices.length})`
    })
  }
  function renderNicknameSettings(settings) {
    nicknameSettings = settings
    nicknameFields.forEach(field => { $('#nickname-' + field).value = (settings['nickname_' + field.replace('-', '_')] || []).join('\n') })
    const catalog = settings.nickname_catalog || {}
    $('#nickname-summary').textContent = `${Number(catalog.available || 0).toLocaleString()} available names. Applies to all adventures.`
    nicknameKinds.forEach(kind => {
      $('#nickname-default-' + kind).innerHTML = (catalog[kind] || []).map(word => `<label class="check"><input type="checkbox" value="${esc(word)}" data-owner>${esc(word)}</label>`).join('')
      $('#nickname-default-' + kind).querySelectorAll('input').forEach(input => { input.onchange = () => {
        const excluded = new Set(nicknameParts('#nickname-excluded-' + kind))
        if (input.checked) excluded.delete(input.value)
        else excluded.add(input.value)
        $('#nickname-excluded-' + kind).value = [...excluded].join('\n')
        nicknamePreview()
      } })
    })
    nicknamePreview()
    permissions()
  }
  $('#nickname-edit').onclick = () => {
    renderNicknameSettings(nicknameSettings)
    $('#nickname-dialog .dialog-feedback').textContent = ''
    $('#nickname-dialog').showModal()
  }
  nicknameFields.forEach(field => { $('#nickname-' + field).oninput = nicknamePreview })
  $('#nickname-form').onsubmit = event => {
    event.preventDefault()
    act(async () => {
      const values = Object.fromEntries(nicknameFields.map(field => ['nickname_' + field.replace('-', '_'), nicknameParts('#nickname-' + field)]))
      const result = await write('/api/v1/settings', values, 'PATCH')
      renderNicknameSettings(result)
      $('#nickname-dialog').close()
      notice(result.pending?.length ? 'Nicknames saved. Reconnecting games will receive them shortly.' : 'Nickname settings saved for all adventures.')
    })
  }
  $('#nickname-reset').onclick = () => {
    nicknameFields.forEach(field => { $('#nickname-' + field).value = '' })
    nicknamePreview()
    $('#nickname-dialog .dialog-feedback').textContent = 'Defaults loaded in the editor. Save to apply them.'
  }
  let backupSelection = null
  async function openBackup(id, inspected) {
    notice('Checking backup…')
    const data = inspected || await api(`/api/v1/backups/${encodeURIComponent(id)}/inspect`)
    backupSelection = {id, adventures: data.adventures}
    $('#backup-date').textContent = `Backup from ${dateLabel(data.created_at)}`
    const usable = data.adventures.filter(game => game.restorable)
    $('#backup-adventure').innerHTML = usable.map(game => `<option value="${esc(game.id)}">${esc(game.name)} · ${esc(game.version)}</option>`).join('')
    $('#backup-load').toggleAttribute('data-blocked', !usable.length)
    $('#backup-adventure').onchange()
    $('#backup-dialog .dialog-feedback').textContent = usable.length ? '' : 'This backup has no saved adventures to load.'
    $('#backup-dialog').showModal()
    notice('')
  }
  $('#backup-adventure').onchange = () => {
    const game = backupSelection?.adventures.find(game => game.id === $('#backup-adventure').value)
    $('#backup-name').value = game ? game.name.slice(0, 109) + ' (restored)' : ''
  }
  $('#upload-backup').onclick = () => $('#backup-file').click()
  $('#backup-file').onchange = () => act(async () => {
    const file = $('#backup-file').files[0]
    if (!file) return
    notice('Uploading and checking backup…')
    try {
      const result = await api('/api/v1/backups/upload', {method: 'POST', headers: {'Content-Type': 'application/zip'}, body: file})
      await refreshBackups()
      await openBackup(result.id, result)
    } finally { $('#backup-file').value = '' }
  })
  $('#backup-load-form').onsubmit = event => {
    event.preventDefault()
    act(async () => {
      $('#backup-dialog .dialog-feedback').textContent = 'Checking and loading the adventure…'
      await write(`/api/v1/backups/${encodeURIComponent(backupSelection.id)}/load`, {adventure_id: $('#backup-adventure').value, name: $('#backup-name').value})
      $('#backup-dialog').close()
      notice('Adventure loaded as a stopped copy. Open the Library when you are ready to start it.')
    })
  }
  $('#quit').onclick = () => act(async () => {
    await write('/api/v1/shutdown')
    closing = true
    notice('PokeSim is saving and closing. You can close this tab.')
    $('#workspace').hidden = true
  })
  function renderPortraits(data) {
    $('#portrait-state').textContent = data.busy ? `Downloading ${data.completed} / ${data.total}` : data.active === 'community' ? 'Community sprites active' : 'Default sprites active'
    const install = $('#portrait-install')
    install.textContent = data.busy ? 'Downloading…' : data.installed ? 'Use community sprites' : 'Install community sprite pack'
    install.hidden = data.active === 'community' && !data.busy
    install.toggleAttribute('data-blocked', data.busy)
    const restore = $('#portrait-default')
    restore.hidden = data.active !== 'community'
    restore.toggleAttribute('data-blocked', data.busy)
    $('#portrait-source').href = data.source
    $('#portrait-license').href = data.license
    $('#portrait-progress').hidden = !data.busy
    $('#portrait-progress').value = data.completed
    $('#portrait-feedback').textContent = data.error || (data.busy ? 'Your current artwork stays in place until all 151 sprites are ready.' : data.installed ? 'Reopen adventure pages after switching artwork.' : '')
    $('#portrait-feedback').classList.toggle('is-error', Boolean(data.error))
    const preview = $('#portrait-preview')
    preview.hidden = !data.installed
    if (data.installed && preview.dataset.revision !== data.revision) {
      preview.dataset.revision = data.revision
      preview.innerHTML = [[1, 'Bulbasaur'], [6, 'Charizard'], [25, 'Pikachu']].map(([dex, name]) => `<div class="plate"><img src="/api/v1/portraits/preview/${dex}.png?v=${encodeURIComponent(data.revision)}" alt="${name}"></div>`).join('') + '<p class="note portrait-preview-caption">Community pack preview</p>'
    }
    permissions()
  }
  async function refreshPortraits() {
    renderPortraits(await api('/api/v1/portraits'))
  }
  $('#portrait-install').onclick = () => act(async () => {
    renderPortraits(await write('/api/v1/portraits/community'))
  })
  $('#portrait-default').onclick = () => act(async () => {
    renderPortraits(await write('/api/v1/portraits/default'))
    notice('Default sprites restored. Reopen an adventure page to see them.')
  })
  async function enter() {
    await initializeSession()
    $('#workspace').hidden = false
    document.querySelectorAll('[data-view]').forEach(section => { section.hidden = section.dataset.view !== page })
    document.querySelector(`[data-nav="${page}"]`)?.setAttribute('aria-current', 'page')
    if (page === 'settings' && owner) {
      renderNicknameSettings(await api('/api/v1/settings'))
      await refreshBackups()
      await refreshPortraits()
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
      connection('Reconnecting…', true)
      notice(error.message, true) }
    finally { connecting = false }
  }
  boot()
  setInterval(() => {
    if (!document.hidden && !busy && !closing) {
      if ($('#workspace').hidden) boot()
      else {
        refresh()
        if (page === 'settings' && owner) refreshPortraits().catch(error => { $('#portrait-feedback').textContent = error.message })
      }
    }
  }, 3000)
})()
