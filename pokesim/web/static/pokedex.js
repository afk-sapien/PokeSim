const $ = (selector) => document.querySelector(selector)
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]))
const num = (dex) => String(dex).padStart(3, '0')
const TYPE_CLASS = new Set(['normal', 'fighting', 'flying', 'poison', 'ground', 'rock', 'bug', 'ghost', 'fire', 'water', 'grass', 'electric', 'psychic', 'ice', 'dragon'])
const typeClass = (name) => TYPE_CLASS.has(String(name).toLowerCase()) ? String(name).toLowerCase() : 'normal'
const typeTags = (types) => types.map((type) => `<span class="tag type-${typeClass(type)}">${esc(type)}</span>`).join('')
// Base stats count in cells of ten, so the tallest Gen 1 stat (190) fills the meter.
const MAX_STAT = 190
const STAT_CELLS = 19
const BANK_CELLS = 20
const RECORD_LABELS = {caught: 'In Pokédex', seen: 'Seen', unseen: 'Not encountered'}
const RECORD_LAMPS = {caught: 'ok', seen: 'signal', unseen: ''}
const cells = (on, total) => Array.from({length: total}, (_, i) => i < on ? '<i class="on"></i>' : '<i></i>').join('')
const outOf = (n) => `${n}<span class="unit">/151</span>`
function paintBank(selector, value) {
  $(selector).innerHTML = cells(value > 0 ? Math.max(1, Math.round(value / 151 * BANK_CELLS)) : 0, BANK_CELLS)
}
const PLAN_LABELS = {available: 'Possible in this run', caught: 'Already registered', external: 'Needs another game', unavailable: 'Out of reach for now'}

let entries = []
let byDex = new Map()
let owned = new Set()
let seen = new Set()
let plan = new Map()
let held = new Map()
let catches = null
let maxed = new Set()
let perfectSpecies = new Set()
let highQualitySpecies = new Set()
let hunting = null
let openDex = null
let gridSignature = ''
let detailSignature = ''
let detailTrigger = null

const count = value => Number.isSafeInteger(value) && value >= 0 ? value : 0
const catchesAvailable = () => Boolean(catches) && catches.available !== false
const caughtCount = dex => catchesAvailable() ? count(catches.counts?.[dex]) : null
function trackingNote() {
  if (catches?.available === false) return 'Catch tracking is unavailable for this game.'
  if (catches?.complete_history) return 'Catches tracked from the start of this adventure.'
  if (Number.isFinite(catches?.started_at) && catches.started_at > 0) {
    return `Catches tracked since ${new Date(catches.started_at * 1000).toLocaleDateString(undefined, {year: 'numeric', month: 'short', day: 'numeric'})}`
  }
  return 'Catch tracking has not started yet.'
}

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
  return `<span class="milestone-badges">${maxed.has(dex) ? '<span class="tag tag--warn mastery-badge"><span aria-hidden="true">⚑</span> Lv. 100</span>' : ''}${perfectSpecies.has(dex) ? '<span class="tag tag--signal perfect-badge"><span aria-hidden="true">★★★★</span> Perfect DV</span>' : highQualitySpecies.has(dex) ? '<span class="tag tag--ok dv-badge dv-stars-3" aria-label="3-star or better DVs found"><span aria-hidden="true">★★★</span> DV found</span>' : ''}</span>`
}

