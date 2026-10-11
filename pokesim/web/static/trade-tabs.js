(() => {
  const $ = selector => document.querySelector(selector)
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp', '<': '&lt', '>': '&gt', '"': '&quot', "'": '&#39'}[char] + String.fromCharCode(59)))
  const BUILDER = '/api/v1/interactions/trade-builder'
  const SETTINGS = '/api/v1/interactions/auto-settings'
  const STORE = 'pokesim-trading-tab'
  const aid = PokeSim.adventureId
  const owner = String(PokeSim.base || '').startsWith('/games/') && typeof PokeSim.api === 'function'
  const query = new URLSearchParams(location.search)

  // Tabs: one selected at a time, arrow keys move between them.
  const tabs = [...document.querySelectorAll('.trade-tabs [role="tab"]')]
  function select(name, focus = false) {
    const target = tabs.find(tab => tab.id === `tab-${name}`) || tabs[0]
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
  }
  for (const tab of tabs) {
    tab.addEventListener('click', () => select(tab.id.slice(4)))
    tab.addEventListener('keydown', event => {
      const index = tabs.indexOf(tab)
      const moves = {ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: tabs.length - 1}
      if (!(event.key in moves)) return
      event.preventDefault()
      const next = tabs[(moves[event.key] + tabs.length) % tabs.length]
      select(next.id.slice(4), true)
    })
  }

  // Pokémon cards: the same grid, filters and detail popup as the PC page (mon-grid.js).
  const Grid = globalThis.MonGrid
  for (const holder of document.querySelectorAll('[data-mon-toolbar]')) {
    if (Grid) holder.outerHTML = Grid.toolbar(holder.dataset.monToolbar, {settings: holder.dataset.settings === 'true'})
  }
  const fit = root => globalThis.Panel?.fitSprites?.(root)
  // Full PC records, by trade key, so cards show types, DVs, moves and stats.
  async function records(path, viaApi) {
    try {
      const response = viaApi ? await PokeSim.api(path, {cache: 'no-store'}) : await PokeSim.fetch(path, {cache: 'no-store'})
      if (!response.ok) return null
      const status = await response.json()
      const map = new Map()
      for (const record of [...(status.party || []), ...(status.storage?.pokemon || [])]) {
        if (record.trade_key) map.set(record.trade_key, record)
      }
      return {map, generation: status.generation}
    } catch (_) { return null }
  }
  let ownRecords = null
  let ownRecordsRead = null
  function readOwn(force = false) {
    if (!ownRecordsRead || force) ownRecordsRead = records('/api/pokedex/status?view=pc', false).then(found => {
      if (found) ownRecords = found
      return ownRecords
    })
    return ownRecordsRead
  }
  // One card's data: the PC record when there is one, else the row the trade API sent.
  function entry(row, found) {
    const record = found?.map?.get(row.key)
    const party = row.location === 'party' || !row.box
    const plain = {nick: row.nickname || row.name, name: row.name || 'Unknown Pokémon', dex: row.dex, level: row.level,
      shiny: Boolean(row.shiny), egg: Boolean(row.egg) || row.name === 'Egg', type_names: row.type_names || [],
      dv_stars: row.dv_stars ?? null, dv_total: row.dv_total, dv_percent: row.dv_percent, perfect_dvs: Boolean(row.perfect_dvs),
      power: row.power, battle_power: row.battle_power, trade_key: row.key}
    const mon = globalThis.PokemonTypes?.asEgg ? PokemonTypes.asEgg({...plain, ...(record || {})}) : {...plain, ...(record || {})}
    const box = party ? 0 : row.box
    const position = row.slot ?? record?.position ?? record?.slot
    return {...mon, box, position, key: row.key, row,
      slot: `${box === 0 ? 'PARTY' : `BOX ${box}`}${position ? ` · SLOT ${position}` : ''}`}
  }
  // The trade setting of one of this adventure's Pokémon, as automatic trading reads it.
  function ownSetting(mon) {
    const offer = globalThis.TradeUI?.find?.(mon.key || mon.trade_key)
    if (offer) return offer.shiny || offer.perfect_dvs ? 'protected' : offer.setting || 'auto'
    if (mon.egg) return ''
    if (mon.shiny || mon.perfect_dvs) return 'protected'
    return mon.trade_setting || (mon.trade_key ? 'auto' : '')
  }
  const theirSetting = mon => mon.shiny || mon.perfect_dvs ? 'protected' : mon.trade_setting || ''
  function grid(target, cards, options) {
    const el = $(target)
    if (!el) return
    const prefix = options.prefix
    const shown = Grid ? Grid.apply(prefix, cards, options.settingOf) : cards
    el.innerHTML = shown.map(mon => {
      const setting = options.settingOf?.(mon)
      return Grid.card(mon, mon.key, {attr: 'key', all: true, slot: mon.slot, sprite: mon.row?.sprite_url,
        blocked: options.blocked(mon), pressed: mon.key === options.chosen, tags: Grid.settingBadge(setting)})
    }).join('') || `<p class="dex-empty">${cards.length ? 'No Pokémon match these filters.' : options.empty}</p>`
    fit(el)
  }

  // Trade: a game to trade with, then a Pokémon in each slot, picked in a modal grid.
  const pick = {mine: [], cards: [], mon: null, games: [], game: null, theirs: [], theirCards: [], their: null, limits: null,
    busy: false, viewerOnly: false, asked: null, gamesAsked: null, theirRecords: null, theirReason: '', side: null}
  const note = (selector, text) => { const el = $(selector)
    if (!el) return
    el.textContent = text || ''
    el.hidden = !text }
  const VIEW_ONLY = 'This adventure is view-only, so it cannot trade'
  const mineBlocked = mon => mon.row?.blocked || (pick.viewerOnly ? VIEW_ONLY : '')
  const theirsBlocked = mon => mon.row?.blocked || ''
  const gameName = id => pick.games.find(game => game.id === id)?.name || ''
  function renderMine() {
    pick.cards = pick.mine.map(row => entry(row, ownRecords))
    grid('#pick-mine', pick.cards, {prefix: 'pick-mine', settingOf: ownSetting, blocked: mineBlocked, chosen: pick.mon?.key, empty: 'No Pokémon to trade here.'})
  }
  function renderTheirs() {
    pick.theirCards = pick.theirs.map(row => entry(row, pick.theirRecords))
    const empty = pick.theirReason || (pick.game ? 'They have no Pokémon to trade.' : 'Choose a game to trade with first.')
    grid('#pick-theirs', pick.theirCards, {prefix: 'pick-theirs', settingOf: theirSetting, blocked: theirsBlocked, chosen: pick.their?.key, empty})
  }
  const mineCard = () => pick.mon && (pick.cards.find(card => card.key === pick.mon.key) || entry(pick.mon, ownRecords))
  const theirCard = () => pick.their && (pick.theirCards.find(card => card.key === pick.their.key) || entry(pick.their, pick.theirRecords))

  // A slot is an empty Choose card until a Pokémon fills it, then a compact card that opens its detail.
  function slot(side) {
    const el = $(side === 'mine' ? '#slot-send' : '#slot-get')
    if (!el) return
    const card = side === 'mine' ? mineCard() : theirCard()
    const what = side === 'mine' ? 'to send' : 'to get'
    if (!card) {
      const off = !owner || (side === 'mine' ? pick.viewerOnly : !pick.game)
      const hint = !owner ? 'Trades are picked from the owner’s page.'
        : side === 'mine' ? (pick.viewerOnly ? 'This adventure is view-only.' : 'From this adventure')
          : pick.game ? `From ${esc(gameName(pick.game))}` : 'Choose a game to trade with first'
      el.innerHTML = `<button type="button" class="slot-empty" data-slot="${side}"${off ? ' disabled' : ''}><span class="slot-plus" aria-hidden="true">+</span><b>Choose a Pokémon</b><span class="micro">${hint}</span></button>`
      return
    }
    const setting = side === 'mine' ? ownSetting(card) : theirSetting(card)
    el.innerHTML = `<div class="pc-grid pick-chosen-grid">${Grid.card(card, card.key, {attr: 'key', slot: card.slot, sprite: card.row?.sprite_url,
      label: `chosen ${what}. Opens its details`, blocked: side === 'mine' ? mineBlocked(card) : theirsBlocked(card), tags: Grid.settingBadge(setting)})}</div><button type="button" class="key pick-change" data-slot="${side}">Change</button>`
    fit(el)
  }
  // The Trade key works only with both slots filled and a pair that is allowed. Otherwise it says why.
  function summary() {
    slot('mine')
    slot('theirs')
    const button = $('#pick-confirm')
    const game = pick.games.find(row => row.id === pick.game)
    const blocked = (pick.mon && mineBlocked(pick.mon)) || (pick.their && theirsBlocked(pick.their)) || ''
    let reason = ''
    if (!owner) reason = 'Trades are picked from the owner’s page, not from a view link.'
    else if (!pick.game) reason = 'Choose a game to trade with.'
    else if (game && !game.available) reason = game.reason
    else if (!pick.mon && !pick.their) reason = 'Choose a Pokémon to send and one to get.'
    else if (!pick.mon) reason = 'Choose a Pokémon to send.'
    else if (!pick.their) reason = 'Choose a Pokémon to get.'
    else if (blocked) reason = blocked
    else if (!pick.limits || pick.limits.from?.key !== pick.mon.key || pick.limits.to?.adventure_id !== pick.game) reason = 'Checking this trade…'
    else if (!pick.limits.starts_now) reason = VIEW_ONLY
    const ready = !reason && !pick.busy
    $('#pick-summary').textContent = reason || 'The trade starts as soon as both games are ready.'
    $('#pick-summary').classList.toggle('is-reason', Boolean(reason))
    button.disabled = !ready
    if ($('#slot-get-game')) $('#slot-get-game').textContent = pick.game ? `In ${gameName(pick.game)}` : ''
  }
  function reset() {
    pick.mon = null
    pick.their = null
    pick.limits = null
    note('#pick-game-reason', '')
    renderMine()
    loadGames()
    if (pick.game) loadTheirs()
    summary()
  }
  async function json(response, fallback) {
    let data = {}
    try { data = await response.json() } catch (_) {}
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : fallback)
    return data
  }
  async function loadMine() {
    if (!owner) {
      $('#pick-game').disabled = true
      summary()
      return
    }
    // The trade settings fill in each card's stamp when they arrive.
    if (!globalThis.TradeUI?.status?.()) globalThis.TradeUI?.refresh?.()
    loadGames()
    try {
      const [data, found] = await Promise.all([
        json(await PokeSim.api(`${BUILDER}/pokemon?adventure_id=${encodeURIComponent(aid)}`, {cache: 'no-store'}), 'Could not read this adventure’s Pokémon.'),
        readOwn()])
      if (found?.generation && Grid) Grid.generation('pick-mine', found.generation)
      pick.mine = data.pokemon || []
      pick.viewerOnly = Boolean(data.viewer_only)
      if (data.viewer_only) note('#pick-note', 'This adventure is view-only, so it cannot trade.')
      else note('#pick-note', data.reason || '')
      renderMine()
      const wanted = query.get('mon')
      const first = wanted && pick.mine.find(mon => mon.key === wanted)
      if (first && !first.blocked && !data.viewer_only) chooseMine(first.key)
      else summary()
    } catch (error) {
      $('#pick-mine').innerHTML = `<p class="dex-empty">${esc(error.message)}</p>`
      note('#pick-note', error.message)
      summary()
    }
  }
  // The games to trade with. Once a Pokémon is chosen to send, each game is checked against it.
  async function loadGames() {
    if (!owner) return
    const key = pick.mon?.key
    const ask = pick.gamesAsked = {}
    try {
      const data = await json(await PokeSim.api(`${BUILDER}/targets?from_id=${encodeURIComponent(aid)}${key ? `&from_key=${encodeURIComponent(key)}` : ''}`, {cache: 'no-store'}), 'Could not check the other games.')
      // A slower answer for a Pokémon picked earlier must not show its reasons for this one.
      if (pick.gamesAsked !== ask || pick.mon?.key !== key) return
      pick.games = data.adventures || []
      const select = $('#pick-game')
      select.innerHTML = `<option value="">${pick.games.length ? 'Choose a game' : 'No other adventure yet'}</option>` + pick.games.map(game =>
        `<option value="${esc(game.id)}"${game.available ? '' : ' disabled'}${game.id === pick.game ? ' selected' : ''}>${esc(game.name)} · ${esc(game.version)}${game.available ? '' : `: ${esc(game.reason)}`}</option>`).join('')
      const current = pick.games.find(game => game.id === pick.game)
      note('#pick-game-reason', current && !current.available ? `${current.name}: ${current.reason}` : '')
      summary()
    } catch (error) {
      if (pick.gamesAsked === ask) note('#pick-game-reason', error.message)
    }
  }
  function chooseMine(key) {
    const mon = pick.mine.find(row => row.key === key)
    if (!mon) return
    pick.mon = mon
    pick.limits = null
    note('#pick-note', '')
    renderMine()
    loadGames()
    // The Pokémon to get is checked again against the new one to send.
    if (pick.game) loadTheirs()
    summary()
  }
  function chooseGame(id) {
    if (id === pick.game) return
    pick.game = id || null
    pick.their = null
    pick.limits = null
    pick.theirs = []
    pick.theirRecords = null
    const game = pick.games.find(row => row.id === id)
    note('#pick-game-reason', game && !game.available ? `${game.name}: ${game.reason}` : '')
    if (pick.game) loadTheirs()
    else renderTheirs()
    summary()
  }
  // Their Pokémon: hard limits only until one is chosen to send, then the limits of that exact pair.
  async function loadTheirs() {
    const id = pick.game
    const key = pick.mon?.key
    const ask = pick.asked = {}
    const stale = () => pick.asked !== ask || pick.game !== id || pick.mon?.key !== key
    pick.theirReason = ''
    if (!pick.theirs.length) $('#pick-theirs').innerHTML = '<p class="dex-empty">Reading their Pokémon…</p>'
    // Their full PC records arrive on their own. The cards fill in when they do.
    if (!pick.theirRecords) records(`/games/${encodeURIComponent(id)}/api/pokedex/status?view=pc`, true).then(found => {
      if (pick.game !== id || !found) return
      pick.theirRecords = found
      if (Grid) Grid.generation('pick-theirs', found.generation)
      if (pick.theirs.length) renderTheirs()
      summary()
    })
    try {
      const path = key
        ? `${BUILDER}/limits?from_id=${encodeURIComponent(aid)}&from_key=${encodeURIComponent(key)}&to_id=${encodeURIComponent(id)}`
        : `${BUILDER}/pokemon?adventure_id=${encodeURIComponent(id)}`
      const data = await json(await PokeSim.api(path, {cache: 'no-store'}), 'Could not read their Pokémon.')
      if (stale()) return
      pick.limits = key ? data : null
      pick.theirs = data.pokemon || []
      pick.theirReason = key ? '' : data.reason || ''
      // A Pokémon chosen to get that left, or that this pair cannot trade, is let go with the reason.
      if (pick.their) {
        const again = pick.theirs.find(row => row.key === pick.their.key)
        if (!again) {
          note('#pick-note', `${pick.their.nickname || pick.their.name} is no longer in ${gameName(id)}. Choose another Pokémon to get.`)
          pick.their = null
        } else pick.their = again
      }
      renderTheirs()
      summary()
    } catch (error) {
      if (stale()) return
      pick.theirs = []
      pick.theirReason = error.message
      renderTheirs()
      note('#pick-note', error.message)
    }
  }
  function chooseTheirs(key) {
    const mon = pick.theirs.find(row => row.key === key)
    if (!mon) return
    pick.their = mon
    note('#pick-note', '')
    renderTheirs()
    summary()
  }
  async function confirm() {
    if (pick.busy || !pick.mon || !pick.their || $('#pick-confirm').disabled) return
    pick.busy = true
    $('#pick-confirm').disabled = true
    const request = globalThis.crypto?.randomUUID ? crypto.randomUUID().replace(/-/g, '') : undefined
    try {
      await json(await PokeSim.api(BUILDER, {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({from_id: aid, from_key: pick.mon.key, to_id: pick.game, to_key: pick.their.key, ...(request ? {request_id: request} : {})})}),
      'That trade could not be set up.')
      pick.busy = false
      reset()
      note('#pick-note', 'Trade started. Follow it under Current exchange and on the History tab.')
      await globalThis.AdventureTrading?.refresh?.()
      select('history')
    } catch (error) {
      note('#pick-note', error.message)
    } finally {
      pick.busy = false
      summary()
    }
  }

  // The picker: the shared grid with search, filters and sort, in a modal that scrolls inside.
  const picker = $('#pick-dialog')
  function openPicker(side) {
    if (!picker || !owner) return
    if (side === 'theirs' && !pick.game) {
      note('#pick-note', 'Choose a game to trade with first.')
      $('#pick-game')?.focus()
      return
    }
    pick.side = side
    $('#pick-mine-pane').hidden = side !== 'mine'
    $('#pick-theirs-pane').hidden = side !== 'theirs'
    $('#pick-dialog-title').textContent = side === 'mine' ? 'Choose a Pokémon to send' : `Choose a Pokémon to get from ${gameName(pick.game)}`
    note('#pick-dialog-note', '')
    if (side === 'mine') renderMine()
    else renderTheirs()
    if (!picker.open) picker.showModal?.()
    // Focus lands on the search box so typing filters straight away.
    $(`#pick-${side}-pane input`)?.focus()
  }
  function pickCard(side, key) {
    const card = (side === 'mine' ? pick.cards : pick.theirCards).find(item => item.key === key)
    if (!card) return
    const blocked = side === 'mine' ? mineBlocked(card) : theirsBlocked(card)
    if (blocked) {
      note('#pick-dialog-note', `${card.nick || card.name} cannot be picked: ${blocked}`)
      return
    }
    picker.close()
    if (side === 'mine') chooseMine(key)
    else chooseTheirs(key)
    $(side === 'mine' ? '#slot-send' : '#slot-get')?.querySelector('[data-key]')?.focus()
  }
  if (picker) {
    $('#pick-dialog-close')?.addEventListener('click', () => picker.close())
    picker.addEventListener('click', event => {
      const button = event.target.closest?.('[data-key]')
      if (button) return pickCard(pick.side, button.dataset.key)
      if (event.target !== picker) return
      const rect = picker.getBoundingClientRect()
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) picker.close()
    })
    picker.addEventListener('close', () => { pick.side = null })
  }

  // The detail popup: the PC page's detail, with the trade setting on top.
  const dialog = $('#trade-detail')
  let open = null
  function detailTop(card, side) {
    const blocked = side === 'mine' ? mineBlocked(card) : side === 'theirs' ? theirsBlocked(card) : ''
    const parts = []
    if (blocked) parts.push(`<p class="pick-blocked-reason" role="note"><span class="micro">Cannot be traded</span>${esc(blocked)}</p>`)
    if (side !== 'theirs' && card.trade_key && globalThis.TradeUI) parts.push(`<div class="trade-detail-setting"><span class="micro">Trade setting</span>${TradeUI.control(card.trade_key, card.nick || card.name)}</div>`)
    if (side === 'mine' || side === 'theirs') parts.push(`<button type="button" class="key" data-detail-change="${side}">Choose another Pokémon</button>`)
    return parts.length ? `<div class="pc-trade-action trade-detail-action">${parts.join('')}</div>` : ''
  }
  function trade(card, side) {
    if (side === 'theirs') return false
    const state = ownSetting(card)
    return state ? {state: Grid.SETTING_LABELS[state], note: state === 'protected' ? 'Never traded automatically' : 'Change it here'} : false
  }
  function renderDetail() {
    if (!open || !Grid) return
    const {card, side} = open
    $('#trade-detail-body').innerHTML = Grid.detail(card, {sprite: card.row?.sprite_url, slot: card.slot, top: detailTop(card, side), trade: trade(card, side), links: side !== 'theirs'})
    fit($('#trade-detail-body'))
  }
  function openDetail(card, side) {
    if (!card || !dialog) return
    open = {card, side}
    renderDetail()
    if (!dialog.open) dialog.showModal?.()
  }
  if (dialog) {
    $('#trade-detail-close')?.addEventListener('click', () => dialog.close())
    dialog.addEventListener('click', event => {
      const change = event.target.closest?.('[data-detail-change]')
      if (change) {
        dialog.close()
        openPicker(change.dataset.detailChange)
        return
      }
      if (event.target !== dialog) return
      const rect = dialog.getBoundingClientRect()
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close()
    })
    dialog.addEventListener('change', event => {
      if (event.target.matches?.('select[data-trade-key]')) TradeUI.change(event.target)
    })
    dialog.addEventListener('close', () => { open = null })
  }

  const cardsIn = (selector, handler) => { const el = $(selector)
    if (el) el.addEventListener('click', event => {
      const button = event.target.closest?.('[data-key]')
      if (button) handler(button.dataset.key)
    }) }
  for (const [selector, side] of [['#slot-send', 'mine'], ['#slot-get', 'theirs']]) {
    $(selector)?.addEventListener('click', event => {
      const opener = event.target.closest?.('[data-slot]')
      if (opener && !opener.disabled) return openPicker(side)
      if (event.target.closest?.('[data-key]')) openDetail(side === 'mine' ? mineCard() : theirCard(), side)
    })
  }
  $('#pick-game')?.addEventListener('change', event => chooseGame(event.target.value))
  if (Grid) {
    Grid.bind('pick-mine', renderMine)
    Grid.bind('pick-theirs', renderTheirs)
  }
  $('#pick-confirm')?.addEventListener('click', confirm)
  $('#pick-reset')?.addEventListener('click', () => { note('#pick-note', '')
    reset() })

  // Auto: the on or off switch, the wish list and one setting per Pokémon.
  let auto = null
  let autoBusy = false
  let autoLoading = false
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
  // Every visit to the tab reads fresh settings. Only an overlapping read is skipped.
  async function loadAuto() {
    globalThis.TradeUI?.refresh?.()
    if (!owner) {
      note('#auto-note', 'Automatic trading is set from the owner’s page, not from a view link.')
      for (const el of document.querySelectorAll('#auto-switch, #wish-input, #wish-add')) el.disabled = true
      return
    }
    if (autoLoading || autoBusy) return
    autoLoading = true
    try {
      auto = await json(await PokeSim.api(`${SETTINGS}?adventure_id=${encodeURIComponent(aid)}`, {cache: 'no-store'}), 'Could not read the automatic trading settings.')
      if (auto.viewer_only) note('#auto-note', 'This adventure is view-only. Its trading settings cannot be changed here.')
      renderAuto()
    } catch (error) {
      note('#auto-note', error.message)
    } finally { autoLoading = false }
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
  // One setting per Pokémon, shown as the same cards. A card opens the popup that changes it.
  let autoCards = []
  function renderSettings(status) {
    const list = $('#auto-list')
    if (!list) return
    // Settings save in the adventure itself, so they work while trading is offline, not while it is stopped.
    if (!status || status.unreachable || !Array.isArray(status.offers)) {
      list.innerHTML = '<p class="dex-empty">Start this adventure to change its trade settings.</p>'
      if ($('#auto-count')) $('#auto-count').textContent = ''
      return
    }
    autoCards = status.offers.map(mon => entry({...mon, key: mon.trade_key, nickname: mon.nick, slot: mon.position, location: mon.box ? 'box' : 'party'}, ownRecords))
    grid('#auto-list', autoCards, {prefix: 'auto', settingOf: ownSetting, blocked: () => '', empty: 'No Pokémon to set yet.'})
    if (open?.side === 'auto') {
      const card = autoCards.find(row => row.key === open.card.key)
      if (card) {
        open.card = card
        renderDetail()
      }
    }
  }
  if (globalThis.TradeUI) {
    TradeUI.subscribe(renderSettings)
    cardsIn('#auto-list', key => openDetail(autoCards.find(card => card.key === key), 'auto'))
    if (Grid) Grid.bind('auto', () => renderSettings(TradeUI.status()))
    // My PC records add types, DVs and moves to the cards once they arrive.
    if (owner) readOwn().then(found => {
      if (found?.generation && Grid) Grid.generation('auto', found.generation)
      if (autoCards.length) renderSettings(TradeUI.status())
    })
  }
  // A setting changed in the popup also updates the trade picker's badges.
  globalThis.TradeUI?.subscribe?.(() => {
    if (pick.cards.length) renderMine()
    if (pick.mon) slot('mine')
    if (open?.side === 'mine') renderDetail()
  })

  // Deep links (?tab=trade&mon=key) win over the remembered tab.
  let saved = null
  try { saved = localStorage.getItem(STORE) } catch (_) {}
  select(query.get('tab') || (query.get('mon') ? 'trade' : saved) || 'trade')
  loadMine()
  globalThis.TradeTabs = {select}
})()
