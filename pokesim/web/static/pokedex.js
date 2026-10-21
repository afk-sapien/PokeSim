const $ = (selector) => document.querySelector(selector)
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]))
const num = (dex) => String(dex).padStart(3, '0')
const typeTags = (types) => PokemonTypes.badges(types)
let maxStat = 190
const STAT_CELLS = 19
const BANK_CELLS = 20
const RECORD_LABELS = {caught: 'In Pokédex', seen: 'Seen', unseen: 'Unseen'}
const RECORD_LAMPS = {caught: 'ok', seen: 'signal', unseen: ''}
const cells = (on, total) => Array.from({length: total}, (_, i) => i < on ? '<i class="on"></i>' : '<i></i>').join('')
const outOf = (n) => `${n}<span class="unit">/${dexTotal}</span>`
function paintBank(selector, value) {
  $(selector).innerHTML = cells(value > 0 ? Math.max(1, Math.round(value / dexTotal * BANK_CELLS)) : 0, BANK_CELLS)
}
const PLAN_LABELS = {available: 'Possible in this run', caught: 'Already registered', external: 'Needs another game', planned: 'Planned for this run', unavailable: 'Out of reach for now'}

let dexTotal = 151
let entries = []
let byDex = new Map()
let owned = new Set()
let seen = new Set()
let plan = new Map()
let held = new Map()
let shinySpecies = new Set()
// Species with a shiny seen in the wild but none acquired or held.
let shinySeen = new Set()
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
  if (filter === 'planned') return plan.get(entry.dex)?.status === 'planned'
  if (filter === 'maxed') return maxed.has(entry.dex)
  if (filter === 'unmastered') return !maxed.has(entry.dex)
  if (filter === 'quality') return highQualitySpecies.has(entry.dex)
  if (filter === 'three-held') return (held.get(entry.dex) || []).some(copy => copy.stars === 3)
  if (filter === 'perfect') return perfectSpecies.has(entry.dex)
  if (filter === 'shiny') return shinySpecies.has(entry.dex)
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
  const seenOnly = !shinySpecies.has(dex) && shinySeen.has(dex)
    ? '<span class="tag shiny-badge shiny-seen-badge" title="A shiny one was seen in the wild, but none has been acquired.">★ Shiny seen</span>' : ''
  return `<span class="milestone-badges">${PokemonTypes.shinyBadge({shiny: shinySpecies.has(dex)})}${seenOnly}${maxed.has(dex) ? '<span class="tag tag--warn mastery-badge"><span aria-hidden="true">⚑</span> Lv. 100</span>' : ''}${perfectSpecies.has(dex) ? '<span class="tag tag--signal perfect-badge"><span aria-hidden="true">★★★★</span> Perfect DV</span>' : highQualitySpecies.has(dex) ? '<span class="tag tag--ok dv-badge dv-stars-3" aria-label="3-star or better DVs found"><span aria-hidden="true">★★★</span> DV found</span>' : ''}</span>`
}

