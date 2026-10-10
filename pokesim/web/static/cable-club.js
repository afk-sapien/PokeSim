(() => {
  const $ = selector => document.querySelector(selector)
  const viewer = document.querySelector('meta[name="pokesim-viewer"]')?.content === 'true'
  const adventureId = PokeSim.adventureId
  const partnerId = new URLSearchParams(location.search).get('with') || ''
  const prefix = PokeSim.base.slice(0, PokeSim.base.lastIndexOf('/'))
  const PHASES = {
    preparing: 'Preparing both adventures',
    travelling: 'Walking to the Cable Club',
    ready: 'Both trainers are ready. Linking the cable',
    in_session: 'In session. You hold both controllers',
    verifying: 'Checking the trade',
    done: 'Done. The trade is saved',
    rolled_back: 'Rolled back',
    rolling_back: 'Rolling back to the Pokémon Center saves',
  }
  const KEYS = {ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right', x: 'a', z: 'a', c: 'b', Backspace: 'b', Enter: 'start', Shift: 'select'}
  let session = null
  let focused = 'left'
  let streaming = ''
  let timer = null

  if (viewer) document.body.classList.add('is-viewer')

  function toast(message) {
    const node = $('#toast')
    node.textContent = message
    node.hidden = false
    clearTimeout(toast.timer)
    toast.timer = setTimeout(() => { node.hidden = true }, 4000)
  }

  async function send(url, body) {
    const response = await PokeSim.api(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body || {})})
    let data = {}
    try { data = await response.json() } catch (_) {}
    if (!response.ok) throw new Error(data.detail || 'PokeSim could not do that.')
    return data
  }

  // The server swaps each side's stream between the session preview and the game itself as the phase moves on,
  // and an ended multipart stream never reconnects, so every new phase binds fresh streams.
  function streams(status) {
    const key = `${status.left_id}:${status.right_id}:${status.phase}`
    if (streaming === key) return
    streaming = key
    const phase = encodeURIComponent(status.phase)
    $('#cable-left-screen').src = `${prefix}/${encodeURIComponent(status.left_id)}/stream?phase=${phase}`
    $('#cable-right-screen').src = `${prefix}/${encodeURIComponent(status.right_id)}/stream?phase=${phase}`
  }

  function render(status, reason) {
    session = status
    const phase = status ? status.phase : 'idle'
    const live = Boolean(status && status.controls_live)
    $('#cable-phase').textContent = status ? (PHASES[phase] || phase) : (reason ? 'Not available' : 'No session yet')
    let detail = reason || (!status && !partnerId ? 'Open the Cable Club from the Trading page to choose a partner.' : '')
    if (status) {
      if (status.reason) detail = status.reason
      else if (phase === 'in_session') detail = `Trades so far: ${status.trades}. ${status.idle_seconds_left ?? 300} seconds before an idle timeout.`
      else if (phase === 'done') detail = `${status.trades} ${status.trades === 1 ? 'trade' : 'trades'} saved to both adventures.`
      const names = status.adventures || {}
      $('#cable-left-name').textContent = names[status.left_id]?.name || 'Left adventure'
      $('#cable-right-name').textContent = names[status.right_id]?.name || 'Right adventure'
      streams(status)
    }
    $('#cable-reason').textContent = detail
    $('#cable-lamp').dataset.state = live ? 'on' : phase
    const open = status && status.cancellable
    $('#cable-start').hidden = viewer || Boolean(open) || !partnerId || Boolean(reason)
    $('#cable-finish').disabled = !live
    $('#cable-cancel').disabled = !open
    document.querySelectorAll('.cable-pad .key').forEach(button => { button.disabled = !live })
    clearTimeout(timer)
    if (open) timer = setTimeout(refresh, 1000)
  }

  async function refresh() {
    try {
      // The game's own Cable Club API answers both the owner page and a view link.
      const response = await PokeSim.fetch('/api/cable', {cache: 'no-store'})
      if (!response.ok) throw new Error('Could not read the Cable Club.')
      const data = await response.json()
      render(data.session || session, data.reason)
      $('#status').textContent = 'Connected'
    } catch (error) {
      $('#status').textContent = 'Reconnecting'
      clearTimeout(timer)
      timer = setTimeout(refresh, 2000)
    }
  }

  async function press(side, button) {
    if (!session || !session.controls_live) return
    try { render(await send(`/api/v1/interactions/cable-sessions/${encodeURIComponent(session.id)}/input`, {side, button})) } catch (error) { toast(error.message) }
  }

  function setFocus(side) {
    focused = side
    document.querySelectorAll('.cable-side').forEach(node => node.classList.toggle('is-focused', node.dataset.side === side))
  }

  $('#cable-start').addEventListener('click', async () => {
    try {
      streaming = ''
      render(await send('/api/v1/interactions/cable-sessions', {left_id: adventureId, right_id: partnerId}))
    } catch (error) { toast(error.message) }
  })
  $('#cable-finish').addEventListener('click', async () => {
    if (!session) return
    try { render(await send(`/api/v1/interactions/cable-sessions/${encodeURIComponent(session.id)}/finish`)) } catch (error) { toast(error.message) }
  })
  $('#cable-cancel').addEventListener('click', async () => {
    if (!session) return
    try { render(await send(`/api/v1/interactions/cable-sessions/${encodeURIComponent(session.id)}/cancel`)) } catch (error) { toast(error.message) }
  })
  document.querySelectorAll('.cable-side').forEach(node => {
    const side = node.dataset.side
    node.addEventListener('focusin', () => setFocus(side))
    node.addEventListener('pointerdown', () => setFocus(side))
    node.querySelectorAll('[data-button]').forEach(button => button.addEventListener('click', () => press(side, button.dataset.button)))
  })
  document.addEventListener('keydown', event => {
    if (viewer || event.ctrlKey || event.metaKey || event.altKey) return
    if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return
    const button = KEYS[event.key] || KEYS[event.key.toLowerCase()]
    if (!button || !session || !session.controls_live) return
    if (event.key === 'Enter' && event.target instanceof HTMLButtonElement) return
    event.preventDefault()
    if (!event.repeat) press(focused, button)
  })
  setFocus('left')
  refresh()
})()
