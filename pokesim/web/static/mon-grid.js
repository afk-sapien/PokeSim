// The shared Pokémon grid: cards, filters, sorting, badges and the detail popup.
// The PC page and the Trading page both draw their Pokémon with it.
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
  // One trade setting per Pokémon. Protected means shiny or perfect, never traded automatically.
  const SETTINGS = [['all', 'All trade settings'], ['auto', 'Auto decides'], ['first', 'Trade first'], ['keep', 'Keep'], ['protected', 'Protected']]
  const SETTING_LABELS = {auto: 'Auto decides', first: 'Trade first', keep: 'Keep', protected: 'Protected'}
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
    const title = Number.isFinite(mon.dv_total) ? ` title="${mon.dv_total} / 75 DVs · ${mon.dv_percent}%"` : ''
    return `<span class="dv-badge dv-stars-${mon.dv_stars}" aria-label="${ratingLabel(mon)}"${title}><span class="dv" aria-hidden="true">${lamps}</span><span class="vh">${'★'.repeat(mon.dv_stars)}${'☆'.repeat(4 - mon.dv_stars)}</span> ${mon.dv_stars === 4 ? 'Perfect DV' : 'DV'}</span>`
  }

  // The small trade setting stamp on a card.
  function settingBadge(state) {
    const label = SETTING_LABELS[state]
    return label ? `<span class="tag trade-tag trade-tag--${state}" title="Trade setting: ${label}">${label}</span>` : ''
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
    : `<img loading="lazy" src="${esc(url || `${base()}/sprites/${Number(mon.dex) || 0}.png?v=rom-portraits-1`)}" alt="">`
  const place = (mon, index) => `${mon.box === 0 ? 'PARTY' : `BOX ${mon.box}`} · SLOT ${mon.position || index + 1}`

  // One card. Options: all (show the four metrics), sprite (a portrait address from another game),
  // attr (the data attribute naming the card), tags (extra stamps), blocked (why it cannot be picked),
  // pressed (the chosen card) and slot (a different location line).
  function card(mon, id, options = {}) {
    const attr = options.attr || 'mon'
    const blocked = options.blocked ? String(options.blocked) : ''
    const level = Number.isFinite(mon.level) ? mon.level : null
    const label = `${esc(mon.nick || mon.name)}${level === null ? '' : `, level ${level}`}${mon.type_names?.length ? ', ' + esc(mon.type_names.join(' / ')) : ''}, ${mon.box === 0 ? 'party' : `box ${mon.box}`}${', ' + ratingLabel(mon)}${mon.shiny ? ', shiny, protected from release and trading' : ''}${mon.perfect_dvs ? ', perfect DVs, preserved for the collection' : ''}${options.label ? ', ' + esc(options.label) : ''}${blocked ? `, cannot be picked: ${esc(blocked)}` : ''}`
    const classes = ['pc-mon', mon.perfect_dvs ? 'perfect-entry' : '', blocked ? 'is-blocked' : '', options.pressed ? 'is-chosen' : ''].filter(Boolean).join(' ')
    const state = [options.pressed !== undefined ? ` aria-pressed="${options.pressed ? 'true' : 'false'}"` : '', blocked ? ` aria-disabled="true" title="${esc(blocked)}"` : ''].join('')
    const metrics = options.all ? `<span class="pc-metrics"><span class="pc-power">Battle Power <b>${Number.isFinite(mon.battle_power) ? mon.battle_power.toLocaleString() : 'Unavailable'}</b></span><span>Stat Power <b>${Number.isFinite(mon.power) ? mon.power.toLocaleString() : 'Unavailable'}</b></span><span>Total DVs <b>${formatTotal(mon, 'dvs')}</b></span><span>Stat exp. <b>${formatTotal(mon, 'stat_exp')}</b></span></span>` : ''
    const reason = blocked ? `<span class="pc-blocked">${esc(blocked)}</span>` : ''
    return `<button type="button" class="${classes}" data-${attr}="${esc(id)}"${state} aria-label="${label}"><span class="pc-slot">${esc(options.slot || place(mon, Number(id) || 0))}</span><span class="plate pc-plate ${types().portraitClass(mon.type_names)}">${sprite(mon, options.sprite)}</span><span class="pc-mon-body"><strong class="pc-name">${esc(mon.nick || mon.name)}</strong><small class="pc-sub">${esc(mon.name)}${level === null ? '' : ` · Lv. ${level}`}</small><span class="type-tags">${types().badges(mon.type_names)}</span><span class="pc-tags">${types().shinyBadge(mon)}${ratingBadge(mon)}${options.tags || ''}</span>${reason}</span>${metrics}</button>`
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

  // The trade setting, as the server names it.
  function tradeState(mon) {
    if (!mon.trade_key) return null
    if (mon.shiny || mon.perfect_dvs) return {state: 'Protected', note: 'Never traded automatically'}
    return {state: SETTING_LABELS[mon.trade_setting] || SETTING_LABELS.auto, note: 'Change it on the Trading page'}
  }

  function moveList(mon) {
    const moves = mon.move_details || []
    if (!moves.length) return '<p class="detail-meta">No moves recorded.</p>'
    return `<ul class="pc-moves">${moves.map(original => {
      // Hidden Power takes its type and power from the DVs, not from the move table.
      const move = original.name === 'Hidden Power' && mon.hidden_power ? {...original, ...mon.hidden_power} : original
      const known = Number.isFinite(move.pp) && Number.isFinite(move.max_pp)
      const pp = known ? `<span class="pc-move-pp${move.pp ? '' : ' empty'}"><b>${move.pp}</b>/${move.max_pp} PP</span>` : ''
      const specs = Number.isFinite(move.power) ? [moveCategory(move), move.power ? `Pow ${move.power}` : 'Pow —',
        Number.isFinite(move.accuracy) && move.accuracy ? `Acc ${move.accuracy}%` : 'Acc —'] : []
      return `<li class="pc-move"><span class="pc-move-name">${esc(move.name)}</span>${pp}<span class="pc-move-specs">${types().badges([move.type])}${specs.map(spec => `<span>${esc(spec)}</span>`).join('')}</span></li>`
    }).join('')}</ul>`
  }

  function conditionRows(mon) {
    const rows = []
    if (Number.isFinite(mon.hp) && Number.isFinite(mon.max_hp) && mon.max_hp > 0) {
      const percent = mon.hp / mon.max_hp * 100
      rows.push(`<div class="meter-row"><span class="micro">HP</span>${gauge(percent, percent < 20 ? 'crit' : percent < 50 ? 'warn' : 'ok', `Health: ${mon.hp} of ${mon.max_hp}`)}<span class="value">${fmt(mon.hp)}/${fmt(mon.max_hp)}</span></div>`)
    }
    const xp = experienceProgress(mon)
    if (xp && Number.isFinite(xp.percent)) {
      rows.push(`<div class="meter-row"><span class="micro">XP</span>${gauge(xp.percent, 'signal', `Progress to level ${mon.level + 1}`)}<span class="value">${xp.max_level ? 'MAX' : `${Math.round(xp.percent)}%`}</span></div>`)
    }
    return rows.join('')
  }

  const cell = (label, value, note = '') => `<div><dt>${label}</dt><dd>${value}${note ? `<small>${note}</small>` : ''}</dd></div>`

  function facts(mon, trade) {
    const number = value => Number.isFinite(value) ? fmt(value) : 'Unavailable'
    const out = []
    const xp = experienceProgress(mon)
    const total = xp?.total ?? (Number.isFinite(mon.experience) ? mon.experience : null)
    if (Number.isFinite(total)) out.push(cell('Experience', fmt(total), xp ? xp.max_level ? 'Max level' : `${fmt(xp.remaining)} to Lv. ${mon.level + 1}` : ''))
    if (mon.battle_power !== undefined) out.push(cell('Battle Power', number(mon.battle_power)))
    out.push(cell('Stat Power', number(mon.power)))
    out.push(cell('Potential Stat Power', number(mon.potential_power)))
    if (mon.hidden_power) out.push(cell('Hidden Power', `${types().badges([mon.hidden_power.type])} ${mon.hidden_power.power}`))
    if (Number.isFinite(mon.friendship)) out.push(cell('Friendship', `${mon.friendship}<span class="unit">/255</span>`))
    if (Number.isFinite(mon.trainer_id)) out.push(cell('Original trainer', `ID ${String(mon.trainer_id).padStart(5, '0')}`))
    if (mon.caught) out.push(cell('Caught', esc(mon.caught.location || 'Unknown place'), [mon.caught.level ? `Lv. ${mon.caught.level}` : '', mon.caught.time].filter(Boolean).map(esc).join(' · ')))
    if ('pokerus' in mon) out.push(cell('Pokérus', mon.pokerus === 'infected' ? '<span class="tag tag--warn">Infected</span>' : mon.pokerus === 'cured' ? '<span class="tag">Cured</span>' : 'None'))
    if (mon.elite_four_wins !== undefined) out.push(cell('Elite Four wins', mon.elite_four_wins === null ? 'Unknown' : `${fmt(mon.elite_four_wins)}${mon.elite_four_wins_incomplete ? '+' : ''}`))
    if (trade) out.push(cell('Trade', trade.state, esc(trade.note)))
    return `<dl class="pc-facts">${out.join('')}</dl>`
  }

  function eggFacts(mon, trade) {
    const cycles = mon.egg_cycles
    const rows = [`<div><dt>Hatches in</dt><dd>${Number.isFinite(cycles) ? `${fmt(cycles)} egg cycle${cycles === 1 ? '' : 's'}<small>About ${fmt(cycles * 256)} steps in the party</small>` : 'Unknown'}</dd></div>`]
    if (trade) rows.push(cell('Trade', trade.state, trade.note ? esc(trade.note) : ''))
    return `<dl class="pc-facts">${rows.join('')}</dl>`
  }

  // The popup body. Options: sprite (a portrait address from another game), trade (replaces the
  // trade fact, or false to leave it out), top (HTML shown under the head, such as a pick button)
  // and links (false hides the guide and Pokédex links).
  function detail(mon, options = {}) {
    const labels = Object.keys(mon.calculated_stats || {})
    const known = mon.dvs?.length === 5 && mon.stat_exp?.length === 5
    const status = mon.status_label || (Number.isFinite(mon.hp) ? mon.hp ? 'Healthy' : 'Fainted' : '')
    const statusTag = !mon.egg && status ? `<span class="tag pc-status${status === 'Healthy' ? '' : mon.hp ? ' tag--warn' : ' tag--crit'}">${esc(status)}</span>` : ''
    const trade = options.trade === false ? null : options.trade || tradeState(mon)
    const head = `<div class="pc-detail-head"><div class="plate plate--bay ${types().portraitClass(mon.type_names)}">${sprite(mon, options.sprite).replace(' loading="lazy"', '')}</div><p class="micro">${options.slot ? esc(options.slot) : `${mon.box === 0 ? 'PARTY' : `BOX ${mon.box}`} · SLOT ${mon.position || '?'}`}${mon.dex ? ` · No.${String(mon.dex).padStart(3, '0')}` : ''}</p><h2 id="pc-detail-name">${esc(mon.nick || mon.name)}</h2>${mon.egg ? '' : `<div class="pc-tags">${types().shinyBadge(mon)}${ratingBadge(mon)}${statusTag}</div>`}${mon.perfect_dvs || mon.shiny ? '<p class="detail-meta">Protected from automatic release and trading.</p>' : ''}<p>${mon.egg ? 'Not yet hatched' : `${esc(mon.name)} · Level ${mon.level}${mon.gender ? ` · ${esc(mon.gender)}` : ''}`}</p>${mon.held_item_name ? `<p>Holding ${esc(mon.held_item_name)}</p>` : ''}<div class="type-tags">${types().badges(mon.type_names)}</div></div>`
    const section = (title, body) => `<section class="pc-detail-section"><h3 class="micro">${title}</h3>${body}</section>`
    const links = options.links === false ? '' : `<div class="pc-detail-links"><a class="dex-open key" href="https://github.com/afk-sapien/PokeSim/blob/main/docs/pokemon-stats.md" target="_blank" rel="noopener noreferrer">Stats guide ↗</a>${mon.dex ? `<a class="dex-open key" href="${base()}/pokedex#${String(mon.dex).padStart(3, '0')}">Pokédex ↗</a>` : ''}</div>`
    const top = options.top || ''
    if (mon.egg) return head + top + section('Egg', eggFacts(mon, trade)) + '<p class="detail-meta pc-detail-note">Its species, moves and stats appear once it hatches.</p>'
    const condition = conditionRows(mon)
    const stats = known ? `<table class="individual-stats"><caption>Stats</caption><thead><tr><th>Stat</th><th>Value</th><th>DV</th><th>Stat exp.</th></tr></thead><tbody>${labels.map((label, i) => `<tr><th scope="row">${label}</th><td>${mon.calculated_stats?.[label] ?? 'Unavailable'}</td><td>${mon.dvs[Math.min(i, 4)]}</td><td>${mon.stat_exp[Math.min(i, 4)].toLocaleString()}</td></tr>`).join('')}</tbody><tfoot><tr><th scope="row">Total</th><td>${Number.isFinite(mon.stat_total) ? mon.stat_total.toLocaleString() : 'Unavailable'}</td><td>${formatTotal(mon, 'dvs')}</td><td>${formatTotal(mon, 'stat_exp')}</td></tr></tfoot></table>` : '<p class="detail-meta">Individual stats are unavailable in this snapshot.</p>'
    const quality = Number.isFinite(mon.dv_top_percent) ? `<p class="detail-meta">DV quality (est.): top ${mon.dv_top_percent.toLocaleString(undefined, {maximumSignificantDigits: 3})}% · Higher roll: ${mon.dv_better_percent.toLocaleString(undefined, {maximumSignificantDigits: 3})}%</p>` : ''
    const battleNote = mon.battle_power === undefined ? '' : '<p class="detail-meta">Battle Power rates known moves at full health and PP. Matchups can change the result.</p>'
    return head + top
      + (condition ? section('Condition', `<div class="mon-meters pc-gauges">${condition}</div>`) : '')
      + section('Moves', moveList(mon))
      + section('Record', facts(mon, trade) + battleNote)
      + `<section class="pc-detail-section">${stats}${quality}</section>`
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
      + (options.settings ? field('setting', 'Trade setting', SETTINGS, 'all') : '')
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
    formatTotal, ratingLabel, ratingBadge, settingBadge, matches, card, detail, tradeState, toolbar, generation,
    orderLabels, bind, apply, filtered}
})()
