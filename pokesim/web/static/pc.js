const $ = (selector) => document.querySelector(selector)
const params = new URLSearchParams(location.search)
let selectedBox = params.get('box') === 'party' ? 0 : Math.min(14, Math.max(1, Number(params.get('box')) || 1))
let followActive = !params.has('box')
let storage = null
let party = []
let busy = false
let signature = ''
let residents = []
$('#pc-rating').value = ['1', '2', '3', '4', '3plus', 'unknown', 'shiny'].includes(params.get('rating')) ? params.get('rating') : 'all'
let viewQueries = {box: '', all: ''}
$('#pc-search').value = params.get('q') || ''
$('#pc-scope').value = params.get('scope') === 'all' ? 'all' : 'box'
viewQueries[$('#pc-scope').value] = $('#pc-search').value
const {sortDefaults, compare: comparePartners, card: monCard} = MonGrid
$('#pc-sort').value = Object.hasOwn(sortDefaults, params.get('sort')) ? params.get('sort') : 'battle_power'
$('#pc-order').value = ['asc', 'desc'].includes(params.get('order')) ? params.get('order') : sortDefaults[$('#pc-sort').value]

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
  const query = search.replace(/^#/, '')
  const all = $('#pc-scope').value === 'all'
  const rating = $('#pc-rating').value
  const sort = $('#pc-sort').value
  const order = $('#pc-order').value
  MonGrid.orderLabels($('#pc-order'), sort)
  const rows = pokemon.filter((mon) => MonGrid.matches(mon, search, rating) && (all || mon.box === selectedBox))
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
  const key = JSON.stringify([storage, party, selectedBox, query, all, sort, order, rating])
  if (key === signature) return
  signature = key
  $('#mobile-box').innerHTML = `<option value="0">Party · ${party.length} / 6</option>` + counts.map((count, index) => `<option value="${index + 1}">Box ${index + 1} · ${count} / 20${index + 1 === storage?.active_box ? ' · Receiving catches' : ''}</option>`).join('')
  $('#mobile-box').value = String(selectedBox)
  const focusedBox = document.activeElement?.dataset.box
  $('#box-picker').innerHTML = `<button data-box="0" aria-pressed="${selectedBox === 0}" class="${selectedBox === 0 ? 'selected' : ''}"><span class="bp-name">Party</span><small>${party.length} / 6</small>${fillMeter(party.length, 6)}</button>` + counts.map((count, index) => `<button data-box="${index + 1}" aria-pressed="${index + 1 === selectedBox}" class="${index + 1 === selectedBox ? 'selected' : ''}"><span class="bp-name">Box ${index + 1}${index + 1 === storage?.active_box ? '<i class="lamp" data-on="ok" title="Receiving new catches"></i><span class="vh"> · receiving catches</span>' : ''}</span><small>${count} / 20</small>${fillMeter(count, 20)}</button>`).join('')
  if (focusedBox) $(`[data-box="${focusedBox}"]`)?.focus()
  const focusedMon = document.activeElement?.dataset.mon
  const card = (mon, index) => monCard(mon, index, {all})
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

function detail(mon) {
  $('#pc-detail-body').innerHTML = MonGrid.detail(mon)
  $('#pc-trade-action').innerHTML = tradeLink(mon)
  $('#pc-detail').showModal()
  fitSprites($('#pc-detail-body'))
}

// Everything about trading lives on the Trading page. The detail only links there.
function tradeLink(mon) {
  if (!mon?.trade_key || mon.egg) return ''
  return `<a class="key pc-trade-link" href="${PokeSim.base}/trading?tab=trade&mon=${encodeURIComponent(mon.trade_key)}">Trade…</a>`
}


async function refresh() {
  if (busy) return
  busy = true
  try {
    const response = await PokeSim.fetch('/api/pokedex/status?view=pc', {cache: 'no-store'})
    if (!response.ok) throw new Error('Unavailable')
    const status = await response.json()
    storage = status.storage
    MonGrid.generation('pc', status.generation)
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
setInterval(() => { if (!document.hidden) refresh() }, 5000)
