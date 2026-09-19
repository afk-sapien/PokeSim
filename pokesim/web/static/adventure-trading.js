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
  const dexNumber = mon => Number.isInteger(mon?.dex) && mon.dex >= 1 && mon.dex <= 151 ? mon.dex : null
  function pokemon(mon, direction, completed, failed) {
    const receiving = direction === 'received'
    const label = completed ? receiving ? 'You received' : 'You sent'
      : failed ? receiving ? 'Planned return' : 'Planned offer' : receiving ? 'Receiving' : 'Sending'
    if (!mon?.name) return `<div class="cable-mon cable-${direction} cable-unknown"><span class="eyebrow">${label}</span><div class="cable-placeholder" aria-hidden="true">?</div><h4>Pokémon details unavailable</h4><p>This older attempt did not record the Pokémon.</p></div>`
    const dex = dexNumber(mon)
    const sprite = dex ? `<img src="${esc(PokeSim.base || '')}/sprites/${dex}.png" alt="" width="64" height="64" loading="lazy">` : '<span class="cable-placeholder" aria-hidden="true">?</span>'
    const nickname = mon.nickname && mon.nickname.toLowerCase() !== mon.name.toLowerCase()
      ? `<p class="cable-nickname">“${esc(mon.nickname)}”</p>` : ''
    const level = Number.isInteger(mon.level) && mon.level > 0 && mon.level <= 100 ? `<span class="cable-level">Lv. ${mon.level}</span>` : ''
    const name = dex ? `<a href="${esc(PokeSim.base || '')}/pokedex#${dex}">${esc(mon.name)} <span class="cable-dex-link" aria-hidden="true">↗</span></a>` : esc(mon.name)
    const evolution = completed && receiving && mon.evolved_from?.name
      ? `<div class="cable-evolution"><span aria-hidden="true">✦</span><span><strong>Trade evolution</strong>${esc(mon.evolved_from.name)} → ${esc(mon.name)}</span></div>` : ''
    return `<div class="cable-mon cable-${direction}"><div class="cable-mon-heading"><span class="eyebrow">${label}</span>${level}</div><div class="cable-mon-body"><div class="cable-sprite">${sprite}</div><div class="cable-mon-info">${dex ? `<span class="cable-dex">#${String(dex).padStart(3, '0')}</span>` : ''}<h4>${name}</h4>${nickname}</div></div>${evolution}</div>`
  }
  function exchange(trade, completed = false) {
    const failed = trade.phase === 'aborted'
    const label = failed ? 'Trade did not complete' : completed ? 'Trade completed' : trade.recovering || trade.decision === 'ABORT'
      ? trade.decision === 'COMMIT' ? 'Finishing the exchange safely' : 'Getting ready to try again'
      : phases[trade.phase] || 'Getting ready'
    const date = new Date(trade.updated_at * 1000)
    const time = (completed || failed) && Number.isFinite(date.getTime())
      ? `<time datetime="${date.toISOString()}">${esc(date.toLocaleString())}</time>` : ''
    const reason = failed ? `<p class="cable-failure">${esc(trade.failure_reason || 'The exchange could not finish safely.')}</p>` : ''
    const peer = /^[a-f0-9]{32}$/.test(trade.peer_id || '')
      ? `<a href="/games/${trade.peer_id}/trading">${esc(trade.peer_name)} <span aria-hidden="true">↗</span></a>` : esc(trade.peer_name)
    const pair = failed && !trade.sent && !trade.received ? ''
      : `<div class="cable-exchange">${pokemon(trade.sent, 'sent', completed, failed)}<div class="cable-connector" aria-hidden="true"><span>⇄</span></div>${pokemon(trade.received, 'received', completed, failed)}</div>`
    return `<article class="trade-deal cable-card${failed ? ' cable-failed' : ''}${completed ? ' cable-completed' : ''}"><header class="cable-heading"><h3>With ${peer}</h3><span class="cable-status">${completed ? '<span aria-hidden="true">✓</span> ' : ''}${esc(label)}</span></header>${pair}${reason}<footer class="cable-card-footer">${time}${completed ? '<span>Saved in both adventures</span>' : ''}</footer></article>`
  }
  let loading = false
  async function refresh() {
    if (loading) return
    loading = true
    try {
      const response = await PokeSim.fetch('/api/interactions', {cache: 'no-store'})
      if (!response.ok) throw new Error('Unavailable')
      const data = await response.json()
      if (data.adventure.id !== PokeSim.adventureId) throw new Error('Wrong adventure')
      $('#edition').textContent = `${data.adventure.version.toUpperCase()} VERSION`
      $('#status').textContent = 'Connected'
      $('#connection').classList.toggle('is-offline', false)
      $('#trade-connection-note').hidden = true
      const running = data.adventure.state === 'running' && !data.adventure.archived
      $('#trade-status').textContent = data.active.length ? 'Exchange in progress' : !running ? 'Waiting for this adventure'
        : data.attention ? 'Trades have not been completing' : 'On · No approvals needed'
      $('#trade-activity').textContent = data.active.length ? 'This adventure is trading. Other adventures keep playing.'
        : !running ? 'Trades resume when this adventure is running. Its history stays here.'
        : data.attention?.message || 'This adventure will trade when a useful exchange is ready.'
      $('#current-exchange-section').hidden = !data.active.length
      $('#trade-active').innerHTML = data.active.length ? data.active.map(trade => exchange(trade)).join('')
        : '<p class="dex-empty">No exchange in progress for this adventure.</p>'
      const completed = data.history.filter(trade => trade.phase === 'completed' && trade.decision === 'COMMIT')
      $('#trade-history-count').textContent = `${completed.length}${completed.length === 20 ? '+' : ''} recent ${completed.length === 1 ? 'exchange' : 'exchanges'}`
      $('#trade-history').innerHTML = completed.length ? completed.map(trade => exchange(trade, true)).join('')
        : '<p class="dex-empty">This adventure’s completed trades will appear here.</p>'
      const failures = data.recent_failures || []
      $('#trade-failures-section').hidden = !failures.length
      $('#trade-failures').innerHTML = failures.map(trade => exchange(trade)).join('')
    } catch (_) {
      $('#status').textContent = 'Reconnecting…'
      $('#connection').classList.toggle('is-offline', true)
      $('#trade-connection-note').textContent = 'This adventure’s trading updates are reconnecting. Any displayed history is from the last successful update.'
      $('#trade-connection-note').hidden = false
    } finally { loading = false }
  }
  refresh()
  setInterval(() => { if (!document.hidden) refresh() }, 5000)
})()
