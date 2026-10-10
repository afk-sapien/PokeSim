// Trade offers from the PC: pick one of your Pokémon, pick another adventure, then pick what to ask for in its PC.
(() => {
  const $ = selector => document.querySelector(selector)
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp', '<': '&lt', '>': '&gt', '"': '&quot', "'": '&#39'}[char] + String.fromCharCode(59)))
  const ID = /^[a-f0-9]{32}$/
  const OFFERS = '/api/v1/interactions/trade-offers'
  const params = new URLSearchParams(location.search)
  // Only the owner's /games/ pages can write. View links never reach the library API.
  const owner = String(PokeSim.base || '').startsWith('/games/') && ID.test(PokeSim.adventureId || '')
  const fromId = params.get('offer_from') || ''
  const fromKey = params.get('offer_key') || ''
  const mode = owner && ID.test(fromId) && fromId !== PokeSim.adventureId && fromKey ? {fromId, fromKey} : null
  const listeners = []
  const state = {targets: null, limits: null, error: '', sending: false, offering: null}
  const notify = () => listeners.forEach(listener => listener())
  const detail = async response => {
    try { return (await response.json()).detail || '' } catch (_) { return '' }
  }
  const randomId = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('')
  const power = mon => [Number.isFinite(mon.battle_power) ? `Battle Power ${mon.battle_power.toLocaleString()}` : '',
    Number.isFinite(mon.power) ? `Stat Power ${mon.power.toLocaleString()}` : ''].filter(Boolean).join(' · ')

  async function load() {
    if (!owner) return
    try {
      if (mode) {
        const query = new URLSearchParams({from_id: mode.fromId, from_key: mode.fromKey, to_id: PokeSim.adventureId})
        const response = await PokeSim.api(`${OFFERS}/limits?${query}`, {cache: 'no-store'})
        if (!response.ok) throw new Error(await detail(response) || 'Could not check this offer. Try again in a moment.')
        state.limits = await response.json()
      } else {
        const response = await PokeSim.api(`${OFFERS}/targets?from_id=${PokeSim.adventureId}`, {cache: 'no-store'})
        if (!response.ok) throw new Error(await detail(response) || 'Trade offers are unavailable right now.')
        state.targets = await response.json()
      }
      state.error = ''
    } catch (error) { state.error = error.message }
    banner()
    notify()
  }

  // Offering is for the owner of a running adventure that is not view only.
  const canOffer = mon => owner && !mode && state.targets && !state.targets.viewer_only && mon?.trade_key && !mon.egg

  function control(mon) {
    if (!mon) return ''
    if (!mode) return canOffer(mon) ? `<button type="button" class="key offer-trade-button" data-offer-trade="${esc(mon.trade_key)}">Offer trade</button>` : ''
    if (!state.limits) return state.error ? `<p class="offer-reason" role="status">${esc(state.error)}</p>` : '<p class="offer-reason" role="status">Checking this trade…</p>'
    if (state.limits.viewer_only) return '<p class="offer-reason" role="status">This adventure is view only.</p>'
    const blocked = state.limits.from?.blocked || state.limits.blocked?.[mon.trade_key]
    if (blocked) return `<p class="offer-reason" role="status"><b>Cannot trade.</b> ${esc(blocked)}</p>`
    const error = state.error ? `<p class="offer-reason offer-error" role="alert">${esc(state.error)}</p>` : ''
    return `<button type="button" class="key key--primary offer-send-button" data-offer-send="${esc(mon.trade_key)}"${state.sending ? ' disabled' : ''}>${state.sending ? 'Sending…' : `Send offer for ${esc(mon.nick || mon.name)}`}</button>${error}`
  }

  // In offer mode, cards the cable cannot accept say so before they are opened.
  const tag = mon => mode && state.limits?.blocked?.[mon.trade_key] ? '<span class="tag offer-blocked-tag">Cannot trade</span>' : ''

  function keep(url) {
    if (!mode) return
    url.set('offer_from', mode.fromId)
    url.set('offer_key', mode.fromKey)
  }

  function banner() {
    const box = $('#pc-offer-banner')
    if (!box || !mode) return
    box.hidden = false
    const back = `<a class="key" href="/games/${mode.fromId}/pc">Cancel offer</a>`
    const mon = state.limits?.from
    if (!mon) {
      box.innerHTML = `<div class="offer-banner-read"><p class="micro">Trade offer</p><p>${esc(state.error || 'Checking the Pokémon you are offering…')}</p></div>${back}`
      return
    }
    const sprite = mon.sprite_url ? `<img src="${esc(mon.sprite_url)}" alt="">` : '<span class="plate-num" aria-hidden="true">?</span>'
    const note = mon.blocked ? `<p class="offer-reason"><b>Cannot trade.</b> ${esc(mon.blocked)}</p>` : `<p>Open a Pokémon from ${esc(state.limits.to?.adventure_name || 'this adventure')} to ask for it.</p>`
    box.innerHTML = `<div class="plate plate--bay offer-banner-plate">${sprite}</div><div class="offer-banner-read"><p class="micro">Offering from ${esc(mon.adventure_name)}</p><h2>${esc(mon.nickname || mon.name)} · Lv. ${esc(mon.level ?? '?')}</h2><p class="detail-meta">${esc(power(mon))}</p>${note}</div>${back}`
    globalThis.Panel?.fitSprites?.(box)
  }

  function openPicker(key) {
    state.offering = key
    const dialog = $('#offer-dialog')
    const games = state.targets?.adventures || []
    const list = games.map(game => `<li><button type="button" class="offer-target" data-offer-target="${esc(game.id)}"${game.available ? '' : ' disabled'}><strong>${esc(game.name)}</strong><small>Pokémon ${esc(game.version ? game.version[0].toUpperCase() + game.version.slice(1) : '')}</small>${game.available ? '' : `<small class="offer-reason">${esc(game.reason)}</small>`}</button></li>`).join('')
    $('#offer-dialog-list').innerHTML = list || '<li class="empty-note">Start another adventure to trade with it.</li>'
    dialog.showModal()
  }

  function targetUrl(aid) {
    const query = new URLSearchParams({scope: 'all', sort: 'battle_power', order: 'desc', offer_from: PokeSim.adventureId, offer_key: state.offering})
    return `/games/${aid}/pc?${query}`
  }

  async function send(key) {
    if (state.sending) return
    state.sending = true
    state.error = ''
    notify()
    try {
      const response = await PokeSim.api(OFFERS, {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({from_id: mode.fromId, from_key: mode.fromKey, to_id: PokeSim.adventureId, to_key: key, request_id: randomId()})})
      if (!response.ok) throw new Error(await detail(response) || 'The offer could not be sent.')
      location.href = `/games/${mode.fromId}/trading`
    } catch (error) {
      state.error = error.message
    } finally {
      state.sending = false
      notify()
    }
  }

  // Returns true when the click belonged to an offer control.
  function click(event) {
    const offer = event.target.closest?.('[data-offer-trade]')
    if (offer) { openPicker(offer.dataset.offerTrade)
      return true }
    const target = event.target.closest?.('[data-offer-target]')
    if (target && !target.disabled && ID.test(target.dataset.offerTarget)) { location.href = targetUrl(target.dataset.offerTarget)
      return true }
    const sending = event.target.closest?.('[data-offer-send]')
    if (sending && mode) { send(sending.dataset.offerSend)
      return true }
    return false
  }

  // Loaded at the end of the page, so its dialog and banner already exist.
  const dialog = $('#offer-dialog')
  if (dialog) {
    dialog.onclick = event => { if (!click(event) && event.target === dialog) dialog.close() }
    $('#offer-dialog-close').onclick = () => dialog.close()
  }
  banner()
  load()
  globalThis.TradeOffer = {mode, control, tag, keep, click, subscribe: fn => listeners.push(fn),
    state: () => [state.targets?.viewer_only, state.limits, state.error, state.sending]}
})()
