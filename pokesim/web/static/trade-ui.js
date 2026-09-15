(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp', '<': '&lt', '>': '&gt', '"': '&quot', "'": '&#39'}[char] + String.fromCharCode(59)))
  let status = null
  let loading = false
  let writing = false
  let pending = null
  let toastTimer = null
  const listeners = []
  const find = key => status?.offers?.find(mon => mon.trade_key === key)
  function control(key) {
    const mon = find(key)
    if (!mon) return '<span class="trade-meta">Trading details unavailable</span>'
    const selected = mon.listed || mon.preference === 'offered'
    const lockDisabled = writing || status.viewer_only || status.holding || !mon.editable
    const disabled = lockDisabled || !status.connected
    const locked = mon.locked || mon.preference === 'locked'
    const label = locked ? 'Locked against trading and automatic release' : mon.listed ? mon.source : mon.reason || 'Not offered'
    const button = !locked && (selected || mon.can_offer)
      ? `<button data-trade-key="${esc(key)}" data-trade-state="${selected ? 'withdrawn' : 'offered'}" ${disabled ? 'disabled' : ''}>${selected ? 'Withdraw offer' : 'Offer for trade'}</button>` : ''
    const lock = `<button data-trade-key="${esc(key)}" data-trade-state="${locked ? 'unlocked' : 'locked'}" ${lockDisabled ? 'disabled' : ''}>${locked ? 'Unlock Pokémon' : 'Lock Pokémon'}</button>`
    return `<span class="trade-meta">${locked ? '<span aria-hidden="true">🔒</span> ' : ''}${esc(label)}</span><div class="partner-actions">${button}${lock}</div>`
  }
  function notify() { listeners.forEach(fn => fn(status)) }
  async function refresh() {
    if (loading) return pending
    if (writing) return
    loading = true
    pending = (async () => { try {
      const response = await fetch('/api/trading', {cache: 'no-store'})
      if (!response.ok) throw new Error('Trading is reconnecting.')
      status = await response.json()
    } catch (_) {
      status = {...status, connected: false, message: 'Trading is reconnecting. Please try again shortly.'}
    } finally { loading = false
      notify() } })()
    return pending
  }
  async function change(button) {
    if (writing || button.disabled) return
    writing = true
    button.disabled = true
    let message
    try {
      const response = await fetch('/api/trading/preferences', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({key: button.dataset.tradeKey, state: button.dataset.tradeState})})
      const result = await response.json()
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not update this offer.')
      const messages = {withdrawn:'Offer withdrawn. Automatic trading will skip this Pokémon.',
        locked:'Pokémon locked. Trading and automatic release are blocked.',
        unlocked:'Pokémon unlocked. Normal eligibility restored, with no previous manual offer.'}
      message = messages[button.dataset.tradeState] || 'Offer saved. Suitable trades happen automatically.'
    } catch (error) { message = error.message }
    finally { writing = false }
    const toast = document.querySelector('#toast')
    if (toast) { toast.textContent = message
      toast.hidden = false
      clearTimeout(toastTimer)
      toastTimer = setTimeout(() => { toast.hidden = true }, 7000) }
    await pending
    await refresh()
  }
  globalThis.TradeUI = {esc, control, find, change, refresh, subscribe: fn => listeners.push(fn), status: () => status}
})()