function renderGrid() {
  if (!entries.length) return
  const rows = sorted(entries.filter(matches))
  $('#result-count').textContent = `${rows.length} Pokémon`
  const signature = JSON.stringify([rows, [...owned], [...seen], [...held], [...plan], hunting, catches, [...maxed], [...perfectSpecies], [...highQualitySpecies], [...shinySpecies], [...shinySeen]])
  if (signature === gridSignature) return
  gridSignature = signature
  paintCards($('#grid'), rows.map((entry) => {
    const state = record(entry.dex)
    const copies = held.get(entry.dex)
    const note = RECORD_LABELS[state]
    const caught = caughtCount(entry.dex)
    const counts = `${caught === null ? 'Catch count unavailable' : `Caught ${caught}`}, Have ${copies?.length || 0}`
    return `<button class="dex-card ${state}${perfectSpecies.has(entry.dex) ? ' perfect-entry' : ''}" data-dex="${entry.dex}" aria-label="${esc(entry.name)}, number ${num(entry.dex)}, ${RECORD_LABELS[state]}${shinySpecies.has(entry.dex) ? ', shiny species found' : shinySeen.has(entry.dex) ? ', shiny seen' : ''}${maxed.has(entry.dex) ? ', level 100 reached' : ''}${perfectSpecies.has(entry.dex) ? ', perfect DV species found' : highQualitySpecies.has(entry.dex) ? ', 3-star or better DV species found' : ''}, ${counts}" aria-describedby="catch-tracking-note">
      <span class="dex-top"><span class="dex-num">${num(entry.dex)}</span>${entry.dex === hunting
        // The hunt flag takes the note's place, so the head stays one line.
        ? '<span class="tag tag--crit hunt-flag" title="The current expedition">Hunting</span>'
        : `<span class="card-note"><i class="lamp"${RECORD_LAMPS[state] ? ` data-on="${RECORD_LAMPS[state]}"` : ''} aria-hidden="true"></i>${esc(note)}</span>`}</span>
      <span class="plate plate--card ${PokemonTypes.portraitClass(entry.types)}"><img loading="lazy" src="${PokeSim.sprite(entry.dex)}" alt="" width="56" height="56"></span>
      <span class="dex-body"><strong class="dex-name">${esc(entry.name)}</strong><span class="card-types">${typeTags(entry.types)}</span>${milestoneBadges(entry.dex)}</span>
      <span class="card-counts">${counts}</span>
    </button>`
  }), '<p class="dex-empty">Nobody matches that search. Try another name, type, or filter.</p>')
  fitSprites($('#grid'))
}

// Draw the first cards now and the rest over the next frames, so 251 cards do not hold up
// the first paint. A newer render cancels the rest of an older one.
const FIRST_CARDS = 40
const LATER_CARDS = 80
const nextFrame = globalThis.requestAnimationFrame || (callback => setTimeout(callback, 0))
let painting = 0
function paintCards(grid, cards, empty) {
  const run = ++painting
  grid.innerHTML = cards.slice(0, FIRST_CARDS).join('') || empty
  grid.removeAttribute?.('aria-busy')
  const more = start => {
    if (run !== painting || start >= cards.length) return
    grid.insertAdjacentHTML('beforeend', cards.slice(start, start + LATER_CARDS).join(''))
    fitSprites(grid)
    nextFrame(() => more(start + LATER_CARDS))
  }
  if (cards.length > FIRST_CARDS) nextFrame(() => more(FIRST_CARDS))
}

function statRow(label, value) {
  const on = Math.max(1, Math.min(STAT_CELLS, Math.round(value / maxStat * STAT_CELLS)))
  return `<div class="stat-row"><span class="micro">${esc(label)}</span><span class="meter" data-level="signal" aria-hidden="true">${cells(on, STAT_CELLS)}</span><b>${value}</b></div>`
}

function chip(step, direction) {
  return `<button class="evo-chip" data-dex="${step.dex}">
    <span class="plate plate--chip ${PokemonTypes.portraitClass(byDex.get(step.dex)?.types)}"><img loading="lazy" src="${PokeSim.sprite(step.dex)}" alt="" width="56" height="56"></span>
    <span><span class="micro">${direction}</span><strong>${esc(step.name)}</strong><small>${esc(step.label)}</small></span></button>`
}

function placeLine(place) {
  const extra = [place.level_range, place.rod ? `${place.rod}` : null,
                 place.gives ? `Trade a ${place.gives}` : null, place.item ? `From the ${place.item}` : null]
  return `<li><span class="tag place-method ${esc(place.method)}">${esc(place.method_label)}</span>
    <strong>${esc(place.map_name)}</strong><small>${extra.filter(Boolean).map(esc).join(', ')}</small></li>`
}

