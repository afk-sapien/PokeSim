if (location.pathname === PokeSim.url('/') && location.hash === '#journal') location.replace(PokeSim.url('/journal'))
const $ = (selector) => document.querySelector(selector)
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&': '&amp', '<': '&lt', '>': '&gt', '"': '&quot', "'": '&#39'}[char] + String.fromCharCode(59)))
function set(selector, property, value) {
  const element = $(selector)
  if (element) element[property] = value
}
const fmt = (value) => Number(value || 0).toLocaleString()
const clamp = (value) => Math.max(0, Math.min(100, Number(value) || 0))
const BADGES = ['Boulder', 'Cascade', 'Thunder', 'Rainbow', 'Soul', 'Marsh', 'Volcano', 'Earth']
const LEADERS = ['Brock', 'Misty', 'Lt. Surge', 'Erika', 'Koga', 'Sabrina', 'Blaine', 'Giovanni']
// A cable trade leaves no screenshot behind, so the card drew a placeholder glyph and said
// nothing about the swap. Draw the two Pokemon instead, with the trainer on the other end.
function tradeArt(event) {
  let detail = null
  try { detail = event.detail ? JSON.parse(event.detail) : null } catch (error) { return '' }
  if (!detail || detail.kind !== 'trade') return ''
  const face = (side) => side && side.dex
    ? `<img loading="lazy" src="${PokeSim.base}/sprites/${Number(side.dex)}.png" alt="${esc(side.name || '')}" width="56" height="56">`
    : '<span class="unknown-sprite" aria-hidden="true">?</span>'
  const label = (side) => esc(side && side.nick ? side.nick : '')
  return `<span class="trade-art">`
    + `<span class="trade-side"><span class="trade-way">Sent</span>${face(detail.sent)}<small>${label(detail.sent)}</small></span>`
    + `<span class="trade-swap" aria-hidden="true">\u2192</span>`
    + `<span class="trade-side"><span class="trade-way">Got</span>${face(detail.received)}<small>${label(detail.received)}</small></span>`
    + `</span>`
}

// The planner passes through a gap between projects, and a decision tick can land on a League map
// or the ceremony, so the raw objective flickers several times a minute. Hold the last real one:
// a gap is not a new plan, and a title has to persist to replace the headline.
const PLANNING = 'collect_plan'
let shownObjective = null
let pendingObjective = null
let pendingSightings = 0
function steadyObjective(objective) {
  if (!objective) return shownObjective
  if (!shownObjective) { shownObjective = objective; return shownObjective }
  if (objective.id === PLANNING) return shownObjective
  if (objective.id === shownObjective.id) { pendingObjective = null; pendingSightings = 0; return shownObjective }
  if (pendingObjective && pendingObjective.id === objective.id) {
    pendingSightings += 1
    if (pendingSightings >= 2) {
      shownObjective = objective
      pendingObjective = null
      pendingSightings = 0
    }
  } else {
    pendingObjective = objective
    pendingSightings = 1
  }
  return shownObjective
}
let viewerOnly = false
let paused = false
let manualMode = false
let stateBusy = false
let partySignature = ''
let currentParty = []
let selectedPartner = null
let eventFilter = 'highlights'
let eventRows = []
let eventGeneration = 0
let eventBusy = false
let moreAvailable = true
let toastTimer

function toast(message, error = false) {
  clearTimeout(toastTimer)
  set('#toast', 'textContent', message)
  $('#toast').classList.toggle('error', error)
  set('#toast', 'hidden', false)
  toastTimer = setTimeout(() => { $('#toast').hidden = true }, 4500)
}

