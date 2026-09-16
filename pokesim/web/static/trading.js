const $ = selector => document.querySelector(selector)
const esc = TradeUI.esc
const query = new URLSearchParams(location.search)
let view = ['block', 'opportunities', 'history'].includes(query.get('view')) ? query.get('view') : 'block'
let signature = ''
function sprite(mon) {
  return `<img src="/sprites/${Number(mon.dex) || 0}.png" alt="" width="72" height="72" loading="lazy">`
}
function side(mon, label) {
  return `<div class="trade-side">${mon.dex ? sprite(mon) : ''}<div><p class="eyebrow">${label}</p><h3>${esc(mon.nick || mon.name)}</h3><p>${esc(mon.name)} · Lv. ${Number(mon.level) || '?'}</p>${mon.evolved_from ? `<small>Evolved from ${esc(mon.evolved_from)}</small>` : ''}</div></div>`
}
function render(status) {
  if (!status) return
  $('#edition').textContent = `${String(status.version || 'Kanto').toUpperCase()} VERSION`
  $('#status').textContent = status.connected ? 'Adventures connected' : 'Reconnecting…'
  $('#connection').classList.toggle('is-offline', !status.connected)
  const trading = status.trading || {}
  $('#trade-status').textContent = !status.connected ? 'Connection unavailable' : trading.enabled ? 'On · No approvals needed' : 'Off'
  const states = {ready: 'Watching for the next useful exchange.', waiting_for_overworld: 'Waiting for the adventures to finish their current activity.', waiting_for_opportunity: 'Waiting for a useful match.', retrying: 'Retrying after a trading interruption.'}
  $('#trade-activity').textContent = !status.connected ? 'Saved offers stay in place while we reconnect.' : !trading.enabled ? 'Offers are saved. Automatic trading is currently off.' : status.holding ? 'An exchange is in progress.' : states[trading.state] || 'Watching for the next useful exchange.'
  const peers = (status.peers || []).filter(peer => peer.error || !peer.started)
  const stale = trading.last_check && Date.now() / 1000 - trading.last_check > Math.max(300, trading.interval_seconds || 900) + 120
  const notice = !status.connected ? status.message : peers.length ? `${peers.map(peer => peer.instance).join(', ')} is unavailable. Trades will wait.` : stale ? 'The coordinator has not checked in recently. These are the last reported opportunities.' : status.viewer_only ? 'Viewing only. Offer controls are disabled for this game.' : ''
  $('#trade-connection-note').textContent = notice
  $('#trade-connection-note').hidden = !notice
  for (const button of document.querySelectorAll('#trade-tabs button')) button.setAttribute('aria-pressed', String(button.dataset.view === view))
  history.replaceState(null, '', `/trading?view=${view}`)
  const nextSignature = JSON.stringify([status, view])
  if (signature === nextSignature) return
  signature = nextSignature
  if (view === 'block') {
    const rows = (status.offers || []).filter(mon => mon.listed || mon.preference === 'offered')
    $('#trade-content').innerHTML = `<div class="section-heading"><h2>Your trading block</h2><span class="count-pill">${rows.length} Pokémon</span></div><p class="trade-help">Automatic offers and your selections are considered for suitable exchanges. Withdrawing an offer also excludes it from automatic selection.</p>` + (rows.map(mon => `<article class="trade-offer">${sprite(mon)}<div class="trade-offer-name"><h3>${esc(mon.nick || mon.name)}</h3><p>${esc(mon.name)} · Lv. ${Number(mon.level)}</p><small>${mon.box ? `Box ${Number(mon.box)} · Slot ${Number(mon.position)}` : 'Party'}${!mon.listed ? ' · Waiting to become eligible' : ''}</small></div><div class="trade-offer-action">${TradeUI.control(mon.trade_key)}</div></article>`).join('') || '<p class="dex-empty">No offers yet. Choose a Pokémon in the PC, or let new spare partners join automatically.</p>')
  } else if (view === 'opportunities') {
    $('#trade-content').innerHTML = '<div class="section-heading"><h2>Possible exchanges</h2></div><p class="trade-help">Matches can change as both adventures progress. The coordinator checks availability again before trading.</p>' + ((status.opportunities || []).map(row => `<article class="trade-deal"><div class="section-heading"><h3>With ${esc(row.peer)}</h3><span class="count-pill">Potential match</span></div><div class="trade-swap">${side(row.send, 'YOU SEND')}<span class="trade-arrow" aria-hidden="true">⇄</span>${side(row.receive, 'YOU RECEIVE')}</div><p class="trade-reason">${esc(row.reason)}</p></article>`).join('') || '<p class="dex-empty">No useful matches right now. Offers remain available as the collections grow.</p>')
  } else {
    $('#trade-content').innerHTML = '<div class="section-heading"><h2>Previous exchanges</h2></div>' + ((status.history || []).map(row => `<article class="trade-deal"><div class="section-heading"><h3>Completed with ${esc(row.peer)}</h3><time datetime="${new Date(row.ts * 1000).toISOString()}">${esc(new Date(row.ts * 1000).toLocaleString())}</time></div><div class="trade-swap">${side(row.sent, 'YOU SENT')}<span class="trade-arrow" aria-hidden="true">⇄</span>${side(row.received, 'YOU RECEIVED')}</div><p class="trade-reason">${esc(row.reason)}</p></article>`).join('') || '<p class="dex-empty">Completed trades will appear here.</p>')
  }
}
$('#trade-tabs').onclick = event => {
  const button = event.target.closest('[data-view]')
  if (!button) return
  view = button.dataset.view
  render(TradeUI.status())
}
$('#trade-content').onclick = event => {
  const button = event.target.closest('[data-trade-key]')
  if (button) TradeUI.change(button)
}
TradeUI.subscribe(render)
TradeUI.refresh()
setInterval(() => { if (!document.hidden) TradeUI.refresh() }, 15000)