function sourceLine(source) {
  const flag = source.planned ? '<span class="tag tag--signal">Planned</span>' : source.external ? '<span class="tag">Outside this cartridge</span>' : ''
  return `<li><span class="tag place-method ${esc(source.kind)}">${esc(source.kind.replace(/_/g, ' '))}</span>
    <strong>${esc(source.label)} ${flag}</strong><small>${esc(source.detail || '')}</small></li>`
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
  const signature = JSON.stringify([entry, state, project, copies, hunting, catches, maxed.has(dex), perfectSpecies.has(dex), highQualitySpecies.has(dex), shinySpecies.has(dex), shinySeen.has(dex)])
  if (refresh && signature === detailSignature) return
  detailSignature = signature
  const partyCount = copies.filter(copy => copy.where.startsWith('Party slot ')).length
  const pcCount = copies.filter(copy => copy.where.startsWith('Box ')).length
  const moves = entry.moves.map((move) => `<tr><td>${move.level ? `Lv. ${move.level}` : 'Start'}</td><td>${esc(move.name)}</td>
    <td>${typeTags([move.type])}</td><td>${move.power || 'N/A'}</td><td>${move.accuracy ?? 'N/A'}%</td><td>${move.pp ?? 'N/A'}</td></tr>`).join('')
  $('#detail-body').innerHTML = `
    <div class="detail-head">
      <span class="plate plate--hero ${PokemonTypes.portraitClass(entry.types)}"><img src="${PokeSim.sprite(dex)}" alt="${esc(entry.name)}" width="56" height="56"></span>
      <div class="detail-id"><span class="micro eyebrow">No. ${num(dex)}${entry.dex === hunting ? ', current expedition' : ''}</span>
        <h2 id="detail-name">${esc(entry.name)}</h2>
        <div class="detail-types">${typeTags(entry.types)}</div>
        <span class="record-pill ${state}"><i class="lamp"${RECORD_LAMPS[state] ? ` data-on="${RECORD_LAMPS[state]}"` : ''} aria-hidden="true"></i>${RECORD_LABELS[state]}</span>${milestoneBadges(entry.dex)}</div>
    </div>
    <section class="detail-section" aria-label="Collection counts">
      <dl class="collection-counts"><div><dt>Caught</dt><dd${catchesAvailable() ? '' : ' class="count-unavailable"'}>${caughtCount(dex) ?? 'Unavailable'}</dd></div><div><dt>Have</dt><dd>${copies.length}</dd></div></dl>
      <p class="detail-meta">Party ${partyCount}, PC ${pcCount}</p>
      <p class="detail-meta">${esc(trackingNote())}</p>
      <div class="link-row"><a class="key" href="${PokeSim.base}/pc?scope=all&q=%23${num(dex)}&sort=power&order=desc">View in PC</a></div>
    </section>
    ${project && state !== 'caught' ? `<p class="plan-note"><b>${esc(PLAN_LABELS[project.status] || 'Status')}</b> ${esc(project.reason || '')}</p>` : ''}
    ${project?.sources?.length ? `<section class="detail-section" aria-label="How the sim gets it"><h3>How the sim gets it</h3>
      <ul class="place-list source-list">${project.sources.map(sourceLine).join('')}</ul></section>` : ''}
    ${copies.length ? `<section class="detail-section"><h3>With you right now</h3><ul class="copy-list">${copies.map((copy, index) => copyRow(copy, index, entry)).join('')}</ul></section>` : ''}
    <section class="detail-section"><h3>Base stats</h3>
      ${Object.entries(entry.stats).map(([label, value]) => statRow(label, value)).join('')}
      <p class="detail-meta">Total ${entry.total}, ${dexTotal === 251 ? 'Separate Special Attack and Special Defense' : 'Generation I shares one Special stat'}</p>
      <p class="detail-meta">Catch rate ${entry.catch_rate} of 255, ${esc(entry.growth)} level curve${entry.hms.length ? `, Field moves: ${entry.hms.map(esc).join(', ')}` : ''}</p>
    </section>
    ${entry.evolves_from.length || entry.evolves_to.length ? `<section class="detail-section"><h3>Family</h3><div class="evo-row">
      ${entry.evolves_from.map((step) => chip(step, 'Evolves from')).join('')}
      ${entry.evolves_to.map((step) => chip(step, 'Evolves into')).join('')}</div></section>` : ''}
    <section class="detail-section"><h3>Where to look</h3>
      ${entry.locations.length ? `<ul class="place-list">${entry.locations.map(placeLine).join('')}</ul>`
        : '<p class="detail-meta">No encounters in this version. Evolution, a trade, or another cartridge is the way in.</p>'}
    </section>
    <section class="detail-section"><h3>Moves it learns on its own</h3>
      <div class="move-scroll" tabindex="0" role="region" aria-label="Moves it learns on its own"><table class="move-table"><thead><tr><th>When</th><th>Move</th><th>Type</th><th>Power</th><th>Acc.</th><th>PP</th></tr></thead><tbody>${moves}</tbody></table></div>
    </section>
    ${Object.keys(entry.links).length ? `<section class="detail-section"><h3>Read more</h3><div class="link-row">
      <a class="key" href="${esc(entry.links.bulbapedia)}" target="_blank" rel="noreferrer">Bulbapedia</a>
      <a class="key" href="${esc(entry.links.serebii)}" target="_blank" rel="noreferrer">Serebii</a>
      <a class="key" href="${esc(entry.links.wikipedia)}" target="_blank" rel="noreferrer">Wikipedia</a>
    </div></section>` : ''}`
  fitSprites($('#detail-body'))
  $('#detail').hidden = false
  $('#backdrop').hidden = false
  $('#detail').scrollTop = refresh ? previousScroll : 0
  if (!refresh) $('#close-detail').focus()
  history.replaceState(null, '', `#${num(dex)}`)
}