async function post(action, value) {
  if (viewerOnly) throw new Error("This instance is view-only.")
  const response = await PokeSim.fetch('/api/control', {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify({action, value})})
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
  if (!$('#party')) return
  currentParty = party
  renderPartnerDetail()
  const signature = JSON.stringify(party)
  if (signature === partySignature || $('#party').contains(document.activeElement)) return
  partySignature = signature
  set('#party-count', 'textContent', `${party.length} / 6`)
  if (!party.length) {
    set('#party', 'innerHTML', '<li class="mon mon--empty"><div class="mon-plate"><div class="plate plate--bay"><span class="plate-num">01</span></div></div><div class="mon-body"><p class="micro">Every team starts somewhere</p><p>The first partner will appear here.</p></div></li>')
    return
  }
  // Same scale as dv_rating() on the server: five DVs out of 75, HP derived from the rest.
  const dvStars = (dvs) => {
    if (!Array.isArray(dvs) || dvs.length !== 5) return null
    if (!dvs.every((value) => Number.isInteger(value) && value >= 0 && value <= 15)) return null
    const total = dvs.reduce((sum, value) => sum + value, 0)
    return total === 75 ? 4 : total >= 60 ? 3 : total >= 38 ? 2 : 1
  }
  const slotNo = (index) => String(index + 1).padStart(2, '0')
  const openBay = (index, title, note) =>
    `<li class="mon mon--empty"><div class="mon-plate"><div class="plate plate--bay"><span class="plate-num">${slotNo(index)}</span></div></div><div class="mon-body"><p class="micro">${title}</p><p>${note}</p></div></li>`
  const emptySlots = (filled) => Array.from({length: Math.max(0, 6 - filled)}, (_, slot) =>
    openBay(filled + slot, `Slot ${slotNo(filled + slot)}`, 'Room for one more')).join('')
  // A Pokémon on the naming screen is counted before the cartridge writes its stats,
  // so show the slot as arriving rather than as a fainted level 0 nobody.
  const pendingSlot = (index) => openBay(index, `Slot ${slotNo(index)}`, 'Joining the team…')
  // Sixteen cells, and a cell only lights once it is earned, so a sliver of HP
  // still shows one lit cell rather than an empty meter.
  const meter = (percent, level, label) => {
    const lit = percent > 0 ? Math.max(1, Math.round(percent / 100 * 16)) : 0
    return `<div class="meter" data-level="${level}" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(percent)}" aria-label="${label}">${Array.from({length: 16}, (_, i) => `<i${i < lit ? ' class="on"' : ''}></i>`).join('')}</div>`
  }
  $('#party').innerHTML = party.map((mon, index) => {
    if (mon.pending) return pendingSlot(index)
    const hp = clamp(mon.max_hp ? mon.hp / mon.max_hp * 100 : 0)
    const health = hp < 20 ? 'crit' : hp < 50 ? 'warn' : 'ok'
    const xp = mon.experience
    const name = mon.nick && mon.nick.toUpperCase() !== mon.name.toUpperCase() ? mon.nick : mon.name
    const types = (mon.type_names || []).map((type) => `<span class="tag">${esc(type)}</span>`).join('')
    const dex = mon.dex ? `<span class="micro dexno">No.${String(mon.dex).padStart(3, '0')}</span>` : ''
    const status = mon.status_label || (mon.hp ? 'Healthy' : 'Fainted')
    const statusTag = status !== 'Healthy' ? `<span class="tag ${mon.hp ? 'tag--warn' : 'tag--crit'}">${esc(status)}</span>` : ''
    const moveRows = (mon.move_details || []).map((move) => `<div class="move" title="${esc(move.name)} · ${esc(move.type || '')} · ${move.pp}/${move.max_pp} PP"><span class="nm">${esc(move.name)}</span><span class="pp${move.pp ? '' : ' empty'}">${move.pp}</span></div>`).join('')
    const rating = dvStars(mon.dvs)
    const dvLamps = rating ? `<span class="dv" title="DV rating ${rating} of 4" role="img" aria-label="DV rating ${rating} of 4">${Array.from({length: 4}, (_, i) => `<i class="lamp"${i < rating ? ' data-on="signal"' : ''}></i>`).join('')}</span>` : ''
    const sprite = mon.dex ? `<img src="${PokeSim.base}/sprites/${Number(mon.dex)}.png" alt="${esc(mon.name)} portrait">` : `<span class="plate-num">?</span>`
    const xpText = xp ? xp.max_level ? 'MAX' : `${Math.floor(clamp(xp.percent))}%` : '—'
    return `<li class="mon${mon.hp ? '' : ' mon--fainted'}"><div class="mon-plate"><div class="plate plate--bay">${sprite}</div></div><div class="mon-body"><div class="mon-head"><span class="slotno">${slotNo(index)}</span><h3 class="name">${esc(name)}</h3><span class="spacer"></span>${dvLamps}<span class="lv"><em>LV</em>${mon.level}</span><button class="mon-open" data-partner="${index}" aria-haspopup="dialog" aria-label="View ${esc(name)} battle stats"><span aria-hidden="true">↗</span></button></div><div class="mon-id">${dex}<span class="micro">${esc(mon.name)}</span>${types}${statusTag}</div><div class="mon-lower"><div class="mon-meters"><div class="meter-row"><span class="micro">HP</span>${meter(hp, health, `${esc(name)} health: ${mon.hp} of ${mon.max_hp}`)}<span class="value">${fmt(mon.hp)}/${fmt(mon.max_hp)}</span></div><div class="meter-row"><span class="micro">XP</span>${meter(clamp(xp?.percent), 'signal', `${esc(name)} progress to next level`)}<span class="value">${xpText}</span></div></div><div class="mon-moves">${moveRows || '<p class="no-moves">No moves yet.</p>'}</div></div></div></li>`
  }).join('') + emptySlots(party.length)
  fitSprites($('#party'))
}

