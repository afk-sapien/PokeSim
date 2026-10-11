(() => {
  const $ = selector => document.querySelector(selector)
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp', '<': '&lt', '>': '&gt', '"': '&quot', "'": '&#39'}[char] + String.fromCharCode(59)))
  const phases = {
    preparing: 'Getting ready for the Cable Club', connecting: 'Connecting the games',
    trading: 'Exchanging Pokémon', saving: 'Saving progress', leaving: 'Leaving the Cable Club',
    resuming: 'Returning to the adventure', returning: 'Returning to the adventure',
    verifying: 'Checking both saves', staging: 'Checking both saves',
    committed: 'Saving the exchange', applying: 'Saving the exchange', releasing: 'Returning to the adventure'
  }
  // Type colours and stamps from the PC page, when the shared scripts are on the page.
  const plateClass = mon => mon?.type_names?.length && globalThis.PokemonTypes ? ` ${PokemonTypes.portraitClass(mon.type_names)}` : ''
  function stamps(mon) {
    const types = globalThis.PokemonTypes
    const tags = [types?.badges?.(mon?.type_names) || '', types?.shinyBadge?.(mon) || '',
      Number.isInteger(mon?.dv_stars) ? globalThis.MonGrid?.ratingBadge?.(mon) || '' : ''].join('')
    return tags ? `<div class="pc-tags swap-tags">${tags}</div>` : ''
  }
  const dexNumber = mon => Number.isInteger(mon?.dex) && mon.dex >= 1 && mon.dex <= 251 ? mon.dex : null
  function pokemon(mon, direction, completed, failed) {
    const receiving = direction === 'received'
    const label = completed ? receiving ? 'You received' : 'You sent'
      : failed ? receiving ? 'Planned return' : 'Planned offer' : receiving ? 'Receiving' : 'Sending'
    if (!mon?.name) return `<div class="swap-side cable-mon cable-${direction} cable-unknown"><div class="plate plate--bay plate--empty"><span class="plate-num" aria-hidden="true">?</span></div><div class="swap-read"><p class="micro">${label}</p><h4>Pokémon details unavailable</h4><p class="swap-sub">This older attempt did not record the Pokémon.</p></div></div>`
    const dex = dexNumber(mon)
    const sprite = dex ? `<img src="${esc(PokeSim.base || '')}/sprites/${dex}.png?v=rom-portraits-1" alt="" loading="lazy">` : '<span class="plate-num" aria-hidden="true">?</span>'
    const nickname = mon.nickname && mon.nickname.toLowerCase() !== mon.name.toLowerCase()
      ? `<p class="swap-sub cable-nickname">“${esc(mon.nickname)}”</p>` : ''
    const level = Number.isInteger(mon.level) && mon.level > 0 && mon.level <= 100 ? ` · Lv. ${mon.level}` : ''
    const name = dex ? `<a href="${esc(PokeSim.base || '')}/pokedex#${dex}">${esc(mon.name)} <span aria-hidden="true">↗</span></a>` : esc(mon.name)
    const evolution = completed && receiving && mon.evolved_from?.name
      ? `<p class="swap-note cable-evolution"><span class="micro">Trade evolution</span> ${esc(mon.evolved_from.name)} → ${esc(mon.name)}</p>` : ''
    return `<div class="swap-side cable-mon cable-${direction}"><div class="plate plate--bay${plateClass(mon)}">${sprite}</div><div class="swap-read"><p class="micro">${label}${dex ? ` · #${String(dex).padStart(3, '0')}` : ''}${level}</p><h4>${name}</h4>${nickname}${stamps(mon)}${evolution}</div></div>`
  }
  function exchange(trade, completed = false) {
    const failed = trade.phase === 'aborted'
    const label = failed ? 'Trade did not complete' : completed ? 'Trade completed' : trade.recovering || trade.decision === 'ABORT'
      ? trade.decision === 'COMMIT' ? 'Finishing the exchange safely' : 'Getting ready to try again'
      : phases[trade.phase] || 'Getting ready'
    const tone = failed ? 'tag--crit' : completed ? 'tag--ok' : 'tag--signal'
    const date = new Date(trade.updated_at * 1000)
    const time = (completed || failed) && Number.isFinite(date.getTime())
      ? `<time datetime="${date.toISOString()}">${esc(date.toLocaleString())}</time>` : ''
    const reason = failed ? `<p class="deal-reason deal-reason--crit cable-failure">${esc(trade.failure_reason || 'The exchange could not finish safely.')}</p>` : ''
    const peer = /^[a-f0-9]{32}$/.test(trade.peer_id || '')
      ? `<a href="/games/${trade.peer_id}/trading">${esc(trade.peer_name)} <span aria-hidden="true">↗</span></a>` : esc(trade.peer_name)
    const pair = failed && !trade.sent && !trade.received ? ''
      : `<div class="swap cable-exchange">${pokemon(trade.sent, 'sent', completed, failed)}<span class="swap-arrow" aria-hidden="true">→</span>${pokemon(trade.received, 'received', completed, failed)}</div>`
    const foot = time || completed ? `<footer class="deal-foot">${time}${completed ? '<span>Saved in both adventures</span>' : ''}</footer>` : ''
    const lamp = completed || failed ? '' : '<i class="lamp lamp--blink" data-on="signal" aria-hidden="true"></i>'
    return `<article class="deal trade-deal cable-card${failed ? ' cable-failed' : ''}${completed ? ' cable-completed' : ''}"><header class="deal-head"><h3>With ${peer}</h3><span class="tag ${tone} cable-status">${lamp}${esc(label)}</span></header>${pair}${reason}${foot}</article>`
  }
  // A trade the owner chose that waits for the Cable Club. Its Pokémon show once it starts.
  function queuedCard(entry) {
    const peer = /^[a-f0-9]{32}$/.test(entry.peer_id || '')
      ? `<a href="/games/${entry.peer_id}/trading">${esc(entry.peer_name)} <span aria-hidden="true">↗</span></a>` : esc(entry.peer_name)
    const place = entry.state === 'starting' ? 'Checking both Pokémon' : entry.position > 1 ? `Number ${entry.position} in line for the Cable Club` : 'Next for the Cable Club'
    return `<article class="deal trade-deal cable-card queued-card"><header class="deal-head"><h3>With ${peer}</h3><span class="tag tag--signal cable-status"><i class="lamp lamp--blink" data-on="signal" aria-hidden="true"></i>Waiting for the Cable Club</span></header><p class="trade-help">${esc(place)}. It starts when the Cable Club is free.</p></article>`
  }
  const setLamp = state => { const lamp = $('#trade-lamp'); if (lamp?.dataset) lamp.dataset.on = state }
  let loading = false
  async function refresh() {
    if (loading) return
    loading = true
    try {
      const response = await PokeSim.fetch('/api/interactions', {cache: 'no-store'})
      if (!response.ok) throw new Error('Unavailable')
      const data = await response.json()
      if (data.adventure.id !== PokeSim.adventureId) throw new Error('Wrong adventure')
      $('#status').textContent = 'Connected'
      $('#connection').title = ''
      $('#connection').classList.toggle('is-offline', false)
      $('#trade-connection-note').hidden = true
      const running = data.adventure.state === 'running' && !data.adventure.archived
      const off = data.auto_enabled === false
      const asking = data.ask_first !== false
      setLamp(data.active.length ? 'signal' : !running || off ? 'warn' : data.attention ? 'warn' : 'ok')
      $('#trade-status').textContent = data.active.length ? 'Exchange in progress' : !running ? 'Waiting for this adventure'
        : off ? 'Off' : data.attention ? 'Trades have not been completing' : asking ? 'On · Asks before trading' : 'On · No approvals needed'
      $('#trade-activity').textContent = data.active.length ? 'This adventure is trading. Other adventures keep playing.'
        : !running ? 'Trades resume when this adventure is running. Its history stays here.'
        : off ? 'Automatic trading is off. Trades you pick on the Trade tab still happen.'
        : data.attention?.message || (asking ? 'Suggested trades wait at the top of this page until you accept them.'
          : 'This adventure will trade when a useful exchange is ready.')
      const queued = data.queued || []
      $('#current-exchange-section').hidden = !data.active.length && !queued.length
      $('#trade-active').innerHTML = data.active.length || queued.length
        ? data.active.map(trade => exchange(trade)).join('') + queued.map(queuedCard).join('')
        : '<p class="empty-note">No exchange in progress for this adventure.</p>'
      // Completed trades and attempts that did not complete, in one list, newest first.
      const completed = data.history.filter(trade => trade.phase === 'completed' && trade.decision === 'COMMIT')
      const failures = data.recent_failures || []
      const rows = [...completed.map(trade => [trade, true]), ...failures.map(trade => [trade, false])]
        .sort((a, b) => (b[0].updated_at || 0) - (a[0].updated_at || 0))
      $('#trade-history-count').textContent = `${completed.length}${completed.length === 20 ? '+' : ''} completed`
        + (failures.length ? ` · ${failures.length} did not complete` : '')
      $('#trade-history').innerHTML = rows.length ? rows.map(([trade, done]) => exchange(trade, done)).join('')
        : '<p class="empty-note">This adventure’s trades will appear here.</p>'
      globalThis.Panel?.fitSprites?.(document)
    } catch (_) {
      $('#status').textContent = 'Reconnecting…'
      $('#connection').title = ''
      $('#connection').classList.toggle('is-offline', true)
      setLamp('crit')
      $('#trade-connection-note').textContent = 'This adventure’s trading updates are reconnecting. Any displayed history is from the last successful update.'
      $('#trade-connection-note').hidden = false
    } finally { loading = false }
  }
  // Only the owner's /games/ page reaches the library API, never a view link.
  const offerOwner = String(PokeSim.base || '').startsWith('/games/') && typeof PokeSim.api === 'function'
  function offerSide(mon, label) {
    const dex = dexNumber(mon)
    const sprite = mon.egg ? globalThis.PokemonTypes?.eggPlate || '<span class="plate-num" aria-hidden="true">?</span>'
      : mon.sprite_url ? `<img src="${esc(mon.sprite_url)}" alt="" loading="lazy">`
        : dex ? `<img src="${esc(PokeSim.base || '')}/sprites/${dex}.png?v=rom-portraits-1" alt="" loading="lazy">` : '<span class="plate-num" aria-hidden="true">?</span>'
    const nickname = mon.nickname && mon.nickname.toLowerCase() !== String(mon.name || '').toLowerCase()
      ? `<p class="swap-sub cable-nickname">“${esc(mon.nickname)}”</p>` : ''
    const level = Number.isInteger(mon.level) ? ` · Lv. ${mon.level}` : ''
    const power = [Number.isFinite(mon.battle_power) ? `Battle Power ${mon.battle_power.toLocaleString()}` : '',
      Number.isFinite(mon.power) ? `Stat Power ${mon.power.toLocaleString()}` : ''].filter(Boolean).join(' · ')
    return `<div class="swap-side offer-mon"><div class="plate plate--bay${plateClass(mon)}">${sprite}</div><div class="swap-read"><p class="micro">${label}${dex ? ` · #${String(dex).padStart(3, '0')}` : ''}${level}</p><h4>${esc(mon.name || 'Unknown Pokémon')}</h4>${nickname}${stamps(mon)}<p class="swap-note">${esc(mon.adventure_name)}${power ? ` · ${esc(power)}` : ''}</p></div></div>`
  }
  // Suggested trades: with Ask me first on, automatic trading waits here for an answer.
  const REQUESTS = '/api/v1/interactions/trade-requests'
  let requestSignature = ''
  let requestBusy = false
  function requestCard(row, viewerOnly) {
    const peer = `<a href="/games/${esc(row.right.adventure_id)}/trading">${esc(row.right.adventure_name)} <span aria-hidden="true">↗</span></a>`
    const reasons = row.reasons.length ? `<ul class="request-reasons">${row.reasons.map(reason => `<li>${esc(reason)}</li>`).join('')}</ul>` : ''
    const actions = viewerOnly ? '' : `<div class="offer-answer"><button type="button" class="key key--primary" data-request-action="accept" data-request-id="${esc(row.id)}">Accept</button><button type="button" class="key" data-request-action="dismiss" data-request-id="${esc(row.id)}">Dismiss</button></div>`
    return `<article class="deal trade-deal offer-card request-card" data-request="${esc(row.id)}"><header class="deal-head"><h3>With ${peer}</h3><span class="tag tag--signal offer-status">Suggested</span></header><div class="swap">${offerSide(row.left, 'You send')}<span class="swap-arrow" aria-hidden="true">⇄</span>${offerSide(row.right, 'You receive')}</div><p class="micro request-why">Why it was suggested</p>${reasons}${actions}</article>`
  }
  function renderRequests(data) {
    const key = JSON.stringify(data)
    if (key === requestSignature) return
    requestSignature = key
    const section = $('#trade-requests-section')
    if (!section) return
    section.hidden = !data.requests.length
    $('#trade-requests').innerHTML = data.requests.map(row => requestCard(row, data.viewer_only)).join('')
    globalThis.Panel?.fitSprites?.(section)
  }
  async function refreshRequests(force = false) {
    if (force) requestSignature = ''
    if (!offerOwner || !$('#trade-requests-section')) return
    try {
      const response = await PokeSim.api(`${REQUESTS}?adventure_id=${encodeURIComponent(PokeSim.adventureId)}`, {cache: 'no-store'})
      if (!response.ok) throw new Error('Unavailable')
      renderRequests(await response.json())
    } catch (_) {}
  }
  async function answerRequest(button) {
    if (requestBusy) return
    requestBusy = true
    button.disabled = true
    const note = $('#requests-note')
    const say = text => { note.textContent = text
      note.hidden = !text }
    say('')
    try {
      const response = await PokeSim.api(`${REQUESTS}/${encodeURIComponent(button.dataset.requestId)}/${button.dataset.requestAction}`, {method: 'POST'})
      let data = {}
      try { data = await response.json() } catch (_) {}
      if (!response.ok) throw new Error(data.detail || 'That did not work. Try again in a moment.')
      say(data.status === 'accepted' ? 'Trade started. Follow it under Current exchange and on the History tab.'
        : data.status === 'dismissed' ? 'Dismissed. This pair will not be suggested again for a week.'
          : data.reason || 'This suggested trade can no longer happen.')
    } catch (error) {
      say(error.message)
    } finally {
      requestBusy = false
      await refreshRequests(true)
      refresh()
    }
  }
  const requestsSection = $('#trade-requests-section')
  if (requestsSection && offerOwner) requestsSection.addEventListener('click', event => {
    const button = event.target.closest?.('[data-request-action]')
    if (button && !button.disabled) answerRequest(button)
  })
  const poll = () => { refresh()
    refreshRequests() }
  poll()
  setInterval(() => { if (!document.hidden) poll() }, 5000)
  globalThis.AdventureTrading = {refresh, refreshRequests, offerOwner, exchange, offerSide}
})()
