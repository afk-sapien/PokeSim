(() => {
  const $ = selector => document.querySelector(selector)
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp', '<': '&lt', '>': '&gt', '"': '&quot', "'": '&#39'}[char] + String.fromCharCode(59)))
  const OFFERS = '/api/v1/interactions/trade-offers'
  const SETTINGS = '/api/v1/interactions/auto-settings'
  const CABLE = '/api/v1/interactions/cable-sessions'
  const STORE = 'pokesim-trading-tab'
  const aid = PokeSim.adventureId
  const owner = String(PokeSim.base || '').startsWith('/games/') && typeof PokeSim.api === 'function'
  const query = new URLSearchParams(location.search)

  // Tabs: one selected at a time, arrow keys move between the enabled ones.
  const tabs = [...document.querySelectorAll('.trade-tabs [role="tab"]')]
  const enabled = () => tabs.filter(tab => !tab.disabled && tab.getAttribute('aria-disabled') !== 'true')
  function select(name, focus = false) {
    const target = enabled().find(tab => tab.id === `tab-${name}`) || enabled()[0]
    if (!target) return
    for (const tab of tabs) {
      const on = tab === target
      tab.setAttribute('aria-selected', String(on))
      tab.tabIndex = on ? 0 : -1
      const panel = tab.getAttribute('aria-controls') && document.getElementById(tab.getAttribute('aria-controls'))
      if (panel) panel.hidden = !on
    }
    if (focus) target.focus()
    const current = target.id.slice(4)
    try { localStorage.setItem(STORE, current) } catch (_) {}
    if (current === 'auto') loadAuto()
    if (current === 'offers') globalThis.AdventureTrading?.refreshOffers?.(true)
    if (current === 'cable') loadCable()
  }
  for (const tab of tabs) {
    tab.addEventListener('click', () => { if (!tab.disabled) select(tab.id.slice(4)) })
    tab.addEventListener('keydown', event => {
      const list = enabled()
      const index = list.indexOf(tab)
      const moves = {ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: list.length - 1}
      if (!(event.key in moves)) return
      event.preventDefault()
      const next = list[(moves[event.key] + list.length) % list.length]
      select(next.id.slice(4), true)
    })
  }

  // Trade: your Pokémon, then a game, then their Pokémon, then confirm.
  const pick = {mine: [], mon: null, game: null, theirs: [], their: null, limits: null, busy: false, viewerOnly: false}
  const note = (selector, text) => { const el = $(selector)
    if (!el) return
    el.textContent = text || ''
    el.hidden = !text }
  const matches = (mon, text) => !text || [mon.name, mon.nickname, mon.dex && String(mon.dex), mon.dex && `#${String(mon.dex).padStart(3, '0')}`]
    .some(value => value && String(value).toLowerCase().includes(text))
  const place = mon => mon.box ? `Box ${mon.box}` : 'Party'
  function monButton(mon, chosen, mine) {
    const sprite = mon.sprite_url ? `<img src="${esc(mon.sprite_url)}" alt="" loading="lazy">` : '<span class="plate-num" aria-hidden="true">?</span>'
    const nickname = mon.nickname && mon.nickname.toLowerCase() !== String(mon.name || '').toLowerCase() ? ` “${esc(mon.nickname)}”` : ''
    const level = Number.isInteger(mon.level) ? `Lv. ${mon.level}` : ''
    const meta = [level, place(mon), mon.shiny ? 'Shiny' : ''].filter(Boolean).join(' · ')
    const blocked = mon.blocked ? `<span class="pick-reason">${esc(mon.blocked)}</span>` : ''
    const off = mon.blocked || (mine && pick.viewerOnly)
    return `<button type="button" class="pick-item" role="radio" aria-checked="${chosen ? 'true' : 'false'}" data-key="${esc(mon.key)}"${off ? ' aria-disabled="true" disabled' : ''}><span class="plate pick-plate">${sprite}</span><span class="pick-read"><b>${esc(mon.name || 'Unknown Pokémon')}${nickname}</b><span class="micro">${esc(meta)}</span>${blocked}</span></button>`
  }
  function renderList(selector, rows, chosen, search) {
    const text = String($(search)?.value || '').trim().toLowerCase()
    const shown = rows.filter(mon => matches(mon, text))
    // A view-only adventure lists its own Pokémon but cannot send them, on every render.
    $(selector).innerHTML = shown.map(mon => monButton(mon, mon.key === chosen, selector === '#pick-mine')).join('')
      || `<p class="empty-note">${rows.length ? 'No Pokémon match this search.' : 'No Pokémon to trade here.'}</p>`
    globalThis.Panel?.fitSprites?.($(selector))
  }
  function show(step, on) { const el = $(step)
    if (el) el.hidden = !on }
  function reset(keepMine = false) {
    if (!keepMine) pick.mon = null
    pick.game = null
    pick.theirs = []
    pick.their = null
    pick.limits = null
    show('#pick-game-step', Boolean(pick.mon))
    show('#pick-theirs-step', false)
    show('#pick-confirm-step', false)
    renderList('#pick-mine', pick.mine, pick.mon?.key, '#pick-mine-search')
  }
  async function json(response, fallback) {
    let data = {}
    try { data = await response.json() } catch (_) {}
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : fallback)
    return data
  }
  async function loadMine() {
    if (!owner) {
      $('#pick-mine').innerHTML = '<p class="empty-note">Trades are picked from the owner’s page, not from a view link.</p>'
      $('#pick-mine-search').disabled = true
      return
    }
    try {
      const data = await json(await PokeSim.api(`${OFFERS}/pokemon?adventure_id=${encodeURIComponent(aid)}`, {cache: 'no-store'}), 'Could not read this adventure’s Pokémon.')
      pick.mine = data.pokemon || []
      pick.viewerOnly = Boolean(data.viewer_only)
      $('#pick-mine-count').textContent = pick.mine.length ? `${pick.mine.length} Pokémon` : ''
      if (data.viewer_only) note('#pick-note', 'This adventure is view-only. It can receive offers but cannot send them.')
      else note('#pick-note', data.reason || '')
      const wanted = query.get('mon')
      const first = wanted && pick.mine.find(mon => mon.key === wanted)
      if (first && !first.blocked && !data.viewer_only) {
        renderList('#pick-mine', pick.mine, null, '#pick-mine-search')
        await chooseMine(first.key)
      } else reset()
    } catch (error) {
      $('#pick-mine').innerHTML = `<p class="empty-note">${esc(error.message)}</p>`
    }
  }
  async function chooseMine(key) {
    const mon = pick.mine.find(row => row.key === key)
    if (!mon || mon.blocked || pick.viewerOnly) return
    pick.mon = mon
    reset(true)
    note('#pick-note', '')
    $('#pick-games').innerHTML = '<p class="empty-note">Checking which games can take it…</p>'
    try {
      const data = await json(await PokeSim.api(`${OFFERS}/targets?from_id=${encodeURIComponent(aid)}&from_key=${encodeURIComponent(key)}`, {cache: 'no-store'}), 'Could not check the other games.')
      // A slower answer for a Pokémon picked earlier must not show its reasons for this one.
      if (pick.mon?.key !== key || (data.from_key !== undefined && data.from_key !== key)) return
      const games = data.adventures || []
      $('#pick-games').innerHTML = games.map(game => `<button type="button" class="pick-item pick-game" role="radio" aria-checked="false" data-game="${esc(game.id)}"${game.available ? '' : ' aria-disabled="true" disabled'}><span class="pick-read"><b>${esc(game.name)}</b><span class="micro">${esc(game.version)}</span>${game.available ? '' : `<span class="pick-reason">${esc(game.reason)}</span>`}</span></button>`).join('')
        || '<p class="empty-note">There is no other adventure to trade with yet.</p>'
      $('#pick-game-step').scrollIntoView?.({block: 'nearest'})
    } catch (error) {
      if (pick.mon?.key !== key) return
      $('#pick-games').innerHTML = `<p class="empty-note">${esc(error.message)}</p>`
    }
  }
  async function chooseGame(id) {
    pick.game = id
    pick.their = null
    for (const button of document.querySelectorAll('#pick-games [data-game]')) button.setAttribute('aria-checked', String(button.dataset.game === id))
    show('#pick-confirm-step', false)
    show('#pick-theirs-step', true)
    $('#pick-theirs').innerHTML = '<p class="empty-note">Reading their Pokémon…</p>'
    try {
      const data = await json(await PokeSim.api(`${OFFERS}/limits?from_id=${encodeURIComponent(aid)}&from_key=${encodeURIComponent(pick.mon.key)}&to_id=${encodeURIComponent(id)}`, {cache: 'no-store'}), 'Could not read their Pokémon.')
      if (pick.game !== id) return
      pick.limits = data
      pick.theirs = data.pokemon || []
      $('#pick-theirs-count').textContent = pick.theirs.length ? `${pick.theirs.length} Pokémon` : ''
      renderList('#pick-theirs', pick.theirs, null, '#pick-theirs-search')
    } catch (error) {
      $('#pick-theirs').innerHTML = `<p class="empty-note">${esc(error.message)}</p>`
    }
  }
  function chooseTheirs(key) {
    const mon = pick.theirs.find(row => row.key === key)
    if (!mon || mon.blocked) return
    pick.their = mon
    renderList('#pick-theirs', pick.theirs, key, '#pick-theirs-search')
    const offer = globalThis.AdventureTrading?.offerSide
    const side = (row, label) => offer ? offer(row, label) : `<p>${esc(label)}: ${esc(row.name)}</p>`
    const now = Boolean(pick.limits?.starts_now)
    $('#pick-summary').innerHTML = `<div class="swap">${side(pick.mon, 'You send')}<span class="swap-arrow" aria-hidden="true">⇄</span>${side(mon, 'You receive')}</div><p class="trade-help">${now
      ? 'You control both adventures, so the trade starts as soon as both games are ready.'
      : `${esc(pick.limits?.to?.adventure_name || 'The other adventure')} is view-only, so this becomes an offer its owner answers.`}</p>`
    $('#pick-confirm').textContent = now ? 'Trade now' : 'Send offer'
    $('#pick-confirm').disabled = false
    show('#pick-confirm-step', true)
    globalThis.Panel?.fitSprites?.($('#pick-summary'))
    $('#pick-confirm-step').scrollIntoView?.({block: 'nearest'})
  }
  async function confirm() {
    if (pick.busy || !pick.mon || !pick.their) return
    pick.busy = true
    $('#pick-confirm').disabled = true
    const request = globalThis.crypto?.randomUUID ? crypto.randomUUID().replace(/-/g, '') : undefined
    try {
      const offer = await json(await PokeSim.api(OFFERS, {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({from_id: aid, from_key: pick.mon.key, to_id: pick.game, to_key: pick.their.key, ...(request ? {request_id: request} : {})})}),
      'That trade could not be set up.')
      note('#pick-note', offer.status === 'accepted' ? 'Trade started. Follow it on the Offers tab.'
        : 'Offer sent. It waits on the Offers tab until it is answered.')
      reset()
      await globalThis.AdventureTrading?.refreshOffers?.(true)
      select('offers')
    } catch (error) {
      note('#pick-note', error.message)
      $('#pick-confirm').disabled = false
    } finally { pick.busy = false }
  }
  const radio = (selector, handler) => { const el = $(selector)
    if (el) el.addEventListener('click', event => {
      const button = event.target.closest?.('.pick-item')
      if (button && !button.disabled) handler(button)
    }) }
  radio('#pick-mine', button => chooseMine(button.dataset.key))
  radio('#pick-games', button => chooseGame(button.dataset.game))
  radio('#pick-theirs', button => chooseTheirs(button.dataset.key))
  $('#pick-mine-search')?.addEventListener('input', () => renderList('#pick-mine', pick.mine, pick.mon?.key, '#pick-mine-search'))
  $('#pick-theirs-search')?.addEventListener('input', () => renderList('#pick-theirs', pick.theirs, pick.their?.key, '#pick-theirs-search'))
  $('#pick-confirm')?.addEventListener('click', confirm)
  $('#pick-reset')?.addEventListener('click', () => { note('#pick-note', '')
    reset() })

  // Auto: the on or off switch, the wish list and one setting per Pokémon.
  let auto = null
  let autoBusy = false
  let autoLoaded = false
  function renderAuto() {
    if (!auto) return
    const locked = auto.viewer_only || autoBusy
    const switcher = $('#auto-switch')
    switcher.setAttribute('aria-checked', String(auto.enabled))
    switcher.disabled = locked
    $('#auto-switch-state').textContent = auto.enabled ? 'On' : 'Off'
    $('#wish-input').disabled = locked
    $('#wish-add').disabled = locked
    $('#wish-species').innerHTML = auto.species.map(row => `<option value="${esc(row.name)}">No. ${row.dex}</option>`).join('')
    $('#wish-list').innerHTML = auto.wishes.map(row => `<li class="wish"><span>${esc(row.name)} <span class="micro">No. ${row.dex}</span></span><button type="button" class="key wish-remove" data-dex="${row.dex}" aria-label="Remove ${esc(row.name)} from the wish list"${locked ? ' disabled' : ''}>Remove</button></li>`).join('')
      || '<li class="empty-note">No wishes yet. Automatic trading picks useful trades on its own.</li>'
  }
  async function saveAuto(change, message) {
    if (autoBusy || !auto) return
    autoBusy = true
    renderAuto()
    try {
      auto = await json(await PokeSim.api(`${SETTINGS}?adventure_id=${encodeURIComponent(aid)}`, {method: 'PUT', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(change)}),
        'Could not save this setting.')
      note('#auto-note', message(auto))
      globalThis.AdventureTrading?.refresh?.()
    } catch (error) {
      note('#auto-note', error.message)
    } finally {
      autoBusy = false
      renderAuto()
    }
  }
  async function loadAuto() {
    if (autoLoaded) return
    autoLoaded = true
    globalThis.TradeUI?.refresh?.()
    if (!owner) {
      note('#auto-note', 'Automatic trading is set from the owner’s page, not from a view link.')
      for (const el of document.querySelectorAll('#auto-switch, #wish-input, #wish-add')) el.disabled = true
      return
    }
    try {
      auto = await json(await PokeSim.api(`${SETTINGS}?adventure_id=${encodeURIComponent(aid)}`, {cache: 'no-store'}), 'Could not read the automatic trading settings.')
      if (auto.viewer_only) note('#auto-note', 'This adventure is view-only. Its trading settings cannot be changed here.')
      renderAuto()
    } catch (error) {
      autoLoaded = false
      note('#auto-note', error.message)
    }
  }
  $('#auto-switch')?.addEventListener('click', () => {
    if (!auto) return
    const enabled = !auto.enabled
    saveAuto({enabled}, data => data.enabled ? 'Auto trading is on.' : 'Auto trading is off. Trades you pick yourself still happen.')
  })
  $('#wish-form')?.addEventListener('submit', event => {
    event.preventDefault()
    if (!auto) return
    const text = String($('#wish-input').value || '').trim().toLowerCase().replace(/^no\.\s*|^#/, '')
    const found = auto.species.find(row => row.name.toLowerCase() === text || String(row.dex) === String(Number(text)))
    if (!found) return note('#auto-note', 'Choose a species from the list.')
    if (auto.wishlist.includes(found.dex)) return note('#auto-note', `${found.name} is already on the wish list.`)
    $('#wish-input').value = ''
    saveAuto({wishlist: [...auto.wishlist, found.dex]}, () => `${found.name} added to the wish list.`)
  })
  $('#wish-list')?.addEventListener('click', event => {
    const button = event.target.closest?.('.wish-remove')
    if (!button || button.disabled || !auto) return
    const dex = Number(button.dataset.dex)
    saveAuto({wishlist: auto.wishlist.filter(value => value !== dex)}, () => 'Removed from the wish list.')
  })
  function renderSettings(status) {
    const list = $('#auto-list')
    if (!list) return
    // Settings save in the adventure itself, so they work while trading is offline, not while it is stopped.
    if (!status || status.unreachable || !Array.isArray(status.offers)) {
      list.innerHTML = '<p class="empty-note">Start this adventure to change its trade settings.</p>'
      $('#auto-count').textContent = ''
      return
    }
    const rows = status.offers || []
    const text = String($('#auto-search')?.value || '').trim().toLowerCase()
    const shown = rows.filter(mon => matches({name: mon.name, nickname: mon.nick, dex: mon.dex}, text))
    $('#auto-count').textContent = rows.length ? `${rows.length} Pokémon` : ''
    list.innerHTML = shown.map(mon => {
      const name = mon.nick && mon.nick.toLowerCase() !== String(mon.name || '').toLowerCase() ? `${mon.name} “${mon.nick}”` : mon.name
      const meta = [Number.isInteger(mon.level) ? `Lv. ${mon.level}` : '', mon.box ? `Box ${mon.box}` : 'Party',
        mon.shiny ? 'Shiny' : '', mon.perfect_dvs ? 'Perfect' : ''].filter(Boolean).join(' · ')
      return `<div class="auto-row"><span class="pick-read"><b>${esc(name || 'Unknown Pokémon')}</b><span class="micro">${esc(meta)}</span></span>${TradeUI.control(mon.trade_key, mon.nick || mon.name)}</div>`
    }).join('') || `<p class="empty-note">${rows.length ? 'No Pokémon match this search.' : 'No Pokémon to set yet.'}</p>`
  }
  if (globalThis.TradeUI) {
    TradeUI.subscribe(renderSettings)
    $('#auto-list')?.addEventListener('change', event => {
      if (event.target.matches?.('select[data-trade-key]')) TradeUI.change(event.target)
    })
    $('#auto-search')?.addEventListener('input', () => renderSettings(TradeUI.status()))
  }

  // Cable Club: link with another adventure and hold both controllers on the Cable Club page.
  let cableLoaded = false
  const cableHref = id => `${PokeSim.base}/cable?with=${encodeURIComponent(id)}`
  async function loadCable() {
    if (cableLoaded) return
    cableLoaded = true
    const list = $('#cable-games')
    try {
      const mine = await json(await PokeSim.fetch(`/api/cable`, {cache: 'no-store'}), 'Could not read the Cable Club.')
      const open = mine.session && !['done', 'rolled_back'].includes(mine.session.phase)
      const partner = open && (mine.session.left_id === aid ? mine.session.right_id : mine.session.left_id)
      const link = $('#cable-open')
      link.innerHTML = open ? `<a class="key key--primary" href="${esc(cableHref(partner))}">Open the session in progress</a>` : ''
      link.hidden = !open
      if (!owner) {
        note('#cable-note', 'Cable Club sessions are started from the owner’s page, not from a view link.')
        list.innerHTML = ''
        return
      }
      note('#cable-note', mine.reason || '')
      const data = await json(await PokeSim.api(`${CABLE}/partners?adventure_id=${encodeURIComponent(aid)}`, {cache: 'no-store'}), 'Could not check the other games.')
      list.innerHTML = (data.partners || []).map(game => {
        const read = `<span class="pick-read"><b>${esc(game.name)}</b><span class="micro">${esc(game.version)}</span>${game.reason ? `<span class="pick-reason">${esc(game.reason)}</span>` : ''}</span>`
        return game.reason
          ? `<span class="pick-item pick-game is-unavailable" data-cable="${esc(game.id)}" aria-disabled="true">${read}</span>`
          : `<a class="pick-item pick-game" data-cable="${esc(game.id)}" href="${esc(cableHref(game.id))}">${read}</a>`
      }).join('') || '<p class="empty-note">There is no other adventure to link with yet.</p>'
    } catch (error) {
      cableLoaded = false
      list.innerHTML = `<p class="empty-note">${esc(error.message)}</p>`
    }
  }

  // Deep links (?tab=trade&mon=key) win over the remembered tab.
  let saved = null
  try { saved = localStorage.getItem(STORE) } catch (_) {}
  select(query.get('tab') || (query.get('mon') ? 'trade' : saved) || 'trade')
  loadMine()
  globalThis.TradeTabs = {select}
})()