// Portrait scaling is shared; see panel.js.
const fitSprites = (root) => globalThis.Panel?.fitSprites?.(root)

async function refreshState() {
  if (stateBusy) return
  stateBusy = true
  try {
    const response = await PokeSim.fetch('/api/state', {cache: 'no-store'})
    if (!response.ok) throw new Error('Unavailable')
    const state = await response.json()
    if ($('#connection').classList.contains('is-offline')) window.pokesimScreen?.reconnect()
    viewerOnly = Boolean(state.viewer_only)
    document.querySelectorAll('.controls, .manual-controls, .controller, #restart').forEach((element) => {
      element.hidden = viewerOnly
    })
    set('#app-version', 'textContent', `v${state.version || 'unknown'}`)
    const edition = state.strategy?.collection?.version
    if (edition) {
      set('.screen-corner', 'textContent', `POKÉMON ${edition.toUpperCase()} · GAME BOY`)
      set('#stream', 'alt', `Live Pokémon ${edition} game`)
    }
    const game = state.game
    paused = state.paused
    if (state.manual_mode && !manualMode) {
      set('#manual-controls', 'open', true)
    }
    manualMode = state.manual_mode
    $('.game-card')?.classList.toggle('is-manual', manualMode)
    set('#take-control', 'textContent', manualMode ? 'Let AI play' : 'Take control')
    set('#control-mode', 'textContent', manualMode ? 'You’re playing · AI paused' : paused ? 'Game frozen' : 'AI is playing')
    set('#control-hint', 'textContent', manualMode ? 'Play at normal speed. Let AI play when you’re ready to hand it back.' : 'Press any game control to pause the AI and take over.')
    $('#connection').classList.toggle('is-paused', paused)
    $('#connection').classList.remove('is-offline')
    set('#status', 'textContent', manualMode ? 'In control' : paused ? 'Frozen' : 'Running')
    $('#connection').title = manualMode ? 'You’re in control' : paused ? 'Game frozen' : 'Adventure in progress'
    set('#pause', 'textContent', paused && !manualMode ? 'Unfreeze' : 'Freeze')
    const progress = state.progress
    const strategy = state.strategy
    const planning = strategy?.objective?.id === PLANNING
    set('#progress-state', 'textContent', paused ? 'Paused' : planning ? 'Choosing what is next' : ({exploring: 'Exploring', making_progress: 'Making progress', recovering: 'Recovering', stalled: 'Stuck?'}[progress?.state] || 'Exploring'))
    const achievement = progress?.last_achievement
    const age = achievement?.age_seconds || 0
    const since = age < 60 ? 'just now' : age < 3600 ? `${Math.floor(age / 60)}m ago` : `${Math.floor(age / 3600)}h ago`
    set('#last-achievement', 'textContent', achievement ? `Last achievement: ${achievement.title} · ${since}` : 'Waiting for the first achievement.')
    set('#strategy-panel', 'hidden', !strategy?.objective)
    renderIntent(strategy || {})
    const steady = steadyObjective(strategy?.objective)
    if (steady) {
      set('#objective', 'textContent', steady.title)
      if (!planning) set('#decision', 'textContent', strategy.reason)
      set('#action-tag', 'textContent', (strategy.action || '').replace(/^./, (letter) => letter.toUpperCase()))
      set('#progress', 'textContent', `${fmt(strategy.visited_tiles)} tiles explored`)
    }
    if (!game) return
    set('#live-heading', 'textContent', game.map_name)
    set('#coordinates', 'textContent', `${game.x}, ${game.y}`)
    set('#game-activity', 'textContent', manualMode ? 'Your adventure. Your next move.' : paused ? 'A moment to take it all in.' : game.in_battle ? game.opponent ? `Trainer battle · ${game.opponent}` : `Wild encounter · ${game.enemy || 'Pokémon'} · Lv. ${game.enemy_level}` : game.textbox ? 'A conversation along the way.' : game.start_menu ? 'Checking the essentials.' : 'Onward to the next little discovery.')
    const clock = state.play_clock
    const time = clock?.display || game.playtime
    set('#playtime', 'textContent', time.split(':').slice(0, 2).map((v) => v.padStart(2, '0')).join(':') + (clock?.lower_bound ? '+' : ''))
    set('#playtime', 'title', clock?.lower_bound ? 'At least this much simulated playtime. The cartridge had already reached its limit when app tracking began.' : 'Simulated playtime tracked by the app. Pauses and server downtime are excluded.')
    set('#clock-note', 'textContent', clock?.lower_bound ? 'Earlier time hit the game limit' : '')
    set('#trainer-name', 'textContent', game.player_name || 'A new trainer')
    set('#trainer-rival', 'textContent', game.rival_name ? `Rival: ${game.rival_name}` : 'A new story begins')
    set('#dex-count', 'innerHTML', `${fmt(game.owned)}<span class="unit">/151</span>`)
    set('#dex-count', 'title', `${game.seen} Pokémon seen`)
    set('#league-wins', 'textContent', fmt(state.league_rewards?.wins ?? game.hall_of_fame_count ?? 0))
    set('#money', 'textContent', `₽${fmt(game.money)}`)
    set('#areas', 'textContent', fmt(state.areas_discovered))
    const earned = game.badges || []
    set('#badge-count', 'textContent', `${earned.length} / 8`)
    set('#badges', 'innerHTML', BADGES.map((badge, i) => `<i class="lamp"${earned.includes(badge) ? ' data-on="signal"' : ''} role="img" aria-label="${badge} Badge, ${earned.includes(badge) ? 'earned' : 'still ahead'}" title="${badge} Badge · ${LEADERS[i]} · ${earned.includes(badge) ? 'Earned' : 'Still ahead'}"></i>`).join(''))
    renderParty(game.party)
  } catch (_) {
    set('#status', 'textContent', 'Reconnecting…')
    $('#connection').title = ''
    $('#connection').classList.add('is-offline')
  } finally {
    stateBusy = false
  }
}

