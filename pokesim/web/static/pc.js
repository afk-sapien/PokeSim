const $ = (selector) => document.querySelector(selector)
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&': '&amp', '<': '&lt', '>': '&gt', '"': '&quot', "'": '&#39'}[char] + String.fromCharCode(59)))
const params = new URLSearchParams(location.search)
let selectedBox = params.get('box') === 'party' ? 0 : Math.min(12, Math.max(1, Number(params.get('box')) || 1))
let followActive = !params.has('box')
let storage = null
let party = []
let page = 0
let busy = false
let signature = ''
let residents = []
let detailKey = null
let viewPages = {box: 0, all: 0}
let viewQueries = {box: '', all: ''}
$('#pc-search').value = params.get('q') || ''
$('#pc-scope').value = params.get('scope') === 'all' ? 'all' : 'box'
viewQueries[$('#pc-scope').value] = $('#pc-search').value
const sortDefaults = {box: 'asc', power: 'desc', level: 'desc', HP: 'desc', Attack: 'desc', Defense: 'desc', Speed: 'desc', Special: 'desc', dvs: 'desc', stat_exp: 'desc', experience: 'desc', dex: 'asc', name: 'asc', nick: 'asc'}
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
  return comparison * (order === 'desc' ? -1 : 1) || a.box - b.box || (a.position || 0) - (b.position || 0)
}

function formatTotal(mon, field) {
  const total = statTotal(mon, field)
  return total === null ? 'Unavailable' : total.toLocaleString()
}

function isLocked(mon) {
  return globalThis.TradeUI?.find(mon.trade_key)?.locked ?? mon.trade_locked
}

function lockBadge(mon) {
  return isLocked(mon) ? '<span class="pc-lock-badge"><span aria-hidden="true">🔒</span> Locked</span>' : ''
}