function renderGrid() {
  if (!entries.length) return
  const rows = sorted(entries.filter(matches))
  $('#result-count').textContent = `${rows.length} Pokémon`
  const signature = JSON.stringify([rows, [...owned], [...seen], [...held], [...plan], hunting, catches, [...maxed], [...perfectSpecies], [...highQualitySpecies]])
  if (signature === gridSignature) return
  gridSignature = signature
  $('#grid').innerHTML = rows.map((entry) => {
    const state = record(entry.dex)
    const copies = held.get(entry.dex)
    const note = RECORD_LABELS[state]
    const caught = caughtCount(entry.dex)
    const counts = `${caught === null ? 'Catch count unavailable' : `Caught ${caught}`} · Have ${copies?.length || 0}`
    return `<button class="dex-card ${state}${perfectSpecies.has(entry.dex) ? ' perfect-entry' : ''}" data-dex="${entry.dex}" aria-label="${esc(entry.name)}, number ${num(entry.dex)}, ${RECORD_LABELS[state]}${maxed.has(entry.dex) ? ', level 100 reached' : ''}${perfectSpecies.has(entry.dex) ? ', perfect DV species found' : highQualitySpecies.has(entry.dex) ? ', 3-star or better DV species found' : ''}, ${counts}" aria-describedby="catch-tracking-note">
      <span class="dex-top"><span class="dex-num">${num(entry.dex)}</span>${entry.dex === hunting ? '<span class="tag tag--crit hunt-flag" title="The current expedition">Hunting</span>' : ''}<span class="card-note"><i class="lamp"${RECORD_LAMPS[state] ? ` data-on="${RECORD_LAMPS[state]}"` : ''} aria-hidden="true"></i>${esc(note)}</span></span>
      <span class="plate plate--card"><img loading="lazy" src="${PokeSim.base}/sprites/${entry.dex}.png" alt="" width="56" height="56"></span>
      <span class="dex-body"><strong class="dex-name">${esc(entry.name)}</strong><span class="card-types">${typeTags(entry.types)}</span>${milestoneBadges(entry.dex)}</span>
      <span class="card-counts">${counts}</span>
    </button>`
  }).join('') || '<p class="dex-empty">Nobody matches that search. Try another name, type, or filter.</p>'
  fitSprites($('#grid'))
}

function statRow(label, value) {
  const on = Math.max(1, Math.min(STAT_CELLS, Math.round(value / MAX_STAT * STAT_CELLS)))
  return `<div class="stat-row"><span class="micro">${esc(label)}</span><span class="meter" data-level="signal" aria-hidden="true">${cells(on, STAT_CELLS)}</span><b>${value}</b></div>`
}

function chip(step, direction) {
  return `<button class="evo-chip" data-dex="${step.dex}">
    <span class="plate plate--chip"><img loading="lazy" src="${PokeSim.base}/sprites/${step.dex}.png" alt="" width="56" height="56"></span>
    <span><span class="micro">${direction}</span><strong>${esc(step.name)}</strong><small>${esc(step.label)}</small></span></button>`
}

function placeLine(place) {
  const extra = [place.level_range, place.rod ? `${place.rod}` : null,
                 place.gives ? `Trade a ${place.gives}` : null, place.item ? `From the ${place.item}` : null]
  return `<li><span class="tag place-method ${esc(place.method)}">${esc(place.method_label)}</span>
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
  const signature = JSON.stringify([entry, state, project, copies, hunting, catches, maxed.has(dex), perfectSpecies.has(dex), highQualitySpecies.has(dex)])
  if (refresh && signature === detailSignature) return
  detailSignature = signature
  const partyCount = copies.filter(copy => copy.where.startsWith('Party slot ')).length
  const pcCount = copies.filter(copy => copy.where.startsWith('Box ')).length
  const moves = entry.moves.map((move) => `<tr><td>${move.level ? `Lv. ${move.level}` : 'Start'}</td><td>${esc(move.name)}</td>
    <td><span class="tag type-${typeClass(move.type)}">${esc(move.type)}</span></td><td>${move.power || 'N/A'}</td><td>${move.accuracy ?? 'N/A'}%</td><td>${move.pp ?? 'N/A'}</td></tr>`).join('')
  $('#detail-body').innerHTML = `
    <header class="detail-head">
      <span class="plate plate--hero"><img src="${PokeSim.base}/sprites/${dex}.png" alt="${esc(entry.name)}" width="56" height="56"></span>
      <div class="detail-id"><span class="micro eyebrow">No. ${num(dex)}${entry.dex === hunting ? ' · Current expedition' : ''}</span>
        <h2 id="detail-name">${esc(entry.name)}</h2>
        <div class="detail-types">${typeTags(entry.types)}</div>
        <span class="record-pill ${state}"><i class="lamp"${RECORD_LAMPS[state] ? ` data-on="${RECORD_LAMPS[state]}"` : ''} aria-hidden="true"></i>${RECORD_LABELS[state]}</span>${milestoneBadges(entry.dex)}</div>
    </header>
    <section class="detail-section" aria-label="Collection counts">
      <dl class="collection-counts"><div><dt>Caught</dt><dd${catchesAvailable() ? '' : ' class="count-unavailable"'}>${caughtCount(dex) ?? 'Unavailable'}</dd></div><div><dt>Have</dt><dd>${copies.length}</dd></div></dl>
      <p class="detail-meta">Party ${partyCount} · PC ${pcCount}</p>
      <p class="detail-meta">${esc(trackingNote())}</p>
      <div class="link-row"><a class="key" href="${PokeSim.base}/pc?scope=all&q=%23${num(dex)}&sort=power&order=desc">View in PC ↗</a></div>
    </section>
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
      <a class="key" href="${esc(entry.links.bulbapedia)}" target="_blank" rel="noreferrer">Bulbapedia ↗</a>
      <a class="key" href="${esc(entry.links.serebii)}" target="_blank" rel="noreferrer">Serebii ↗</a>
      <a class="key" href="${esc(entry.links.wikipedia)}" target="_blank" rel="noreferrer">Wikipedia ↗</a>
    </div></section>`
  fitSprites($('#detail-body'))
  $('#detail').hidden = false
  $('#backdrop').hidden = false
  $('#detail').scrollTop = refresh ? previousScroll : 0
  if (!refresh) $('#close-detail').focus()
  history.replaceState(null, '', `#${num(dex)}`)
}

