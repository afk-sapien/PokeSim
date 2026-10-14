const $ = selector => document.querySelector(selector)
const esc = TradeUI.esc
// One page: possible exchanges, then completed ones. Locks are set on the PC page,
// so an old ?view= link (auto, block, opportunities or history) lands here as well.
let signature = ''
function sprite(mon, size = 'bay') {
  const dex = Number(mon.dex) || 0
  const img = dex ? `<img src="${PokeSim.sprite(dex, Boolean(mon?.shiny))}" alt="" loading="lazy">` : '<span class="plate-num">?</span>'
  return `<div class="plate plate--${size}">${img}</div>`
}
function side(mon, label) {
  return `<div class="swap-side">${sprite(mon)}<div class="swap-read"><p class="micro">${label}</p><h4>${esc(mon.nick || mon.name)}</h4><p class="swap-sub">${esc(mon.name)}, Lv. ${Number(mon.level) || '?'}</p>${mon.evolved_from ? `<p class="swap-note">Evolved from ${esc(mon.evolved_from)}</p>` : ''}</div></div>`
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
  $('#trade-status').textContent = !status.connected ? 'Connection unavailable' : trading.enabled ? 'On, trades automatically' : 'Off'
  const states = {ready: 'Watching for the next useful exchange.', waiting_for_overworld: 'Waiting for the adventures to finish their current activity.', waiting_for_opportunity: 'Waiting for a useful match.', retrying: 'Retrying after a trading interruption.'}
  $('#trade-activity').textContent = !status.connected ? 'Saved offers stay in place while we reconnect.' : !trading.enabled ? 'Offers are saved. Automatic trading is currently off.' : status.holding ? 'An exchange is in progress.' : states[trading.state] || 'Watching for the next useful exchange.'
  const peers = (status.peers || []).filter(peer => peer.error || !peer.started)
  const stale = trading.last_check && Date.now() / 1000 - trading.last_check > Math.max(300, trading.interval_seconds || 900) + 120
  const notice = !status.connected ? status.message : peers.length ? `${peers.map(peer => peer.instance).join(', ')} is unavailable. Trades will wait.` : stale ? 'The coordinator has not checked in recently. These are the last reported opportunities.' : status.viewer_only ? 'Viewing only. Offer controls are disabled for this game.' : ''
  $('#trade-connection-note').textContent = notice
  $('#trade-connection-note').hidden = !notice
  const nextSignature = JSON.stringify(status)
  if (signature === nextSignature) return
  signature = nextSignature
  const matches = status.opportunities || []
  const done = status.history || []
  $('#trade-content').innerHTML = head('Possible exchanges', matches.length ? `${matches.length} ${matches.length === 1 ? 'match' : 'matches'}` : '') + '<p class="trade-help">Every Pokémon can be traded unless it is locked on the <a href="' + PokeSim.base + '/pc">PC page</a>. Matches can change as both adventures progress. The coordinator checks availability again before trading.</p>' + (matches.length ? `<div class="deal-list">${matches.map(row => deal(`With ${esc(row.peer)}`, '<span class="tag">Potential match</span>', side(row.send, 'You send'), side(row.receive, 'You receive'), row.reason)).join('')}</div>` : '<p class="empty-note">No useful matches right now. Offers remain available as the collections grow.</p>')
    + head('History', done.length ? `${done.length} completed` : '') + (done.length ? `<div class="deal-list">${done.map(row => deal(`Completed with ${esc(row.peer)}`, '<span class="tag tag--ok">Completed</span>', side(row.sent, 'You sent'), side(row.received, 'You received'), row.reason, `<time datetime="${new Date(row.ts * 1000).toISOString()}">${esc(new Date(row.ts * 1000).toLocaleString())}</time>`)).join('')}</div>` : '<p class="empty-note">Completed trades will appear here.</p>')
  fitSprites(document.querySelector('#trade-content'))
}
TradeUI.subscribe(render)
TradeUI.refresh()
setInterval(() => { if (!document.hidden) TradeUI.refresh() }, 15000)
