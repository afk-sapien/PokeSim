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
  // Trade offers: one adventure asks another, often someone else's, for a trade. Accepting queues it.
  const OFFERS = '/api/v1/interactions/trade-offers'
  const offerLabels = {pending: 'Waiting for an answer', accepted: 'Accepted, waiting for the Cable Club', declined: 'Declined',
    withdrawn: 'Cancelled', expired: 'Expired', failed: 'Did not complete', completed: 'Trade completed'}
  const offerTones = {pending: 'tag--signal', accepted: 'tag--signal', completed: 'tag--ok', failed: 'tag--crit', expired: 'tag--crit'}
  let offerData = null
  let offerSignature = ''
  let offerBusy = false
  // The offer being accepted: its id, the Pokémon picked to give, and a change the receiver must confirm.
  let asking = null
  const offerNote = text => { const el = $('#offers-note')
    if (el) el.textContent = text || '' }
  function offerSide(mon, label) {
    if (!mon?.name) return `<div class="swap-side offer-mon"><div class="plate plate--bay plate--empty"><span class="plate-num" aria-hidden="true">?</span></div><div class="swap-read"><p class="micro">${label}</p><h4>Your pick</h4><p class="swap-sub">Choose one of your Pokémon when you accept.</p></div></div>`
    const dex = dexNumber(mon)
    const sprite = mon.sprite_url ? `<img src="${esc(mon.sprite_url)}" alt="" loading="lazy">`
      : dex ? `<img src="${esc(PokeSim.sprite(dex, Boolean(mon.shiny)))}" alt="" loading="lazy">` : '<span class="plate-num" aria-hidden="true">?</span>'
    const nickname = mon.nickname && mon.nickname.toLowerCase() !== String(mon.name).toLowerCase()
      ? `<p class="swap-sub cable-nickname">“${esc(mon.nickname)}”</p>` : ''
    const level = Number.isInteger(mon.level) && mon.level > 0 && mon.level <= 100 ? `, Lv. ${mon.level}` : ''
    return `<div class="swap-side offer-mon"><div class="plate plate--bay${plateClass(mon)}">${sprite}</div><div class="swap-read"><p class="micro">${label}${dex ? `, #${String(dex).padStart(3, '0')}` : ''}${level}</p><h4>${esc(mon.name)}</h4>${nickname}${stamps(mon)}</div></div>`
  }
  function offerCard(offer, incoming, viewerOnly) {
    const mine = incoming ? offer.to : offer.from
    const theirs = incoming ? offer.from : offer.to
    const peer = `${esc(theirs.adventure_name)}${theirs.owner_name ? ` <span class="offer-owner">(${esc(theirs.owner_name)})</span>` : ''}`
    const lamp = ['pending', 'accepted'].includes(offer.status) ? '<i class="lamp lamp--blink" data-on="signal" aria-hidden="true"></i>' : ''
    const reason = offer.reason ? `<p class="deal-reason${['failed', 'expired'].includes(offer.status) ? ' deal-reason--crit' : ''}">${esc(offer.reason)}</p>` : ''
    const id = esc(offer.id)
    const button = (action, label, primary = false) => `<button type="button" class="key${primary ? ' key--primary' : ''}" data-offer-action="${action}" data-offer-id="${id}">${label}</button>`
    let actions = ''
    if (offer.status === 'pending' && !viewerOnly) {
      if (!incoming) actions = `<div class="offer-answer">${button('cancel', 'Cancel')}</div>`
      else if (asking?.id === offer.id) {
        actions = `<p class="deal-reason offer-confirm">${asking.changed ? `${esc(asking.changed)} ` : ''}Trades cannot be undone. Trade now?</p>`
          + `<div class="offer-answer">${button('confirm', 'Trade now', true)}${button('back', 'Back')}</div>`
      } else actions = `<div class="offer-answer">${button('accept', 'Accept', true)}${button('decline', 'Decline')}</div>`
    }
    const date = new Date((offer.expires_at || offer.updated_at) * 1000)
    const when = Number.isFinite(date.getTime()) ? `<footer class="deal-foot"><time datetime="${date.toISOString()}">${offer.expires_at ? 'Expires ' : ''}${esc(date.toLocaleString())}</time></footer>` : ''
    const chosen = asking?.id === offer.id && asking.mon ? asking.mon : mine
    return `<article class="deal trade-deal offer-card" data-offer="${id}"><header class="deal-head"><h3>${incoming ? 'From' : 'To'} ${peer}</h3><span class="tag ${offerTones[offer.status] || ''} offer-status">${lamp}${esc(offerLabels[offer.status] || offer.status)}</span></header><div class="swap">${offerSide(chosen, 'You send')}<span class="swap-arrow" aria-hidden="true">⇄</span>${offerSide(theirs, 'You receive')}</div>${reason}${actions}${when}</article>`
  }
  function renderOffers(force = false) {
    if (!offerData) return
    const key = JSON.stringify([offerData, asking])
    if (key === offerSignature && !force) return
    offerSignature = key
    const viewerOnly = Boolean(offerData.viewer_only)
    $('#offers-incoming').innerHTML = offerData.incoming.map(offer => offerCard(offer, true, viewerOnly)).join('')
      || '<p class="empty-note">No offers yet.</p>'
    $('#offers-outgoing').innerHTML = offerData.outgoing.map(offer => offerCard(offer, false, viewerOnly)).join('')
      || '<p class="empty-note">Offers you send from Make a trade show here.</p>'
    // The tab counts offers still open: waiting for an answer or for the Cable Club.
    const open = [...offerData.incoming, ...offerData.outgoing].filter(offer => ['pending', 'accepted'].includes(offer.status)).length
    const count = $('#offers-count')
    if (count) {
      count.textContent = open ? `(${open})` : ''
      count.setAttribute?.('aria-label', `${open} open ${open === 1 ? 'offer' : 'offers'}`)
    }
    globalThis.Panel?.fitSprites?.($('#trade-offers-section'))
  }
  async function refreshOffers() {
    if (!owner()) {
      if ($('#offers-incoming')) $('#offers-incoming').innerHTML = '<p class="empty-note">Offers are answered from the owner’s page, not from a view link.</p>'
      return
    }
    try {
      const response = await PokeSim.api(`${OFFERS}?adventure_id=${encodeURIComponent(PokeSim.adventureId)}`, {cache: 'no-store'})
      if (response.status === 403 || response.status === 404) {
        $('#offers-incoming').innerHTML = '<p class="empty-note">Offers are answered by the people who manage this adventure.</p>'
        return
      }
      if (!response.ok) throw new Error('Unavailable')
      const data = await response.json()
      if (data.adventure_id !== PokeSim.adventureId) throw new Error('Wrong adventure')
      offerData = data
      // An offer answered somewhere else drops its confirm question.
      if (asking && !data.incoming.some(offer => offer.id === asking.id && offer.status === 'pending')) asking = null
      renderOffers()
    } catch (_) {
      if (!offerBusy) offerNote(offerData ? 'Offers are reconnecting.' : '')
    }
  }
  const findOffer = id => offerData?.incoming.find(offer => offer.id === id)
  // Accepting asks first. An offer that asks for nothing opens the picker of this adventure's Pokémon.
  function askAccept(id, mon = null) {
    const offer = findOffer(id)
    if (!offer) return
    if (!offer.to.key && !mon) {
      globalThis.TradeTabs?.pickToGive?.(picked => askAccept(id, picked))
      return
    }
    asking = {id, key: mon?.key || null, mon, confirm: false, changed: ''}
    offerNote('')
    renderOffers()
  }
  async function answerOffer(id, action) {
    if (offerBusy) return
    if (action === 'accept') return askAccept(id)
    if (action === 'back') {
      asking = null
      return renderOffers()
    }
    offerBusy = true
    offerNote('')
    const confirming = action === 'confirm' && asking?.id === id ? asking : null
    const path = confirming ? 'accept' : action
    const body = confirming ? {...(confirming.key ? {to_key: confirming.key} : {}), confirm: confirming.confirm} : null
    try {
      const response = await PokeSim.api(`${OFFERS}/${encodeURIComponent(id)}/${path}`, {method: 'POST',
        ...(body ? {headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)} : {})})
      let data = {}
      try { data = await response.json() } catch (_) {}
      // A Pokémon that changed since the offer was sent asks once more, with the change shown.
      if (response.status === 409 && data.changed && confirming) {
        asking = {...confirming, confirm: true, changed: typeof data.detail === 'string' ? data.detail : 'A Pokémon in this offer changed.'}
        return
      }
      if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : 'That did not work. Try again in a moment.')
      asking = null
      if (data.status === 'expired' || data.status === 'failed') offerNote(data.reason || 'This offer can no longer happen.')
      else if (data.status === 'accepted') offerNote('Accepted. The trade waits in line under Current exchange.')
      refresh()
    } catch (error) {
      offerNote(error.message)
    } finally {
      offerBusy = false
      offerSignature = ''
      await refreshOffers()
      renderOffers(true)
    }
  }
  $('#trade-offers-section')?.addEventListener('click', event => {
    const button = event.target.closest?.('[data-offer-action]')
    if (button && !button.disabled && owner()) answerOffer(button.dataset.offerId, button.dataset.offerAction)
  })

  // Offers refresh on every second poll, so every 10 s.
  let ticks = 0
  const poll = () => {
    refresh()
    if (ticks++ % 2 === 0 && !offerBusy) refreshOffers()
  }
  poll()
  setInterval(() => { if (!document.hidden) poll() }, 5000)
  globalThis.AdventureTrading = {refresh, exchange, refreshOffers}
})()
