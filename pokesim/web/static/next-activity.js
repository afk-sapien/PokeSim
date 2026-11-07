// The next activity: a manager picks one goal from the planner's own list, or cancels the pick.
// The planner runs it once, after upkeep, then goes back to its own order. Nothing is queued.
// A goal that targets one Pokémon lists the species it can reach and when to stop. Those two
// fields show only for such a goal, so most picks are a single Goal list and Set.
(() => {
  const $ = selector => document.querySelector(selector)
  const FAILED = 'That action could not be sent. Please try again.'
  let owner = false
  let busy = false
  // The pin key the picker last drew for. Undefined until the first draw, so that draw loads the list.
  let shown
  // True while the planner offers nothing to choose, so a state refresh keeps the list hidden.
  let empty = false
  // When the list was last read. A hidden empty list cannot take focus, so it is read again each minute.
  let asked = 0
  // The goals from the last read, by key, so a choice can show its own species and stop fields.
  let goals = new Map()

  const status = pin => pin ? `Next: ${spell(pin.label)}` : ''
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
    section.hidden = !owner
    const active = Boolean(pin)
    const line = $('#next-activity-status')
    line.textContent = status(pin)
    line.hidden = !active
    $('#next-activity-cancel').hidden = !active
    $('#next-activity-goal-field').hidden = active || empty
    $('#next-activity-set').hidden = active || empty
    fields(active || empty ? null : chosen())
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
    try {
      const response = await PokeSim.fetch('/api/goals', {cache: 'no-store'})
      if (!response.ok) throw new Error(FAILED)
      const body = await response.json()
      const list = Array.isArray(body.goals) ? body.goals : []
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
  $('#next-activity-cancel')?.addEventListener('click', cancel)
  globalThis.NextActivity = {status, spell, render, update, load, pick, cancel}
})()
