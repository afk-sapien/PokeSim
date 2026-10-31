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
    ? `<img loading="lazy" src="${PokeSim.sprite(side.dex, Boolean(side.shiny))}" alt="${esc(side.name || '')}" width="56" height="56">`
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
let speedBusy = false
let currentSpeed = 1
let shownObjective = null
let pendingObjective = null
let pendingSightings = 0
// Gold, Silver and Crystal name a goal by key and label, Red, Blue and Yellow by id and title.
function objectiveOf(strategy) {
  const objective = strategy?.objective
  const title = objective?.title || objective?.label
  return title ? {...objective, id: objective.id ?? objective.key, title} : null
}
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
let stoppedNow = false
// This person's role on the adventure. Without accounts everyone is the owner.
let role = 'owner'
let lease = null
let leaseEnforced = false
let stateBusy = false
let partySignature = ''
let currentParty = []
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

async function problem(response, fallback) {
  try {
    const data = await response.json()
    return typeof data.detail === 'string' ? data.detail : fallback
  } catch (_) { return fallback }
}

async function post(action, value) {
  if (viewerOnly) throw new Error("This instance is view-only.")
  const response = await PokeSim.fetch('/api/control', {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify({action, value})})
  if (!response.ok) throw new Error(await problem(response, 'That action could not be sent. Please try again.'))
  return response.json()
}

// With accounts, one person at a time plays by hand. The library keeps that control lease.
const holding = () => !leaseEnforced || Boolean(lease?.you_hold)
const canPress = () => !viewerOnly && role !== 'viewer' && holding()

async function refreshLease() {
  // A standalone game, or a library without accounts, has no lease. The library stamps the page when it has one.
  if (!PokeSim.base || !document.querySelector('meta[name="pokesim-lease"]')) return
  try {
    const response = await PokeSim.fetch('/api/lease', {cache: 'no-store'})
    if (!response.ok) throw new Error('Unavailable')
    const status = await response.json()
    if (status.you_hold && !lease?.you_hold) set('#manual-controls', 'open', true)
    lease = status
    leaseEnforced = Boolean(status.enforced)
  } catch (_) {
    // Keep the last answer through a brief outage rather than flashing the controls.
  }
}

async function leaseAction(button, action, userId) {
  releaseControls()
  if (button) button.disabled = true
  try {
    const response = await PokeSim.fetch('/api/lease', {method: 'POST', headers: {'content-type': 'application/json'},
      body: JSON.stringify(userId ? {action, user_id: userId} : {action})})
    if (!response.ok) throw new Error(await problem(response, 'Control could not change. Please try again.'))
    const status = await response.json()
    if (status.you_hold && !lease?.you_hold) set('#manual-controls', 'open', true)
    lease = status
    leaseEnforced = Boolean(status.enforced)
    if (action === 'request' && !status.you_hold) toast('You are in line. The person playing can hand control to you.')
    renderLease()
    await refreshState()
  } catch (error) {
    toast(error.message, true)
  } finally {
    if (button) button.disabled = false
  }
}

