const $ = (selector) => document.querySelector(selector)
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&': '&amp', '<': '&lt', '>': '&gt', '"': '&quot', "'": '&#39'}[char] + String.fromCharCode(59)))
const params = new URLSearchParams(location.search)
let selectedBox = params.get('box') === 'party' ? 0 : Math.min(14, Math.max(1, Number(params.get('box')) || 1))
let followActive = !params.has('box')
let storage = null
let party = []
let busy = false
let signature = ''
let residents = []
let detailKey = null
$('#pc-rating').value = ['1', '2', '3', '4', '3plus', 'unknown', 'shiny'].includes(params.get('rating')) ? params.get('rating') : 'all'
let viewQueries = {box: '', all: ''}
$('#pc-search').value = params.get('q') || ''
$('#pc-scope').value = params.get('scope') === 'all' ? 'all' : 'box'
viewQueries[$('#pc-scope').value] = $('#pc-search').value
const sortDefaults = {box: 'asc', battle_power: 'desc', power: 'desc', stat_total: 'desc', level: 'desc', HP: 'desc', Attack: 'desc', Defense: 'desc', Speed: 'desc', Special: 'desc', 'Special Attack': 'desc', 'Special Defense': 'desc', dv_stars: 'desc', dvs: 'desc', stat_exp: 'desc', experience: 'desc', dex: 'asc', name: 'asc', nick: 'asc'}
$('#pc-sort').value = Object.hasOwn(sortDefaults, params.get('sort')) ? params.get('sort') : 'battle_power'
$('#pc-order').value = ['asc', 'desc'].includes(params.get('order')) ? params.get('order') : sortDefaults[$('#pc-sort').value]

function statTotal(mon, field) {
  const values = mon[field]
  return Array.isArray(values) && values.length === 5 && values.every(Number.isFinite)
    ? values.reduce((sum, value) => sum + value, 0) : null
}

function sortValue(mon, field) {
  if (field === 'dvs' || field === 'stat_exp') return statTotal(mon, field)
  if (['HP', 'Attack', 'Defense', 'Speed', 'Special', 'Special Attack', 'Special Defense'].includes(field)) return mon.calculated_stats?.[field] ?? null
  if (field === 'experience') return mon.experience?.total ?? mon.experience ?? null
  if (field === 'box') return mon.box * 20 + (mon.position || 0)
  if (field === 'nick') return mon.nick || mon.name || ''
  if (field === 'name') return mon.name || ''
  return Number.isFinite(mon[field]) ? mon[field] : null
}

function comparePartners(a, b, field, order) {
  const left = sortValue(a, field)
  const right = sortValue(b, field)
  // Unavailable individual stats stay last in either direction.
  if (left === null && right !== null) return 1
  if (right === null && left !== null) return -1
  const comparison = typeof left === 'string'
    ? left.localeCompare(right, undefined, {sensitivity: 'base', numeric: true})
    : (left ?? 0) - (right ?? 0)
  const ratingTie = field === 'dv_stars' && left !== null && right !== null
    ? ((a.dv_total ?? 0) - (b.dv_total ?? 0)) * (order === 'desc' ? -1 : 1) : 0
  return comparison * (order === 'desc' ? -1 : 1) || ratingTie || a.box - b.box || (a.position || 0) - (b.position || 0)
}

function formatTotal(mon, field) {
  const total = statTotal(mon, field)
  return total === null ? 'Unavailable' : total.toLocaleString()
}

function isLocked(mon) {
  return globalThis.TradeUI?.find(mon.trade_key)?.locked ?? mon.trade_locked
}

function ratingLabel(mon) {
  return Number.isInteger(mon.dv_stars) && mon.dv_stars >= 1 && mon.dv_stars <= 4
    ? `${mon.dv_stars}-star DVs` : 'DV rating unavailable'
}

