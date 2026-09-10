const $ = (selector) => document.querySelector(selector)
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&': '&amp', '<': '&lt', '>': '&gt', '"': '&quot', "'": '&#39'}[char] + String.fromCharCode(59)))
const fmt = (value) => Number(value || 0).toLocaleString()
const clamp = (value) => Math.max(0, Math.min(100, Number(value) || 0))
const BADGES = ['Boulder', 'Cascade', 'Thunder', 'Rainbow', 'Soul', 'Marsh', 'Volcano', 'Earth']
const BADGE_SYMBOLS = ['◆', '◒', '✧', '✿', '♡', '◉', '✷', '❧']
const LEADERS = ['Brock', 'Misty', 'Lt. Surge', 'Erika', 'Koga', 'Sabrina', 'Blaine', 'Giovanni']
const TYPE_CLASS = new Set(['normal', 'fighting', 'flying', 'poison', 'ground', 'rock', 'bug', 'ghost', 'fire', 'water', 'grass', 'electric', 'psychic', 'ice', 'dragon'])
const typeClass = (name) => TYPE_CLASS.has(String(name).toLowerCase()) ? String(name).toLowerCase() : 'normal'
let viewerOnly = false
let paused = false
let manualMode = false
let stateBusy = false
let partySignature = ''
let eventFilter = 'highlights'
let eventRows = []
let eventGeneration = 0
let eventBusy = false
let moreAvailable = true
let toastTimer

function toast(message, error = false) {
  clearTimeout(toastTimer)
  $('#toast').textContent = message
  $('#toast').classList.toggle('error', error)
  $('#toast').hidden = false
  toastTimer = setTimeout(() => { $('#toast').hidden = true }, 4500)
}

async function post(action, value) {
  if (viewerOnly) throw new Error("This instance is view-only.")
  const response = await fetch('/api/control', {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify({action, value})})
  if (!response.ok) throw new Error('That action could not be sent. Please try again.')
  return response.json()
}

async function control(button, action, value, message) {
  button.disabled = true
  try {
    await post(action, value)
    if (message) toast(message)
    await refreshState()
  } catch (error) {
    toast(error.message, true)
  } finally {
    button.disabled = false
  }
}

