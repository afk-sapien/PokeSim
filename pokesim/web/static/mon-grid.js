// The shared Pokémon grid: cards, filters, sorting, badges and the detail popup.
// The PC, Pokédex and Trading pages and the Live party popup draw their Pokémon with it.
(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp', '<': '&lt', '>': '&gt', '"': '&quot', "'": '&#39'}[char] + String.fromCharCode(59)))
  const base = () => globalThis.PokeSim?.base || ''
  const types = () => globalThis.PokemonTypes

  const SORTS = [['box', 'Location and slot'], ['battle_power', 'Battle Power'], ['power', 'Stat Power'],
    ['stat_total', 'Stat total'], ['level', 'Level'], ['HP', 'Max HP'], ['Attack', 'Attack'], ['Defense', 'Defense'],
    ['Speed', 'Speed'], ['Special', 'Special'], ['dv_stars', 'DV star rating'], ['dvs', 'Total DVs'],
    ['stat_exp', 'Total stat experience'], ['experience', 'Total experience'], ['dex', 'Pokédex number'],
    ['name', 'Species name'], ['nick', 'Nickname']]
  const RATINGS = [['all', 'All ratings'], ['shiny', '★ Shiny partners'], ['3plus', '3★ and better'], ['4', '4★ Perfect'],
    ['3', '3★'], ['2', '2★'], ['1', '1★'], ['unknown', 'Unknown DVs']]
  // Every Pokémon can be traded unless it is locked. Protected means shiny or perfect DVs.
  const SETTINGS = [['all', 'All Pokémon'], ['auto', 'Can trade'], ['keep', 'Locked'], ['protected', 'Protected']]
  const SETTING_LABELS = {auto: 'Can trade', first: 'Can trade', keep: 'Locked', protected: 'Protected'}
  const sortDefaults = {box: 'asc', battle_power: 'desc', power: 'desc', stat_total: 'desc', level: 'desc', HP: 'desc', Attack: 'desc', Defense: 'desc', Speed: 'desc', Special: 'desc', 'Special Attack': 'desc', 'Special Defense': 'desc', dv_stars: 'desc', dvs: 'desc', stat_exp: 'desc', experience: 'desc', dex: 'asc', name: 'asc', nick: 'asc'}

  function statTotal(mon, field) {
    const values = mon[field]
    return Array.isArray(values) && values.length === 5 && values.every(Number.isFinite)
      ? values.reduce((sum, value) => sum + value, 0) : null
  }

  function sortValue(mon, field) {
    if (field === 'dvs' || field === 'stat_exp') return statTotal(mon, field)
    if (['HP', 'Attack', 'Defense', 'Speed', 'Special', 'Special Attack', 'Special Defense'].includes(field)) return mon.calculated_stats?.[field] ?? null
    if (field === 'experience') return mon.experience?.total ?? mon.experience ?? null
    if (field === 'box') return mon.box * 20 + (mon.position || 0)
    if (field === 'nick') return mon.nick || mon.name || ''
    if (field === 'name') return mon.name || ''
    return Number.isFinite(mon[field]) ? mon[field] : null
  }

  function compare(a, b, field, order) {
    const left = sortValue(a, field)
    const right = sortValue(b, field)
    // Unavailable individual stats stay last in either direction.
    if (left === null && right !== null) return 1
    if (right === null && left !== null) return -1
    const comparison = typeof left === 'string'
      ? left.localeCompare(right, undefined, {sensitivity: 'base', numeric: true})
      : (left ?? 0) - (right ?? 0)
    const ratingTie = field === 'dv_stars' && left !== null && right !== null
      ? ((a.dv_total ?? 0) - (b.dv_total ?? 0)) * (order === 'desc' ? -1 : 1) : 0
    return comparison * (order === 'desc' ? -1 : 1) || ratingTie || a.box - b.box || (a.position || 0) - (b.position || 0)
  }

  function formatTotal(mon, field) {
    const total = statTotal(mon, field)
    return total === null ? 'Unavailable' : total.toLocaleString()
  }

  function ratingLabel(mon) {
    return Number.isInteger(mon.dv_stars) && mon.dv_stars >= 1 && mon.dv_stars <= 4
      ? `${mon.dv_stars}-star DVs` : 'DV rating unavailable'
  }

  // Four lamps, lit to the star count. The stars stay in the text for copy and search.
  function ratingBadge(mon) {
    if (!Number.isInteger(mon.dv_stars) || mon.dv_stars < 1 || mon.dv_stars > 4) return '<span class="dv-badge dv-unknown">DVs unknown</span>'
    const lamps = Array.from({length: 4}, (_, i) => `<i class="lamp"${i < mon.dv_stars ? ' data-on="signal"' : ''}></i>`).join('')
    const title = Number.isFinite(mon.dv_total) ? ` title="${mon.dv_total} / 75 DVs, ${mon.dv_percent}%"` : ''
    return `<span class="dv-badge dv-stars-${mon.dv_stars}" aria-label="${ratingLabel(mon)}"${title}><span class="dv" aria-hidden="true">${lamps}</span><span class="vh">${'★'.repeat(mon.dv_stars)}${'☆'.repeat(4 - mon.dv_stars)}</span> ${mon.dv_stars === 4 ? 'Perfect DV' : 'DV'}</span>`
  }

  // The small trade setting stamp on a card. Only a lock is worth a stamp: every other
  // Pokémon may be traded automatically within the built-in rules.
  function settingBadge(state) {
    const label = SETTING_LABELS[state]
    return state === 'keep' || state === 'protected' ? `<span class="tag trade-tag trade-tag--${state}" title="${state === 'keep' ? 'Locked: never traded automatically' : 'Protected from automatic trading'}">${label}</span>` : ''
  }

  // ---- locks: a locked Pokémon is never traded automatically. Set on the PC page. ----
  const isLocked = mon => Boolean(mon && (mon.trade_setting === 'keep' || mon.trade_locked))
  const isProtected = mon => Boolean(mon && (mon.shiny || mon.perfect_dvs))
  // A pixel padlock drawn on a 12 by 12 grid, shut or open.
  function lockIcon(locked = true, extra = '') {
    const shackle = locked ? 'M3 1h6v1H3zM2 2h1v3H2zM9 2h1v3H9z' : 'M3 0h6v1H3zM2 1h1v4H2zM9 1h1v2H9z'
    return `<svg class="lock-icon${extra ? ' ' + extra : ''}" viewBox="0 0 12 12" width="12" height="12" aria-hidden="true" focusable="false" shape-rendering="crispEdges"><path fill="currentColor" fill-rule="evenodd" d="${shackle}M1 5h10v6H1zM5 7v2h2V7z"/></svg>`
  }
  // Why a Pokémon cannot be locked or unlocked from here, or '' when it can.
  function lockBlocked(mon, options = {}) {
    if (mon.egg) return 'Eggs are never traded automatically.'
    if (!mon.trade_key) return 'This Pokémon cannot be traded.'
    if (mon.trade_ambiguous) return 'An identical copy shares this Pokémon’s record, so it cannot be locked on its own.'
    if (options.viewer) return 'Only the owner can lock Pokémon.'
    if (options.stale) return 'Waiting for the PC to update.'
    return ''
  }
  // The lock toggle for the popup. Its face is the state: a shut padlock and Locked, or an open
  // padlock and Tradeable. A press flips it. Options: busy (a change is saving), viewer, stale and
  // note (a refused change to show under it). Why it cannot be pressed goes in its title.
  function lockControl(mon, options = {}) {
    if (!mon || mon.egg) return ''
    if (isProtected(mon)) return `<div class="pc-lock-row"><span class="tag trade-tag trade-tag--protected lock-stamp" title="${mon.shiny ? 'Shiny' : 'Perfect DV'} Pokémon are never traded automatically">${lockIcon(true)}Protected</span></div>`
    const locked = isLocked(mon)
    const blocked = lockBlocked(mon, options)
    const label = locked ? 'Locked' : 'Tradeable'
    const title = blocked || (locked ? 'Locked: never traded automatically. Press to unlock.' : 'Tradeable: may be traded automatically. Press to lock.')
    const why = blocked ? `<span class="vh">, ${esc(blocked)}</span>` : ''
    return `<div class="pc-lock-row"><button type="button" class="lock-toggle" data-lock-key="${esc(mon.trade_key || '')}" data-locked="${locked ? 'true' : 'false'}"${blocked || options.busy ? ' disabled' : ''}${options.busy ? ' aria-busy="true"' : ''} title="${esc(title)}">${lockIcon(locked)}<span>${label}</span>${why}</button>${options.note ? `<p class="lock-note" role="status">${esc(options.note)}</p>` : ''}</div>`
  }
  // Save a lock ('keep') or an unlock ('auto'). A refused change throws with the server's reason.
  async function saveLock(key, state) {
    const response = await globalThis.PokeSim.fetch('/api/trading/preferences', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({key, state})})
    if (response.ok) return
    let reason = ''
    try { reason = (await response.json()).detail } catch (_) {}
    throw new Error(typeof reason === 'string' && reason ? reason : 'Could not save the lock.')
  }
  // Everything about trading lives on the Trading page. The popup only links there.
  function tradeLink(mon) {
    if (!mon?.trade_key || mon.egg) return ''
    return `<a class="key pc-trade-link" href="${base()}/trading?tab=trade&mon=${encodeURIComponent(mon.trade_key)}">Trade…</a>`
  }

  // Search by name, nickname or Pokédex number, and by DV rating.
  function matches(mon, search, rating = 'all') {
    const text = String(search || '').trim().toLowerCase()
    const query = text.replace(/^#/, '')
    const rated = rating === 'all' || (rating === 'shiny' ? mon.shiny : rating === 'unknown' ? mon.dv_stars == null
      : rating === '3plus' ? mon.dv_stars >= 3 : mon.dv_stars === Number(rating))
    return rated && (!query || `${mon.nick} ${mon.name}`.toLowerCase().includes(query) || String(mon.dex).padStart(3, '0').includes(query))
  }

  const sprite = (mon, url) => mon.egg ? types().eggPlate
    : `<img loading="lazy" src="${esc(url || (globalThis.PokeSim?.sprite ? globalThis.PokeSim.sprite(mon.dex) : `${base()}/sprites/${Number(mon.dex) || 0}.png?v=rom-portraits-1`))}" alt="">`
  const place = (mon, index) => `${mon.box === 0 ? 'Party' : `Box ${mon.box}`}, slot ${mon.position || index + 1}`

  // One card. Options: all (show the four metrics), sprite (a portrait address from another game),
  // attr (the data attribute naming the card), tags (extra stamps), blocked (why it cannot be picked),
  // pressed (the chosen card) and slot (a different location line).
  function card(mon, id, options = {}) {
    const attr = options.attr || 'mon'
    const blocked = options.blocked ? String(options.blocked) : ''
    const locked = options.locked ?? isLocked(mon)
    const level = Number.isFinite(mon.level) ? mon.level : null
    const label = `${esc(mon.nick || mon.name)}${level === null ? '' : `, level ${level}`}${mon.type_names?.length ? ', ' + esc(mon.type_names.join(' / ')) : ''}, ${mon.box === 0 ? 'party' : `box ${mon.box}`}${', ' + ratingLabel(mon)}${mon.shiny ? ', shiny, protected from release and trading' : ''}${mon.perfect_dvs ? ', perfect DVs, preserved for the collection' : ''}${locked ? ', locked, never traded automatically' : ''}${options.label ? ', ' + esc(options.label) : ''}${blocked ? `, cannot be picked: ${esc(blocked)}` : ''}`
    const classes = ['pc-mon', mon.perfect_dvs ? 'perfect-entry' : '', blocked ? 'is-blocked' : '', options.pressed ? 'is-chosen' : ''].filter(Boolean).join(' ')
    const state = [options.pressed !== undefined ? ` aria-pressed="${options.pressed ? 'true' : 'false'}"` : '', blocked ? ` aria-disabled="true" title="${esc(blocked)}"` : ''].join('')
    const metrics = options.all ? `<span class="pc-metrics"><span class="pc-power">Battle Power <b>${Number.isFinite(mon.battle_power) ? mon.battle_power.toLocaleString() : 'Unavailable'}</b></span><span>Stat Power <b>${Number.isFinite(mon.power) ? mon.power.toLocaleString() : 'Unavailable'}</b></span><span>Total DVs <b>${formatTotal(mon, 'dvs')}</b></span><span>Stat exp. <b>${formatTotal(mon, 'stat_exp')}</b></span></span>` : ''
    const reason = blocked ? `<span class="pc-blocked">${esc(blocked)}</span>` : ''
    return `<button type="button" class="${classes}" data-${attr}="${esc(id)}"${state} aria-label="${label}"><span class="pc-slot">${esc(options.slot || place(mon, Number(id) || 0))}</span>${locked ? `<span class="pc-lock" title="Locked: never traded automatically">${lockIcon(true)}</span>` : ''}<span class="plate pc-plate ${types().portraitClass(mon.type_names)}">${sprite(mon, options.sprite)}</span><span class="pc-mon-body"><strong class="pc-name">${esc(mon.nick || mon.name)}</strong><small class="pc-sub">${esc(mon.name)}${level === null ? '' : `, Lv. ${level}`}</small><span class="type-tags">${types().badges(mon.type_names)}</span><span class="pc-tags">${types().shinyBadge(mon)}${ratingBadge(mon)}${options.tags || ''}</span>${reason}</span>${metrics}</button>`
  }

  // Gen I and II split physical and special by type. A move with no power is a status move.
  const SPECIAL_TYPES = new Set(['Fire', 'Water', 'Grass', 'Electric', 'Psychic', 'Ice', 'Dragon', 'Dark'])
  const moveCategory = move => !move.power ? 'Status' : SPECIAL_TYPES.has(move.type) ? 'Special' : 'Physical'
  const fmt = value => Number(value).toLocaleString()

  // Sixteen discrete cells, matching the live party meters. A sliver still lights one cell.
  function gauge(percent, level, label) {
    const value = Math.max(0, Math.min(100, Number(percent) || 0))
    const lit = value > 0 ? Math.max(1, Math.round(value / 100 * 16)) : 0
    return `<span class="meter" data-level="${level}" role="meter" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${Math.round(value)}" aria-label="${esc(label)}">${Array.from({length: 16}, (_, i) => `<i${i < lit ? ' class="on"' : ''}></i>`).join('')}</span>`
  }

  // Gen II sends progress as the experience itself. Gen I sends it beside the running total.
  function experienceProgress(mon) {
    if (mon.experience_progress && typeof mon.experience_progress === 'object') return mon.experience_progress
    return mon.experience && typeof mon.experience === 'object' ? mon.experience : null
  }

  // The trade stamp in the popup head: Protected or Locked, or nothing when it may trade.
  function tradeState(mon) {
    if (!mon.trade_key) return null
    if (isProtected(mon)) return {state: 'Protected', note: 'Never traded automatically'}
    return isLocked(mon) ? {state: 'Locked', note: 'Never traded automatically. Change it on the PC page'} : null
  }

  function tradeBadge(trade, mon) {
    if (!trade) return isProtected(mon) ? '<span class="tag trade-tag trade-tag--protected" title="Protected from automatic release and trading">Protected</span>' : ''
    const key = trade.state === 'Protected' ? 'protected' : 'keep'
    return `<span class="tag trade-tag trade-tag--${key}" title="${esc(trade.state)}${trade.note ? `. ${esc(trade.note)}` : ''}">${key === 'keep' ? lockIcon(true) : ''}${esc(trade.state)}</span>`
  }

  // One entry per move on two lines: the name and its type, then kind, power, accuracy and PP.
  // A Pokémon knows up to four moves, so unused slots show as blank lines and the card keeps its height.
  function moveList(mon) {
    const moves = mon.move_details || []
    if (!moves.length) return '<p class="detail-meta pc-card-empty">No moves recorded.</p>'
    const stat = (label, value, cls) => `<span class="pc-move-stat"><span class="pc-k">${label}</span> <b class="${cls}">${value}</b></span>`
    const rows = moves.map(original => {
      // Hidden Power takes its type and power from the DVs, not from the move table.
      const move = original.name === 'Hidden Power' && mon.hidden_power ? {...original, ...mon.hidden_power} : original
      const known = Number.isFinite(move.pp) && Number.isFinite(move.max_pp)
      const pp = known ? `<span class="pc-move-pp${move.pp ? '' : ' empty'}"><b>${move.pp}</b>/${move.max_pp}</span>` : '<span class="pc-move-pp pc-move-none">—</span>'
      const rated = Number.isFinite(move.power)
      const power = rated && move.power ? move.power : '—'
      const accuracy = rated && Number.isFinite(move.accuracy) && move.accuracy ? `${move.accuracy}%` : '—'
      return `<li class="pc-move"><span class="pc-move-name">${esc(move.name)}</span><span class="pc-move-type">${types().badges([move.type])}</span>`
        + `<span class="pc-move-specs"><span class="pc-move-kind">${rated ? moveCategory(move) : ''}</span>${stat('Pow', power, 'pc-move-pow')}${stat('Acc', accuracy, 'pc-move-acc')}</span>`
        + `<span class="pc-move-stat pc-move-ppcell"><span class="pc-k">PP</span> ${pp}</span></li>`
    }).join('')
    const blanks = '<li class="pc-move-blank" aria-hidden="true">—</li>'.repeat(Math.max(0, 4 - moves.length))
    return `<ol class="pc-moves">${rows}${blanks}</ol>`
  }

  // The summary strip: HP and XP meters, then the two power readings, as equal cells.
  function meterCell(label, percent, level, aria, value, title = '') {
    return `<div class="pc-sum pc-sum-meter"><div class="pc-sum-top"><span class="micro">${label}</span><span class="value"${title ? ` title="${title}"` : ''}>${value}</span></div>${gauge(percent, level, aria)}</div>`
  }

  function conditionRows(mon) {
    const rows = []
    if (Number.isFinite(mon.hp) && Number.isFinite(mon.max_hp) && mon.max_hp > 0) {
      const percent = mon.hp / mon.max_hp * 100
      rows.push(meterCell('HP', percent, percent < 20 ? 'crit' : percent < 50 ? 'warn' : 'ok', `Health: ${mon.hp} of ${mon.max_hp}`, `${fmt(mon.hp)}<span class="unit">/${fmt(mon.max_hp)}</span>`))
    }
    const xp = experienceProgress(mon)
    if (xp && Number.isFinite(xp.percent)) {
      const next = xp.max_level ? 'Max level' : Number.isFinite(xp.remaining) ? `${fmt(xp.remaining)} to Lv. ${mon.level + 1}` : ''
      rows.push(meterCell('XP', xp.percent, 'signal', `Progress to level ${mon.level + 1}`, xp.max_level ? 'MAX' : `${Math.round(xp.percent)}%`, next))
    }
    return rows.join('')
  }

  // Stat Power now against its ceiling: the same Pokémon at level 100 with full training.
  // At the ceiling it is one number.
  function statPower(mon) {
    if (!Number.isFinite(mon.power)) return 'Unavailable'
    if (!Number.isFinite(mon.potential_power)) return fmt(mon.power)
    if (mon.power >= mon.potential_power) return `${fmt(mon.power)} <span class="unit">(max)</span>`
    return `${fmt(mon.power)} <span class="unit">/ ${fmt(mon.potential_power)}</span>`
  }

  function readouts(mon) {
    const cells = [`<div class="pc-sum pc-readout" title="Stat Power now / at level 100 with full training"><dt class="micro">Stat Power</dt><dd>${statPower(mon)}</dd></div>`]
    if (mon.battle_power !== undefined) cells.push(`<div class="pc-sum pc-readout" title="Rates known moves at full health and PP. Matchups can change the result."><dt class="micro">Battle Power</dt><dd>${Number.isFinite(mon.battle_power) ? fmt(mon.battle_power) : 'Unavailable'}</dd></div>`)
    return `<dl class="pc-readouts">${cells.join('')}</dl>`
  }

  function eggFacts(mon) {
    const cycles = mon.egg_cycles
    return `<dl class="pc-facts"><div><dt>Hatches in</dt><dd>${Number.isFinite(cycles) ? `${fmt(cycles)} egg cycle${cycles === 1 ? '' : 's'}<small>About ${fmt(cycles * 256)} steps in the party</small>` : 'Unknown'}</dd></div></dl>`
  }

  // The stats guide and Pokédex keys, on their own so a page can put them in its footer.
  // A phone shows short labels without the arrows, so every footer key fits one row.
  // Options: dex (false leaves out the Pokédex key, for a popup already on the Pokédex).
  function detailLinks(mon, options = {}) {
    if (mon.egg) return ''
    return `<a class="dex-open key" aria-label="Stats guide" href="https://github.com/afk-sapien/PokeSim/blob/main/docs/pokemon-stats.md" target="_blank" rel="noopener noreferrer"><span class="key-long">Stats guide</span><span class="key-short">Guide</span></a>${mon.dex && options.dex !== false ? `<a class="dex-open key" href="${base()}/pokedex#${String(mon.dex).padStart(3, '0')}">Pokédex</a>` : ''}`
  }

  // The popup body. Options: sprite (a portrait address from another game), trade (replaces the
  // trade stamp, or false to leave it out), top (HTML shown under the head, such as a pick button)
  // and links (false hides the guide and Pokédex links).
  // Layout: a head (portrait, name, one line of facts, one row of stamps), a summary strip of four
  // equal cells, then Moves and Stats as two cards side by side, stacked on a phone.
  function detail(mon, options = {}) {
    const labels = Object.keys(mon.calculated_stats || {})
    const known = mon.dvs?.length === 5 && mon.stat_exp?.length === 5
    // Healthy is the usual state, so only a condition worth noticing gets a stamp.
    const status = mon.status_label || (Number.isFinite(mon.hp) && !mon.hp ? 'Fainted' : '')
    const statusTag = !mon.egg && status && status !== 'Healthy' ? `<span class="tag pc-status ${mon.hp ? 'tag--warn' : 'tag--crit'}">${esc(status)}</span>` : ''
    const trade = options.trade === false ? null : options.trade || tradeState(mon)
    const pokerus = mon.pokerus === 'infected' ? '<span class="tag tag--warn">Pokérus</span>' : mon.pokerus === 'cured' ? '<span class="tag" title="Pokérus, cured">Pokérus cured</span>' : ''
    const tags = mon.egg ? tradeBadge(trade, mon) : `${types().shinyBadge(mon)}${ratingBadge(mon)}${statusTag}${pokerus}${tradeBadge(trade, mon)}`
    const line = mon.egg ? 'Not yet hatched' : [esc(mon.name), `Level ${mon.level}`, mon.gender ? esc(mon.gender) : '', mon.held_item_name ? `Holding ${esc(mon.held_item_name)}` : ''].filter(Boolean).join(', ')
    const where = options.slot ? esc(options.slot) : `${mon.box === 0 ? 'Party' : `Box ${mon.box}`}, slot ${mon.position || '?'}`
    const head = `<div class="pc-detail-head"><div class="plate plate--bay ${types().portraitClass(mon.type_names)}">${sprite(mon, options.sprite).replace(' loading="lazy"', '')}</div>`
      + `<div class="pc-detail-id"><p class="micro">${where}${mon.dex ? `, No.${String(mon.dex).padStart(3, '0')}` : ''}</p><h2 id="pc-detail-name">${esc(mon.nick || mon.name)}</h2>`
      + `<p class="pc-detail-line">${line}</p></div><div class="pc-tags pc-detail-tags"><span class="type-tags">${types().badges(mon.type_names)}</span>${tags}</div></div>`
    const section = (title, body, extra = '') => `<section class="pc-detail-section${extra}"><h3 class="micro">${title}</h3>${body}</section>`
    const card = (name, title, note, body) => `<section class="pc-card pc-card-${name}"><header class="pc-card-head"><h3 class="micro">${title}</h3>${note}</header>${body}</section>`
    const links = options.links === false ? '' : `<div class="pc-detail-links">${detailLinks(mon)}</div>`
    const top = options.top || ''
    if (mon.egg) return head + top + section('Egg', eggFacts(mon)) + '<p class="detail-meta pc-detail-note">Its species, moves and stats appear once it hatches.</p>'
    const condition = conditionRows(mon)
    const quality = Number.isFinite(mon.dv_top_percent) ? `<span class="pc-card-note" title="Chance a random roll is at least this good">DVs top ${mon.dv_top_percent.toLocaleString(undefined, {maximumSignificantDigits: 3})}%</span>` : ''
    const count = mon.move_details?.length ? `<span class="pc-card-note">${mon.move_details.length} of 4</span>` : ''
    const stats = known ? `<table class="individual-stats"><caption class="vh">Stats</caption><thead><tr><th scope="col">Stat</th><th scope="col">Value</th><th scope="col">DV</th><th scope="col">Stat exp.</th></tr></thead><tbody>${labels.map((label, i) => `<tr><th scope="row">${label}</th><td>${mon.calculated_stats?.[label] ?? 'Unavailable'}</td><td>${mon.dvs[Math.min(i, 4)]}</td><td>${mon.stat_exp[Math.min(i, 4)].toLocaleString()}</td></tr>`).join('')}</tbody><tfoot><tr><th scope="row">Total</th><td>${Number.isFinite(mon.stat_total) ? mon.stat_total.toLocaleString() : 'Unavailable'}</td><td>${formatTotal(mon, 'dvs')}</td><td>${formatTotal(mon, 'stat_exp')}</td></tr></tfoot></table>` : '<p class="detail-meta pc-card-empty">Individual stats are unavailable in this snapshot.</p>'
    return head + top
      + `<div class="pc-detail-summary">${condition ? `<div class="pc-gauges">${condition}</div>` : ''}${readouts(mon)}</div>`
      + `<div class="pc-detail-grid">${card('moves', 'Moves', count, moveList(mon))}${card('stats', 'Stats', quality, stats)}</div>`
      + links
  }

  // ---- toolbar: the same filters as the PC page, under a page's own id prefix ----
  const optionList = (rows, selected) => rows.map(([value, text]) => `<option value="${value}"${value === selected ? ' selected' : ''}>${text}</option>`).join('')
  function toolbar(prefix, options = {}) {
    const sort = options.sort || 'box'
    const field = (id, label, rows, selected, extra = '') => `<label class="field" id="${prefix}-${id}-control" for="${prefix}-${id}"${extra}><span class="micro">${label}</span><span class="select"><select id="${prefix}-${id}">${optionList(rows, selected)}</select></span></label>`
    return `<div class="pc-toolbar panel mon-toolbar">`
      + `<label class="field field--grow" for="${prefix}-search"><span class="micro">${esc(options.searchLabel || 'Find Pokémon')}</span><input id="${prefix}-search" type="search" placeholder="Name or Pokédex number" autocomplete="off"></label>`
      + field('rating', 'DV rating', RATINGS, 'all')
      + (options.settings ? field('setting', 'Lock', SETTINGS, 'all') : '')
      + field('sort', 'Sort by', SORTS, sort)
      + field('order', 'Order', [['asc', 'Lowest first'], ['desc', 'Highest first']], sortDefaults[sort])
      + `<span class="pc-count micro" id="${prefix}-count">0 Pokémon</span></div>`
  }
  const byId = (prefix, id) => document.querySelector(`#${prefix}-${id}`)
  // Gen II splits Special into Special Attack and Special Defense.
  function generation(prefix, value) {
    const special = byId(prefix, 'sort')?.querySelector?.('option[value="Special"]')
    if (value !== 2 || !special) return
    special.value = 'Special Attack'
    special.textContent = 'Special Attack'
    const defense = document.createElement('option')
    defense.value = 'Special Defense'
    defense.textContent = 'Special Defense'
    special.after(defense)
  }
  function orderLabels(select, sort) {
    if (!select?.options) return
    const alphabetical = sort === 'name' || sort === 'nick'
    select.options[0].textContent = alphabetical ? 'A to Z' : sort === 'box' ? 'First to last' : 'Lowest first'
    select.options[1].textContent = alphabetical ? 'Z to A' : sort === 'box' ? 'Last to first' : 'Highest first'
  }
  function bind(prefix, onchange) {
    byId(prefix, 'search')?.addEventListener('input', onchange)
    for (const id of ['rating', 'setting', 'order']) byId(prefix, id)?.addEventListener('change', onchange)
    byId(prefix, 'sort')?.addEventListener('change', () => {
      byId(prefix, 'order').value = sortDefaults[byId(prefix, 'sort').value] || 'desc'
      onchange()
    })
  }
  // Filter and sort rows with a toolbar's choices. settingOf names each row's trade setting.
  function apply(prefix, rows, settingOf) {
    const search = byId(prefix, 'search')?.value || ''
    const rating = byId(prefix, 'rating')?.value || 'all'
    const setting = byId(prefix, 'setting')?.value || 'all'
    const sort = byId(prefix, 'sort')?.value || 'box'
    const order = byId(prefix, 'order')?.value || 'asc'
    orderLabels(byId(prefix, 'order'), sort)
    const shown = rows.filter(mon => matches(mon, search, rating) && (setting === 'all' || !settingOf || settingOf(mon) === setting))
      .sort((a, b) => compare(a, b, sort, order))
    const count = byId(prefix, 'count')
    if (count) count.textContent = shown.length === rows.length ? `${rows.length} Pokémon` : `${shown.length} of ${rows.length} Pokémon`
    return shown
  }
  const filtered = prefix => ['search', 'rating', 'setting'].some(id => {
    const value = byId(prefix, id)?.value
    return value && value !== 'all'
  })

  globalThis.MonGrid = {esc, SORTS, RATINGS, SETTINGS, SETTING_LABELS, sortDefaults, statTotal, sortValue, compare,
    formatTotal, ratingLabel, ratingBadge, settingBadge, isLocked, lockIcon, lockControl, saveLock, tradeLink, matches, card, detail, detailLinks, tradeState, statPower, toolbar, generation,
    orderLabels, bind, apply, filtered}
})()