// Four lamps, lit to the star count; the stars stay in the text for copy and search.
function ratingBadge(mon) {
  if (!Number.isInteger(mon.dv_stars) || mon.dv_stars < 1 || mon.dv_stars > 4) return '<span class="dv-badge dv-unknown">DVs unknown</span>'
  const lamps = Array.from({length: 4}, (_, i) => `<i class="lamp"${i < mon.dv_stars ? ' data-on="signal"' : ''}></i>`).join('')
  return `<span class="dv-badge dv-stars-${mon.dv_stars}" aria-label="${ratingLabel(mon)}" title="${mon.dv_total} / 75 DVs · ${mon.dv_percent}%"><span class="dv" aria-hidden="true">${lamps}</span><span class="vh">${'★'.repeat(mon.dv_stars)}${'☆'.repeat(4 - mon.dv_stars)}</span> ${mon.dv_stars === 4 ? 'Perfect DV' : 'DV'}</span>`
}

function lockBadge(mon) {
  return isLocked(mon) ? '<span class="pc-lock-badge">Locked</span>' : ''
}

// A slot's fill as discrete cells, one per slot.
function fillMeter(count, size) {
  const level = count >= size ? 'warn' : 'signal'
  return `<span class="meter" data-level="${level}" aria-hidden="true">${Array.from({length: size}, (_, i) => `<i${i < count ? ' class="on"' : ''}></i>`).join('')}</span>`
}

// Portrait scaling is shared; see panel.js.
const fitSprites = (root) => globalThis.Panel?.fitSprites?.(root)