// One Pokémon with you, as a key that opens its full record in the PC's popup.
function copyRow(copy, index, entry) {
  const name = copy.nick || entry.name
  const rating = copy.stars ? `${copy.stars}★ DVs` : 'DVs unknown'
  const label = `Open ${name}, level ${copy.level}, ${copy.where}, ${copy.stars ? `${copy.stars}-star DVs` : 'DVs unknown'}${copy.shiny ? ', shiny' : ''}`
  return `<li><button type="button" class="copy-open" data-copy="${index}" aria-label="${esc(label)}"><span class="copy-text"><strong>${esc(name)}</strong>${PokemonTypes.shinyBadge(copy)}<span>Lv. ${copy.level}, ${esc(copy.where)}, ${rating}</span></span><span class="copy-go" aria-hidden="true">›</span></button></li>`
}

// The Pokédex only knows who holds a species. The full record comes from the PC's own data:
// its saved copy paints at once, then the server's answer replaces it. A copy is matched by
// where it sits (party slot, or box and slot) and checked against its species and nickname.
let copyOpen = null
let copyRun = 0
const pcLink = copy => `${PokeSim.base}/pc?box=${copy.box === 0 ? 'party' : copy.box}&slot=${copy.slot}`
function findPartner(full, copy, dex) {
  const list = copy.box === 0 ? full?.party : full?.storage?.pokemon
  const found = (list || []).find(partner => partner?.dex === dex && (partner.nick || '') === (copy.nick || '')
    && (copy.box === 0 ? partner.slot === copy.slot : partner.box === copy.box && partner.position === copy.slot))
  return found ? PokemonTypes.asEgg({...found, box: copy.box, position: copy.slot}) : null
}

function showPartner(partner, copy, note = '') {
  const where = copy.box === 0 ? `Party, slot ${copy.slot}` : `Box ${copy.box}, slot ${copy.slot}`
  $('#mon-detail-body').innerHTML = partner ? MonGrid.detail(partner, {links: false})
    : `<div class="pc-detail-head"><div class="pc-detail-id"><p class="micro">${where}</p><h2 id="pc-detail-name">${esc(copy.nick || byDex.get(openDex)?.name || '')}</h2><p class="pc-detail-line">${esc(note)}</p></div></div>`
  $('#mon-detail-action').innerHTML = `${partner ? MonGrid.detailLinks(partner, {dex: false}) : ''}<a class="key pc-show-link" href="${pcLink(copy)}">Show in PC</a>`
  fitSprites($('#mon-detail-body'))
}

