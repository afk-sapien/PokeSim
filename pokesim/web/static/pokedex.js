const $ = (selector) => document.querySelector(selector)
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]))
const num = (dex) => String(dex).padStart(3, '0')
const TYPE_CLASS = new Set(['normal', 'fighting', 'flying', 'poison', 'ground', 'rock', 'bug', 'ghost', 'fire', 'water', 'grass', 'electric', 'psychic', 'ice', 'dragon'])
const typeClass = (name) => TYPE_CLASS.has(String(name).toLowerCase()) ? String(name).toLowerCase() : 'normal'
const typeTags = (types) => types.map((type) => `<span class="type-tag ${typeClass(type)}">${esc(type)}</span>`).join('')
const MAX_STAT = 190
const RECORD_LABELS = {caught: 'Registered', seen: 'Seen', unseen: 'Not met yet'}
const PLAN_LABELS = {available: 'Possible in this run', caught: 'Already registered', external: 'Needs another game', unavailable: 'Out of reach for now'}

let entries = []
let byDex = new Map()
let owned = new Set()
let seen = new Set()
let plan = new Map()
let held = new Map()
let maxed = new Set()
let perfectSpecies = new Set()
let highQualitySpecies = new Set()
let hunting = null
let openDex = null
let gridSignature = ''
let detailSignature = ''
let detailTrigger = null

function record(dex) {
  return owned.has(dex) ? 'caught' : seen.has(dex) ? 'seen' : 'unseen'
}