function render() {
  const counts = storage?.box_counts || Array(12).fill(0)
  const pokemon = [...party, ...(storage?.pokemon || [])].map(PokemonTypes.asEgg)
  const search = $('#pc-search').value.trim().toLowerCase()
  const dexQuery = /^#\d{1,3}$/.test(search) ? Number(search.slice(1)) : null
  const query = search.replace(/^#/, '')
  const all = $('#pc-scope').value === 'all'
  const rating = $('#pc-rating').value
  const sort = $('#pc-sort').value
  const order = $('#pc-order').value
  const alphabetical = sort === 'name' || sort === 'nick'
  $('#pc-order').options[0].textContent = alphabetical ? 'A to Z' : sort === 'box' ? 'First to last' : 'Lowest first'
  $('#pc-order').options[1].textContent = alphabetical ? 'Z to A' : sort === 'box' ? 'Last to first' : 'Highest first'
  const rows = pokemon.filter((mon) => (rating === 'all' || (rating === 'shiny' ? mon.shiny : rating === 'unknown' ? mon.dv_stars == null : rating === '3plus' ? mon.dv_stars >= 3 : mon.dv_stars === Number(rating))) && (all || mon.box === selectedBox) && (!query ||
    `${mon.nick} ${mon.name}`.toLowerCase().includes(query) || String(mon.dex).padStart(3, '0').includes(query)))
  rows.sort((a, b) => comparePartners(a, b, all ? sort : 'box', all ? order : 'asc'))
  residents = rows
  const url = new URLSearchParams({box: selectedBox === 0 ? 'party' : String(selectedBox)})
  if (query) url.set('q', $('#pc-search').value)
  if (all) url.set('scope', 'all')
  if (rating !== 'all') url.set('rating', rating)
  url.set('sort', sort)
  url.set('order', order)
  history.replaceState(null, '', `${PokeSim.base}/pc?${url}`)
  $('#pc-total').textContent = `${counts.reduce((sum, count) => sum + count, 0)} / ${counts.length * 20}`
  $('#pc-active').textContent = `Box ${storage?.active_box || 1}`
  $('#pc-heading').textContent = all ? 'Party and all boxes' : selectedBox === 0 ? 'Party' : `Box ${selectedBox}`
  $('#pc-note').textContent = all ? 'ALL PARTNERS' : selectedBox === 0 ? 'TRAVELING TEAM' : selectedBox === storage?.active_box ? 'TAKING NEW ARRIVALS' : 'STORED PARTNERS'
  $('#pc-count').textContent = `${rows.length} Pokémon`
  $('#pc-sidebar').hidden = all
  $('#pc-sort-control').hidden = !all
  $('#pc-order-control').hidden = !all
  $('#pc-workspace').classList.toggle('pc-workspace-all', all)
  $('#pc-grid').classList.toggle('pc-all-grid', all)
  $('#pc-boxes-view').setAttribute('aria-pressed', String(!all))
  $('#pc-all-view').setAttribute('aria-pressed', String(all))
  const key = JSON.stringify([storage, party, selectedBox, query, all, sort, order, rating, globalThis.TradeUI?.status()])
  if (key === signature) return
  signature = key
  $('#mobile-box').innerHTML = `<option value="0">Party · ${party.length} / 6</option>` + counts.map((count, index) => `<option value="${index + 1}">Box ${index + 1} · ${count} / 20${index + 1 === storage?.active_box ? ' · Receiving catches' : ''}</option>`).join('')
  $('#mobile-box').value = String(selectedBox)
  const focusedBox = document.activeElement?.dataset.box
  $('#box-picker').innerHTML = `<button data-box="0" aria-pressed="${selectedBox === 0}" class="${selectedBox === 0 ? 'selected' : ''}"><span class="bp-name">Party</span><small>${party.length} / 6</small>${fillMeter(party.length, 6)}</button>` + counts.map((count, index) => `<button data-box="${index + 1}" aria-pressed="${index + 1 === selectedBox}" class="${index + 1 === selectedBox ? 'selected' : ''}"><span class="bp-name">Box ${index + 1}${index + 1 === storage?.active_box ? '<i class="lamp" data-on="ok" title="Receiving new catches"></i><span class="vh"> · receiving catches</span>' : ''}</span><small>${count} / 20</small>${fillMeter(count, 20)}</button>`).join('')
  if (focusedBox) $(`[data-box="${focusedBox}"]`)?.focus()
  const focusedMon = document.activeElement?.dataset.mon
  const card = (mon, index) => `<button class="pc-mon${mon.perfect_dvs ? ' perfect-entry' : ''}" data-mon="${index}" aria-label="${esc(mon.nick || mon.name)}, level ${mon.level}${mon.type_names?.length ? ", " + esc(mon.type_names.join(" / ")) : ""}, ${mon.box === 0 ? 'party' : `box ${mon.box}`}${', ' + ratingLabel(mon)}${isLocked(mon) ? ', locked' : ''}${mon.shiny ? ', shiny, protected from release and trading' : ''}${mon.perfect_dvs ? ', perfect DVs, preserved for the collection' : ''}"><span class="pc-slot">${mon.box === 0 ? 'PARTY' : `BOX ${mon.box}`} · SLOT ${mon.position || index + 1}</span><span class="plate pc-plate ${PokemonTypes.portraitClass(mon.type_names)}">${mon.egg ? PokemonTypes.eggPlate : `<img loading="lazy" src="${PokeSim.base}/sprites/${Number(mon.dex) || 0}.png?v=rom-portraits-1" alt="">`}</span><span class="pc-mon-body"><strong class="pc-name">${esc(mon.nick || mon.name)}</strong><small class="pc-sub">${esc(mon.name)} · Lv. ${mon.level}</small><span class="type-tags">${PokemonTypes.badges(mon.type_names)}</span><span class="pc-tags">${PokemonTypes.shinyBadge(mon)}${ratingBadge(mon)}${lockBadge(mon)}</span></span>${all ? `<span class="pc-metrics"><span class="pc-power">Battle Power <b>${Number.isFinite(mon.battle_power) ? mon.battle_power.toLocaleString() : 'Unavailable'}</b></span><span>Stat Power <b>${Number.isFinite(mon.power) ? mon.power.toLocaleString() : 'Unavailable'}</b></span><span>Total DVs <b>${formatTotal(mon, 'dvs')}</b></span><span>Stat exp. <b>${formatTotal(mon, 'stat_exp')}</b></span></span>` : ''}</button>`
  if (all) {
    $('#pc-grid').innerHTML = residents.map(card).join('') || '<p class="dex-empty">No Pokémon match these filters.</p>'
  } else {
    $('#pc-grid').innerHTML = Array.from({length: selectedBox === 0 ? 6 : 20}, (_, slot) => {
      const index = residents.findIndex(mon => mon.position === slot + 1)
      return index >= 0 ? card(residents[index], index) : `<div class="pc-empty-slot"><span class="pc-slot">SLOT ${slot + 1}</span></div>`
    }).join('')
    if ((query || rating !== 'all') && !residents.length) $('#pc-grid').innerHTML = '<p class="dex-empty">No partners match these filters here.</p>'
  }
  if (focusedMon) $(`[data-mon="${focusedMon}"]`)?.focus()
  fitSprites($('#pc-grid'))
}

// Gen I and II split physical and special by type; a move with no power is a status move.
const SPECIAL_TYPES = new Set(['Fire', 'Water', 'Grass', 'Electric', 'Psychic', 'Ice', 'Dragon', 'Dark'])
const moveCategory = move => !move.power ? 'Status' : SPECIAL_TYPES.has(move.type) ? 'Special' : 'Physical'
const fmt = value => Number(value).toLocaleString()

// Sixteen discrete cells, matching the live party meters; a sliver still lights one cell.
function gauge(percent, level, label) {
  const value = Math.max(0, Math.min(100, Number(percent) || 0))
  const lit = value > 0 ? Math.max(1, Math.round(value / 100 * 16)) : 0
  return `<span class="meter" data-level="${level}" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(value)}" aria-label="${esc(label)}">${Array.from({length: 16}, (_, i) => `<i${i < lit ? ' class="on"' : ''}></i>`).join('')}</span>`
}

// Gen II sends progress as the experience itself; Gen I sends it beside the running total.
function experienceProgress(mon) {
  if (mon.experience_progress && typeof mon.experience_progress === 'object') return mon.experience_progress
  return mon.experience && typeof mon.experience === 'object' ? mon.experience : null
}

// Mirrors the trade control below the popup: its state, and why when it is not offered.
function tradeState(mon) {
  if (mon.shiny || mon.perfect_dvs) return {state: 'Protected', note: 'Kept from release and trading'}
  const offer = globalThis.TradeUI?.find(mon.trade_key)
  if (offer?.locked || offer?.preference === 'locked' || (!offer && (mon.trade_locked || mon.trade_preference === 'locked'))) return {state: 'Locked', note: ''}
  if (offer?.listed || offer?.preference === 'offered' || (!offer && mon.trade_preference === 'offered')) return {state: 'Offered', note: offer?.source || ''}
  return offer ? {state: 'Not offered', note: offer.reason || ''} : null
}

function moveList(mon) {
  const moves = mon.move_details || []
  if (!moves.length) return '<p class="detail-meta">No moves recorded.</p>'
  return `<ul class="pc-moves">${moves.map(original => {
    // Hidden Power takes its type and power from the DVs, not from the move table.
    const move = original.name === 'Hidden Power' && mon.hidden_power ? {...original, ...mon.hidden_power} : original
    const known = Number.isFinite(move.pp) && Number.isFinite(move.max_pp)
    const pp = known ? `<span class="pc-move-pp${move.pp ? '' : ' empty'}"><b>${move.pp}</b>/${move.max_pp} PP</span>` : ''
    const specs = Number.isFinite(move.power) ? [moveCategory(move), move.power ? `Pow ${move.power}` : 'Pow —',
      Number.isFinite(move.accuracy) && move.accuracy ? `Acc ${move.accuracy}%` : 'Acc —'] : []
    return `<li class="pc-move"><span class="pc-move-name">${esc(move.name)}</span>${pp}<span class="pc-move-specs">${PokemonTypes.badges([move.type])}${specs.map(spec => `<span>${esc(spec)}</span>`).join('')}</span></li>`
  }).join('')}</ul>`
}

function conditionRows(mon) {
  const rows = []
  if (Number.isFinite(mon.hp) && Number.isFinite(mon.max_hp) && mon.max_hp > 0) {
    const percent = mon.hp / mon.max_hp * 100
    rows.push(`<div class="meter-row"><span class="micro">HP</span>${gauge(percent, percent < 20 ? 'crit' : percent < 50 ? 'warn' : 'ok', `Health: ${mon.hp} of ${mon.max_hp}`)}<span class="value">${fmt(mon.hp)}/${fmt(mon.max_hp)}</span></div>`)
  }
  const xp = experienceProgress(mon)
  if (xp && Number.isFinite(xp.percent)) {
    rows.push(`<div class="meter-row"><span class="micro">XP</span>${gauge(xp.percent, 'signal', `Progress to level ${mon.level + 1}`)}<span class="value">${xp.max_level ? 'MAX' : `${Math.round(xp.percent)}%`}</span></div>`)
  }
  return rows.join('')
}

function facts(mon) {
  const cell = (label, value, note = '') => `<div><dt>${label}</dt><dd>${value}${note ? `<small>${note}</small>` : ''}</dd></div>`
  const number = value => Number.isFinite(value) ? fmt(value) : 'Unavailable'
  const out = []
  const xp = experienceProgress(mon)
  const total = xp?.total ?? (Number.isFinite(mon.experience) ? mon.experience : null)
  if (Number.isFinite(total)) out.push(cell('Experience', fmt(total), xp ? xp.max_level ? 'Max level' : `${fmt(xp.remaining)} to Lv. ${mon.level + 1}` : ''))
  if (mon.battle_power !== undefined) out.push(cell('Battle Power', number(mon.battle_power)))
  out.push(cell('Stat Power', number(mon.power)))
  out.push(cell('Potential Stat Power', number(mon.potential_power)))
  if (mon.hidden_power) out.push(cell('Hidden Power', `${PokemonTypes.badges([mon.hidden_power.type])} ${mon.hidden_power.power}`))
  if (Number.isFinite(mon.friendship)) out.push(cell('Friendship', `${mon.friendship}<span class="unit">/255</span>`))
  if (Number.isFinite(mon.trainer_id)) out.push(cell('Original trainer', `ID ${String(mon.trainer_id).padStart(5, '0')}`))
  if (mon.caught) out.push(cell('Caught', esc(mon.caught.location || 'Unknown place'), [mon.caught.level ? `Lv. ${mon.caught.level}` : '', mon.caught.time].filter(Boolean).map(esc).join(' · ')))
  if ('pokerus' in mon) out.push(cell('Pokérus', mon.pokerus === 'infected' ? '<span class="tag tag--warn">Infected</span>' : mon.pokerus === 'cured' ? '<span class="tag">Cured</span>' : 'None'))
  if (mon.elite_four_wins !== undefined) out.push(cell('Elite Four wins', mon.elite_four_wins === null ? 'Unknown' : `${fmt(mon.elite_four_wins)}${mon.elite_four_wins_incomplete ? '+' : ''}`))
  const trade = tradeState(mon)
  if (trade) out.push(cell('Trade', trade.state, esc(trade.note)))
  return `<dl class="pc-facts">${out.join('')}</dl>`
}

function eggFacts(mon) {
  const cycles = mon.egg_cycles
  const rows = [`<div><dt>Hatches in</dt><dd>${Number.isFinite(cycles) ? `${fmt(cycles)} egg cycle${cycles === 1 ? '' : 's'}<small>About ${fmt(cycles * 256)} steps in the party</small>` : 'Unknown'}</dd></div>`]
  const trade = tradeState(mon)
  if (trade) rows.push(`<div><dt>Trade</dt><dd>${trade.state}${trade.note ? `<small>${esc(trade.note)}</small>` : ''}</dd></div>`)
  return `<dl class="pc-facts">${rows.join('')}</dl>`
}

function detail(mon) {
  detailKey = mon.trade_key
  const labels = Object.keys(mon.calculated_stats || {})
  const known = mon.dvs?.length === 5 && mon.stat_exp?.length === 5
  const status = mon.status_label || (Number.isFinite(mon.hp) ? mon.hp ? 'Healthy' : 'Fainted' : '')
  const statusTag = !mon.egg && status ? `<span class="tag pc-status${status === 'Healthy' ? '' : mon.hp ? ' tag--warn' : ' tag--crit'}">${esc(status)}</span>` : ''
  const head = `<div class="pc-detail-head"><div class="plate plate--bay ${PokemonTypes.portraitClass(mon.type_names)}">${mon.egg ? PokemonTypes.eggPlate : `<img src="${PokeSim.base}/sprites/${Number(mon.dex) || 0}.png?v=rom-portraits-1" alt="">`}</div><p class="micro">${mon.box === 0 ? 'PARTY' : `BOX ${mon.box}`} · SLOT ${mon.position || '?'}${mon.dex ? ` · No.${String(mon.dex).padStart(3, '0')}` : ''}</p><h2 id="pc-detail-name">${esc(mon.nick || mon.name)}</h2>${mon.egg ? '' : `<div class="pc-tags">${PokemonTypes.shinyBadge(mon)}${ratingBadge(mon)}${statusTag}</div>`}${mon.perfect_dvs || mon.shiny ? '<p class="detail-meta">Protected from automatic release and trading.</p>' : ''}<p>${mon.egg ? 'Not yet hatched' : `${esc(mon.name)} · Level ${mon.level}${mon.gender ? ` · ${esc(mon.gender)}` : ''}`}</p>${mon.held_item_name ? `<p>Holding ${esc(mon.held_item_name)}</p>` : ''}<div class="type-tags">${PokemonTypes.badges(mon.type_names)}</div></div>`
  const section = (title, body) => `<section class="pc-detail-section"><h3 class="micro">${title}</h3>${body}</section>`
  const links = `<div class="pc-detail-links"><a class="dex-open key" href="https://github.com/afk-sapien/PokeSim/blob/main/docs/pokemon-stats.md" target="_blank" rel="noopener noreferrer">Stats guide ↗</a>${mon.dex ? `<a class="dex-open key" href="${PokeSim.base}/pokedex#${String(mon.dex).padStart(3, '0')}">Pokédex ↗</a>` : ''}</div>`
  if (mon.egg) {
    $('#pc-detail-body').innerHTML = head + section('Egg', eggFacts(mon)) + '<p class="detail-meta pc-detail-note">Its species, moves and stats appear once it hatches.</p>'
  } else {
    const condition = conditionRows(mon)
    const stats = known ? `<table class="individual-stats"><caption>Stats</caption><thead><tr><th>Stat</th><th>Value</th><th>DV</th><th>Stat exp.</th></tr></thead><tbody>${labels.map((label, i) => `<tr><th scope="row">${label}</th><td>${mon.calculated_stats?.[label] ?? 'Unavailable'}</td><td>${mon.dvs[Math.min(i, 4)]}</td><td>${mon.stat_exp[Math.min(i, 4)].toLocaleString()}</td></tr>`).join('')}</tbody><tfoot><tr><th scope="row">Total</th><td>${Number.isFinite(mon.stat_total) ? mon.stat_total.toLocaleString() : 'Unavailable'}</td><td>${formatTotal(mon, 'dvs')}</td><td>${formatTotal(mon, 'stat_exp')}</td></tr></tfoot></table>` : '<p class="detail-meta">Individual stats are unavailable in this snapshot.</p>'
    const quality = Number.isFinite(mon.dv_top_percent) ? `<p class="detail-meta">DV quality (est.): top ${mon.dv_top_percent.toLocaleString(undefined, {maximumSignificantDigits: 3})}% · Higher roll: ${mon.dv_better_percent.toLocaleString(undefined, {maximumSignificantDigits: 3})}%</p>` : ''
    const battleNote = mon.battle_power === undefined ? '' : '<p class="detail-meta">Battle Power rates known moves at full health and PP. Matchups can change the result.</p>'
    $('#pc-detail-body').innerHTML = head
      + (condition ? section('Condition', `<div class="mon-meters pc-gauges">${condition}</div>`) : '')
      + section('Moves', moveList(mon))
      + section('Record', facts(mon) + battleNote)
      + `<section class="pc-detail-section">${stats}${quality}</section>`
      + links
  }
  $('#pc-trade-action').innerHTML = globalThis.TradeUI?.control(detailKey) || ''
  $('#pc-detail').showModal()
  fitSprites($('#pc-detail-body'))
}

async function refresh() {
  if (busy) return
  busy = true
  try {
    const response = await PokeSim.fetch('/api/pokedex/status', {cache: 'no-store'})
    if (!response.ok) throw new Error('Unavailable')
    const status = await response.json()
    storage = status.storage
    const special = $('#pc-sort option[value="Special"]')
    if (status.generation === 2 && special) {
      special.value = 'Special Attack'
      special.textContent = 'Special Attack'
      const defense = document.createElement('option')
      defense.value = 'Special Defense'
      defense.textContent = 'Special Defense'
      special.after(defense)
    }
    party = (status.party || []).map((mon) => ({...mon, box: 0, position: mon.slot}))
    if (followActive && storage) { selectedBox = storage.active_box
      followActive = false }
    $('#status').textContent = status.started ? 'Running' : 'Waiting'
    $('#connection').title = status.started ? 'Adventure in progress' : 'Waiting for the adventure'
    $('#connection').classList.remove('is-offline')
    render()
  } catch (_) {
    $('#status').textContent = 'Reconnecting…'
    $('#connection').title = ''
    $('#connection').classList.add('is-offline')
  } finally { busy = false }
}

$('#box-picker').onclick = (event) => {
  const button = event.target.closest('[data-box]')
  if (!button) return
  selectedBox = Number(button.dataset.box)
  followActive = false
  $('#pc-scope').value = 'box'
  render()
}
$('#mobile-box').onchange = (event) => {
  selectedBox = Number(event.target.value)
  followActive = false
  $('#pc-scope').value = 'box'
  render()
}
$('#pc-grid').onclick = (event) => {
  const offer = event.target.closest('[data-trade-key]')
  if (offer?.dataset.tradeKey) { globalThis.TradeUI?.change(offer)
    return }
  const button = event.target.closest('[data-mon]')
  if (button) detail(residents[Number(button.dataset.mon)])
}
if ($('#pc-strongest')) $('#pc-strongest').onclick = () => {
  switchView('all')
  $('#pc-search').value = ''
  $('#pc-rating').value = 'all'
  $('#pc-sort').value = 'battle_power'
  $('#pc-sort').onchange()
}
function switchView(view) {
  const previous = $('#pc-scope').value
  if (previous !== view) {
    viewQueries[previous] = $('#pc-search').value
    $('#pc-scope').value = view
    $('#pc-search').value = viewQueries[view]
  }
  render()
}
$('#pc-boxes-view').onclick = () => switchView('box')
$('#pc-all-view').onclick = () => switchView('all')
$('#pc-trade-action').onclick = event => {
  const button = event.target.closest('[data-trade-key]')
  if (button) globalThis.TradeUI?.change(button)
}
$('#pc-sort').onchange = () => {
  $('#pc-order').value = sortDefaults[$('#pc-sort').value]
  render()
}
$('#pc-order').onchange = render
for (const selector of ['#pc-search', '#pc-scope', '#pc-rating']) {
  $(selector).oninput = render
}
$('#pc-close').onclick = () => $('#pc-detail').close()
$('#pc-detail').onclick = (event) => {
  if (event.target !== $('#pc-detail')) return
  const rect = event.target.getBoundingClientRect()
  if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) event.target.close()
}
refresh()
if (globalThis.TradeUI) {
  TradeUI.subscribe(() => {
    render()
    if (detailKey) $('#pc-trade-action').innerHTML = TradeUI.control(detailKey)
  })
  TradeUI.refresh()
  setInterval(() => { if (!document.hidden) TradeUI.refresh() }, 15000)
}
setInterval(() => { if (!document.hidden) refresh() }, 5000)