const EVENT_LABELS = {trade: 'A PARTNER FROM AFAR', badge: 'A BADGE TO REMEMBER', catch: 'A NEW FRIEND', evolve: 'GROWING TOGETHER', obtain: 'A NEW COMPANION', map: 'SOMEWHERE NEW', level: 'A LITTLE STRONGER', blackout: 'A FRESH START', champion: 'HALL OF FAME', item: 'A GOOD FIND', trainer: 'CHALLENGE ACCEPTED', seen: 'FIRST SIGHTING', playtime: 'TIME WELL SPENT'}
// Each entry's lamp says what kind of moment it was, so the log can be skimmed by colour
// as well as read: milestones in signal, the team in green, a blackout in red.
const EVENT_LAMPS = {badge: 'signal', champion: 'signal', catch: 'ok', obtain: 'ok', trade: 'ok', evolve: 'ok', level: 'ok', blackout: 'crit', trainer: 'warn'}
function renderEvents() {
  $('#events').innerHTML = eventRows.map((event) => {
    const date = new Date(event.ts * 1000)
    const lamp = EVENT_LAMPS[event.type] ? ` data-on="${EVENT_LAMPS[event.type]}"` : ''
    const picture = event.shot
      ? `<img loading="lazy" src="${PokeSim.base}/shots/${encodeURIComponent(event.shot)}" alt="Game screen at ${esc(event.title)}" width="160" height="144">`
      : tradeArt(event) || '<span class="no-frame">No screen kept</span>'
    return `<a class="event-card event-${esc(event.type)}" href="${PokeSim.base}/events/${event.id}"><div class="event-time"><i class="lamp"${lamp} aria-hidden="true"></i><time datetime="${date.toISOString()}"><span class="day">${date.toLocaleDateString(undefined, {month: 'short', day: 'numeric'})}</span><span class="clock">${date.toLocaleTimeString(undefined, {hour: '2-digit', minute: '2-digit'})}</span></time></div><div class="event-picture${event.shot ? '' : ' is-art'}">${picture}</div><div class="event-copy"><span class="event-label">${EVENT_LABELS[event.type] || 'FROM THE JOURNAL'}</span><h3>${esc(event.title)}</h3>${event.map && !String(event.title).toLowerCase().includes(String(event.map).toLowerCase()) ? `<span class="event-where">${esc(event.map)}</span>` : ''}</div><span class="event-go" aria-hidden="true">↗</span></a>`
  }).join('') || '<div class="journal-empty"><p class="micro">Nothing logged yet</p><h3>The best pages are still unwritten.</h3><p>New moments will find their way here as the adventure unfolds.</p></div>'
  set('#load-more', 'hidden', !moreAvailable || !eventRows.length)
}