function render() {
  const counts = storage?.box_counts || Array(12).fill(0)
  const pokemon = [...party, ...(storage?.pokemon || [])]
  const query = $('#pc-search').value.trim().toLowerCase().replace(/^#/, '')
  const all = $('#pc-scope').value === 'all'
  const sort = $('#pc-sort').value
  const order = $('#pc-order').value
  const alphabetical = sort === 'name' || sort === 'nick'
  $('#pc-order').options[0].textContent = alphabetical ? 'A to Z' : sort === 'box' ? 'First to last' : 'Lowest first'
  $('#pc-order').options[1].textContent = alphabetical ? 'Z to A' : sort === 'box' ? 'Last to first' : 'Highest first'
  const rows = pokemon.filter((mon) => (all || mon.box === selectedBox) && (!query ||
    `${mon.nick} ${mon.name}`.toLowerCase().includes(query) || String(mon.dex).padStart(3, '0').includes(query)))
  rows.sort((a, b) => comparePartners(a, b, all ? sort : 'box', all ? order : 'asc'))
  const pages = Math.max(1, Math.ceil(rows.length / 20))
  page = Math.min(page, pages - 1)
  residents = rows.slice(page * 20, (page + 1) * 20)
  const url = new URLSearchParams({box: selectedBox === 0 ? 'party' : String(selectedBox)})
  if (query) url.set('q', $('#pc-search').value)
  if (all) url.set('scope', 'all')
  url.set('sort', sort)
  url.set('order', order)
  history.replaceState(null, '', `${PokeSim.base}/pc?${url}`)
  $('#pc-total').textContent = `${counts.reduce((sum, count) => sum + count, 0)} / ${counts.length * 20}`
  $('#pc-active').textContent = `Box ${storage?.active_box || 1}`
  $('#pc-heading').textContent = all ? 'Party and all boxes' : selectedBox === 0 ? 'Party' : `Box ${selectedBox}`
  $('#pc-note').textContent = all ? 'ALL PARTNERS' : selectedBox === 0 ? 'TRAVELING TEAM' : selectedBox === storage?.active_box ? 'TAKING NEW ARRIVALS' : 'STORED PARTNERS'
  $('#pc-count').textContent = `${rows.length} Pokémon`
  $('#pc-page').textContent = `Page ${page + 1} of ${pages}`
  $('#pc-prev').disabled = page === 0
  $('#pc-next').disabled = page >= pages - 1
  $('#pc-sidebar').hidden = all
  $('#pc-sort-control').hidden = !all
  $('#pc-order-control').hidden = !all
  $('#pc-power-note').hidden = !all
  $('#pc-pagination').hidden = !all
  $('#pc-workspace').classList.toggle('pc-workspace-all', all)
  $('#pc-grid').classList.toggle('pc-list', all)
  $('#pc-boxes-view').setAttribute('aria-pressed', String(!all))
  $('#pc-all-view').setAttribute('aria-pressed', String(all))
  const key = JSON.stringify([storage, party, selectedBox, query, all, sort, order, page, globalThis.TradeUI?.status()])
  if (key === signature) return
  signature = key
  $('#mobile-box').innerHTML = `<option value="0">Party · ${party.length} / 6</option>` + counts.map((count, index) => `<option value="${index + 1}">Box ${index + 1} · ${count} / 20${index + 1 === storage?.active_box ? ' · Receiving catches' : ''}</option>`).join('')
  $('#mobile-box').value = String(selectedBox)
  const focusedBox = document.activeElement?.dataset.box
  $('#box-picker').innerHTML = `<button data-box="0" aria-pressed="${selectedBox === 0}" class="${selectedBox === 0 ? 'selected' : ''}"><span>Party</span><small>${party.length} / 6</small></button>` + counts.map((count, index) => `<button data-box="${index + 1}" aria-pressed="${index + 1 === selectedBox}" class="${index + 1 === selectedBox ? 'selected' : ''}"><span>Box ${index + 1}${index + 1 === storage?.active_box ? ' ●' : ''}</span><small>${count} / 20</small></button>`).join('')
  if (focusedBox) $(`[data-box="${focusedBox}"]`)?.focus()
  const focusedMon = document.activeElement?.dataset.mon
  const card = (mon, index) => `<button class="pc-mon" data-mon="${index}" aria-label="${esc(mon.nick || mon.name)}, level ${mon.level}, ${mon.box === 0 ? 'party' : `box ${mon.box}`}${isLocked(mon) ? ', locked' : ''}"><span class="eyebrow">${mon.box === 0 ? 'PARTY' : `BOX ${mon.box}`} · SLOT ${mon.position || index + 1}</span><img loading="lazy" src="${PokeSim.base}/sprites/${Number(mon.dex) || 0}.png" alt="" width="72" height="72"><strong>${esc(mon.nick || mon.name)}${lockBadge(mon)}</strong><small>${esc(mon.name)} · Lv. ${mon.level}</small>${all ? `<span class="pc-metrics"><span class="pc-power">Power <b>${Number.isFinite(mon.power) ? mon.power.toLocaleString() : 'Unavailable'}</b></span><span>Total DVs <b>${formatTotal(mon, 'dvs')}</b></span><span>Stat exp. <b>${formatTotal(mon, 'stat_exp')}</b></span></span>` : ''}</button>`
  if (all) {
    $('#pc-grid').innerHTML = residents.map((mon, index) => `<div class="pc-list-row">${card(mon, index)}<div class="pc-list-trade">${globalThis.TradeUI?.control(mon.trade_key) || ''}</div></div>`).join('') || '<p class="dex-empty">No Pokémon match this search.</p>'
  } else {
    $('#pc-grid').innerHTML = Array.from({length: selectedBox === 0 ? 6 : 20}, (_, slot) => {
      const index = residents.findIndex(mon => mon.position === slot + 1)
      return index >= 0 ? card(residents[index], index) : `<div class="pc-empty-slot"><span class="eyebrow">SLOT ${slot + 1}</span></div>`
    }).join('')
    if (query && !residents.length) $('#pc-grid').innerHTML = '<p class="dex-empty">No partners match this search in this box.</p>'
  }
  if (focusedMon) $(`[data-mon="${focusedMon}"]`)?.focus()
}

function detail(mon) {
  detailKey = mon.trade_key
  const labels = ['HP', 'Attack', 'Defense', 'Speed', 'Special']
  const known = mon.dvs?.length === 5 && mon.stat_exp?.length === 5
  $('#pc-detail-body').innerHTML = `<div class="pc-detail-head"><img src="${PokeSim.base}/sprites/${Number(mon.dex) || 0}.png" alt="" width="96" height="96"><p class="eyebrow">${mon.box === 0 ? 'PARTY' : `BOX ${mon.box}`} · SLOT ${mon.position || '?'}</p><h2 id="pc-detail-name">${esc(mon.nick || mon.name)}</h2><p>${esc(mon.name)} · Level ${mon.level}</p></div>
    ${known ? `<table class="individual-stats"><caption>Calculated stats, potential, and training</caption><thead><tr><th>Stat</th><th>Value</th><th>DV / 15</th><th>Stat experience</th></tr></thead><tbody>${labels.map((label, i) => `<tr><th scope="row">${label}</th><td>${mon.calculated_stats?.[label] ?? 'Unavailable'}</td><td>${mon.dvs[i]}</td><td>${mon.stat_exp[i].toLocaleString()}</td></tr>`).join('')}</tbody><tfoot><tr><th scope="row">Total</th><td>${Number.isFinite(mon.power) ? mon.power.toLocaleString() : 'Unavailable'}</td><td>${formatTotal(mon, 'dvs')} / 75</td><td>${formatTotal(mon, 'stat_exp')} / 327,675</td></tr></tfoot></table><p class="detail-meta">Total DVs include HP, which is derived from the other four DVs. DVs are fixed. Stat experience grows through training, up to 65,535 in each stat.</p>` : '<p class="detail-meta">Individual stats are unavailable in this snapshot.</p>'}
    <p class="detail-meta">Power = max HP + Attack + Defense + Speed + Special. Values are calculated at this level from species, DVs, and stat experience, as on PC withdrawal. Moves, type matchups, and battle bonuses are not included.</p>
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
    if (status.version) $('#edition').textContent = `${status.version.toUpperCase()} VERSION`
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
  page = 0
  render()
}
$('#mobile-box').onchange = (event) => {
  selectedBox = Number(event.target.value)
  followActive = false
  $('#pc-scope').value = 'box'
  page = 0
  render()
}
$('#pc-grid').onclick = (event) => {
  const offer = event.target.closest('[data-trade-key]')
  if (offer?.dataset.tradeKey) { globalThis.TradeUI?.change(offer)
    return }
  const button = event.target.closest('[data-mon]')
  if (button) detail(residents[Number(button.dataset.mon)])
}
$('#pc-strongest').onclick = () => {
  switchView('all')
  $('#pc-search').value = ''
  $('#pc-sort').value = 'power'
  $('#pc-sort').onchange()
}
function switchView(view) {
  const previous = $('#pc-scope').value
  if (previous !== view) {
    viewPages[previous] = page
    viewQueries[previous] = $('#pc-search').value
    $('#pc-scope').value = view
    page = viewPages[view]
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
  page = 0
  render()
}
$('#pc-order').onchange = () => { page = 0
  render() }
for (const selector of ['#pc-search', '#pc-scope']) {
  $(selector).oninput = () => { page = 0
    render() }
}
$('#pc-prev').onclick = () => { page -= 1
  render() }
$('#pc-next').onclick = () => { page += 1
  render() }
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
