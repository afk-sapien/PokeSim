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
    if (current === 'offers') globalThis.AdventureTrading?.refreshOffers?.(true)
    if (current === 'cable') loadCable()
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

  // Trade: your Pokémon, then a game, then their Pokémon, then confirm.
  const pick = {mine: [], cards: [], mon: null, game: null, theirs: [], theirCards: [], their: null, limits: null,
    busy: false, viewerOnly: false, asked: null, theirRecords: null}
  const note = (selector, text) => { const el = $(selector)
    if (!el) return
    el.textContent = text || ''
    el.hidden = !text }
  const VIEW_ONLY = 'This adventure is view-only, so it can receive offers but cannot send Pokémon'
  const mineBlocked = mon => mon.row?.blocked || (pick.viewerOnly ? VIEW_ONLY : '')
  const theirsBlocked = mon => mon.row?.blocked || ''
  function renderMine() {
    pick.cards = pick.mine.map(row => entry(row, ownRecords))
    grid('#pick-mine', pick.cards, {prefix: 'pick-mine', settingOf: ownSetting, blocked: mineBlocked, chosen: pick.mon?.key, empty: 'No Pokémon to trade here.'})
  }
  function renderTheirs() {
    pick.theirCards = pick.theirs.map(row => entry(row, pick.theirRecords))
    grid('#pick-theirs', pick.theirCards, {prefix: 'pick-theirs', settingOf: theirSetting, blocked: theirsBlocked, chosen: pick.their?.key, empty: 'They have no Pokémon to trade.'})
  }
  // A chosen Pokémon folds its grid away into one card with a Change key.
  function chosen(side, card, label) {
    const holder = $(`#pick-${side}-chosen`)
    const browse = $(`#pick-${side}-browse`)
    if (holder) {
      holder.hidden = !card
      holder.innerHTML = card ? `<div class="pc-grid pc-all-grid pick-chosen-grid">${Grid.card(card, card.key, {attr: 'key', all: true, slot: card.slot,
        sprite: card.row?.sprite_url, pressed: true, label, tags: Grid.settingBadge(side === 'mine' ? ownSetting(card) : theirSetting(card))})}</div><button type="button" class="key pick-change" data-change="${side}">Change</button>` : ''
      fit(holder)
    }
    if (browse) browse.hidden = Boolean(card)
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
    chosen('mine', pick.mon && pick.cards.find(card => card.key === pick.mon.key), 'chosen to send')
    chosen('theirs', null)
    renderMine()
  }
  async function json(response, fallback) {
    let data = {}
    try { data = await response.json() } catch (_) {}
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : fallback)
    return data
  }
  async function loadMine() {
    if (!owner) {
      $('#pick-mine').innerHTML = '<p class="dex-empty">Trades are picked from the owner’s page, not from a view link.</p>'
      for (const el of document.querySelectorAll('#pick-mine-browse input, #pick-mine-browse select')) el.disabled = true
      return
    }
    // The trade settings fill in each card's stamp when they arrive.
    if (!globalThis.TradeUI?.status?.()) globalThis.TradeUI?.refresh?.()
    try {
      const [data, found] = await Promise.all([
        json(await PokeSim.api(`${OFFERS}/pokemon?adventure_id=${encodeURIComponent(aid)}`, {cache: 'no-store'}), 'Could not read this adventure’s Pokémon.'),
        readOwn()])
      if (found?.generation && Grid) Grid.generation('pick-mine', found.generation)
      pick.mine = data.pokemon || []
      pick.viewerOnly = Boolean(data.viewer_only)
      if (data.viewer_only) note('#pick-note', 'This adventure is view-only. It can receive offers but cannot send them.')
      else note('#pick-note', data.reason || '')
      const wanted = query.get('mon')
      const first = wanted && pick.mine.find(mon => mon.key === wanted)
      if (first && !first.blocked && !data.viewer_only) {
        renderMine()
        await chooseMine(first.key)
      } else reset()
    } catch (error) {
      $('#pick-mine').innerHTML = `<p class="dex-empty">${esc(error.message)}</p>`
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
      $('#pick-games').innerHTML = games.map(game => `<button type="button" class="pick-item pick-game" role="radio" aria-checked="false" data-game="${esc(game.id)}"${game.available ? '' : ' aria-disabled="true" disabled'}><i class="lamp" data-on="${game.available ? 'ok' : 'warn'}" aria-hidden="true"></i><span class="pick-read"><b>${esc(game.name)}</b><span class="micro">${esc(game.version)}</span>${game.available ? '' : `<span class="pick-reason">${esc(game.reason)}</span>`}</span></button>`).join('')
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
    pick.theirRecords = null
    for (const button of document.querySelectorAll('#pick-games [data-game]')) button.setAttribute('aria-checked', String(button.dataset.game === id))
    show('#pick-confirm-step', false)
    show('#pick-theirs-step', true)
    chosen('theirs', null)
    const name = $(`#pick-games [data-game="${id}"] b`)?.textContent || ''
    if ($('#pick-theirs-game')) $('#pick-theirs-game').textContent = name ? `In ${name}` : ''
    $('#pick-theirs').innerHTML = '<p class="dex-empty">Reading their Pokémon…</p>'
    const key = pick.mon.key
    // Only the latest request may fill the list. An answer for an earlier Pokémon or game, or its error, is dropped.
    const ask = pick.asked = {}
    const stale = () => pick.asked !== ask || pick.game !== id || pick.mon?.key !== key
    // Their full PC records arrive on their own. The cards fill in when they do.
    records(`/games/${encodeURIComponent(id)}/api/pokedex/status?view=pc`, true).then(found => {
      if (stale() || !found) return
      pick.theirRecords = found
      if (Grid) Grid.generation('pick-theirs', found.generation)
      if (pick.theirs.length) renderTheirs()
    })
    try {
      const data = await json(await PokeSim.api(`${OFFERS}/limits?from_id=${encodeURIComponent(aid)}&from_key=${encodeURIComponent(key)}&to_id=${encodeURIComponent(id)}`, {cache: 'no-store'}), 'Could not read their Pokémon.')
      if (stale()) return
      pick.limits = data
      pick.theirs = data.pokemon || []
      renderTheirs()
    } catch (error) {
      if (stale()) return
      $('#pick-theirs').innerHTML = `<p class="dex-empty">${esc(error.message)}</p>`
    }
  }
  function chooseTheirs(key) {
    const mon = pick.theirs.find(row => row.key === key)
    if (!mon || mon.blocked) return
    pick.their = mon
    chosen('theirs', pick.theirCards.find(card => card.key === key), 'chosen to receive')
    const offer = globalThis.AdventureTrading?.offerSide
    const side = (row, label) => offer ? offer(row, label) : `<p>${esc(label)}: ${esc(row.name)}</p>`
    const now = Boolean(pick.limits?.starts_now)
    // The summary takes types and DVs from the cards, which may come from the full PC records.
    const fuller = (row, cards) => { const card = cards.find(item => item.key === row.key) || {}
      return {...row, type_names: card.type_names || row.type_names, dv_stars: card.dv_stars ?? row.dv_stars, dv_total: card.dv_total, dv_percent: card.dv_percent, shiny: card.shiny ?? row.shiny} }
    $('#pick-summary').innerHTML = `<div class="swap">${side(fuller(pick.mon, pick.cards), 'You send')}<span class="swap-arrow" aria-hidden="true">⇄</span>${side(fuller(mon, pick.theirCards), 'You receive')}</div><p class="trade-help">${now
      ? 'You control both adventures, so the trade starts as soon as both games are ready.'
      : `${esc(pick.limits?.to?.adventure_name || 'The other adventure')} is view-only, so this becomes an offer its owner answers.`}</p>`
    $('#pick-confirm').textContent = now ? 'Trade now' : 'Send offer'
    $('#pick-confirm').disabled = false
    show('#pick-confirm-step', true)
    fit($('#pick-summary'))
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

  // The detail popup: the PC page's detail, with the trade choice and setting on top.
  const dialog = $('#trade-detail')
  let open = null
  function detailTop(card, side) {
    const name = esc(card.nick || card.name)
    const blocked = side === 'mine' ? mineBlocked(card) : side === 'theirs' ? theirsBlocked(card) : ''
    const parts = []
    if (blocked) parts.push(`<p class="pick-blocked-reason" role="note"><span class="micro">Cannot be picked</span>${esc(blocked)}</p>`)
    else if (side === 'mine' && pick.mon?.key !== card.key) parts.push(`<button type="button" class="key key--primary" data-detail-pick="mine" data-key="${esc(card.key)}">Choose ${name} to send</button>`)
    else if (side === 'theirs' && pick.their?.key !== card.key) parts.push(`<button type="button" class="key key--primary" data-detail-pick="theirs" data-key="${esc(card.key)}">Ask for ${name}</button>`)
    if (side !== 'theirs' && card.trade_key && globalThis.TradeUI) parts.push(`<div class="trade-detail-setting"><span class="micro">Trade setting</span>${TradeUI.control(card.trade_key, card.nick || card.name)}</div>`)
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
      const choose = event.target.closest?.('[data-detail-pick]')
      if (choose) {
        dialog.close()
        if (choose.dataset.detailPick === 'mine') chooseMine(choose.dataset.key)
        else chooseTheirs(choose.dataset.key)
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
  cardsIn('#pick-mine', key => openDetail(pick.cards.find(card => card.key === key), 'mine'))
  cardsIn('#pick-theirs', key => openDetail(pick.theirCards.find(card => card.key === key), 'theirs'))
  cardsIn('#pick-mine-chosen', key => openDetail(pick.cards.find(card => card.key === key), 'mine'))
  cardsIn('#pick-theirs-chosen', key => openDetail(pick.theirCards.find(card => card.key === key), 'theirs'))
  for (const side of ['mine', 'theirs']) {
    $(`#pick-${side}-chosen`)?.addEventListener('click', event => {
      if (!event.target.closest?.('[data-change]')) return
      note('#pick-note', '')
      if (side === 'mine') reset()
      else {
        pick.their = null
        show('#pick-confirm-step', false)
        chosen('theirs', null)
        renderTheirs()
      }
    })
  }
  $('#pick-games')?.addEventListener('click', event => {
    const button = event.target.closest?.('.pick-item')
    if (button && !button.disabled) chooseGame(button.dataset.game)
  })
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
    if (open?.side === 'mine') renderDetail()
  })

  // Cable Club: link with another adventure and hold both controllers on the Cable Club page.
  let cableLoading = false
  const cableHref = id => `${PokeSim.base}/cable?with=${encodeURIComponent(id)}`
  async function loadCable() {
    if (cableLoading) return
    cableLoading = true
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
        const read = `<i class="lamp" data-on="${game.reason ? 'warn' : 'ok'}" aria-hidden="true"></i><span class="pick-read"><b>${esc(game.name)}</b><span class="micro">${esc(game.version)}</span>${game.reason ? `<span class="pick-reason">${esc(game.reason)}</span>` : ''}</span>`
        return game.reason
          ? `<span class="pick-item pick-game is-unavailable" data-cable="${esc(game.id)}" aria-disabled="true">${read}</span>`
          : `<a class="pick-item pick-game" data-cable="${esc(game.id)}" href="${esc(cableHref(game.id))}">${read}</a>`
      }).join('') || '<p class="empty-note">There is no other adventure to link with yet.</p>'
    } catch (error) {
      list.innerHTML = `<p class="empty-note">${esc(error.message)}</p>`
    } finally { cableLoading = false }
  }

  // Deep links (?tab=trade&mon=key) win over the remembered tab.
  let saved = null
  try { saved = localStorage.getItem(STORE) } catch (_) {}
  select(query.get('tab') || (query.get('mon') ? 'trade' : saved) || 'trade')
  loadMine()
  globalThis.TradeTabs = {select}
})()
