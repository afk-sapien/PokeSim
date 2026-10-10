// Progress of a chosen (manual) trade, shared by the library's trade page and each game's offers.
(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp', '<': '&lt', '>': '&gt', '"': '&quot', "'": '&#39'}[char] + String.fromCharCode(59)))
  const steps = [
    ['queued', 'Waiting for the Cable Club'], ['preparing', 'Heading to the Cable Club'],
    ['connecting', 'Connecting the games'], ['trading', 'Exchanging Pokémon'],
    ['verifying', 'Checking both saves'], ['committed', 'Saving the trade'], ['completed', 'Trade complete']]
  const stepOf = {queued: 0, checking: 0, preparing: 1, connecting: 2, trading: 3, saving: 3, leaving: 3, resuming: 3,
    returning: 3, verifying: 4, staging: 4, committed: 5, releasing: 5, completed: 6}
  const preparationLabels = {travelling: 'travelling to a Pokémon Center', storage: 'at the PC', rendezvous: 'at the Cable Club counter',
    ready: 'ready at the Cable Club'}
  const unnamed = () => 'An adventure'

  function phase(trade) {
    if (trade.decision === 'ABORT' || trade.error || ['recovering', 'aborting', 'aborted'].includes(trade.phase)) {
      return trade.decision === 'COMMIT' ? 'Finishing the exchange safely' : 'Getting ready to try again'
    }
    const labels = {
      proposed: 'Getting ready', preparing: 'Heading to the Cable Club',
      connecting: 'Connecting the games', trading: 'Exchanging Pokémon',
      saving: 'Saving progress', leaving: 'Leaving the Cable Club',
      resuming: 'Returning to the adventure', returning: 'Returning to the adventure',
      verifying: 'Checking both saves', staging: 'Checking both saves',
      committed: 'Saving the exchange', applying: 'Saving the exchange',
      releasing: 'Returning to the adventure', completed: 'Trade completed'
    }
    return labels[trade.phase || trade.state || trade.status] || 'Getting ready'
  }

  function outcome(status, name = unnamed) {
    if (status.state === 'rejected') return {done: true, failed: true, text: status.error || 'This trade could not start.'}
    if (status.state === 'cancelled') return {done: true, failed: true, text: 'Trade cancelled. Both adventures kept their Pokémon.'}
    if (status.phase === 'aborted') {
      const detail = status.error && status.error !== status.failure_reason ? ` ${status.error}` : ''
      return {done: true, failed: true, text: `${status.failure_reason || 'The trade did not complete.'}${detail}`}
    }
    if (status.phase === 'completed') {
      const display = status.display || {}
      const got = id => display[id]?.received?.name
      const parts = [status.left_id, status.right_id].filter(got).map(id => `${name(id)} received ${got(id)}.`)
      return {done: true, failed: false, text: `Trade complete. ${parts.join(' ')}`.trim()}
    }
    return {done: false}
  }

  // The step list, the line under it and the outcome, ready to place in a card.
  function view(status, name = unnamed) {
    const result = outcome(status, name)
    const step = status.state === 'queued' ? 0 : stepOf[status.phase] ?? 0
    const stopping = ['aborting', 'aborted', 'recovering'].includes(status.phase) || ['rejected', 'cancelled'].includes(status.state)
    const list = steps.map(([, label], index) => {
      const state = result.done && !result.failed ? 'done' : index < step ? 'done' : index === step && !stopping ? 'now' : 'todo'
      return `<li class="manual-step is-${state}"${state === 'now' ? ' aria-current="step"' : ''}>${esc(label)}</li>`
    }).join('')
    let text = ''
    if (status.state === 'queued') text = status.position > 1 ? `Waiting in line. ${status.position - 1} chosen ${status.position === 2 ? 'trade goes' : 'trades go'} first.` : 'Waiting for the Cable Club to be free.'
    else if (status.state === 'starting') text = 'Checking both Pokémon with their adventures.'
    else if (status.phase === 'preparing') {
      const sides = Object.entries(status.preparation || {}).map(([id, prep]) => `${name(id)} is ${preparationLabels[prep] || 'getting ready'}`)
      text = sides.length ? `${sides.join('. ')}.` : 'Both adventures are heading to the Cable Club.'
    } else if (['aborting', 'recovering'].includes(status.phase)) text = 'Stopping the trade safely. Both adventures keep their Pokémon.'
    else if (!result.done) text = phase(status)
    return {steps: list, text, outcome: result}
  }

  // The same progress as one block of markup, for pages that list several trades.
  function card(status, name = unnamed) {
    const shown = view(status, name)
    const result = shown.outcome.done ? `<p class="manual-result${shown.outcome.failed ? ' error' : ''}">${esc(shown.outcome.text)}</p>` : ''
    return `<div class="manual-progress-card"><ol class="manual-steps">${shown.steps}</ol>${shown.text ? `<p class="manual-text">${esc(shown.text)}</p>` : ''}${result}</div>`
  }

  globalThis.TradeProgress = {phase, outcome, view, card}
})()