function renderLease() {
  window.pokesimHoldsControl = holding()
  const box = $('#lease')
  const status = leaseEnforced ? lease : null
  const manages = role === 'manager' || role === 'owner'
  if (box) box.hidden = !status || stoppedNow || (!status.holder && role !== 'owner')
  $('.controller')?.querySelectorAll('[data-b]').forEach((button) => { button.disabled = !holding() })
  const take = $('#take-control')
  if (take) {
    let action = ''
    let text = manualMode ? 'Let AI play' : 'Take control'
    if (status?.you_hold) [action, text] = ['release', status.end === 'pause' ? 'Stop playing' : 'Let AI play']
    else if (status?.holder) [action, text] = manages ? ['take', 'Take control back'] : status.queued ? ['release', 'Leave the line'] : ['request', 'Ask for control']
    else if (status) [action, text] = ['request', 'Take control']
    take.dataset.lease = action
    take.textContent = text
  }
  if (!status) return
  const holder = status.holder
  set('#lease-holder', 'textContent', status.you_hold
    ? `You have control. ${status.end === 'pause' ? 'The game stays paused when you stop.' : 'The AI plays again when you stop.'}`
    : holder ? `${holder.name} has control.${status.queued ? ' You are in line.' : ''}` : 'Nobody is playing by hand.')
  if (holder && !status.you_hold && !stoppedNow) set('#control-mode', 'textContent', `${holder.name} is playing. AI paused`)
  set('#lease-idle', 'hidden', !status.idle_warning)
  if (status.idle_warning) set('#lease-idle', 'textContent', `No buttons pressed for a while. Control ends in ${status.idle_ends_in} s unless you press one.`)
  const queue = $('#lease-queue')
  const decides = status.you_hold || manages
  const rows = decides ? (status.queue || []).filter((entry) => entry.id) : []
  if (queue) {
    queue.hidden = !rows.length
    const signature = JSON.stringify([rows, status.you_hold])
    if (queue.dataset.signature !== signature && !queue.contains(document.activeElement)) {
      queue.dataset.signature = signature
      queue.innerHTML = rows.map((entry) => `<li><span>${esc(entry.name)} asks for control</span>${status.you_hold ? `<button class="key" data-lease-action="handover" data-user="${esc(entry.id)}">Hand over</button>` : ''}<button class="key" data-lease-action="refuse" data-user="${esc(entry.id)}">Refuse</button></li>`).join('')
    }
  }
  set('#lease-end-field', 'hidden', role !== 'owner')
  const end = $('#lease-end')
  if (end && document.activeElement !== end) end.value = status.end || 'resume'
}

