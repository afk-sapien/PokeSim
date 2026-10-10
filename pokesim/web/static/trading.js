const $ = selector => document.querySelector(selector)
const esc = TradeUI.esc
const query = new URLSearchParams(location.search)
// The old Trading block view is now Auto, one setting per Pokémon.
const VIEWS = ['auto', 'opportunities', 'history']
const asked = (query.get('view') || query.get('tab')) === 'block' ? 'auto' : query.get('view') || query.get('tab')
let view = VIEWS.includes(asked) ? asked : 'auto'
let signature = ''
function sprite(mon, size = 'bay') {
  const dex = Number(mon.dex) || 0
  const img = dex ? `<img src="${PokeSim.base}/sprites/${dex}.png?v=rom-portraits-1" alt="" loading="lazy">` : '<span class="plate-num">?</span>'
  return `<div class="plate plate--${size}">${img}</div>`
}
function side(mon, label) {
  return `<div class="swap-side">${sprite(mon)}<div class="swap-read"><p class="micro">${label}</p><h4>${esc(mon.nick || mon.name)}</h4><p class="swap-sub">${esc(mon.name)} · Lv. ${Number(mon.level) || '?'}</p>${mon.evolved_from ? `<p class="swap-note">Evolved from ${esc(mon.evolved_from)}</p>` : ''}</div></div>`
}
function deal(peer, state, send, receive, reason, foot = '') {
  return `<article class="deal trade-deal"><header class="deal-head"><h3>${peer}</h3>${state}</header><div class="swap">${send}<span class="swap-arrow" aria-hidden="true">→</span>${receive}</div><p class="deal-reason trade-reason">${esc(reason)}</p>${foot ? `<footer class="deal-foot">${foot}</footer>` : ''}</article>`
}
function head(title, count = '') {
  return `<div class="section-head"><h2 class="legend legend--ink">${title}</h2>${count ? `<span class="micro">${count}</span>` : ''}</div>`
}
// Portrait scaling is shared; see panel.js.
const fitSprites = (root) => globalThis.Panel?.fitSprites?.(root)
function render(status) {
  if (!status) return
  $('#status').textContent = status.connected ? 'Connected' : 'Reconnecting…'
  $('#connection').title = status.connected ? 'Adventures connected' : ''
  $('#connection').classList.toggle('is-offline', !status.connected)
  const trading = status.trading || {}
  const lamp = $('#trade-lamp')
  if (lamp) lamp.dataset.on = !status.connected ? 'crit' : status.holding ? 'signal' : trading.enabled ? 'ok' : 'warn'
  $('#trade-status').textContent = !status.connected ? 'Connection unavailable' : trading.enabled ? 'On · No approvals needed' : 'Off'
  const states = {ready: 'Watching for the next useful exchange.', waiting_for_overworld: 'Waiting for the adventures to finish their current activity.', waiting_for_opportunity: 'Waiting for a useful match.', retrying: 'Retrying after a trading interruption.'}
  $('#trade-activity').textContent = !status.connected ? 'Saved offers stay in place while we reconnect.' : !trading.enabled ? 'Offers are saved. Automatic trading is currently off.' : status.holding ? 'An exchange is in progress.' : states[trading.state] || 'Watching for the next useful exchange.'
  const peers = (status.peers || []).filter(peer => peer.error || !peer.started)
  const stale = trading.last_check && Date.now() / 1000 - trading.last_check > Math.max(300, trading.interval_seconds || 900) + 120
  const notice = !status.connected ? status.message : peers.length ? `${peers.map(peer => peer.instance).join(', ')} is unavailable. Trades will wait.` : stale ? 'The coordinator has not checked in recently. These are the last reported opportunities.' : status.viewer_only ? 'Viewing only. Offer controls are disabled for this game.' : ''
  $('#trade-connection-note').textContent = notice
  $('#trade-connection-note').hidden = !notice
  for (const button of document.querySelectorAll('#trade-tabs [role="tab"]')) {
    button.setAttribute('aria-selected', String(button.dataset.view === view))
    button.tabIndex = button.dataset.view === view ? 0 : -1
  }
  $('#trade-content').setAttribute('aria-labelledby', `tab-${view}`)
  $('#trade-search-row').hidden = view !== 'auto'
  history.replaceState(null, '', `${PokeSim.base}/trading?view=${view}`)
  const search = String($('#trade-search').value || '').trim().toLowerCase()
  const nextSignature = JSON.stringify([status, view, search])
  if (signature === nextSignature) return
  signature = nextSignature
  if (view === 'auto') {
    const all = status.offers || []
    const rows = all.filter(mon => !search || [mon.name, mon.nick, String(mon.dex || '')].some(value => String(value || '').toLowerCase().includes(search)))
    $('#trade-content').innerHTML = head('Trade settings', `${all.length} Pokémon`) + '<p class="trade-help"><b>Auto decides</b> may trade spare duplicates. <b>Trade first</b> goes before anything else. <b>Keep</b> is never traded automatically. Automatic trades also never take a shiny, a last copy or your active party.</p>' + (rows.length ? `<div class="auto-list">${rows.map(mon => `<div class="auto-row">${sprite(mon)}<span class="pick-read"><b>${esc(mon.nick || mon.name)}</b><span class="micro">${esc(mon.name)} · Lv. ${Number(mon.level)} · ${mon.box ? `Box ${Number(mon.box)} · Slot ${Number(mon.position)}` : 'Party'}</span></span>${TradeUI.control(mon.trade_key)}</div>`).join('')}</div>` : `<p class="empty-note">${all.length ? 'No Pokémon match this search.' : 'No Pokémon to set yet.'}</p>`)
  } else if (view === 'opportunities') {
    const rows = status.opportunities || []
    $('#trade-content').innerHTML = head('Possible exchanges', rows.length ? `${rows.length} ${rows.length === 1 ? 'match' : 'matches'}` : '') + '<p class="trade-help">Matches can change as both adventures progress. The coordinator checks availability again before trading.</p>' + (rows.length ? `<div class="deal-list">${rows.map(row => deal(`With ${esc(row.peer)}`, '<span class="tag">Potential match</span>', side(row.send, 'You send'), side(row.receive, 'You receive'), row.reason)).join('')}</div>` : '<p class="empty-note">No useful matches right now. Offers remain available as the collections grow.</p>')
  } else {
    const rows = status.history || []
    $('#trade-content').innerHTML = head('Previous exchanges', rows.length ? `${rows.length} completed` : '') + (rows.length ? `<div class="deal-list">${rows.map(row => deal(`Completed with ${esc(row.peer)}`, '<span class="tag tag--ok">Completed</span>', side(row.sent, 'You sent'), side(row.received, 'You received'), row.reason, `<time datetime="${new Date(row.ts * 1000).toISOString()}">${esc(new Date(row.ts * 1000).toLocaleString())}</time>`)).join('')}</div>` : '<p class="empty-note">Completed trades will appear here.</p>')
  }
  fitSprites(document.querySelector('#trade-content'))
}
function choose(next, focus = false) {
  view = next
  if (focus) $(`#tab-${view}`)?.focus()
  render(TradeUI.status())
}
$('#trade-tabs').onclick = event => {
  const button = event.target.closest('[data-view]')
  if (button) choose(button.dataset.view)
}
$('#trade-tabs').onkeydown = event => {
  const index = VIEWS.indexOf(view)
  const moves = {ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: VIEWS.length - 1}
  if (!(event.key in moves)) return
  event.preventDefault()
  choose(VIEWS[(moves[event.key] + VIEWS.length) % VIEWS.length], true)
}
$('#trade-content').onchange = event => {
  if (event.target.matches('select[data-trade-key]')) TradeUI.change(event.target)
}
$('#trade-search').oninput = () => render(TradeUI.status())
TradeUI.subscribe(render)
TradeUI.refresh()
setInterval(() => { if (!document.hidden) TradeUI.refresh() }, 15000)
