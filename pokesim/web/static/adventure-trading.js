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
    const sprite = dex ? `<img src="${esc(PokeSim.sprite(dex, Boolean(mon?.shiny)))}" alt="" loading="lazy">` : '<span class="plate-num" aria-hidden="true">?</span>'
    const nickname = mon.nickname && mon.nickname.toLowerCase() !== mon.name.toLowerCase()
      ? `<p class="swap-sub cable-nickname">“${esc(mon.nickname)}”</p>` : ''
    const level = Number.isInteger(mon.level) && mon.level > 0 && mon.level <= 100 ? `, Lv. ${mon.level}` : ''
    const name = dex ? `<a href="${esc(PokeSim.base || '')}/pokedex#${dex}">${esc(mon.name)}</a>` : esc(mon.name)
    const evolution = completed && receiving && mon.evolved_from?.name
      ? `<p class="swap-note cable-evolution"><span class="micro">Trade evolution</span> ${esc(mon.evolved_from.name)} → ${esc(mon.name)}</p>` : ''
    return `<div class="swap-side cable-mon cable-${direction}"><div class="plate plate--bay${plateClass(mon)}">${sprite}</div><div class="swap-read"><p class="micro">${label}${dex ? `, #${String(dex).padStart(3, '0')}` : ''}${level}</p><h4>${name}</h4>${nickname}${stamps(mon)}${evolution}</div></div>`
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
      ? `<a href="/games/${trade.peer_id}/trading${completed || failed ? '#history' : ''}">${esc(trade.peer_name)}</a>` : esc(trade.peer_name)
    const pair = failed && !trade.sent && !trade.received ? ''
      : `<div class="swap cable-exchange">${pokemon(trade.sent, 'sent', completed, failed)}<span class="swap-arrow" aria-hidden="true">→</span>${pokemon(trade.received, 'received', completed, failed)}</div>`
    const foot = time || completed ? `<footer class="deal-foot">${time}${completed ? '<span>Saved in both adventures</span>' : ''}</footer>` : ''
    const lamp = completed || failed ? '' : '<i class="lamp lamp--blink" data-on="signal" aria-hidden="true"></i>'
    return `<article class="deal trade-deal cable-card${failed ? ' cable-failed' : ''}${completed ? ' cable-completed' : ''}"><header class="deal-head"><h3>With ${peer}</h3><span class="tag ${tone} cable-status">${lamp}${esc(label)}</span></header>${pair}${reason}${foot}</article>`
  }
  // Only the owner's page can take a trade out of line. A view link only watches.
  const owner = () => String(PokeSim.base || '').startsWith('/games/') && typeof PokeSim.api === 'function'
  // A trade the owner chose that waits for the Cable Club. Its Pokémon show once it starts.
  function queuedCard(entry) {
    const peer = /^[a-f0-9]{32}$/.test(entry.peer_id || '')
      ? `<a href="/games/${entry.peer_id}/trading">${esc(entry.peer_name)}</a>` : esc(entry.peer_name)
    const place = entry.state === 'starting' ? 'Checking both Pokémon' : entry.position > 1 ? `Number ${entry.position} in line for the Cable Club` : 'Next for the Cable Club'
    const wait = 'Busy with a trade. Your trade will wait in line.'
    const cancel = entry.cancellable && entry.state === 'queued' && owner() && /^[a-f0-9]{32}$/.test(entry.id || '')
      ? `<footer class="deal-foot"><button type="button" class="key queued-cancel" data-cancel="${entry.id}">Cancel trade</button></footer>` : ''
    return `<article class="deal trade-deal cable-card queued-card"><header class="deal-head"><h3>With ${peer}</h3><span class="tag tag--signal cable-status"><i class="lamp lamp--blink" data-on="signal" aria-hidden="true"></i>Waiting for the Cable Club</span></header><p class="queued-place">${esc(place)}${entry.state !== 'starting' && entry.busy ? `. ${esc(wait)}` : ''}</p>${cancel}</article>`
  }
  // Cancel takes a waiting trade out of line. Once it has started, the server refuses and says why.
  async function cancelQueued(button) {
    button.disabled = true
    try {
      const response = await PokeSim.api(`/api/v1/interactions/trade-builder/${button.dataset.cancel}/cancel`, {method: 'POST'})
      if (!response.ok) {
        let detail = ''
        try { detail = (await response.json()).detail } catch (_) {}
        throw new Error(typeof detail === 'string' && detail ? detail : 'This trade could not be cancelled.')
      }
      $('#trade-connection-note').hidden = true
    } catch (error) {
      $('#trade-connection-note').textContent = error.message
      $('#trade-connection-note').hidden = false
    }
    await refresh()
  }
  $('#trade-active')?.addEventListener?.('click', event => {
    const button = event.target?.closest?.('[data-cancel]')
    if (button && !button.disabled) cancelQueued(button)
  })
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
      setLamp(data.active.length ? 'signal' : !running || off ? 'warn' : data.attention ? 'warn' : 'ok')
      // The lamp carries the state. A problem shows as the lamp's tooltip, not as text.
      const lamp = $('#trade-lamp')
      if (lamp) lamp.title = data.active.length ? 'Trading now' : !running ? 'Waiting for this adventure'
        : off ? 'Off' : data.attention?.message || 'On'
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
      // The History tab counts its rows. Its tooltip splits them into completed and not.
      $('#trade-history-count').textContent = rows.length ? `(${rows.length}${completed.length === 20 ? '+' : ''})` : ''
      $('#tab-history')?.setAttribute?.('title', `${completed.length}${completed.length === 20 ? '+' : ''} completed`
        + (failures.length ? `, ${failures.length} did not complete` : ''))
      $('#trade-history').innerHTML = rows.length ? rows.map(([trade, done]) => exchange(trade, done)).join('')
        : '<p class="empty-note">No trades yet.</p>'
      globalThis.Panel?.fitSprites?.(document)
    } catch (_) {
      $('#status').textContent = 'Reconnecting…'
      $('#connection').title = ''
      $('#connection').classList.toggle('is-offline', true)
      setLamp('crit')
      $('#trade-connection-note').textContent = 'Reconnecting…'
      $('#trade-connection-note').hidden = false
    } finally { loading = false }
  }
  const poll = () => refresh()
  poll()
  setInterval(() => { if (!document.hidden) poll() }, 5000)
  globalThis.AdventureTrading = {refresh, exchange}
})()