async function control(button, action, value, message) {
  releaseControls()
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
  globalThis.PartyPopup?.update(party)
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
    `<li class="mon mon--empty"><div class="mon-plate"><div class="plate plate--bay"><span class="plate-num">${slotNo(index)}</span></div></div><div class="mon-body">${title ? `<p class="micro">${title}</p>` : ''}<p>${note}</p></div></li>`
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
    mon = PokemonTypes.asEgg(mon)
    const hp = clamp(mon.max_hp ? mon.hp / mon.max_hp * 100 : 0)
    const health = hp < 20 ? 'crit' : hp < 50 ? 'warn' : 'ok'
    const xp = mon.experience
    const name = mon.nick && mon.nick.toUpperCase() !== mon.name.toUpperCase() ? mon.nick : mon.name
    const types = PokemonTypes.badges(mon.type_names)
    const dex = mon.dex ? `<span class="micro dexno">No.${String(mon.dex).padStart(3, '0')}</span>` : ''
    const status = mon.status_label || (mon.hp ? 'Healthy' : 'Fainted')
    const statusTag = status !== 'Healthy' && !mon.egg ? `<span class="tag ${mon.hp ? 'tag--warn' : 'tag--crit'}">${esc(status)}</span>` : ''
    const moveRows = (mon.move_details || []).map((move) => `<div class="move" title="${esc(move.name)}, ${esc(move.type || '')}, ${move.pp}/${move.max_pp} PP"><span class="nm">${esc(move.name)}</span><span class="pp${move.pp ? '' : ' empty'}">${move.pp}</span></div>`).join('')
    const rating = dvStars(mon.dvs)
    const dvLamps = rating ? `<span class="dv" title="DV rating ${rating} of 4" role="img" aria-label="DV rating ${rating} of 4">${Array.from({length: 4}, (_, i) => `<i class="lamp"${i < rating ? ' data-on="signal"' : ''}></i>`).join('')}</span>` : ''
    const sprite = mon.egg ? PokemonTypes.eggPlate : mon.dex ? `<img src="${PokeSim.sprite(mon.dex, Boolean(mon.shiny))}" alt="${esc(mon.name)} portrait">` : `<span class="plate-num">?</span>`
    const xpText = xp ? xp.max_level ? 'MAX' : `${Math.floor(clamp(xp.percent))}%` : '—'
    return `<li class="mon${mon.hp ? '' : ' mon--fainted'}"><div class="mon-plate"><div class="plate plate--bay ${PokemonTypes.portraitClass(mon.type_names)}">${sprite}</div></div><div class="mon-body"><div class="mon-head"><span class="slotno">${slotNo(index)}</span><h3 class="name">${esc(name)}</h3><span class="spacer"></span>${dvLamps}<span class="lv"><em>LV</em>${mon.level}</span><button class="mon-open" data-partner="${index}" aria-haspopup="dialog" aria-label="View ${esc(name)} details"><span aria-hidden="true">▶</span></button></div><div class="mon-id">${dex}<span class="micro">${esc(mon.name)}</span>${types}${PokemonTypes.shinyBadge(mon)}${statusTag}</div><div class="mon-lower"><div class="mon-meters"><div class="meter-row"><span class="micro">HP</span>${meter(hp, health, `${esc(name)} health: ${mon.hp} of ${mon.max_hp}`)}<span class="value">${fmt(mon.hp)}/${fmt(mon.max_hp)}</span></div><div class="meter-row"><span class="micro">XP</span>${meter(clamp(xp?.percent), 'signal', `${esc(name)} progress to next level`)}<span class="value">${xpText}</span></div></div><div class="mon-moves">${moveRows || '<p class="no-moves">No moves yet.</p>'}</div></div></div></li>`
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
    // A stopped adventure shows its last save read only, so it takes no controls either.
    const stopped = Boolean(state.stopped)
    stoppedNow = stopped
    role = ['viewer', 'player', 'manager', 'owner'].includes(state.role) ? state.role : 'owner'
    // A player's page is view-only for everything except playing by hand.
    viewerOnly = (Boolean(state.viewer_only) && role !== 'player') || stopped
    const manages = role === 'manager' || role === 'owner'
    $('.game-card')?.classList.toggle('is-stopped', stopped)
    document.querySelectorAll('.controls > :not(#sound):not(#sound-status), .manual-controls, .controller, #restart').forEach((element) => {
      element.hidden = viewerOnly
    })
    for (const selector of ['#take-control', '.manual-controls', '.controller']) set(selector, 'hidden', viewerOnly || role === 'viewer')
    for (const selector of ['#pause', '#save', '.controls > .live-speed']) set(selector, 'hidden', viewerOnly || !manages)
    set('#restart', 'hidden', viewerOnly || role !== 'owner')
    await refreshLease()
    set('#app-version', 'textContent', `v${state.version || 'unknown'}${state.build?.revision ? ` (${String(state.build.revision).slice(0, 7)})` : ''}`)
    const edition = state.strategy?.collection?.version
    if (edition) {
      set('.screen-corner', 'textContent', `Pokémon ${edition[0].toUpperCase()}${edition.slice(1)}`)
      set('#stream', 'alt', `Live Pokémon ${edition} game`)
    }
    const game = state.game
    paused = state.paused
    if (state.manual_mode && !manualMode) {
      set('#manual-controls', 'open', true)
    }
    manualMode = state.manual_mode
    $('.game-card')?.classList.toggle('is-manual', manualMode)
    // The bezel's power LED is lit while the game runs and dark while it is paused.
    $('.game-card')?.classList.toggle('is-paused', Boolean(paused) && !manualMode)
    set('#on-air-label', 'textContent', stopped ? 'Stopped' : manualMode ? 'Manual' : paused ? 'Paused' : 'Live')
    set('#control-mode', 'textContent', stopped ? 'Showing the last save' : manualMode ? 'You’re playing. AI paused' : paused ? 'Game paused' : 'AI is playing')
    renderLease()
    $('#connection').classList.toggle('is-paused', paused)
    $('#connection').classList.remove('is-offline')
    set('#status', 'textContent', stopped ? 'Stopped' : manualMode ? 'In control' : paused ? 'Paused' : 'Running')
    $('#connection').title = stopped ? 'Adventure stopped. Start it from the library.' : manualMode ? 'You’re in control' : paused ? 'Game paused' : 'Adventure in progress'
    set('#pause', 'textContent', paused && !manualMode ? 'Resume' : 'Pause')
    set('#pause', 'title', paused && !manualMode ? 'Resume AI play' : 'Pause the game and AI')
    const speedSelect = $('#simulation-speed')
    if (speedSelect && !speedBusy && Number.isFinite(state.speed)) {
      currentSpeed = state.speed
      if (![...speedSelect.options].some(option => Number(option.value) === currentSpeed)) {
        speedSelect.add(new Option(`${currentSpeed}×`, String(currentSpeed)))
      }
      speedSelect.value = String(currentSpeed)
    }
    const progress = state.progress
    const strategy = state.strategy
    const objective = objectiveOf(strategy)
    const planning = objective?.id === PLANNING
    set('#progress-state', 'textContent', paused ? 'Paused' : planning ? 'Choosing what is next' : ({exploring: 'Exploring', making_progress: 'Making progress', recovering: 'Recovering', waiting: 'Waiting', stalled: 'Stuck?'}[progress?.state] || 'Exploring'))
    const achievement = progress?.last_achievement
    const age = achievement?.age_seconds || 0
    const since = age < 60 ? 'just now' : age < 3600 ? `${Math.floor(age / 60)}m ago` : `${Math.floor(age / 3600)}h ago`
    set('#last-achievement', 'textContent', achievement ? `Last achievement: ${achievement.title}, ${since}` : 'Waiting for the first achievement.')
    set('#strategy-panel', 'hidden', !objective)
    renderIntent(strategy || {})
    const steady = steadyObjective(objective)
    if (steady) {
      set('#objective', 'textContent', steady.title)
      // The reason often repeats the objective word for word, which read as a
      // second copy of the heading. Show it only when it adds something.
      if (!planning) {
        const reason = String(strategy.reason || '').trim()
        const plain = (text) => String(text || '').toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim()
        const repeats = !reason || plain(reason) === plain(steady.title) || plain(reason).startsWith(plain(steady.title)) && plain(reason).length < plain(steady.title).length + 12
        set('#decision', 'textContent', repeats ? '' : reason)
        set('#decision', 'hidden', repeats)
      }
      // Actions are internal names like "shortcut: choose_move", so they read as words, and a comma keeps them apart from the tile count.
      const action = (strategy.action || '').replace(/_/g, ' ').replace(/^./, (letter) => letter.toUpperCase())
      set('#action-tag', 'textContent', action)
      set('#progress', 'textContent', `${action ? ', ' : ''}${fmt(strategy.visited_tiles)} tiles explored`)
    }
    if (!game) return
    set('#live-heading', 'textContent', game.map_name)
    set('#coordinates', 'textContent', `${game.x}, ${game.y}`)
    set('#game-activity', 'textContent', manualMode ? 'Your adventure. Your next move.' : paused ? game.enemy_shiny ? '★ Shiny encounter paused. Take control to choose what happens next.' : 'A moment to take it all in.' : game.in_battle ? game.opponent ? `Trainer battle, ${game.opponent}` : `Wild encounter${game.enemy_shiny ? ', ★ Shiny' : ''}, ${game.enemy || 'Pokémon'}, Lv. ${game.enemy_level}` : game.textbox ? 'A conversation along the way.' : game.start_menu ? 'Checking the essentials.' : 'Onward to the next little discovery.')
    const clock = state.play_clock
    const time = clock?.display || game.playtime
    set('#playtime', 'textContent', time.split(':').slice(0, 2).map((v) => v.padStart(2, '0')).join(':') + (clock?.lower_bound ? '+' : ''))
    set('#playtime', 'title', clock?.lower_bound ? 'At least this much simulated playtime. The cartridge had already reached its limit when app tracking began.' : 'Simulated playtime tracked by the app. Pauses and server downtime are excluded.')
    set('#clock-note', 'textContent', clock?.lower_bound ? 'Earlier time hit the game limit' : '')
    // Gold, Silver and Crystal keep a cartridge clock that decides what appears and when. It runs on
    // game time, so it moves at the simulation's speed. Gen I has none and the slot stays hidden.
    const cartridge = state.clock
    set('#game-clock', 'hidden', !cartridge)
    if (cartridge) {
      const day = cartridge.weekday.slice(0, 3)
      const shown = `${String(cartridge.hour).padStart(2, '0')}:${String(cartridge.minute).padStart(2, '0')}`
      set('#game-clock-day', 'textContent', day)
      set('#game-clock-time', 'textContent', shown)
      set('#game-clock-period', 'textContent', cartridge.period || '')
      // A phone shows the game's own short words (MORN, DAY, NITE) so the place name keeps its room.
      const period = $('#game-clock-period')
      if (period) period.dataset.short = ({ Morning: 'Morn', Night: 'Nite' })[cartridge.period] || cartridge.period || ''
      set('#game-clock', 'title', `In-game clock: ${cartridge.weekday} ${shown}, ${cartridge.period}. It runs on game time, so it moves at the simulation's speed.`)
    }
    set('#trainer-name', 'textContent', game.player_name || 'A new trainer')
    set('#randomizer-code', 'hidden', !state.randomizer)
    if (state.randomizer && !$('#randomizer-code').dataset.copied) set('#randomizer-code', 'textContent', state.randomizer.code)
    set('#trainer-rival', 'textContent', game.rival_name ? `Trainer, rival ${game.rival_name}` : 'Trainer, a new story begins')
    set('#dex-count', 'innerHTML', `${fmt(game.owned)}<span class="unit">/${game.dex_total || 151}</span>`)
    set('#dex-count', 'title', `${game.seen} Pokémon seen`)
    set('#league-wins', 'textContent', fmt(state.league_rewards?.wins ?? game.hall_of_fame_count ?? 0))
    set('#money', 'textContent', `₽${fmt(game.money)}`)
    set('#areas', 'textContent', fmt(state.areas_discovered))
    const earned = game.badges || []
    set('#badge-count', 'textContent', `${earned.length} / ${game.badge_total || 8}`)
    const badgeNames = game.generation === 2 ? ['Zephyr', 'Hive', 'Plain', 'Fog', 'Mineral', 'Storm', 'Glacier', 'Rising', ...BADGES] : BADGES
    const leaderNames = game.generation === 2 ? ['Falkner', 'Bugsy', 'Whitney', 'Morty', 'Jasmine', 'Chuck', 'Pryce', 'Clair', 'Brock', 'Misty', 'Lt. Surge', 'Erika', 'Janine', 'Sabrina', 'Blaine', 'Blue'] : LEADERS
    set('#badges', 'innerHTML', badgeNames.map((badge, i) => `<i class="lamp"${earned.includes(badge) ? ' data-on="signal"' : ''} role="img" aria-label="${badge} Badge, ${earned.includes(badge) ? 'earned' : 'still ahead'}" title="${badge} Badge, ${leaderNames[i]}, ${earned.includes(badge) ? 'Earned' : 'Still ahead'}"></i>`).join(''))
    renderParty(game.party)
  } catch (_) {
    set('#status', 'textContent', 'Reconnecting…')
    $('#connection').title = ''
    $('#connection').classList.add('is-offline')
  } finally {
    stateBusy = false
  }
}

