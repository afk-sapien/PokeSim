(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp', '<': '&lt', '>': '&gt', '"': '&quot', "'": '&#39'}[char] + String.fromCharCode(59)))
  // One trade setting per Pokémon. Automatic trades follow it, trades you pick yourself ignore it.
  const SETTINGS = [['auto', 'Auto decides'], ['first', 'Trade first'], ['keep', 'Keep']]
  let status = null
  let loading = false
  let writing = false
  let pending = null
  let toastTimer = null
  // The last change, shown under its own row so no toast covers the list.
  let saved = null
  const listeners = []
  const find = key => status?.offers?.find(mon => mon.trade_key === key)
  const setting = mon => mon?.setting || 'auto'
  function control(key, label) {
    const mon = find(key)
    if (!mon) return '<span class="trade-meta">Trade setting unavailable</span>'
    const current = setting(mon)
    const disabled = writing || !status || status.viewer_only || status.holding || !mon.editable
    // Shiny and perfect Pokémon never trade automatically, so Trade first means nothing for them.
    const noFirst = mon.shiny || mon.perfect_dvs
    const options = SETTINGS.map(([value, text]) => `<option value="${value}"${value === current ? ' selected' : ''}${value === 'first' && noFirst && current !== 'first' ? ' disabled' : ''}>${text}</option>`).join('')
    const name = label || mon.nick || mon.name || 'this Pokémon'
    const note = saved?.key === key ? `<span class="trade-saved${saved.error ? ' is-error' : ''}">${esc(saved.text)}</span>` : ''
    return `<label class="trade-setting"><span class="vh">Trade setting for ${esc(name)}</span><select data-trade-key="${esc(key)}" data-trade-setting="${esc(current)}"${disabled ? ' disabled' : ''}>${options}</select></label>${note}`
  }
  function notify() { listeners.forEach(fn => fn(status)) }
  async function refresh() {
    if (loading) return pending
    if (writing) return
    loading = true
    pending = (async () => { try {
      const response = await PokeSim.fetch('/api/trading', {cache: 'no-store'})
      if (!response.ok) throw new Error('Trading is reconnecting.')
      status = await response.json()
    } catch (_) {
      status = {...status, connected: false, unreachable: true, message: 'Trading is reconnecting. Please try again shortly.'}
    } finally { loading = false
      notify() } })()
    return pending
  }
  const messages = {auto: 'Auto decides. Automatic trading may use it when it is a spare.',
    first: 'Trade first. Automatic trading uses it before anything else.',
    keep: 'Keep. Automatic trading never trades it.'}
  async function change(control) {
    if (writing || control.disabled) return
    const state = control.value || control.dataset?.tradeState
    if (!state || state === control.dataset?.tradeSetting) return
    writing = true
    control.disabled = true
    let message
    let error = false
    try {
      const response = await PokeSim.fetch('/api/trading/preferences', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({key: control.dataset.tradeKey, state})})
      const result = await response.json()
      if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not save this setting.')
      message = messages[state] || 'Setting saved.'
    } catch (failure) {
      message = failure.message
      error = true
      if (control.dataset?.tradeSetting && 'value' in control) control.value = control.dataset.tradeSetting
    } finally { writing = false }
    saved = {key: control.dataset?.tradeKey, text: message, error}
    // A page with a settings list announces the change in a quiet live region and shows it
    // under the row. Other pages still use the toast.
    const live = document.querySelector('[data-trade-status]')
    if (live) live.textContent = message
    const toast = live ? null : document.querySelector('#toast')
    if (toast) { toast.textContent = message
      toast.hidden = false
      clearTimeout(toastTimer)
      toastTimer = setTimeout(() => { toast.hidden = true }, 7000) }
    await pending
    await refresh()
  }
  globalThis.TradeUI = {esc, control, find, change, refresh, setting, SETTINGS, subscribe: fn => listeners.push(fn), status: () => status}
})()