async function refreshEvents(append = false) {
  if (!$('#events')) return
  if (eventBusy) return
  eventBusy = true
  const generation = eventGeneration
  const params = new URLSearchParams({limit: '8'})
  if (eventFilter === 'all') params.set('all', '1')
  if (eventFilter === 'team') {
    params.set('types', 'catch,evolve,obtain,level,trade')
    params.set('all', '1')
  }
  if (append && eventRows.length) params.set('before', String(eventRows.at(-1).id))
  try {
    const response = await PokeSim.fetch(`/api/events?${params}`)
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

if ($('#pause')) $('#pause').onclick = (event) => control(event.currentTarget, paused && !manualMode ? 'take_control' : 'pause')
if ($('#take-control')) $('#take-control').onclick = (event) => control(event.currentTarget, manualMode ? 'resume' : 'take_control')
if ($('#save')) $('#save').onclick = (event) => control(event.currentTarget, 'save', undefined, 'Save requested. A little moment to come back to.')
if ($('#restart')) $('#restart').onclick = (event) => {
  if (confirm('Start a fresh adventure from the beginning? Your event journal will be kept.')) control(event.currentTarget, 'restart', undefined, 'A new adventure is starting.')
}
if ($('.controller')) $('.controller').onclick = (event) => {
  const button = event.target.closest('[data-b]')
  if (button) manualPress(button.dataset.b)
}
if ($('#fullscreen')) $('#fullscreen').onclick = async () => {
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
    set('#events', 'innerHTML', '<p class="journal-empty">Turning the page…</p>')
    set('#load-more', 'hidden', true)
    refreshEvents()
  }
})
if ($('#load-more')) $('#load-more').onclick = () => refreshEvents(true)
async function manualPress(button) {
  try {
    await post('press', button)
    manualMode = true
    paused = true
    set('#take-control', 'textContent', 'Let AI play')
    set('#control-mode', 'textContent', 'You’re playing · AI paused')
    $('.game-card')?.classList.add('is-manual')
  } catch (error) { toast(error.message, true) }
}
let lastKeyPress = 0
window.addEventListener('keydown', (event) => {
  if (viewerOnly || !$('#screen') || $('#partner-detail')?.open) return
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
setInterval(() => { if (!document.hidden) refreshState() }, 2000)
setInterval(() => { if (!document.hidden) refreshEvents() }, 15000)

function renderIntent(strategy) {
  // Side by side in the plan row, a next step identical to the current one just reads as an echo.
  const next = strategy.next?.title
  const repeated = Boolean(next) && next === (shownObjective?.title || strategy.objective?.title)
  set('#next-objective', 'textContent', repeated ? 'Still on this one' : next || 'Continue the journey')
}

function renderPartnerDetail() {
  const dialog = $('#partner-detail')
  if (!dialog?.open || !selectedPartner) return
  const mon = currentParty[selectedPartner.index]
  if (!mon || mon.species !== selectedPartner.species || mon.nick !== selectedPartner.nick) {
    dialog.close()
    return
  }
  const name = mon.nick || mon.name
  const xp = mon.experience
  const moves = (mon.move_details || []).map((move) => `<div class="move"><span class="nm">${esc(move.name)}</span><span class="pp${move.pp ? '' : ' empty'}">${move.pp}/${move.max_pp} PP</span></div>`).join('')
  const stats = Object.entries(mon.stats || {}).map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${fmt(value)}</dd></div>`).join('')
  const portrait = mon.dex ? `<img src="${PokeSim.base}/sprites/${Number(mon.dex)}.png" alt="">` : '<span class="plate-num">?</span>'
  set('#partner-detail-content', 'innerHTML', `<div class="partner-detail-head"><div class="plate plate--bay">${portrait}</div><p class="micro">Partner ${selectedPartner.index + 1} · Level ${mon.level}</p><h2 id="partner-detail-heading">${esc(name)}</h2><p>${esc(mon.name)} · ${mon.hp} / ${mon.max_hp} HP · ${esc(mon.status_label || (mon.hp ? 'Healthy' : 'Fainted'))}</p></div><section><h3 class="micro">Moves</h3><div class="moves">${moves || '<p class="no-moves">No moves yet.</p>'}</div></section><section><h3 class="micro">Battle stats</h3><dl class="battle-stats">${stats}</dl>${xp ? `<p class="total-xp">${fmt(xp.total)} total experience · ${xp.max_level ? 'MAX LEVEL' : `${fmt(xp.remaining)} XP to Lv. ${mon.level + 1}`}</p>` : ''}</section>`)
  fitSprites($('#partner-detail-content'))
}
$('#party')?.addEventListener('click', (event) => {
  const button = event.target.closest('[data-partner]')
  if (!button) return
  const index = Number(button.dataset.partner)
  const mon = currentParty[index]
  selectedPartner = {index, species: mon.species, nick: mon.nick}
  $('#partner-detail').showModal()
  renderPartnerDetail()
})
$('#partner-detail')?.addEventListener('close', () => {
  const index = selectedPartner?.index
  selectedPartner = null
  $(`[data-partner="${index}"]`)?.focus()
})
