// The next activity: a manager picks one goal from the planner's own list, or cancels the pick.
// The planner runs it once, after upkeep, then goes back to its own order. Nothing is queued.
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

  const status = pin => pin ? `Next: ${pin.label}` : ''

  function note(text, error = false) {
    const element = $('#next-activity-note')
    if (!element) return
    element.textContent = text || ''
    element.classList.toggle('error', Boolean(error && text))
  }

  async function send(action, value) {
    const response = await PokeSim.fetch('/api/control', {method: 'POST', headers: {'content-type': 'application/json'}, body: JSON.stringify({action, value})})
    const body = await response.json().catch(() => ({}))
    // A refusal says why the planner cannot take the goal now, such as a goal that dropped out of the list.
    if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : FAILED)
    return body
  }

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
    $('#next-activity-goal').hidden = active || empty
    $('#next-activity-set').hidden = active || empty
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
      const goals = Array.isArray(body.goals) ? body.goals : []
      // The list is read again on focus, so a choice still on it stays chosen.
      const chosen = select.value
      select.innerHTML = ''
      select.add(new Option(goals.length ? 'Choose a goal' : 'No goals to choose now', ''))
      for (const goal of goals) select.add(new Option(goal.label, goal.key))
      if (goals.some(goal => goal.key === chosen)) select.value = chosen
      // With nothing to choose, the row shows only the planner's reason, not an empty list and a dead button.
      empty = !goals.length
      select.hidden = empty
      $('#next-activity-set').hidden = empty
      $('#next-activity-set').disabled = !goals.length
      note(goals.length ? '' : body.reason)
    } catch (error) {
      note(error.message, true)
    }
  }

  async function act(action, value) {
    if (busy) return
    busy = true
    try {
      const body = await send(action, value)
      note('')
      shown = undefined
      render(action === 'pin_goal' ? body.pin : null)
    } catch (error) {
      note(error.message, true)
    } finally {
      busy = false
    }
  }

  const pick = () => {
    const key = $('#next-activity-goal')?.value
    if (!key) return note('Choose a goal from the list.', true)
    return act('pin_goal', key)
  }
  const cancel = () => act('unpin_goal')

  // Called on every state refresh. A view link and a stopped adventure never see the picker.
  function update(state) {
    owner = !state.viewer_only && !state.stopped
    render(state.strategy?.pin || null)
  }

  $('#next-activity-set')?.addEventListener('click', pick)
  $('#next-activity-goal')?.addEventListener('focus', load)
  $('#next-activity-cancel')?.addEventListener('click', cancel)
  globalThis.NextActivity = {status, render, update, load, pick, cancel}
})()