async function openCopy(index) {
  const dex = openDex
  const copy = (held.get(dex) || [])[index]
  if (!copy) return
  const run = ++copyRun
  const dialog = $('#mon-detail')
  const current = () => run === copyRun && dialog.open
  copyOpen = {dex, index}
  showPartner(null, copy, 'Loading…')
  if (!dialog.open) dialog.showModal()
  let shown = false
  try {
    const saved = findPartner(await PokeSim.recall?.('pc'), copy, dex)
    if (saved && current()) { showPartner(saved, copy)
      shown = true }
  } catch (_) {}
  try {
    const response = await PokeSim.fetch('/api/pokedex/status?view=pc', {cache: 'no-store'})
    if (!response.ok) throw new Error('Unavailable')
    const full = await response.json()
    PokeSim.remember?.('pc', full)
    if (!current()) return
    const partner = findPartner(full, copy, dex)
    showPartner(partner, copy, partner ? '' : 'It has moved since the Pokédex last updated. Show in PC finds where it is now.')
  } catch (_) {
    if (current() && !shown) showPartner(null, copy, 'Its full record could not be loaded. Try again in a moment.')
  }
}

function closeCopy() {
  if ($('#mon-detail').open) $('#mon-detail').close()
}

// Closing returns to the Pokédex entry as it was, with focus on the row that opened it.
function copyClosed() {
  const opened = copyOpen
  copyOpen = null
  copyRun++
  if (opened && opened.dex === openDex) $(`#detail-body [data-copy="${opened.index}"]`)?.focus()
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
  const next = Math.min(dexTotal, Math.max(1, openDex + offset))
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
  party.forEach((mon) => add(mon.dex, {nick: mon.nick, level: mon.level, stars: mon.dv_stars, shiny: mon.shiny, where: `Party slot ${mon.slot}`, box: 0, slot: mon.slot}))
  stored.forEach((mon) => add(mon.dex, {nick: mon.nick, level: mon.level, stars: mon.dv_stars, shiny: mon.shiny, where: `Box ${mon.box}`, box: mon.box, slot: mon.position}))

}

async function loadReference() {
  const response = await PokeSim.fetch('/api/pokedex')
  if (!response.ok) throw new Error('The Pokédex could not be opened.')
  const data = await response.json()
  fresh = true
  showReference(data)
  // The reference only changes with the cartridge; its ETag says whether the saved copy is current.
  const etag = response.headers?.get?.('etag') || ''
  if (!etag || etag !== savedReference) PokeSim.remember?.('dex-reference', {etag, data})
}

function showReference(data) {
  entries = data.entries
  dexTotal = data.count || entries.length
  const regions = data.generation === 2 ? 'Johto and Kanto' : 'Kanto'
  document.title = `The ${regions} Pokédex. · pokesim`
  $('.skip-link').textContent = 'Skip to the Pokédex.'
  $('.who .micro').textContent = `${regions}, ${dexTotal} entries`
  $('.dex-lede').textContent = `Pick any species for its stats, family, where to find it in ${regions}, and the moves it learns.`
  for (const id of ['#owned-meter', '#seen-meter', '#maxed-meter']) $(id).max = dexTotal
  maxStat = data.generation === 2 ? 255 : 190
  byDex = new Map(entries.map((entry) => [entry.dex, entry]))
  const types = [...new Set(entries.flatMap((entry) => entry.types))].sort()
  $('#type-filter').innerHTML = '<option value="all">Every type</option>' + types.map((type) => `<option value="${esc(type)}">${esc(type)}</option>`).join('')
}

async function fetchStatus() {
  const response = await PokeSim.fetch('/api/pokedex/status?view=dex', {cache: 'no-store'})
  if (!response.ok) throw new Error('Unavailable')
  return response.json()
}