const EVENT_LABELS = {trade: 'Trade', badge: 'Badge', catch: 'Caught', evolve: 'Evolved', obtain: 'New Pokémon', hatch: 'Hatched', map: 'New place', level: 'Level up', blackout: 'Blacked out', champion: 'Hall of Fame', item: 'Item', trainer: 'Trainer battle', seen: 'First sighting', playtime: 'Playtime'}
// Each entry's lamp says what kind of moment it was, so the log can be skimmed by colour
// as well as read: milestones in signal, the team in green, a blackout in red.
const EVENT_LAMPS = {badge: 'signal', champion: 'signal', catch: 'ok', obtain: 'ok', trade: 'ok', evolve: 'ok', level: 'ok', blackout: 'crit', trainer: 'warn'}
function renderEvents() {
  $('#events').innerHTML = eventRows.map((event) => {
    const date = new Date(event.ts * 1000)
    const lamp = EVENT_LAMPS[event.type] ? ` data-on="${EVENT_LAMPS[event.type]}"` : ''
    // A catch, hatch or evolution is usually logged mid-cutscene, while the screen is black or
    // showing a dialog, so the Pokemon it is about says more than its screenshot does.
    const species = event.species_dex
      ? `<span class="species-art"><img loading="lazy" src="${PokeSim.sprite(event.species_dex)}" alt="" width="56" height="56"></span>`
      : ''
    const art = species || tradeArt(event)
    const picture = art || (event.shot
      ? `<img loading="lazy" src="${PokeSim.base}/shots/${encodeURIComponent(event.shot)}" alt="Game screen at ${esc(event.title)}" width="160" height="144">`
      : '<span class="no-frame">No screen kept</span>')
    return `<a class="event-card event-${esc(event.type)}" href="${PokeSim.base}/events/${event.id}"><div class="event-time"><i class="lamp"${lamp} aria-hidden="true"></i><time datetime="${date.toISOString()}"><span class="day">${date.toLocaleDateString(undefined, {month: 'short', day: 'numeric'})}</span><span class="clock">${date.toLocaleTimeString(undefined, {hour: '2-digit', minute: '2-digit'})}</span></time></div><div class="event-picture${art || !event.shot ? ' is-art' : ''}">${picture}</div><div class="event-copy"><span class="event-label">${EVENT_LABELS[event.type] || 'Journal'}</span><h3>${esc(event.title)}</h3>${event.map && !String(event.title).toLowerCase().includes(String(event.map).toLowerCase()) ? `<span class="event-where">${esc(event.map)}</span>` : ''}</div></a>`
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

if ($('#pause')) $('#pause').onclick = (event) => control(event.currentTarget, paused && !manualMode ? 'resume' : 'pause')
if ($('#take-control')) $('#take-control').onclick = (event) => {
  // A press before the first lease answer still asks the library, so it never skips the lease.
  const early = !lease && PokeSim.base && document.querySelector('meta[name="pokesim-lease"]')
  const action = event.currentTarget.dataset.lease || (early ? 'request' : '')
  if (action) return leaseAction(event.currentTarget, action)
  control(event.currentTarget, manualMode ? 'resume' : 'take_control')
}
$('#lease-queue')?.addEventListener('click', (event) => {
  const button = event.target.closest('[data-lease-action]')
  if (button) leaseAction(button, button.dataset.leaseAction, button.dataset.user)
})
if ($('#lease-end')) $('#lease-end').onchange = async (event) => {
  const select = event.currentTarget
  select.disabled = true
  try {
    const response = await PokeSim.fetch('/api/lease', {method: 'POST', headers: {'content-type': 'application/json'},
      body: JSON.stringify({action: 'setting', end: select.value})})
    if (!response.ok) throw new Error(await problem(response, 'That choice could not be saved. Please try again.'))
    lease = await response.json()
    toast(lease.end === 'pause' ? 'The game will stay paused when someone stops playing.' : 'The AI will play again when someone stops playing.')
  } catch (error) {
    toast(error.message, true)
  } finally {
    select.disabled = false
    renderLease()
  }
}
// The library ends a lease whose page goes quiet, so a holding page checks in.
setInterval(() => {
  if (!leaseEnforced || !lease?.you_hold) return
  PokeSim.fetch('/api/lease', {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify({action: 'heartbeat'})})
    .catch(() => {})
}, 15000)
if ($('#save')) $('#save').onclick = (event) => control(event.currentTarget, 'save', undefined, 'Checkpoint save requested. Progress also saves automatically.')
if ($('#simulation-speed')) $('#simulation-speed').onchange = async (event) => {
  const select = event.currentTarget
  const speed = Number(select.value)
  speedBusy = true
  select.disabled = true
  try {
    if (viewerOnly) throw new Error('This instance is view-only.')
    const response = await PokeSim.setSpeed(speed)
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Could not change the simulation speed.')
    currentSpeed = speed
    toast(data.pace_pending ? 'Speed saved. It will apply when this adventure reconnects.'
      : `Simulation speed set to ${speed === 0 ? 'Max' : `${speed}×`}.`)
  } catch (error) {
    select.value = String(currentSpeed)
    toast(error.message, true)
  } finally {
    speedBusy = false
    select.disabled = false
  }
}
if ($('#export-save')) $('#export-save').onclick = async (event) => {
  const button = event.currentTarget
  button.disabled = true
  button.textContent = 'Preparing…'
  try {
    const response = await PokeSim.fetch('/api/export-save', {method: 'POST'})
    if (!response.ok) {
      const error = await response.json()
      throw new Error(error.detail || 'The save could not be exported. Please try again.')
    }
    const url = URL.createObjectURL(await response.blob())
    const link = document.createElement('a')
    link.href = url
    link.download = response.headers.get('Content-Disposition')?.match(/filename="([^"]+)"/)?.[1] || 'pokesim.sav'
    document.body.append(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 60000)
    toast('Save downloaded. Load it with the matching game ROM in your emulator.')
  } catch (error) {
    toast(error.message, true)
  } finally {
    button.disabled = false
    button.textContent = 'Download .sav'
  }
}
let viewLinkTimer = 0
if ($('#copy-view-link')) $('#copy-view-link').onclick = async (event) => {
  const button = event.currentTarget
  const link = new URL(button.dataset.viewLink, location.origin).href
  try {
    await navigator.clipboard.writeText(link)
    // A small "Copied" note under the rail key, also read out as a status.
    const note = button.querySelector('.rail-key-note')
    button.dataset.copied = ''
    if (note) note.textContent = 'Copied'
    clearTimeout(viewLinkTimer)
    viewLinkTimer = setTimeout(() => {
      delete button.dataset.copied
      if (note) note.textContent = ''
    }, 1800)
  } catch (_) {
    window.prompt('Copy this view link. It shows this adventure without any controls.', link)
  }
}
if ($('#randomizer-code')) $('#randomizer-code').onclick = async (event) => {
  const button = event.currentTarget
  const code = button.textContent
  try {
    await navigator.clipboard.writeText(code)
    button.dataset.copied = ''
    button.textContent = 'Copied'
    setTimeout(() => {
      delete button.dataset.copied
      button.textContent = code
    }, 1800)
  } catch (_) {
    window.prompt('Copy this share code to play the same randomized world.', code)
  }
}
if ($('#restart')) $('#restart').onclick = (event) => {
  if (confirm('Start a fresh adventure from the beginning? Your event journal will be kept.')) control(event.currentTarget, 'restart', undefined, 'A new adventure is starting.')
}
const heldControls = new Map()
function releaseControls(pointerId) {
  for (const [id, held] of heldControls) {
    if (pointerId !== undefined && id !== pointerId) continue
    clearTimeout(held.timer)
    held.button.classList.remove('is-held')
    heldControls.delete(id)
  }
}
const controller = $('.controller')
if (controller) {
  controller.addEventListener('pointerdown', event => {
    const button = event.target.closest('[data-b]')
    if (!button || button.disabled || !canPress() || event.button !== 0) return
    event.preventDefault()
    releaseControls(event.pointerId)
    button.setPointerCapture(event.pointerId)
    const held = {button, timer: null}
    heldControls.set(event.pointerId, held)
    button.classList.add('is-held')
    const repeat = async () => {
      if (heldControls.get(event.pointerId) !== held || !canPress() || document.hidden) return
      const ok = await manualPress(button.dataset.b)
      if (!ok) return releaseControls(event.pointerId)
      if (heldControls.get(event.pointerId) === held && !['start', 'select'].includes(button.dataset.b)) {
        held.timer = setTimeout(repeat, 150)
      }
    }
    repeat()
  })
  for (const name of ['pointerup', 'pointercancel', 'lostpointercapture']) {
    controller.addEventListener(name, event => releaseControls(event.pointerId))
  }
  controller.addEventListener('contextmenu', event => event.preventDefault())
  // Keyboard and assistive activation produce a click without a pointing device.
  controller.addEventListener('click', event => {
    const button = event.target.closest('[data-b]')
    if (button && event.detail === 0 && canPress()) manualPress(button.dataset.b)
  })
}
window.addEventListener('blur', () => releaseControls())
window.addEventListener('pagehide', () => releaseControls())
document.addEventListener('visibilitychange', () => { if (document.hidden) releaseControls() })
for (const button of document.querySelectorAll('#take-control, #pause, #restart')) {
  button.addEventListener('pointerdown', () => releaseControls())
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
    if (!leaseEnforced) set('#take-control', 'textContent', 'Let AI play')
    set('#control-mode', 'textContent', 'You’re playing. AI paused')
    $('.game-card')?.classList.add('is-manual')
    return true
  } catch (error) { toast(error.message, true)
    return false }
}
let lastKeyPress = 0
window.addEventListener('keydown', (event) => {
  if (!canPress() || !$('#screen') || globalThis.PartyPopup?.isOpen()) return
  const map = {ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right', z: 'a', x: 'b', Z: 'a', X: 'b', Enter: 'start', Shift: 'select'}
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

// A party member opens the same detail popup as the PC page (party-popup.js).
$('#party')?.addEventListener('click', (event) => {
  const button = event.target.closest('[data-partner]')
  if (!button) return
  const index = Number(button.dataset.partner)
  globalThis.PartyPopup?.show(index, currentParty[index], () => $(`[data-partner="${index}"]`))
})
