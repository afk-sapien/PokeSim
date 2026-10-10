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
    return `<div class="swap-side cable-mon cable-${direction}"><div class="plate plate--bay">${sprite}</div><div class="swap-read"><p class="micro">${label}${dex ? ` · #${String(dex).padStart(3, '0')}` : ''}${level}</p><h4>${name}</h4>${nickname}${evolution}</div></div>`
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
      setLamp(data.active.length ? 'signal' : !running ? 'warn' : data.attention ? 'warn' : 'ok')
      $('#trade-status').textContent = data.active.length ? 'Exchange in progress' : !running ? 'Waiting for this adventure'
        : data.attention ? 'Trades have not been completing' : 'On · No approvals needed'
      $('#trade-activity').textContent = data.active.length ? 'This adventure is trading. Other adventures keep playing.'
        : !running ? 'Trades resume when this adventure is running. Its history stays here.'
        : data.attention?.message || 'This adventure will trade when a useful exchange is ready.'
      $('#current-exchange-section').hidden = !data.active.length
      $('#trade-active').innerHTML = data.active.length ? data.active.map(trade => exchange(trade)).join('')
        : '<p class="empty-note">No exchange in progress for this adventure.</p>'
      const completed = data.history.filter(trade => trade.phase === 'completed' && trade.decision === 'COMMIT')
      $('#trade-history-count').textContent = `${completed.length}${completed.length === 20 ? '+' : ''} recent ${completed.length === 1 ? 'exchange' : 'exchanges'}`
      $('#trade-history').innerHTML = completed.length ? completed.map(trade => exchange(trade, true)).join('')
        : '<p class="empty-note">This adventure’s completed trades will appear here.</p>'
      const failures = data.recent_failures || []
      $('#trade-failures-section').hidden = !failures.length
      $('#trade-failures').innerHTML = failures.map(trade => exchange(trade)).join('')
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
  // Trade offers between adventures. Only the owner's /games/ page reaches the library API, never a view link.
  const OFFERS = '/api/v1/interactions/trade-offers'
  const offerOwner = String(PokeSim.base || '').startsWith('/games/') && typeof PokeSim.api === 'function'
  const offerLabels = {pending: 'Waiting for an answer', accepted: 'Accepted · Trading', declined: 'Declined', withdrawn: 'Withdrawn',
    expired: 'Expired', failed: 'Did not complete', completed: 'Trade completed'}
  const offerTones = {pending: 'tag--signal', accepted: 'tag--signal', completed: 'tag--ok', failed: 'tag--crit', expired: 'tag--crit'}
  let offerSignature = ''
  let offerBusy = false
  function offerSide(mon, label) {
    const sprite = mon.sprite_url ? `<img src="${esc(mon.sprite_url)}" alt="" loading="lazy">` : '<span class="plate-num" aria-hidden="true">?</span>'
    const nickname = mon.nickname && mon.nickname.toLowerCase() !== String(mon.name || '').toLowerCase()
      ? `<p class="swap-sub cable-nickname">“${esc(mon.nickname)}”</p>` : ''
    const level = Number.isInteger(mon.level) ? ` · Lv. ${mon.level}` : ''
    const power = [Number.isFinite(mon.battle_power) ? `Battle Power ${mon.battle_power.toLocaleString()}` : '',
      Number.isFinite(mon.power) ? `Stat Power ${mon.power.toLocaleString()}` : ''].filter(Boolean).join(' · ')
    return `<div class="swap-side offer-mon"><div class="plate plate--bay">${sprite}</div><div class="swap-read"><p class="micro">${label}${level}</p><h4>${esc(mon.name || 'Unknown Pokémon')}</h4>${nickname}<p class="swap-note">${esc(mon.adventure_name)}${power ? ` · ${esc(power)}` : ''}</p></div></div>`
  }
  function offerCard(offer, incoming, viewerOnly) {
    const mine = incoming ? offer.to : offer.from
    const theirs = incoming ? offer.from : offer.to
    const peer = `<a href="/games/${esc(theirs.adventure_id)}/trading">${esc(theirs.adventure_name)} <span aria-hidden="true">↗</span></a>`
    const lamp = ['pending', 'accepted'].includes(offer.status) ? '<i class="lamp lamp--blink" data-on="signal" aria-hidden="true"></i>' : ''
    const reason = offer.reason ? `<p class="deal-reason${['failed', 'expired'].includes(offer.status) ? ' deal-reason--crit' : ''}">${esc(offer.reason)}</p>` : ''
    const name = id => [offer.from, offer.to].find(side => side.adventure_id === id)?.adventure_name || 'An adventure'
    const progress = offer.trade && offer.status !== 'pending' ? globalThis.TradeProgress?.card(offer.trade, name) || '' : ''
    const actions = offer.status !== 'pending' || viewerOnly ? ''
      : incoming ? `<div class="offer-answer"><button type="button" class="key key--primary" data-offer-action="accept" data-offer-id="${esc(offer.id)}">Accept</button><button type="button" class="key" data-offer-action="decline" data-offer-id="${esc(offer.id)}">Decline</button></div>`
        : `<div class="offer-answer"><button type="button" class="key" data-offer-action="withdraw" data-offer-id="${esc(offer.id)}">Withdraw</button></div>`
    const date = new Date((offer.expires_at || offer.updated_at) * 1000)
    const when = Number.isFinite(date.getTime()) ? `<footer class="deal-foot"><time datetime="${date.toISOString()}">${offer.expires_at ? 'Expires ' : ''}${esc(date.toLocaleString())}</time></footer>` : ''
    return `<article class="deal trade-deal offer-card" data-offer="${esc(offer.id)}"><header class="deal-head"><h3>${incoming ? 'From' : 'To'} ${peer}</h3><span class="tag ${offerTones[offer.status] || ''} offer-status">${lamp}${esc(offerLabels[offer.status] || offer.status)}</span></header><div class="swap">${offerSide(mine, 'You send')}<span class="swap-arrow" aria-hidden="true">⇄</span>${offerSide(theirs, 'You receive')}</div>${reason}${progress}${actions}${when}</article>`
  }
  function renderOffers(data) {
    const key = JSON.stringify(data)
    if (key === offerSignature) return
    offerSignature = key
    const viewerOnly = Boolean(data.viewer_only)
    $('#trade-offers-section').hidden = false
    $('#offers-incoming').innerHTML = data.incoming.map(offer => offerCard(offer, true, viewerOnly)).join('')
      || '<p class="empty-note">No offers from other adventures yet.</p>'
    $('#offers-outgoing').innerHTML = data.outgoing.map(offer => offerCard(offer, false, viewerOnly)).join('')
      || '<p class="empty-note">Open a Pokémon in the PC and choose Offer trade.</p>'
    globalThis.Panel?.fitSprites?.($('#trade-offers-section'))
  }
  async function refreshOffers() {
    if (!offerOwner) return
    try {
      const response = await PokeSim.api(`${OFFERS}?adventure_id=${encodeURIComponent(PokeSim.adventureId)}`, {cache: 'no-store'})
      if (!response.ok) throw new Error('Unavailable')
      const data = await response.json()
      if (data.adventure_id !== PokeSim.adventureId) throw new Error('Wrong adventure')
      renderOffers(data)
    } catch (_) {
      if ($('#offers-note') && !offerBusy) $('#offers-note').textContent = offerSignature ? 'Offers are reconnecting.' : ''
    }
  }
  async function answerOffer(button) {
    if (offerBusy) return
    offerBusy = true
    button.disabled = true
    $('#offers-note').textContent = ''
    try {
      const response = await PokeSim.api(`${OFFERS}/${encodeURIComponent(button.dataset.offerId)}/${button.dataset.offerAction}`, {method: 'POST'})
      let data = {}
      try { data = await response.json() } catch (_) {}
      if (!response.ok) throw new Error(data.detail || 'That did not work. Try again in a moment.')
      if (data.status === 'expired' || data.status === 'failed') $('#offers-note').textContent = data.reason || 'This offer can no longer happen.'
    } catch (error) {
      $('#offers-note').textContent = error.message
    } finally {
      offerBusy = false
      offerSignature = ''
      await refreshOffers()
    }
  }
  const offersSection = $('#trade-offers-section')
  if (offersSection && offerOwner) offersSection.onclick = event => {
    const button = event.target.closest?.('[data-offer-action]')
    if (button && !button.disabled) answerOffer(button)
  }
  const poll = () => { refresh()
    refreshOffers() }
  poll()
  setInterval(() => { if (!document.hidden) poll() }, 5000)
  globalThis.AdventureTrading = {refreshOffers}
})()
