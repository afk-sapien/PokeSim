// The next activity: a manager picks one goal from the planner's own list, or cancels the pick.
// The planner runs it once, after upkeep, then goes back to its own order. Nothing is queued.
// A goal that targets one Pokémon lists the species it can reach and when to stop. Those two
// fields show only for such a goal, so most picks are a single Goal list and Set.
// A goal the planner cannot run now says why it waits, and it can still be set.
// Someone who can only watch sees every goal, read from the goal catalogue, and no pin control.
(() => {
  const $ = selector => document.querySelector(selector)
  const FAILED = 'That action could not be sent. Please try again.'
  const UNREAD = 'The goals could not be read. Please try again.'
  // The server lists the best 30 goals. The select never holds more than this, whatever it sends.
  const MOST = 40
  let owner = false
  // True for a view link, a viewer or a player while the adventure runs: the goals show, the controls do not.
  let viewer = false
  let busy = false
  let typing
  let finding
  // Counts catalogue reads, so an answer that comes back after a newer search is dropped.
  let browsing = 0
  // The pin key the picker last drew for. Undefined until the first draw, so that draw loads the list.
  let shown
  // True while the planner offers nothing to choose, so a state refresh keeps the list hidden.
  let empty = false
  // When the list was last read. A hidden empty list cannot take focus, so it is read again each minute.
  let asked = 0
  // The goals from the last read, by key, so a choice can show its own species and stop fields.
  let goals = new Map()
  // The goal whose species and stop fields are drawn, so a state refresh leaves a half-typed name alone.
  let drawnFor
  // A state refresh runs every 2 seconds and writes only what changed.
  const put = (element, property, value) => { if (element && element[property] !== value) element[property] = value }

  // A pin the planner cannot run now says why after its label, so a waiting pin never looks like one
  // that does nothing. The reason is a failure's kind and detail, and a pin without one shows only its label.
  const status = pin => {
    if (!pin) return ''
    const parked = spell(pin.parked?.detail).trim()
    return `Next: ${spell(pin.label)}${parked ? ` (waiting: ${parked})` : ''}`
  }
  // The game's own spelling, whatever the label source wrote.
  const spell = text => String(text ?? '').replace(/\bPokemon\b/g, 'Pokémon')
  // Why a goal waits, in plain words, or null for a goal the planner can run now. A row that does not
  // say it is not feasible counts as open, so a list where every goal is open reads as it always has.
  const waits = goal => (goal && goal.feasible === false ? spell(goal.why_not?.detail).trim() : null)
  // A goal's name in the list, with why it waits after it as the Next line words a waiting pin.
  const named = goal => {
    const why = waits(goal)
    const label = spell(goal.label ?? goal.title)
    return why === null ? label : `${label} (waiting${why ? `: ${why}` : ''})`
  }
  // Choosing a waiting goal says it can still be set. The planner keeps it and runs it once it can.
  const advice = goal => {
    const why = waits(goal)
    return why === null ? '' : `This goal waits${why ? `: ${why}` : ''}. Set keeps it as next, and it runs once it can.`
  }
  // Typed names match without case, accents or punctuation, so "farfetchd" finds "Farfetch’d".
  const fold = text => String(text ?? '').normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9♀♂]/gi, '').toLowerCase()

  function note(text, error = false) {
    const element = $('#next-activity-note')
    if (!element) return
    element.textContent = text || ''
    element.classList.toggle('error', Boolean(error && text))
  }

  async function send(body) {
    const response = await PokeSim.fetch('/api/control', {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify(body)})
    const reply = await response.json().catch(() => ({}))
    // A refusal says why the planner cannot take the goal now, such as a goal that dropped out of the list.
    if (!response.ok) throw new Error(typeof reply.detail === 'string' ? reply.detail : FAILED)
    return reply
  }

  // The species and stop fields follow the chosen goal. Only the species its target kind can reach are listed.
  function fields(goal) {
    drawnFor = goal?.key ?? null
    const species = Array.isArray(goal?.species) ? goal.species : []
    const stops = Array.isArray(goal?.stops) ? goal.stops : []
    const list = $('#next-activity-species-list')
    const input = $('#next-activity-species')
    list.replaceChildren(...species.map(name => new Option(spell(name))))
    if (!species.some(name => fold(name) === fold(input.value))) input.value = ''
    $('#next-activity-species-field').hidden = !species.length
    const stop = $('#next-activity-stop')
    const kept = stop.value
    stop.innerHTML = ''
    for (const option of stops) stop.add(new Option(spell(option.label), option.key))
    if (stops.some(option => option.key === kept)) stop.value = kept
    $('#next-activity-stop-field').hidden = !stops.length
  }

  const chosen = () => goals.get($('#next-activity-goal')?.value) || null

  // The pin from /api/state. While it is set the picker gives way to its label and a Cancel button.
  // Someone who can only watch sees the label and the goal catalogue, never the picker or Cancel.
  function render(pin) {
    const section = $('#next-activity')
    if (!section) return
    put(section, 'hidden', !owner && !viewer)
    put($('#next-activity-heading'), 'textContent', owner ? 'Choose next' : 'Goals')
    const active = Boolean(pin)
    const picking = owner && !active
    const line = $('#next-activity-status')
    put(line, 'textContent', status(pin))
    put(line, 'hidden', !active)
    put($('#next-activity-cancel'), 'hidden', !owner || !active)
    put($('#next-activity-goal-field'), 'hidden', !picking || empty)
    put($('#next-activity-search-field'), 'hidden', !picking)
    put($('#next-activity-set'), 'hidden', !picking || empty)
    put($('#next-activity-catalogue'), 'hidden', owner)
    // The fields are drawn again only for another goal. Redrawing them each refresh cleared a name
    // still being typed and closed an open list.
    const goal = !picking || empty ? null : chosen()
    if ((goal?.key ?? null) !== drawnFor) fields(goal)
    const key = pin ? pin.key : null
    if (owner && key !== shown) {
      shown = key
      if (!active) load()
    } else if (owner && !active && empty && Date.now() - asked > 60000) load()
  }

  async function load() {
    const select = $('#next-activity-goal')
    if (!select || !owner) return
    asked = Date.now()
    // A name in the search box finds goals past the best few, such as one species to hunt.
    const query = ($('#next-activity-search')?.value || '').trim()
    const url = query ? `/api/goals?q=${encodeURIComponent(query)}` : '/api/goals'
    try {
      const response = await PokeSim.fetch(url, {cache: 'no-store'})
      if (!response.ok) throw new Error(FAILED)
      const body = await response.json()
      const list = (Array.isArray(body.goals) ? body.goals : []).slice(0, MOST)
      goals = new Map(list.map(goal => [goal.key, goal]))
      // The list is read again on focus, so a choice still on it stays chosen.
      const kept = select.value
      select.innerHTML = ''
      select.add(new Option(list.length ? 'Choose a goal' : 'No goals to choose now', ''))
      for (const goal of list) select.add(new Option(named(goal), goal.key))
      if (goals.has(kept)) select.value = kept
      // With nothing to choose, the row shows only the planner's reason, not an empty list and a dead button.
      empty = !list.length
      $('#next-activity-goal-field').hidden = empty
      $('#next-activity-set').hidden = empty
      $('#next-activity-set').disabled = !list.length
      fields(empty ? null : chosen())
      note(list.length ? advice(chosen()) : body.reason)
    } catch (error) {
      note(error.message, true)
    }
  }

  // One catalogue goal as a line of the read-only list, with why it waits under its name.
  function entry(goal) {
    const item = document.createElement('li')
    const name = document.createElement('span')
    name.className = 'plan-goal-name'
    name.textContent = spell(goal.title ?? goal.label)
    item.append(name)
    const why = waits(goal)
    if (why !== null) {
      const reason = document.createElement('span')
      reason.className = 'plan-goal-why'
      reason.textContent = why ? `Waiting: ${why}` : 'Waiting'
      item.append(reason)
    }
    return item
  }

  // The goal catalogue for someone who can only watch: the goals open now or waiting, best first.
  // It is read when the list is opened or searched, never on a state refresh.
  async function browse() {
    const list = $('#next-activity-catalogue-list')
    const said = $('#next-activity-catalogue-note')
    if (!list || !viewer) return
    const asking = ++browsing
    const query = ($('#next-activity-catalogue-search')?.value || '').trim()
    const url = `/api/catalogue?limit=${MOST}${query ? `&q=${encodeURIComponent(query)}` : ''}`
    try {
      const response = await PokeSim.fetch(url, {cache: 'no-store'})
      if (!response.ok) throw new Error(UNREAD)
      const body = await response.json()
      if (asking !== browsing) return
      const rows = (Array.isArray(body.goals) ? body.goals : []).slice(0, MOST)
      list.replaceChildren(...rows.map(entry))
      put(said, 'textContent', rows.length ? '' : spell(body.reason || 'No goals to show now'))
      said?.classList.toggle('error', false)
    } catch (error) {
      if (asking !== browsing) return
      put(said, 'textContent', error.message)
      said?.classList.toggle('error', true)
    }
  }

  async function act(body) {
    if (busy) return
    busy = true
    try {
      const reply = await send(body)
      note('')
      shown = undefined
      render(body.action === 'pin_goal' ? reply.pin : null)
    } catch (error) {
      note(error.message, true)
    } finally {
      busy = false
    }
  }

  const pick = () => {
    const key = $('#next-activity-goal')?.value
    if (!key) return note('Choose a goal from the list.', true)
    const goal = goals.get(key)
    const body = {action: 'pin_goal', value: key}
    if (goal?.species?.length) {
      const typed = fold($('#next-activity-species').value)
      const species = goal.species.find(name => fold(name) === typed)
      if (!species) return note('Choose a Pokémon from the list.', true)
      body.target = {species}
      if (goal.stops?.length) body.target.stop = $('#next-activity-stop').value || goal.stops[0].key
    }
    return act(body)
  }
  const cancel = () => act({action: 'unpin_goal'})

  // Called on every state refresh. A view link sees the goals but never the picker, and a stopped
  // adventure shows neither.
  function update(state) {
    owner = !state.viewer_only && !state.stopped
    viewer = Boolean(state.viewer_only) && !state.stopped
    render(state.strategy?.pin || null)
  }

  $('#next-activity-set')?.addEventListener('click', pick)
  $('#next-activity-goal')?.addEventListener('focus', load)
  $('#next-activity-goal')?.addEventListener('change', () => { const goal = chosen(); note(advice(goal)); fields(goal) })
  // The list is read again a moment after typing stops, not on every key.
  const search = () => {
    clearTimeout(typing)
    typing = setTimeout(load, 300)
  }
  $('#next-activity-search')?.addEventListener('input', search)
  $('#next-activity-cancel')?.addEventListener('click', cancel)
  const catalogue = $('#next-activity-catalogue')
  catalogue?.addEventListener('toggle', () => { if (catalogue.open) browse() })
  $('#next-activity-catalogue-search')?.addEventListener('input', () => {
    clearTimeout(finding)
    finding = setTimeout(browse, 300)
  })
  globalThis.NextActivity = {status, spell, render, update, load, pick, cancel, browse, MOST}
})()