// Portrait scaling is shared; see panel.js.
const fitSprites = (root) => globalThis.Panel?.fitSprites?.(root)

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
  const response = await PokeSim.fetch('/api/pokedex')
  if (!response.ok) throw new Error('The Pokédex could not be opened.')
  const data = await response.json()
  entries = data.entries
  byDex = new Map(entries.map((entry) => [entry.dex, entry]))
  const types = [...new Set(entries.flatMap((entry) => entry.types))].sort()
  $('#type-filter').innerHTML = '<option value="all">Every type</option>' + types.map((type) => `<option value="${esc(type)}">${esc(type)}</option>`).join('')
}

async function refreshStatus() {
  try {
    const response = await PokeSim.fetch('/api/pokedex/status', {cache: 'no-store'})
    if (!response.ok) throw new Error('Unavailable')
    const status = await response.json()
    catches = status.catches || null
    const goals = status.milestones || {}
    maxed = new Set(goals.level_100 || [])
    perfectSpecies = new Set(goals.perfect_species || [])
    highQualitySpecies = new Set([...(goals.high_quality_species || []), ...perfectSpecies])
    $('#sum-maxed').innerHTML = outOf(maxed.size)
    $('#maxed-meter').value = maxed.size
    paintBank('#maxed-cells', maxed.size)
    $('#sum-perfect').textContent = `${goals.perfect_found || 0}${goals.perfect_found ? '+' : ''}`
    $('#perfect-note').textContent = `${perfectSpecies.size} species discovered · ${goals.perfect_held || 0} perfect partners with you. Confirmed minimum.`
    owned = new Set(status.owned || [])
    seen = new Set(status.seen || [])
    plan = new Map((status.plan || []).map((row) => [row.dex, row]))
    hunting = (status.plan || []).find((row) => row.species === status.hunting)?.dex ?? null
    $('#connection').classList.remove('is-offline')
    $('#status').textContent = status.started ? 'Adventure in progress' : 'Waiting for the adventure'
    $('#sum-owned').innerHTML = outOf(owned.size)
    $('#sum-seen').innerHTML = outOf(seen.size)
    $('#sum-caught').textContent = catchesAvailable() ? count(catches.total) : 'Unavailable'
    $('#sum-caught').classList[catchesAvailable() ? 'remove' : 'add']('is-word')
    $('#sum-caught-label').textContent = catches?.complete_history ? 'Total caught' : 'Catches tracked'
    $('#catch-tracking-note').textContent = trackingNote()
    $('#owned-meter').value = owned.size
    $('#seen-meter').value = seen.size
    paintBank('#owned-cells', owned.size)
    paintBank('#seen-cells', seen.size)
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
