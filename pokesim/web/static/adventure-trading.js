(() => {
  const $ = selector => document.querySelector(selector)
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp', '<': '&lt', '>': '&gt', '"': '&quot', "'": '&#39'}[char] + String.fromCharCode(59)))
  const phases = {
    preparing: 'Getting ready for the Cable Club', connecting: 'Connecting the games',
    trading: 'Exchanging Pokémon', saving: 'Saving progress', leaving: 'Leaving the Cable Club',
    resuming: 'Returning to the adventure', returning: 'Returning to the adventure',
    verifying: 'Checking both saves', staging: 'Checking both saves',
    committed: 'Saving the exchange', applying: 'Saving the exchange', releasing: 'Returning to the adventure'
  }
  function exchange(trade, completed = false) {
    const label = completed ? 'Trade completed' : trade.recovering || trade.decision === 'ABORT'
      ? trade.decision === 'COMMIT' ? 'Finishing the exchange safely' : 'Getting ready to try again'
      : phases[trade.phase] || 'Getting ready'
    const time = completed ? `<p>${esc(new Date(trade.updated_at * 1000).toLocaleString())}</p>` : ''
    return `<article class="trade-deal"><div class="section-heading"><h3>With ${esc(trade.peer_name)}</h3><span class="count-pill">${esc(label)}</span></div>${time}</article>`
  }
  let loading = false
  async function refresh() {
    if (loading) return
    loading = true
    try {
      const response = await PokeSim.fetch('/api/interactions', {cache: 'no-store'})
      if (!response.ok) throw new Error('Unavailable')
      const data = await response.json()
      if (data.adventure.id !== PokeSim.adventureId) throw new Error('Wrong adventure')
      $('#edition').textContent = `${data.adventure.version.toUpperCase()} VERSION`
      $('#status').textContent = 'Connected'
      $('#connection').classList.toggle('is-offline', false)
      $('#trade-connection-note').hidden = true
      const running = data.adventure.state === 'running' && !data.adventure.archived
      $('#trade-status').textContent = data.active.length ? 'Exchange in progress' : running ? 'On · No approvals needed' : 'Waiting for this adventure'
      $('#trade-activity').textContent = data.active.length ? 'This adventure is trading. Other adventures keep playing.'
        : running ? 'This adventure will trade when a useful exchange is ready.' : 'Trades resume when this adventure is running. Its history stays here.'
      $('#trade-active').innerHTML = data.active.length ? data.active.map(trade => exchange(trade)).join('')
        : '<p class="dex-empty">No exchange in progress for this adventure.</p>'
      const completed = data.history.filter(trade => trade.phase === 'completed' && trade.decision === 'COMMIT')
      $('#trade-history').innerHTML = completed.length ? completed.map(trade => exchange(trade, true)).join('')
        : '<p class="dex-empty">This adventure’s completed trades will appear here.</p>'
    } catch (_) {
      $('#status').textContent = 'Reconnecting…'
      $('#connection').classList.toggle('is-offline', true)
      $('#trade-connection-note').textContent = 'This adventure’s trading updates are reconnecting. Any displayed history is from the last successful update.'
      $('#trade-connection-note').hidden = false
    } finally { loading = false }
  }
  refresh()
  setInterval(() => { if (!document.hidden) refresh() }, 5000)
})()
