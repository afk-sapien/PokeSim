// The next activity: a manager picks one goal from the planner's own list, or cancels the pick.
// The planner runs it once, after upkeep, then goes back to its own order. Nothing is queued.
// A goal that targets one Pokémon lists the species it can reach and when to stop. Those two
// fields show only for such a goal, so most picks are a single Goal list and Set.
(() => {
  const $ = selector => document.querySelector(selector)
  const FAILED = 'That action could not be sent. Please try again.'
  // The server lists the best 30 goals. The select never holds more than this, whatever it sends.
  const MOST = 40
  let owner = false
  let busy = false
  let typing
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
  function render(pin) {
    const section = $('#next-activity')
    if (!section) return
    put(section, 'hidden', !owner)
    const active = Boolean(pin)
    const line = $('#next-activity-status')
    put(line, 'textContent', status(pin))
    put(line, 'hidden', !active)
    put($('#next-activity-cancel'), 'hidden', !active)
    put($('#next-activity-goal-field'), 'hidden', active || empty)
    put($('#next-activity-search-field'), 'hidden', active)
    put($('#next-activity-set'), 'hidden', active || empty)
    // The fields are drawn again only for another goal. Redrawing them each refresh cleared a name
    // still being typed and closed an open list.
    const goal = active || empty ? null : chosen()
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
      for (const goal of list) select.add(new Option(spell(goal.label), goal.key))
      if (goals.has(kept)) select.value = kept
      // With nothing to choose, the row shows only the planner's reason, not an empty list and a dead button.
      empty = !list.length
      $('#next-activity-goal-field').hidden = empty
      $('#next-activity-set').hidden = empty
      $('#next-activity-set').disabled = !list.length
      fields(empty ? null : chosen())
      note(list.length ? '' : body.reason)
    } catch (error) {
      note(error.message, true)
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

  // Called on every state refresh. A view link and a stopped adventure never see the picker.
  function update(state) {
    owner = !state.viewer_only && !state.stopped
    render(state.strategy?.pin || null)
  }

  $('#next-activity-set')?.addEventListener('click', pick)
  $('#next-activity-goal')?.addEventListener('focus', load)
  $('#next-activity-goal')?.addEventListener('change', () => { note(''); fields(chosen()) })
  // The list is read again a moment after typing stops, not on every key.
  const search = () => {
    clearTimeout(typing)
    typing = setTimeout(load, 300)
  }
  $('#next-activity-search')?.addEventListener('input', search)
  $('#next-activity-cancel')?.addEventListener('click', cancel)
  globalThis.NextActivity = {status, spell, render, update, load, pick, cancel, MOST}
})()