async function refreshStatus(pending = fetchStatus(), saved = false) {
  try {
    const status = await pending
    if (saved && fresh) return
    if (!saved) latest = status
    const shiny = status.shiny || {}
    shinySpecies = new Set(shiny.collection_species || [])
    shinySeen = new Set(shiny.seen_species || [])
    catches = status.catches || null
    const goals = status.milestones || {}
    maxed = new Set(goals.level_100 || [])
    perfectSpecies = new Set(goals.perfect_collection || goals.perfect_species || [])
    highQualitySpecies = new Set([...(goals.high_quality_species || []), ...(goals.perfect_species || [])])
    $('#sum-maxed').innerHTML = outOf(maxed.size)
    $('#maxed-meter').value = maxed.size
    paintBank('#maxed-cells', maxed.size)
    $('#sum-perfect').innerHTML = outOf(perfectSpecies.size)
    $('#perfect-meter').value = perfectSpecies.size
    paintBank('#perfect-cells', perfectSpecies.size)
    $('#sum-shiny').innerHTML = outOf(shinySpecies.size)
    $('#shiny-meter').value = shinySpecies.size
    paintBank('#shiny-cells', shinySpecies.size)
    owned = new Set(status.owned || [])
    seen = new Set(status.seen || [])
    plan = new Map((status.plan || []).map((row) => [row.dex, row]))
    hunting = (status.plan || []).find((row) => row.species === status.hunting)?.dex ?? null
    $('#connection').classList.remove('is-offline')
    $('#status').textContent = saved ? 'Updating…' : status.started ? 'Running' : 'Waiting'
    $('#connection').title = saved ? 'Showing the Pokédex as last seen while it updates'
      : status.started ? 'Adventure in progress' : 'Waiting for the adventure'
    $('#sum-owned').innerHTML = outOf(owned.size)
    $('#sum-seen').innerHTML = outOf(seen.size)
    $('#catch-tracking-note').textContent = trackingNote()
    $('#owned-meter').value = owned.size
    $('#seen-meter').value = seen.size
    paintBank('#owned-cells', owned.size)
    paintBank('#seen-cells', seen.size)
    renderHolders(status)
    renderGrid()
    if (openDex !== null) renderDetail(openDex, true)
  } catch (_) {
    if (saved) return
    $('#connection').classList.add('is-offline')
    $('#status').textContent = 'Reconnecting…'
    $('#connection').title = ''
  }
}

document.addEventListener('click', (event) => {
  const row = event.target.closest('[data-copy]')
  if (row) return openCopy(Number(row.dataset.copy))
  const card = event.target.closest('[data-dex]')
  if (card && card.dataset.dex) renderDetail(Number(card.dataset.dex))
})
$('#backdrop').onclick = closeDetail
$('#close-detail').onclick = closeDetail
$('#prev-mon').onclick = () => step(-1)
$('#next-mon').onclick = () => step(1)
$('#mon-close').onclick = closeCopy
$('#mon-detail').onclose = copyClosed
$('#mon-detail').onclick = (event) => {
  if (event.target !== $('#mon-detail')) return
  const rect = event.target.getBoundingClientRect()
  if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) closeCopy()
}
for (const control of ['#search', '#type-filter', '#status-filter', '#sort']) {
  $(control).oninput = renderGrid
}
window.addEventListener('keydown', (event) => {
  // The partner popup is a modal dialog of its own: it handles Tab and Escape itself.
  if (openDex === null || $('#mon-detail').open) return
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

// Paint the Pokédex as it was last seen while the fresh one loads. It is only looked at:
// the page offers nothing that acts.
let fresh = false
let latest = null
let savedReference = ''
async function showSaved() {
  const [reference, status] = await Promise.all([PokeSim.recall?.('dex-reference'), PokeSim.recall?.('dex-status')])
  if (reference?.etag) savedReference = reference.etag
  if (!reference?.data || !status || fresh) return
  try {
    showReference(reference.data)
    await refreshStatus(Promise.resolve(status), true)
    const requested = Number(location.hash.replace('#', ''))
    if (openDex === null && requested >= 1 && requested <= dexTotal) renderDetail(requested)
  } catch (_) {}
}
showSaved()
document.addEventListener('visibilitychange', () => {
  if (document.hidden && latest) PokeSim.remember?.('dex-status', latest)
})

// The status request starts at once, but counts paint only after the reference sets
// dexTotal, so a Gen II Pokédex never flashes the Gen I total of 151.
const firstStatus = fetchStatus()
firstStatus.catch(() => {})
loadReference().then(async () => {
  renderGrid()
  await refreshStatus(firstStatus)
  if (latest) PokeSim.remember?.('dex-status', latest)
  const requested = Number(location.hash.replace('#', ''))
  if (openDex === null && requested >= 1 && requested <= dexTotal) renderDetail(requested)
}).catch(() => {
  $('#grid').innerHTML = '<p class="dex-empty">The Pokédex data could not be loaded. Refresh to try again.</p>'
  refreshStatus(firstStatus)
})
setInterval(() => { if (!document.hidden) refreshStatus() }, 12000)
