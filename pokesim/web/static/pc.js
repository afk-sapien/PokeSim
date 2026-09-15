const $ = (selector) => document.querySelector(selector)
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&': '&amp', '<': '&lt', '>': '&gt', '"': '&quot', "'": '&#39'}[char] + String.fromCharCode(59)))
const params = new URLSearchParams(location.search)
let selectedBox = Math.min(12, Math.max(1, Number(params.get('box')) || 1))
let followActive = !params.has('box')
let storage = null
let page = 0
let busy = false
let signature = ''
let residents = []
$('#pc-search').value = params.get('q') || ''
$('#pc-scope').value = params.get('scope') === 'all' ? 'all' : 'box'
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

function render() {
  const counts = storage?.box_counts || Array(12).fill(0)
  const pokemon = storage?.pokemon || []
  const query = $('#pc-search').value.trim().toLowerCase().replace(/^#/, '')
  const all = $('#pc-scope').value === 'all'
  const sort = $('#pc-sort').value
  const order = $('#pc-order').value
  const alphabetical = sort === 'name' || sort === 'nick'
  $('#pc-order').options[0].textContent = alphabetical ? 'A to Z' : sort === 'box' ? 'First to last' : 'Lowest first'
  $('#pc-order').options[1].textContent = alphabetical ? 'Z to A' : sort === 'box' ? 'Last to first' : 'Highest first'
  const rows = pokemon.filter((mon) => (all || mon.box === selectedBox) && (!query ||
    `${mon.nick} ${mon.name}`.toLowerCase().includes(query) || String(mon.dex).padStart(3, '0').includes(query)))
  rows.sort((a, b) => comparePartners(a, b, sort, order))
  const pages = Math.max(1, Math.ceil(rows.length / 20))
  page = Math.min(page, pages - 1)
  residents = rows.slice(page * 20, (page + 1) * 20)
  const url = new URLSearchParams({box: String(selectedBox)})
  if (query) url.set('q', $('#pc-search').value)
  if (all) url.set('scope', 'all')
  url.set('sort', sort)
  url.set('order', order)
  history.replaceState(null, '', `/pc?${url}`)
  $('#pc-total').textContent = `${counts.reduce((sum, count) => sum + count, 0)} / ${counts.length * 20}`
  $('#pc-active').textContent = `Box ${storage?.active_box || 1}`
  $('#pc-heading').textContent = all ? 'Across all boxes' : `Box ${selectedBox}`
  $('#pc-note').textContent = !all && selectedBox === storage?.active_box ? 'TAKING NEW ARRIVALS' : 'STORED PARTNERS'
  $('#pc-count').textContent = `${rows.length} Pokémon`
  $('#pc-page').textContent = `Page ${page + 1} of ${pages}`
  $('#pc-prev').disabled = page === 0
  $('#pc-next').disabled = page >= pages - 1
  const key = JSON.stringify([storage, selectedBox, query, all, sort, order, page])
  if (key === signature) return
  signature = key
  $('#mobile-box').innerHTML = counts.map((count, index) => `<option value="${index + 1}">Box ${index + 1} · ${count} / 20${index + 1 === storage?.active_box ? ' · Receiving catches' : ''}</option>`).join('')
  $('#mobile-box').value = String(selectedBox)
  const focusedBox = document.activeElement?.dataset.box
  $('#box-picker').innerHTML = counts.map((count, index) => `<button data-box="${index + 1}" aria-pressed="${index + 1 === selectedBox}" class="${index + 1 === selectedBox ? 'selected' : ''}"><span>Box ${index + 1}${index + 1 === storage?.active_box ? ' ●' : ''}</span><small>${count} / 20</small></button>`).join('')
  if (focusedBox) $(`[data-box="${focusedBox}"]`)?.focus()
  const focusedMon = document.activeElement?.dataset.mon
  $('#pc-grid').innerHTML = residents.map((mon, index) => `<button class="pc-mon" data-mon="${index}" aria-label="${esc(mon.nick || mon.name)}, level ${mon.level}, box ${mon.box}"><span class="eyebrow">BOX ${mon.box} · SLOT ${mon.position || index + 1}</span><img loading="lazy" src="/sprites/${Number(mon.dex) || 0}.png" alt="" width="72" height="72"><strong>${esc(mon.nick || mon.name)}</strong><small>${esc(mon.name)} · Lv. ${mon.level}</small><span class="pc-metrics"><span class="pc-power">Power <b>${Number.isFinite(mon.power) ? mon.power.toLocaleString() : 'Unavailable'}</b></span><span>Total DVs <b>${formatTotal(mon, 'dvs')}</b></span><span>Stat exp. <b>${formatTotal(mon, 'stat_exp')}</b></span></span></button>`).join('') || `<p class="dex-empty">${query ? 'No partners match this search.' : all ? 'Your stored Pokémon will appear here.' : 'This box has room for new partners.'}</p>`
  if (focusedMon) $(`[data-mon="${focusedMon}"]`)?.focus()
}

function detail(mon) {
  const labels = ['HP', 'Attack', 'Defense', 'Speed', 'Special']
  const known = mon.dvs?.length === 5 && mon.stat_exp?.length === 5
  $('#pc-detail-body').innerHTML = `<div class="pc-detail-head"><img src="/sprites/${Number(mon.dex) || 0}.png" alt="" width="96" height="96"><p class="eyebrow">BOX ${mon.box} · SLOT ${mon.position || '?'}</p><h2 id="pc-detail-name">${esc(mon.nick || mon.name)}</h2><p>${esc(mon.name)} · Level ${mon.level}</p></div>
    ${known ? `<table class="individual-stats"><caption>Calculated stats, potential, and training</caption><thead><tr><th>Stat</th><th>Value</th><th>DV / 15</th><th>Stat experience</th></tr></thead><tbody>${labels.map((label, i) => `<tr><th scope="row">${label}</th><td>${mon.calculated_stats?.[label] ?? 'Unavailable'}</td><td>${mon.dvs[i]}</td><td>${mon.stat_exp[i].toLocaleString()}</td></tr>`).join('')}</tbody><tfoot><tr><th scope="row">Total</th><td>${Number.isFinite(mon.power) ? mon.power.toLocaleString() : 'Unavailable'}</td><td>${formatTotal(mon, 'dvs')} / 75</td><td>${formatTotal(mon, 'stat_exp')} / 327,675</td></tr></tfoot></table><p class="detail-meta">Total DVs include HP, which is derived from the other four DVs. DVs are fixed. Stat experience grows through training, up to 65,535 in each stat.</p>` : '<p class="detail-meta">Individual stats are unavailable in this snapshot.</p>'}
    <p class="detail-meta">Power = max HP + Attack + Defense + Speed + Special. Values are calculated at this level from species, DVs, and stat experience, as on PC withdrawal. Moves, type matchups, and battle bonuses are not included.</p>
    <p class="detail-meta">${Number(mon.experience || 0).toLocaleString()} total experience</p>
    ${mon.dex ? `<a class="dex-open" href="/pokedex#${String(mon.dex).padStart(3, '0')}">View ${esc(mon.name)} in the Pokédex ↗</a>` : ''}`
  $('#pc-detail').showModal()
}

async function refresh() {
  if (busy) return
  busy = true
  try {
    const response = await fetch('/api/pokedex/status', {cache: 'no-store'})
    if (!response.ok) throw new Error('Unavailable')
    const status = await response.json()
    storage = status.storage
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
  const button = event.target.closest('[data-mon]')
  if (button) detail(residents[Number(button.dataset.mon)])
}
$('#pc-strongest').onclick = () => {
  $('#pc-scope').value = 'all'
  $('#pc-search').value = ''
  $('#pc-sort').value = 'power'
  $('#pc-sort').onchange()
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
setInterval(() => { if (!document.hidden) refresh() }, 5000)
