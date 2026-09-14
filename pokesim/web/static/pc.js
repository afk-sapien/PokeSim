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

function render() {
  const counts = storage?.box_counts || Array(12).fill(0)
  const pokemon = storage?.pokemon || []
  const query = $('#pc-search').value.trim().toLowerCase().replace(/^#/, '')
  const all = $('#pc-scope').value === 'all'
  const rows = pokemon.filter((mon) => (all || mon.box === selectedBox) && (!query ||
    `${mon.nick} ${mon.name}`.toLowerCase().includes(query) || String(mon.dex).padStart(3, '0').includes(query)))
  const pages = Math.max(1, Math.ceil(rows.length / 20))
  page = Math.min(page, pages - 1)
  residents = rows.slice(page * 20, (page + 1) * 20)
  const url = new URLSearchParams({box: String(selectedBox)})
  if (query) url.set('q', $('#pc-search').value)
  if (all) url.set('scope', 'all')
  history.replaceState(null, '', `/pc?${url}`)
  $('#pc-total').textContent = `${counts.reduce((sum, count) => sum + count, 0)} / ${counts.length * 20}`
  $('#pc-active').textContent = `Box ${storage?.active_box || 1}`
  $('#pc-heading').textContent = all ? 'Across all boxes' : `Box ${selectedBox}`
  $('#pc-note').textContent = !all && selectedBox === storage?.active_box ? 'TAKING NEW ARRIVALS' : 'STORED PARTNERS'
  $('#pc-count').textContent = `${rows.length} Pokémon`
  $('#pc-page').textContent = `Page ${page + 1} of ${pages}`
  $('#pc-prev').disabled = page === 0
  $('#pc-next').disabled = page >= pages - 1
  const key = JSON.stringify([storage, selectedBox, query, all, page])
  if (key === signature) return
  signature = key
  $('#mobile-box').innerHTML = counts.map((count, index) => `<option value="${index + 1}">Box ${index + 1} · ${count} / 20${index + 1 === storage?.active_box ? ' · Receiving catches' : ''}</option>`).join('')
  $('#mobile-box').value = String(selectedBox)
  const focusedBox = document.activeElement?.dataset.box
  $('#box-picker').innerHTML = counts.map((count, index) => `<button data-box="${index + 1}" aria-pressed="${index + 1 === selectedBox}" class="${index + 1 === selectedBox ? 'selected' : ''}"><span>Box ${index + 1}${index + 1 === storage?.active_box ? ' ●' : ''}</span><small>${count} / 20</small></button>`).join('')
  if (focusedBox) $(`[data-box="${focusedBox}"]`)?.focus()
  const focusedMon = document.activeElement?.dataset.mon
  $('#pc-grid').innerHTML = residents.map((mon, index) => `<button class="pc-mon" data-mon="${index}" aria-label="${esc(mon.nick || mon.name)}, level ${mon.level}, box ${mon.box}"><span class="eyebrow">BOX ${mon.box} · SLOT ${mon.position || index + 1}</span><img loading="lazy" src="/sprites/${Number(mon.dex) || 0}.png" alt="" width="72" height="72"><strong>${esc(mon.nick || mon.name)}</strong><small>${esc(mon.name)} · Lv. ${mon.level}</small></button>`).join('') || `<p class="dex-empty">${query ? 'No partners match this search.' : all ? 'Your stored Pokémon will appear here.' : 'This box has room for new partners.'}</p>`
  if (focusedMon) $(`[data-mon="${focusedMon}"]`)?.focus()
}

function detail(mon) {
  const labels = ['HP', 'Attack', 'Defense', 'Speed', 'Special']
  const known = mon.dvs?.length === 5 && mon.stat_exp?.length === 5
  $('#pc-detail-body').innerHTML = `<div class="pc-detail-head"><img src="/sprites/${Number(mon.dex) || 0}.png" alt="" width="96" height="96"><p class="eyebrow">BOX ${mon.box} · SLOT ${mon.position || '?'}</p><h2 id="pc-detail-name">${esc(mon.nick || mon.name)}</h2><p>${esc(mon.name)} · Level ${mon.level}</p></div>
    ${known ? `<table class="individual-stats"><caption>Natural potential and training</caption><thead><tr><th>Stat</th><th>DV / 15</th><th>Stat experience</th></tr></thead><tbody>${labels.map((label, i) => `<tr><th scope="row">${label}</th><td>${mon.dvs[i]}</td><td>${mon.stat_exp[i].toLocaleString()}</td></tr>`).join('')}</tbody></table><p class="detail-meta">DVs are fixed. Stat experience grows through training, up to 65,535 in each stat.</p>` : '<p class="detail-meta">Individual stats are unavailable in this snapshot.</p>'}
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
