const $ = (selector) => document.querySelector(selector)
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&': '&amp', '<': '&lt', '>': '&gt', '"': '&quot', "'": '&#39'}[char] + String.fromCharCode(59)))
const params = new URLSearchParams(location.search)
let selectedBox = params.get('box') === 'party' ? 0 : Math.min(12, Math.max(1, Number(params.get('box')) || 1))
let followActive = !params.has('box')
let storage = null
let party = []
let busy = false
let signature = ''
let residents = []
let detailKey = null
$('#pc-rating').value = ['1', '2', '3', '4', '3plus', 'unknown'].includes(params.get('rating')) ? params.get('rating') : 'all'
let viewQueries = {box: '', all: ''}
$('#pc-search').value = params.get('q') || ''
$('#pc-scope').value = params.get('scope') === 'all' ? 'all' : 'box'
viewQueries[$('#pc-scope').value] = $('#pc-search').value
const sortDefaults = {box: 'asc', power: 'desc', level: 'desc', HP: 'desc', Attack: 'desc', Defense: 'desc', Speed: 'desc', Special: 'desc', elite_four_wins: 'desc', dv_stars: 'desc', dvs: 'desc', stat_exp: 'desc', experience: 'desc', dex: 'asc', name: 'asc', nick: 'asc'}
$('#pc-sort').value = Object.hasOwn(sortDefaults, params.get('sort')) ? params.get('sort') : 'box'
$('#pc-order').value = ['asc', 'desc'].includes(params.get('order')) ? params.get('order') : sortDefaults[$('#pc-sort').value]

function statTotal(mon, field) {
  const values = mon[field]
  return Array.isArray(values) && values.length === 5 && values.every(Number.isFinite)
    ? values.reduce((sum, value) => sum + value, 0) : null
}