function renderParty(party) {
  const signature = JSON.stringify(party)
  if (signature === partySignature || $('#party').contains(document.activeElement)) return
  partySignature = signature
  const expanded = new Set([...document.querySelectorAll('.mon-details[open]')].map((el) => el.dataset.key))
  $('#party-count').textContent = `${party.length} / 6`
  if (!party.length) {
    $('#party').innerHTML = '<li class="empty-party"><span aria-hidden="true">◌</span><h3>Every team starts somewhere.</h3><p>The first partner will appear here.</p></li>'
    return
  }
  $('#party').innerHTML = party.map((mon, index) => {
    const hp = clamp(mon.max_hp ? mon.hp / mon.max_hp * 100 : 0)
    const health = hp < 20 ? 'critical' : hp < 50 ? 'low' : 'healthy'
    const xp = mon.experience
    const key = `${index}-${mon.species}`
    const name = mon.nick && mon.nick.toUpperCase() !== mon.name.toUpperCase() ? mon.nick : mon.name
    const typeNames = mon.type_names || []
    const types = typeNames.map((type) => `<span class="type-tag ${typeClass(type)}">${esc(type)}</span>`).join('')
    const dex = mon.dex ? `No. ${String(mon.dex).padStart(3, '0')}` : 'Partner'
    const status = mon.status_label || (mon.hp ? 'Healthy' : 'Fainted')
    const nextLevel = xp?.max_level ? 'A lifetime of experience' : `${fmt(xp?.remaining)} XP to Lv. ${mon.level + 1}`
    const sprite = mon.dex ? `<img src="/sprites/${Number(mon.dex)}.png" alt="${esc(mon.name)} portrait" width="96" height="96">` : '<span class="unknown-sprite">?</span>'
    const moves = (mon.move_details || []).map((move) => `<div class="move"><span class="move-type ${typeClass(move.type)}" aria-hidden="true"></span><span>${esc(move.name)}</span><small class="${move.pp ? '' : 'depleted'}">${move.pp}/${move.max_pp} PP</small></div>`).join('')
    const stats = Object.entries(mon.stats || {}).map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${fmt(value)}</dd></div>`).join('')
    return `<li class="mon-card ${mon.hp ? '' : 'fainted'}"><div class="mon-main"><div class="sprite-stage ${typeClass(typeNames[0])}">${sprite}<span class="party-slot">${String(index + 1).padStart(2, '0')}</span></div><div class="mon-info"><div class="mon-title"><h3>${esc(name)}</h3><span class="level"><small>LV.</small> ${mon.level}</span></div><div class="mon-subtitle"><span>${dex}${name !== mon.name ? ` · ${esc(mon.name)}` : ''}</span>${types}</div><div class="meter-label"><span>HP <b class="${health}">${mon.hp > 0 ? '●' : '○'}</b></span><span><strong>${fmt(mon.hp)}</strong> / ${fmt(mon.max_hp)}</span></div><progress class="hp-meter ${health}" max="100" value="${hp}" aria-label="${esc(name)} health: ${mon.hp} of ${mon.max_hp}"></progress><div class="meter-label xp-label"><span>XP</span><span>${xp ? xp.max_level ? 'MAX LEVEL' : `${clamp(xp.percent)}%` : 'Unavailable'}</span></div><progress class="xp-meter" max="100" value="${clamp(xp?.percent)}" aria-label="${esc(name)} progress to next level"></progress><div class="mon-foot"><span>${xp ? nextLevel : 'Experience not available'}</span>${status !== 'Healthy' ? `<span class="condition">${esc(status)}</span>` : ''}</div></div></div><details class="mon-details" data-key="${key}" ${expanded.has(key) ? 'open' : ''}><summary><span>Moves & stats</span><span>＋</span></summary><div class="mon-extra"><div class="moves">${moves || '<p>No moves yet.</p>'}</div><dl class="battle-stats">${stats}</dl>${xp ? `<p class="total-xp">${fmt(xp.total)} total experience</p>` : ''}</div></details></li>`
  }).join('')
}

async function refreshState() {
  if (stateBusy) return
  stateBusy = true
  try {
    const response = await fetch('/api/state', {cache: 'no-store'})
    if (!response.ok) throw new Error('Unavailable')
    const state = await response.json()
    if ($('#connection').classList.contains('is-offline')) window.pokesimScreen?.reconnect()
    viewerOnly = Boolean(state.viewer_only)
    document.querySelectorAll('.controls, .controller, .wander-control, .wander-hint, label[for="adventure-pace"], #restart').forEach((element) => {
      element.hidden = viewerOnly
    })
    $('#app-version').textContent = `v${state.version || 'unknown'}`
    const game = state.game
    paused = state.paused
    manualMode = state.manual_mode
    $('.game-card').classList.toggle('is-manual', manualMode)
    $('#take-control').textContent = manualMode ? 'Let AI play' : 'Take control'
    $('#control-mode').textContent = manualMode ? 'You’re playing · AI paused' : paused ? 'Game frozen' : 'AI is playing'
    $('#control-hint').textContent = manualMode ? 'Play at normal speed. Let AI play when you’re ready to hand it back.' : 'Press any game control to pause the AI and take over.'
    if (document.activeElement !== $('#wander')) $('#wander').value = String(state.strategy?.exploration ?? 0.12)
    $('#connection').classList.toggle('is-paused', paused)
    $('#connection').classList.remove('is-offline')
    $('#status').textContent = manualMode ? 'You’re in control' : paused ? 'Game frozen' : 'Adventure in progress'
    $('#pause').textContent = paused && !manualMode ? '▶ Unfreeze' : 'Ⅱ Freeze game'
    if (document.activeElement !== $('#speed')) $('#speed').value = String(state.speed)
    const strategy = state.strategy
    $('#journey').innerHTML = (strategy?.journey || []).map((step) => `<li class="${step.done ? 'done' : step.current ? 'current' : ''}">${step.done ? '✓ ' : ''}${esc(step.title)}</li>`).join('')
    $('#strategy-panel').hidden = !strategy?.objective
    if (strategy?.objective) {
      renderIntent(strategy)
      renderCollection(strategy.collection, state.game)
      $('#objective').textContent = strategy.objective.title
      $('#decision').textContent = strategy.reason
      $('#action-tag').textContent = strategy.action.charAt(0).toUpperCase() + strategy.action.slice(1)
      $('#progress').textContent = `${fmt(strategy.visited_tiles)} tiles explored`
    }
    if (!game) return
    $('#live-heading').textContent = game.map_name
    $('#coordinates').textContent = `${game.x}, ${game.y}`
    $('#game-activity').textContent = manualMode ? 'Your adventure. Your next move.' : paused ? 'A moment to take it all in.' : game.in_battle ? game.opponent ? `Trainer battle · ${game.opponent}` : `Wild encounter · ${game.enemy || 'Pokémon'} · Lv. ${game.enemy_level}` : game.textbox ? 'A conversation along the way.' : game.start_menu ? 'Checking the essentials.' : 'Onward to the next little discovery.'
    $('#playtime').textContent = game.playtime.split(':').slice(0, 2).map((v) => v.padStart(2, '0')).join(':')
    $('#trainer-name').textContent = game.player_name || 'A new trainer'
    $('#trainer-rival').textContent = game.rival_name ? `Rival: ${game.rival_name}` : 'A new story begins'
    $('#dex-count').innerHTML = `${game.owned} <small>/ 151</small>`
    $('#dex-count').title = `${game.seen} Pokémon seen`
    $('#money').textContent = `₽${fmt(game.money)}`
    $('#areas').textContent = fmt(state.areas_discovered)
    const earned = game.badges || []
    $('#badge-count').textContent = `${earned.length} / 8`
    $('#badges').innerHTML = BADGES.map((badge, i) => `<div class="badge ${earned.includes(badge) ? 'earned' : ''}" title="${badge} Badge · ${LEADERS[i]} · ${earned.includes(badge) ? 'Earned' : 'Still ahead'}"><span class="badge-icon badge-${i}" aria-hidden="true">${BADGE_SYMBOLS[i]}</span><span>${badge}</span><small>${earned.includes(badge) ? 'EARNED' : String(i + 1).padStart(2, '0')}</small></div>`).join('')
    renderParty(game.party)
    const items = game.items || []
    $('#bag-count').textContent = `${items.length} ${items.length === 1 ? 'item' : 'items'}`
    $('#bag-items').innerHTML = items.length ? items.map((item) => `<div><span>${esc(item.name)}</span><strong>×${item.qty}</strong></div>`).join('') : '<p>A little room for future finds.</p>'
  } catch (_) {
    $('#status').textContent = 'Reconnecting…'
    $('#connection').classList.add('is-offline')
  } finally {
    stateBusy = false
  }
}

const EVENT_LABELS = {badge: 'A BADGE TO REMEMBER', catch: 'A NEW FRIEND', evolve: 'GROWING TOGETHER', obtain: 'A NEW COMPANION', map: 'SOMEWHERE NEW', level: 'A LITTLE STRONGER', blackout: 'A FRESH START', champion: 'HALL OF FAME', item: 'A GOOD FIND', trainer: 'CHALLENGE ACCEPTED', seen: 'FIRST SIGHTING', playtime: 'TIME WELL SPENT'}
function renderEvents() {
  $('#events').innerHTML = eventRows.map((event) => {
    const date = new Date(event.ts * 1000)
    return `<a class="event-card event-${esc(event.type)}" href="/events/${event.id}"><div class="event-picture">${event.shot ? `<img loading="lazy" src="/shots/${encodeURIComponent(event.shot)}" alt="Game screen at ${esc(event.title)}" width="160" height="144">` : '<span aria-hidden="true">✧</span>'}<span class="event-label">${EVENT_LABELS[event.type] || 'FROM THE JOURNAL'}</span></div><div class="event-copy"><time datetime="${date.toISOString()}">${date.toLocaleDateString(undefined, {month: 'short', day: 'numeric'})} · ${date.toLocaleTimeString(undefined, {hour: '2-digit', minute: '2-digit'})}</time><h3>${esc(event.title)}</h3><p>${esc(event.map)}<span aria-hidden="true">↗</span></p></div></a>`
  }).join('') || '<div class="journal-empty"><span>✧</span><h3>The best pages are still unwritten.</h3><p>New moments will find their way here as the adventure unfolds.</p></div>'
  $('#load-more').hidden = !moreAvailable || !eventRows.length
}

async function refreshEvents(append = false) {
  if (eventBusy) return
  eventBusy = true
  const generation = eventGeneration
  const params = new URLSearchParams({limit: '8'})
  if (eventFilter === 'all') params.set('all', '1')
  if (eventFilter === 'team') {
    params.set('types', 'catch,evolve,obtain,level')
    params.set('all', '1')
  }
  if (append && eventRows.length) params.set('before', String(eventRows.at(-1).id))
  try {
    const response = await fetch(`/api/events?${params}`)
    if (!response.ok) throw new Error('Could not open the journal')
    const rows = await response.json()
    if (generation !== eventGeneration) return
    moreAvailable = append || !eventRows.length ? rows.length === 8 : moreAvailable
    if (append) eventRows = [...eventRows, ...rows.filter((row) => !eventRows.some((existing) => existing.id === row.id))]
    else eventRows = [...rows, ...eventRows.filter((row) => !rows.some((existing) => existing.id === row.id))]
    renderEvents()
  } catch (_) {
    if (!eventRows.length) $('#events').innerHTML = '<p class="journal-empty">The journal is taking a moment. We’ll try again shortly.</p>'
  } finally {
    eventBusy = false
    if (generation !== eventGeneration) refreshEvents()
  }
}

$('#pause').onclick = (event) => control(event.currentTarget, paused && !manualMode ? 'take_control' : 'pause')
$('#take-control').onclick = (event) => control(event.currentTarget, manualMode ? 'resume' : 'take_control')
$('#wander').onchange = (event) => control(event.currentTarget, 'exploration', Number(event.target.value))
$('#speed').onchange = (event) => control(event.currentTarget, 'speed', Number(event.target.value))
$('#save').onclick = (event) => control(event.currentTarget, 'save', undefined, 'Save requested. A little moment to come back to.')
$('#restart').onclick = (event) => {
  if (confirm('Start a fresh adventure from the beginning? Your event journal will be kept.')) control(event.currentTarget, 'restart', undefined, 'A new adventure is starting.')
}
$('.controller').onclick = (event) => {
  const button = event.target.closest('[data-b]')
  if (button) manualPress(button.dataset.b)
}
$('#fullscreen').onclick = async () => {
  try {
    if (document.fullscreenElement) await document.exitFullscreen()
    else await $('#screen').requestFullscreen()
  } catch (_) { toast('Fullscreen is unavailable in this browser.', true) }
}
document.querySelectorAll('[data-filter]').forEach((button) => {
  button.onclick = () => {
    if (eventFilter === button.dataset.filter) return
    eventFilter = button.dataset.filter
    eventGeneration += 1
    eventRows = []
    moreAvailable = true
    document.querySelectorAll('[data-filter]').forEach((item) => {
      const active = item === button
      item.classList.toggle('active', active)
      item.setAttribute('aria-pressed', String(active))
    })
    $('#events').innerHTML = '<p class="journal-empty">Turning the page…</p>'
    $('#load-more').hidden = true
    refreshEvents()
  }
})
$('#load-more').onclick = () => refreshEvents(true)
async function manualPress(button) {
  try {
    await post('press', button)
    manualMode = true
    paused = true
    $('#take-control').textContent = 'Let AI play'
    $('#control-mode').textContent = 'You’re playing · AI paused'
    $('.game-card').classList.add('is-manual')
  } catch (error) { toast(error.message, true) }
}
let lastKeyPress = 0
window.addEventListener('keydown', (event) => {
  if (viewerOnly) return
  const map = {ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right', z: 'a', x: 'b', Enter: 'start', Shift: 'select'}
  if (map[event.key] && !event.target.closest('input, select, textarea, [contenteditable]') && !(event.key === 'Enter' && event.target.closest('button, summary, a'))) {
    event.preventDefault()
    if (!event.repeat || Date.now() - lastKeyPress > 140) {
      lastKeyPress = Date.now()
      manualPress(map[event.key])
    }
  }
})
refreshState()
refreshEvents()
setInterval(refreshState, 2000)
setInterval(() => { if (!document.hidden) refreshEvents() }, 15000)

function renderIntent(strategy) {
  const assessment = strategy.readiness || {}
  $('#next-objective').textContent = strategy.next?.title || 'Continue the journey'
  $('#expectation').textContent = strategy.expectation || ''
  $('#personality').textContent = strategy.personality || ''
  $('#readiness-label').textContent = assessment.opponent ? `${assessment.status} for ${assessment.opponent}` : 'Team readiness'
  $('#readiness-meter').value = assessment.score || 0
  $('#readiness-concerns').textContent = (assessment.concerns || []).join('. ') || 'The team has a useful matchup and supplies.'
  $('#readiness-members').innerHTML = (assessment.members || []).map((p) => `<span>${esc(p.name)} · ${p.score}/100${p.index === assessment.lead ? ' · best matchup' : ''}</span>`).join('')
  $('#recovery-history').innerHTML = (strategy.history || []).slice().reverse().map((entry) => `<li>${esc(entry.message)}<small>${esc(entry.time)} · ${esc(entry.place)}. ${esc(entry.response)}</small></li>`).join('') || '<li>No recent recovery needed.</li>'
  const map = strategy.map
  if (!map) return
  const canvas = $('#route-map')
  const ctx = canvas.getContext('2d')
  const size = Math.min(canvas.width / map.width, canvas.height / map.height)
  const ox = (canvas.width - map.width * size) / 2
  const oy = (canvas.height - map.height * size) / 2
  ctx.fillStyle = '#263b34'
  ctx.fillRect(0, 0, canvas.width, canvas.height)
  const passable = new Set(map.passable)
  let y = 0
  while (y < map.height) {
    let x = 0
    while (x < map.width) {
      const tile = map.tiles[y][x]
      ctx.fillStyle = passable.has(tile) ? '#58735e' : ['OVERWORLD', 'CAVERN', 'FOREST', 'PLATEAU'].includes(map.tileset) && [20, 50, 72].includes(tile) ? '#396a80' : '#30483c'
      ctx.fillRect(ox + x * size, oy + y * size, size, size)
      x++
    }
    y++
  }
  ctx.fillStyle = '#69d6bf'
  for (const [m, x, y] of strategy.route || []) {
    if (m === map.id) ctx.fillRect(ox + x * size, oy + y * size, size, size)
  }
  ctx.fillStyle = '#f4f3db'
  for (const [x, y] of map.warps) ctx.fillRect(ox + x * size, oy + y * size, size, size)
  ctx.fillStyle = '#ffcd64'
  ctx.beginPath()
  ctx.arc(ox + (map.player[0] + 0.5) * size, oy + (map.player[1] + 0.5) * size, Math.max(3, size * 0.6), 0, Math.PI * 2)
  ctx.fill()
  canvas.setAttribute('aria-label', `${map.name}, player at ${map.player.join(', ')}, planned route in teal`)
}

let collectionEntries = []
let collectionRenderKey = ''
function renderCollection(collection, game) {
  if (!collection) return
  const key = JSON.stringify([collection, game?.storage])
  if (key === collectionRenderKey) return
  collectionRenderKey = key
  if (document.activeElement !== $('#adventure-pace')) $('#adventure-pace').value = collection.pace
  $('#collection-phase').textContent = collection.phase || 'Adventure'
  $('#collection-caught').textContent = `${collection.caught || 0} / 151`
  $('#collection-available').textContent = collection.available || 0
  const hunt = collection.hunt
  const target = collection.entries?.find(entry => entry.species === hunt?.species)
  $('#collection-hunt').textContent = hunt ? `${target?.name || hunt.item?.replaceAll('_', ' ') || 'Exploration'} · ${({grass:'Pokédex hunt', surf:'Surf expedition', fish:'Fishing', safari:'Safari expedition', evolve:'Evolution', gift:'Gift', fossil:'Fossil revival', static:'Legendary encounter', rod:'Fishing gear', trade:'In-game trade', prize:'Game Corner', rematch:'League rematch', trainer:'Trainer battle', explore:'Exploration', amber:'Fossil discovery'})[hunt.method] || 'Expedition'}` : 'Watching for new discoveries'
  $('#collection-budget').textContent = hunt ? `Reassess in ${Math.ceil(collection.remaining_seconds / 60)} game minutes` : 'Short expeditions alternate with the main journey'
  $('#collection-evolutions').innerHTML = collection.evolutions?.length ? collection.evolutions.map(e => `<li><strong>${esc(e.from)} → ${esc(e.to)}</strong><span>${e.method === 'level' ? `Level ${e.level} → ${e.requirement}` : e.method === 'trade' ? 'Requires a link trade' : esc(String(e.requirement).replaceAll('_', ' '))}</span></li>`).join('') : '<li>More evolution projects will appear as the collection grows.</li>'
  $('#collection-history').innerHTML = collection.history?.length ? collection.history.map(line => `<li>${esc(line)}</li>`).join('') : '<li>The next discovery is out there.</li>'
  collectionEntries = collection.entries || []
  renderCollectionEntries()
  const storage = game?.storage
  if (storage) {
    $('#collection-box-summary').textContent = `Storage · Box ${storage.active_box} active · ${storage.box_counts.reduce((a, b) => a + b, 0)} Pokémon stored`
    const openBoxes = new Set([...document.querySelectorAll('.storage-box[open]')].map(box => Number(box.dataset.box)))
    $('#collection-boxes').innerHTML = storage.box_counts.map((count, index) => `<details class="storage-box" data-box="${index}" ${openBoxes.has(index) ? 'open' : ''}><summary>Box ${index + 1}${index + 1 === storage.active_box ? ' · Active' : ''}<span>${count} / 20</span></summary><ul>${storage.pokemon.filter(p => p.box === index + 1).map(p => `<li><strong>${esc(p.nick || p.name)}</strong><span>${esc(p.name)} · Lv. ${p.level}</span></li>`).join('') || '<li>Room for new friends.</li>'}</ul></details>`).join('')
  }
}
function renderCollectionEntries() {
  const query = $('#dex-search').value.toLowerCase().trim()
  const filter = $('#dex-filter').value
  const entries = collectionEntries.filter(e => (!query || e.name.toLowerCase().includes(query) || String(e.dex).includes(query)) && (filter === 'all' || filter === 'unavailable' ? filter === 'all' || !['available', 'caught'].includes(e.status) : e.status === filter))
  $('#collection-entries').innerHTML = entries.map(e => `<article class="dex-entry ${e.status}"><img loading="lazy" src="/sprites/${e.dex}.png" alt="" width="56" height="56"><div><small>#${String(e.dex).padStart(3, '0')} · ${e.status === 'available' ? 'Possible here' : e.status === 'caught' ? 'Caught' : 'Other requirements'}</small><strong>${esc(e.name)}</strong><p>${esc(e.reason)}</p></div></article>`).join('') || '<p>No Pokémon match this search.</p>'
}
$('#adventure-pace').onchange = event => control(event.currentTarget, 'adventure_pace', event.target.value)
$('#dex-search').oninput = renderCollectionEntries
$('#dex-filter').onchange = renderCollectionEntries