function matches(entry) {
  const query = $('#search').value.trim().toLowerCase()
  const type = $('#type-filter').value
  const filter = $('#status-filter').value
  if (query && !entry.name.toLowerCase().includes(query) && !num(entry.dex).includes(query.replace(/^#/, ''))) return false
  if (type !== 'all' && !entry.types.includes(type)) return false
  if (filter === 'available') return plan.get(entry.dex)?.status === 'available'
  if (filter === 'maxed') return maxed.has(entry.dex)
  if (filter === 'unmastered') return !maxed.has(entry.dex)
  if (filter === 'quality') return highQualitySpecies.has(entry.dex)
  if (filter === 'three-held') return (held.get(entry.dex) || []).some(copy => copy.stars === 3)
  if (filter === 'perfect') return perfectSpecies.has(entry.dex)
  if (filter === 'held') return held.has(entry.dex)
  if (filter !== 'all') return record(entry.dex) === filter
  return true
}

function sorted(rows) {
  const order = $('#sort').value
  const copy = [...rows]
  if (order === 'name') copy.sort((a, b) => a.name.localeCompare(b.name))
  if (order === 'total') copy.sort((a, b) => b.total - a.total)
  if (order === 'catch') copy.sort((a, b) => b.catch_rate - a.catch_rate || a.dex - b.dex)
  return copy
}

function milestoneBadges(dex) {
  return `<span class="milestone-badges">${maxed.has(dex) ? '<span class="mastery-badge"><span aria-hidden="true">★</span> Lv. 100</span>' : ''}${perfectSpecies.has(dex) ? '<span class="perfect-badge"><span aria-hidden="true">★★★★</span> Perfect DV</span>' : highQualitySpecies.has(dex) ? '<span class="dv-badge dv-stars-3" aria-label="3-star or better DVs found"><span aria-hidden="true">★★★</span> DV found</span>' : ''}</span>`
}

function renderGrid() {
  if (!entries.length) return
  const rows = sorted(entries.filter(matches))
  $('#result-count').textContent = `${rows.length} Pokémon`
  const signature = JSON.stringify([rows, [...owned], [...seen], [...held], [...plan], hunting, [...maxed], [...perfectSpecies], [...highQualitySpecies]])
  if (signature === gridSignature) return
  gridSignature = signature
  $('#grid').innerHTML = rows.map((entry) => {
    const state = record(entry.dex)
    const copies = held.get(entry.dex)
    const project = plan.get(entry.dex)
    const note = state === 'caught' ? (copies ? `${copies.length} with you` : 'In the Pokédex')
      : project?.status === 'available' ? 'Possible in this run' : PLAN_LABELS[project?.status] || 'Somewhere out there'
    return `<button class="dex-card ${state}${perfectSpecies.has(entry.dex) ? ' perfect-entry' : ''}" data-dex="${entry.dex}" aria-label="${esc(entry.name)}, number ${num(entry.dex)}, ${RECORD_LABELS[state]}${maxed.has(entry.dex) ? ', level 100 star earned' : ''}${perfectSpecies.has(entry.dex) ? ', perfect DV species found' : highQualitySpecies.has(entry.dex) ? ', 3-star or better DV species found' : ''}">
      <span class="dex-num">#${num(entry.dex)}</span>
      ${entry.dex === hunting ? '<span class="hunt-flag" title="The current expedition">Hunting</span>' : ''}
      <img loading="lazy" src="/sprites/${entry.dex}.png" alt="" width="72" height="72">
      <strong>${esc(entry.name)}</strong>${milestoneBadges(entry.dex)}
      <span class="card-types">${typeTags(entry.types)}</span>
      <span class="card-note">${esc(note)}</span>
    </button>`
  }).join('') || '<p class="dex-empty">Nobody matches that search. Try another name, type, or filter.</p>'
}

function statRow(label, value) {
  const width = Math.min(100, Math.round(value / MAX_STAT * 100))
  return `<div class="stat-row"><span>${esc(label)}</span><span class="stat-bar"><i style="width:${width}%"></i></span><b>${value}</b></div>`
}

function chip(step, direction) {
  return `<button class="evo-chip" data-dex="${step.dex}">
    <img loading="lazy" src="/sprites/${step.dex}.png" alt="" width="44" height="44">
    <span><strong>${esc(step.name)}</strong><small>${direction} · ${esc(step.label)}</small></span></button>`
}

function placeLine(place) {
  const extra = [place.level_range, place.rod ? `${place.rod}` : null,
                 place.gives ? `Trade a ${place.gives}` : null, place.item ? `From the ${place.item}` : null]
  return `<li><span class="place-method ${esc(place.method)}">${esc(place.method_label)}</span>
    <strong>${esc(place.map_name)}</strong><small>${extra.filter(Boolean).map(esc).join(' · ')}</small></li>`
}

function renderDetail(dex, refresh = false) {
  const entry = byDex.get(dex)
  if (!entry) return
  if (openDex === null) detailTrigger = document.activeElement
  const previousScroll = $('#detail').scrollTop
  openDex = dex
  const state = record(dex)
  const project = plan.get(dex)
  const copies = held.get(dex) || []
  const signature = JSON.stringify([entry, state, project, copies, hunting, maxed.has(dex), perfectSpecies.has(dex), highQualitySpecies.has(dex)])
  if (refresh && signature === detailSignature) return
  detailSignature = signature
  const moves = entry.moves.map((move) => `<tr><td>${move.level ? `Lv. ${move.level}` : 'Start'}</td><td>${esc(move.name)}</td>
    <td><span class="type-tag ${typeClass(move.type)}">${esc(move.type)}</span></td><td>${move.power || 'N/A'}</td><td>${move.accuracy ?? 'N/A'}%</td><td>${move.pp ?? 'N/A'}</td></tr>`).join('')
  $('#detail-body').innerHTML = `
    <header class="detail-head ${typeClass(entry.types[0])}">
      <img src="/sprites/${dex}.png" alt="${esc(entry.name)}" width="112" height="112">
      <div><span class="eyebrow">NO. ${num(dex)}${entry.dex === hunting ? ' · CURRENT EXPEDITION' : ''}</span>
        <h2 id="detail-name">${esc(entry.name)}</h2>${milestoneBadges(entry.dex)}
        <div class="detail-types">${typeTags(entry.types)}</div>
        <span class="record-pill ${state}">${RECORD_LABELS[state]}</span></div>
    </header>
    ${project && state !== 'caught' ? `<p class="plan-note"><b>${esc(PLAN_LABELS[project.status] || 'Status')}</b> ${esc(project.reason || '')}</p>` : ''}
    ${copies.length ? `<section class="detail-section"><h3>With you right now</h3><ul class="copy-list">${copies.map((copy) =>
      `<li><strong>${esc(copy.nick || entry.name)}</strong><span>Lv. ${copy.level} · ${esc(copy.where)} · ${copy.stars ? `${copy.stars}★ DVs` : 'DVs unknown'}</span></li>`).join('')}</ul></section>` : ''}
    <section class="detail-section"><h3>Base stats</h3>
      ${Object.entries(entry.stats).map(([label, value]) => statRow(label, value)).join('')}
      <p class="detail-meta">Total ${entry.total} · Generation I shares one Special stat</p>
      <p class="detail-meta">Catch rate ${entry.catch_rate} of 255 · ${esc(entry.growth)} level curve${entry.hms.length ? ` · Field moves: ${entry.hms.map(esc).join(', ')}` : ''}</p>
    </section>
    ${entry.evolves_from.length || entry.evolves_to.length ? `<section class="detail-section"><h3>Family</h3><div class="evo-row">
      ${entry.evolves_from.map((step) => chip(step, 'Evolves from')).join('')}
      ${entry.evolves_to.map((step) => chip(step, 'Evolves into')).join('')}</div></section>` : ''}
    <section class="detail-section"><h3>Where to look in Kanto</h3>
      ${entry.locations.length ? `<ul class="place-list">${entry.locations.map(placeLine).join('')}</ul>`
        : '<p class="detail-meta">No encounters in this version. Evolution, a trade, or another cartridge is the way in.</p>'}
    </section>
    <section class="detail-section"><h3>Moves it learns on its own</h3>
      <div class="move-scroll"><table class="move-table"><thead><tr><th>When</th><th>Move</th><th>Type</th><th>Power</th><th>Acc.</th><th>PP</th></tr></thead><tbody>${moves}</tbody></table></div>
    </section>
    <section class="detail-section"><h3>Read more</h3><div class="link-row">
      <a href="${esc(entry.links.bulbapedia)}" target="_blank" rel="noreferrer">Bulbapedia ↗</a>
      <a href="${esc(entry.links.serebii)}" target="_blank" rel="noreferrer">Serebii Red &amp; Blue dex ↗</a>
      <a href="${esc(entry.links.wikipedia)}" target="_blank" rel="noreferrer">Wikipedia ↗</a>
    </div></section>`
  $('#detail').hidden = false
  $('#backdrop').hidden = false
  $('#detail').scrollTop = refresh ? previousScroll : 0
  if (!refresh) $('#close-detail').focus()
  history.replaceState(null, '', `#${num(dex)}`)
}

function closeDetail() {
  openDex = null
  detailTrigger?.focus()
  $('#detail').hidden = true
  $('#backdrop').hidden = true
  history.replaceState(null, '', location.pathname)
}

function step(offset) {
  if (openDex === null) return
  const next = Math.min(151, Math.max(1, openDex + offset))
  renderDetail(next)
}

function renderHolders(status) {
  const party = status.party || []
  const storage = status.storage
  const stored = storage?.pokemon || []
  held = new Map()
  const add = (dex, copy) => {
    if (!dex) return
    held.set(dex, [...(held.get(dex) || []), copy])
  }
  party.forEach((mon) => add(mon.dex, {nick: mon.nick, level: mon.level, stars: mon.dv_stars, where: `Party slot ${mon.slot}`}))
  stored.forEach((mon) => add(mon.dex, {nick: mon.nick, level: mon.level, stars: mon.dv_stars, where: `Box ${mon.box}`}))


}

async function loadReference() {
  const response = await fetch('/api/pokedex')
  if (!response.ok) throw new Error('The Pokédex could not be opened.')
  const data = await response.json()
  entries = data.entries
  byDex = new Map(entries.map((entry) => [entry.dex, entry]))
  const types = [...new Set(entries.flatMap((entry) => entry.types))].sort()
  $('#type-filter').innerHTML = '<option value="all">Every type</option>' + types.map((type) => `<option value="${esc(type)}">${esc(type)}</option>`).join('')
}

async function refreshStatus() {
  try {
    const response = await fetch('/api/pokedex/status', {cache: 'no-store'})
    if (!response.ok) throw new Error('Unavailable')
    const status = await response.json()
    const goals = status.milestones || {}
    maxed = new Set(goals.level_100 || [])
    perfectSpecies = new Set(goals.perfect_species || [])
    highQualitySpecies = new Set([...(goals.high_quality_species || []), ...perfectSpecies])
    $('#sum-three-star').textContent = String(goals.three_star_held || 0)
    $('#sum-quality').innerHTML = `${highQualitySpecies.size} <small>/ 151</small>`
    $('#sum-maxed').innerHTML = `${maxed.size} <small>/ 151</small>`
    $('#maxed-meter').value = maxed.size
    $('#sum-perfect').textContent = `${goals.perfect_found || 0}${goals.perfect_found ? '+' : ''}`
    $('#perfect-note').textContent = `${perfectSpecies.size} species discovered · ${goals.perfect_held || 0} perfect partners with you. Confirmed minimum.`
    owned = new Set(status.owned || [])
    seen = new Set(status.seen || [])
    plan = new Map((status.plan || []).map((row) => [row.dex, row]))
    hunting = (status.plan || []).find((row) => row.species === status.hunting)?.dex ?? null
    $('#connection').classList.remove('is-offline')
    $('#status').textContent = status.started ? 'Adventure in progress' : 'Waiting for the adventure'
    if (status.version) $('#edition').textContent = `${status.version.toUpperCase()} VERSION`
    $('#sum-owned').innerHTML = `${owned.size} <small>/ 151</small>`
    $('#sum-seen').innerHTML = `${seen.size} <small>/ 151</small>`
    $('#owned-meter').value = owned.size
    $('#seen-meter').value = seen.size
    renderHolders(status)
    renderGrid()
    if (openDex !== null) renderDetail(openDex, true)
  } catch (_) {
    $('#connection').classList.add('is-offline')
    $('#status').textContent = 'Reconnecting…'
  }
}

document.addEventListener('click', (event) => {
  const card = event.target.closest('[data-dex]')
  if (card && card.dataset.dex) renderDetail(Number(card.dataset.dex))
})
$('#backdrop').onclick = closeDetail
$('#close-detail').onclick = closeDetail
$('#prev-mon').onclick = () => step(-1)
$('#next-mon').onclick = () => step(1)
for (const control of ['#search', '#type-filter', '#status-filter', '#sort']) {
  $(control).oninput = renderGrid
}
window.addEventListener('keydown', (event) => {
  if (openDex === null) return
  if (event.key === 'Tab') {
    const focusable = [...$('#detail').querySelectorAll('button, a[href]')]
    const first = focusable[0]
    const last = focusable.at(-1)
    if (event.shiftKey && document.activeElement === first) { event.preventDefault()
      last.focus() }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault()
      first.focus() }
  }
  if (event.key === 'Escape') closeDetail()
  if (event.key === 'ArrowLeft') step(-1)
  if (event.key === 'ArrowRight') step(1)
})

loadReference().then(() => {
  renderGrid()
  refreshStatus()
  const requested = Number(location.hash.replace('#', ''))
  if (requested >= 1 && requested <= 151) renderDetail(requested)
}).catch(() => {
  $('#grid').innerHTML = '<p class="dex-empty">The Pokédex data could not be loaded. Refresh to try again.</p>'
})
refreshStatus()
setInterval(() => { if (!document.hidden) refreshStatus() }, 12000)