function sortValue(mon, field) {
  if (field === 'dvs' || field === 'stat_exp') return statTotal(mon, field)
  if (['HP', 'Attack', 'Defense', 'Speed', 'Special'].includes(field)) return mon.calculated_stats?.[field] ?? null
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

function ratingBadge(mon) {
  if (!Number.isInteger(mon.dv_stars) || mon.dv_stars < 1 || mon.dv_stars > 4) return '<span class="dv-badge dv-unknown">DVs unknown</span>'
  return `<span class="dv-badge dv-stars-${mon.dv_stars}" aria-label="${ratingLabel(mon)}" title="${mon.dv_total} / 75 DVs · ${mon.dv_percent}%"><span aria-hidden="true">${'★'.repeat(mon.dv_stars)}${'☆'.repeat(4 - mon.dv_stars)}</span> ${mon.dv_stars === 4 ? 'Perfect DV' : 'DV'}</span>`
}

function lockBadge(mon) {
  return isLocked(mon) ? '<span class="pc-lock-badge"><span aria-hidden="true">🔒</span> Locked</span>' : ''
}

function render() {
  const counts = storage?.box_counts || Array(12).fill(0)
  const pokemon = [...party, ...(storage?.pokemon || [])]
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
  const rows = pokemon.filter((mon) => (rating === 'all' || (rating === 'unknown' ? mon.dv_stars == null : rating === '3plus' ? mon.dv_stars >= 3 : mon.dv_stars === Number(rating))) && (all || mon.box === selectedBox) && (!query ||
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
  $('#pc-power-note').hidden = !all
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
  $('#box-picker').innerHTML = `<button data-box="0" aria-pressed="${selectedBox === 0}" class="${selectedBox === 0 ? 'selected' : ''}"><span>Party</span><small>${party.length} / 6</small></button>` + counts.map((count, index) => `<button data-box="${index + 1}" aria-pressed="${index + 1 === selectedBox}" class="${index + 1 === selectedBox ? 'selected' : ''}"><span>Box ${index + 1}${index + 1 === storage?.active_box ? ' ●' : ''}</span><small>${count} / 20</small></button>`).join('')
  if (focusedBox) $(`[data-box="${focusedBox}"]`)?.focus()
  const focusedMon = document.activeElement?.dataset.mon
  const card = (mon, index) => `<button class="pc-mon${mon.perfect_dvs ? ' perfect-entry' : ''}" data-mon="${index}" aria-label="${esc(mon.nick || mon.name)}, level ${mon.level}, ${mon.box === 0 ? 'party' : `box ${mon.box}`}${', ' + ratingLabel(mon)}${isLocked(mon) ? ', locked' : ''}${mon.perfect_dvs ? ', perfect DVs, preserved for the collection' : ''}"><span class="eyebrow">${mon.box === 0 ? 'PARTY' : `BOX ${mon.box}`} · SLOT ${mon.position || index + 1}</span><img loading="lazy" src="${PokeSim.base}/sprites/${Number(mon.dex) || 0}.png" alt="" width="72" height="72"><strong>${esc(mon.nick || mon.name)}${lockBadge(mon)}${ratingBadge(mon)}</strong><small>${esc(mon.name)} · Lv. ${mon.level}</small>${all ? `<span class="pc-metrics"><span class="pc-power">Power <b>${Number.isFinite(mon.power) ? mon.power.toLocaleString() : 'Unavailable'}</b></span><span>Elite Four wins <b>${Number.isFinite(mon.elite_four_wins) ? mon.elite_four_wins.toLocaleString() : 'Unavailable'}</b></span><span>Total DVs <b>${formatTotal(mon, 'dvs')}</b></span><span>Stat exp. <b>${formatTotal(mon, 'stat_exp')}</b></span></span>` : ''}</button>`
  if (all) {
    $('#pc-grid').innerHTML = residents.map(card).join('') || '<p class="dex-empty">No Pokémon match these filters.</p>'
  } else {
    $('#pc-grid').innerHTML = Array.from({length: selectedBox === 0 ? 6 : 20}, (_, slot) => {
      const index = residents.findIndex(mon => mon.position === slot + 1)
      return index >= 0 ? card(residents[index], index) : `<div class="pc-empty-slot"><span class="eyebrow">SLOT ${slot + 1}</span></div>`
    }).join('')
    if ((query || rating !== 'all') && !residents.length) $('#pc-grid').innerHTML = '<p class="dex-empty">No partners match these filters here.</p>'
  }
  if (focusedMon) $(`[data-mon="${focusedMon}"]`)?.focus()
}

function detail(mon) {
  detailKey = mon.trade_key
  const labels = ['HP', 'Attack', 'Defense', 'Speed', 'Special']
  const known = mon.dvs?.length === 5 && mon.stat_exp?.length === 5
  $('#pc-detail-body').innerHTML = `<div class="pc-detail-head"><img src="${PokeSim.base}/sprites/${Number(mon.dex) || 0}.png" alt="" width="96" height="96"><p class="eyebrow">${mon.box === 0 ? 'PARTY' : `BOX ${mon.box}`} · SLOT ${mon.position || '?'}</p><h2 id="pc-detail-name">${esc(mon.nick || mon.name)}</h2>${ratingBadge(mon)}${mon.perfect_dvs ? '<p class="detail-meta">All five DVs are 15. Preserved from automatic release and trading.</p>' : ''}<p>${esc(mon.name)} · Level ${mon.level}</p></div>
    <p class="detail-meta">DV stars measure fixed potential using the total of all five DVs, including derived HP, out of 75. 1★: 0–37, 2★: 38–59, 3★: 60–74, 4★: 75 (perfect). Level and training do not affect this rating.</p>
    ${known ? `<table class="individual-stats"><caption>Calculated stats, potential, and training</caption><thead><tr><th>Stat</th><th>Value</th><th>DV / 15</th><th>Stat experience</th></tr></thead><tbody>${labels.map((label, i) => `<tr><th scope="row">${label}</th><td>${mon.calculated_stats?.[label] ?? 'Unavailable'}</td><td>${mon.dvs[i]}</td><td>${mon.stat_exp[i].toLocaleString()}</td></tr>`).join('')}</tbody><tfoot><tr><th scope="row">Total</th><td>${Number.isFinite(mon.power) ? mon.power.toLocaleString() : 'Unavailable'}</td><td>${formatTotal(mon, 'dvs')} / 75</td><td>${formatTotal(mon, 'stat_exp')} / 327,675</td></tr></tfoot></table><p class="detail-meta">Total DVs include HP, which is derived from the other four DVs. DVs are fixed. Stat experience grows through training, up to 65,535 in each stat.</p>` : '<p class="detail-meta">Individual stats are unavailable in this snapshot.</p>'}
    <p class="detail-meta">Power = max HP + Attack + Defense + Speed + Special. Values are calculated at this level from species, DVs, and stat experience, as on PC withdrawal. Moves, type matchups, and battle bonuses are not included.</p>
    <p class="detail-meta"><strong>Elite Four wins: ${Number.isFinite(mon.elite_four_wins) ? mon.elite_four_wins.toLocaleString() : 'Unavailable'}</strong>. One win for being in the Hall of Fame party after defeating the Elite Four and Champion. Includes verified saved victories and follows this Pokémon through trades. Missing historical records are not estimated.</p>
    <p class="detail-meta">${Number(mon.experience || 0).toLocaleString()} total experience</p>
    ${mon.dex ? `<a class="dex-open" href="${PokeSim.base}/pokedex#${String(mon.dex).padStart(3, '0')}">View ${esc(mon.name)} in the Pokédex ↗</a>` : ''}`
  $('#pc-trade-action').innerHTML = globalThis.TradeUI?.control(detailKey) || ''
  $('#pc-detail').showModal()
}

async function refresh() {
  if (busy) return
  busy = true
  try {
    const response = await PokeSim.fetch('/api/pokedex/status', {cache: 'no-store'})
    if (!response.ok) throw new Error('Unavailable')
    const status = await response.json()
    storage = status.storage
    party = (status.party || []).map((mon) => ({...mon, box: 0, position: mon.slot}))
    if (followActive && storage) { selectedBox = storage.active_box
      followActive = false }
    $('#status').textContent = status.started ? 'Adventure in progress' : 'Waiting for the adventure'
    $('#connection').classList.remove('is-offline')
    render()
  } catch (_) {
    $('#status').textContent = 'Reconnecting…'
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
  $('#pc-sort').value = 'power'
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
