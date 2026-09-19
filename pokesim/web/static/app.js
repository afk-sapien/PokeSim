if (location.pathname === '/' && location.hash === '#journal') location.replace('/journal')
const $ = (selector) => document.querySelector(selector)
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&': '&amp', '<': '&lt', '>': '&gt', '"': '&quot', "'": '&#39'}[char] + String.fromCharCode(59)))
function set(selector, property, value) {
  const element = $(selector)
  if (element) element[property] = value
}
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
  if (!$('#party')) return
  currentParty = party
  renderPartnerDetail()
  const signature = JSON.stringify(party)
  if (signature === partySignature || $('#party').contains(document.activeElement)) return
  partySignature = signature
  set('#party-count', 'textContent', `${party.length} / 6`)
  if (!party.length) {
    set('#party', 'innerHTML', '<li class="empty-party"><span aria-hidden="true">◌</span><h3>Every team starts somewhere.</h3><p>The first partner will appear here.</p></li>')
    return
  }
  $('#party').innerHTML = party.map((mon, index) => {
    const hp = clamp(mon.max_hp ? mon.hp / mon.max_hp * 100 : 0)
    const health = hp < 20 ? 'critical' : hp < 50 ? 'low' : 'healthy'
    const xp = mon.experience
    const name = mon.nick && mon.nick.toUpperCase() !== mon.name.toUpperCase() ? mon.nick : mon.name
    const typeNames = mon.type_names || []
    const types = typeNames.map((type) => `<span class="type-tag ${typeClass(type)}">${esc(type)}</span>`).join('')
    const dex = mon.dex ? `No. ${String(mon.dex).padStart(3, '0')}` : 'Partner'
    const status = mon.status_label || (mon.hp ? 'Healthy' : 'Fainted')
    const sprite = mon.dex ? `<img src="/sprites/${Number(mon.dex)}.png" alt="${esc(mon.name)} portrait" width="96" height="96">` : '<span class="unknown-sprite">?</span>'
    return `<li class="mon-card ${mon.hp ? '' : 'fainted'}"><div class="mon-main"><div class="sprite-stage ${typeClass(typeNames[0])}">${sprite}<span class="party-slot">${String(index + 1).padStart(2, '0')}</span></div><div class="mon-info"><div class="mon-title"><h3>${esc(name)}</h3><span class="level"><small>LV.</small> ${mon.level}</span></div><div class="mon-subtitle"><span>${dex}${name !== mon.name ? ` · ${esc(mon.name)}` : ''}</span>${types}${status !== 'Healthy' ? `<span class="condition">${esc(status)}</span>` : ''}</div><div class="meter-label"><span>HP <b class="${health}">${mon.hp > 0 ? '●' : '○'}</b></span><span><strong>${fmt(mon.hp)}</strong> / ${fmt(mon.max_hp)}</span></div><progress class="hp-meter ${health}" max="100" value="${hp}" aria-label="${esc(name)} health: ${mon.hp} of ${mon.max_hp}"></progress><div class="meter-label xp-label"><span>XP</span><span>${xp ? xp.max_level ? 'MAX LEVEL' : `${clamp(xp.percent)}%` : 'Unavailable'}</span></div><progress class="xp-meter" max="100" value="${clamp(xp?.percent)}" aria-label="${esc(name)} progress to next level"></progress></div></div><button class="partner-open" data-partner="${index}" aria-haspopup="dialog" aria-label="View ${esc(name)} moves and stats">Moves & stats <span aria-hidden="true">↗</span></button></li>`
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
    document.querySelectorAll('.controls, .manual-controls, .controller, #restart').forEach((element) => {
      element.hidden = viewerOnly
    })
    set('#app-version', 'textContent', `v${state.version || 'unknown'}`)
    const edition = state.strategy?.collection?.version
    if (edition) {
      $('#edition').textContent = `${edition.toUpperCase()} VERSION`
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
    set('#status', 'textContent', manualMode ? 'You’re in control' : paused ? 'Game frozen' : 'Adventure in progress')
    set('#pause', 'textContent', paused && !manualMode ? '▶ Unfreeze' : 'Ⅱ Freeze game')
    if ($('#speed') && document.activeElement !== $('#speed')) $('#speed').value = String(state.speed)
    const progress = state.progress
    set('#progress-state', 'textContent', paused ? 'Paused' : ({exploring: 'Exploring', making_progress: 'Making progress', recovering: 'Recovering'}[progress?.state] || 'Exploring'))
    const achievement = progress?.last_achievement
    const age = achievement?.age_seconds || 0
    const since = age < 60 ? 'just now' : age < 3600 ? `${Math.floor(age / 60)}m ago` : `${Math.floor(age / 3600)}h ago`
    set('#last-achievement', 'textContent', achievement ? `Last achievement: ${achievement.title} · ${since}` : 'Waiting for the first achievement.')
    const strategy = state.strategy
    set('#strategy-panel', 'hidden', !strategy?.objective)
    renderIntent(strategy || {})
    if (strategy?.objective) {
      set('#objective', 'textContent', strategy.objective.title)
      set('#decision', 'textContent', strategy.reason)
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
    set('#dex-count', 'innerHTML', `${game.owned} <small>/ 151</small>`)
    set('#dex-count', 'title', `${game.seen} Pokémon seen`)
    set('#league-wins', 'textContent', fmt(state.league_rewards?.wins ?? game.hall_of_fame_count ?? 0))
    set('#money', 'textContent', `₽${fmt(game.money)}`)
    set('#areas', 'textContent', fmt(state.areas_discovered))
    const earned = game.badges || []
    set('#badge-count', 'textContent', `${earned.length} / 8`)
    set('#badges', 'innerHTML', BADGES.map((badge, i) => `<div class="badge ${earned.includes(badge) ? 'earned' : ''}" title="${badge} Badge · ${LEADERS[i]} · ${earned.includes(badge) ? 'Earned' : 'Still ahead'}"><span class="badge-icon badge-${i}" aria-hidden="true">${BADGE_SYMBOLS[i]}</span><span>${badge}</span><small>${earned.includes(badge) ? 'EARNED' : String(i + 1).padStart(2, '0')}</small></div>`).join(''))
    renderParty(game.party)
  } catch (_) {
    set('#status', 'textContent', 'Reconnecting…')
    $('#connection').classList.add('is-offline')
  } finally {
    stateBusy = false
  }
}

const EVENT_LABELS = {trade: 'A PARTNER FROM AFAR', badge: 'A BADGE TO REMEMBER', catch: 'A NEW FRIEND', evolve: 'GROWING TOGETHER', obtain: 'A NEW COMPANION', map: 'SOMEWHERE NEW', level: 'A LITTLE STRONGER', blackout: 'A FRESH START', champion: 'HALL OF FAME', item: 'A GOOD FIND', trainer: 'CHALLENGE ACCEPTED', seen: 'FIRST SIGHTING', playtime: 'TIME WELL SPENT'}
function renderEvents() {
  $('#events').innerHTML = eventRows.map((event) => {
    const date = new Date(event.ts * 1000)
    return `<a class="event-card event-${esc(event.type)}" href="/events/${event.id}"><div class="event-picture">${event.shot ? `<img loading="lazy" src="/shots/${encodeURIComponent(event.shot)}" alt="Game screen at ${esc(event.title)}" width="160" height="144">` : '<span aria-hidden="true">✧</span>'}<span class="event-label">${EVENT_LABELS[event.type] || 'FROM THE JOURNAL'}</span></div><div class="event-copy"><time datetime="${date.toISOString()}">${date.toLocaleDateString(undefined, {month: 'short', day: 'numeric'})} · ${date.toLocaleTimeString(undefined, {hour: '2-digit', minute: '2-digit'})}</time><h3>${esc(event.title)}</h3><p>${esc(event.map)}<span aria-hidden="true">↗</span></p></div></a>`
  }).join('') || '<div class="journal-empty"><span>✧</span><h3>The best pages are still unwritten.</h3><p>New moments will find their way here as the adventure unfolds.</p></div>'
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

if ($('#pause')) $('#pause').onclick = (event) => control(event.currentTarget, paused && !manualMode ? 'take_control' : 'pause')
if ($('#take-control')) $('#take-control').onclick = (event) => control(event.currentTarget, manualMode ? 'resume' : 'take_control')
if ($('#speed')) $('#speed').onchange = (event) => control(event.currentTarget, 'speed', Number(event.target.value))
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
  set('#next-objective', 'textContent', strategy.next?.title || 'Continue the journey')
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
  const moves = (mon.move_details || []).map((move) => `<div class="move"><span class="move-type ${typeClass(move.type)}" aria-hidden="true"></span><span>${esc(move.name)}</span><small class="${move.pp ? '' : 'depleted'}">${move.pp}/${move.max_pp} PP</small></div>`).join('')
  const stats = Object.entries(mon.stats || {}).map(([label, value]) => `<div><dt>${esc(label)}</dt><dd>${fmt(value)}</dd></div>`).join('')
  set('#partner-detail-content', 'innerHTML', `<div class="partner-detail-head">${mon.dex ? `<img src="/sprites/${Number(mon.dex)}.png" alt="" width="96" height="96">` : ''}<p class="eyebrow">PARTNER ${selectedPartner.index + 1} · LEVEL ${mon.level}</p><h2 id="partner-detail-heading">${esc(name)}</h2><p>${esc(mon.name)} · ${mon.hp} / ${mon.max_hp} HP · ${esc(mon.status_label || (mon.hp ? 'Healthy' : 'Fainted'))}</p></div><h3>Moves</h3><div class="moves">${moves || '<p>No moves yet.</p>'}</div><h3>Battle stats</h3><dl class="battle-stats">${stats}</dl>${xp ? `<p class="total-xp">${fmt(xp.total)} total experience · ${xp.max_level ? 'MAX LEVEL' : `${fmt(xp.remaining)} XP to Lv. ${mon.level + 1}`}</p>` : ''}`)
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
