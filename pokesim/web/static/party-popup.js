// The PC detail popup for one party member, opened from the Live page.
// It draws with the same MonGrid renderer as the PC page. The full record (DVs, stat
// experience, the lock) comes from the PC's party view, fetched when the popup opens and
// again whenever the Live page sees that partner change.
(() => {
  const $ = selector => document.querySelector(selector)
  const fit = root => globalThis.Panel?.fitSprites?.(root)
  const dialog = () => $('#mon-detail')
  // The open partner: slot (1 to 6), the species and nickname it was opened for, and opener, which
  // finds the key to hand focus back to (the party may have been drawn again since).
  let open = null
  let record = null
  let fresh = false
  let viewerOnly = false
  let run = 0
  let lastLive = ''
  // A lock change in flight, and a refused change's reason to show under the toggle.
  let locking = {key: '', note: ''}
  const viewer = () => String(globalThis.PokeSim?.base || '').startsWith('/view/') || viewerOnly
  const same = mon => Boolean(mon) && mon.species === open.species && (mon.nick || '') === open.nick
  const placed = mon => globalThis.PokemonTypes.asEgg({...mon, box: 0, position: open.slot})

  function draw() {
    if (!open || !record) return
    const mon = record
    const focused = document.activeElement?.classList?.contains('lock-toggle')
    const top = viewer() ? '' : MonGrid.lockControl(mon, {stale: !fresh, busy: Boolean(locking.key) && locking.key === mon.trade_key,
      note: locking.note && locking.key === `done:${mon.trade_key}` ? locking.note : ''})
    $('#mon-detail-body').innerHTML = MonGrid.detail(mon, {links: false, top, trade: viewer() ? undefined : false})
    $('#mon-detail-action').innerHTML = `${MonGrid.detailLinks(mon)}${fresh ? MonGrid.tradeLink(mon) : ''}`
    fit($('#mon-detail-body'))
    if (focused) $('#mon-detail-body .lock-toggle')?.focus()
  }

  // Fetch the party as the PC sees it and draw the open partner from it.
  async function load() {
    if (!open) return
    const ticket = ++run
    try {
      const response = await PokeSim.fetch('/api/pokedex/status?view=party', {cache: 'no-store'})
      if (!response.ok) throw new Error('Unavailable')
      const status = await response.json()
      if (ticket !== run || !open || !dialog().open) return
      viewerOnly = status.viewer_only === true
      const party = status.party || []
      const found = party.find(mon => mon.slot === open.slot) || party[open.slot - 1]
      // It moved or left the party since the Live page drew it: the popup no longer fits it.
      if (!same(found)) return dialog().close()
      record = placed(found)
      fresh = true
    } catch (_) {
      if (ticket !== run) return
    }
    draw()
  }

  // Open the popup for party slot index (from 0), drawing the Live record until the full one arrives.
  // opener returns the element that gets focus back when the popup closes.
  function show(index, live, opener) {
    if (!live) return
    open = {slot: index + 1, species: live.species, nick: live.nick || '', opener}
    record = placed(live)
    fresh = false
    lastLive = JSON.stringify(live)
    locking = {key: '', note: ''}
    draw()
    if (!dialog().open) dialog().showModal()
    load()
  }

  // The Live page calls this with each fresh party. A change to the open partner fetches it again.
  function update(party) {
    if (!open || !dialog()?.open) return
    const live = party[open.slot - 1]
    if (!same(live)) return dialog().close()
    const signature = JSON.stringify(live)
    if (signature === lastLive || locking.key && !locking.key.startsWith('done:')) return
    lastLive = signature
    load()
  }

  async function toggle(button) {
    const key = button.dataset.lockKey
    const mon = record
    if (!key || !mon || mon.trade_key !== key || locking.key === key || button.disabled || viewer()) return
    const locked = MonGrid.isLocked(mon)
    const state = locked ? 'auto' : 'keep'
    const before = {trade_setting: mon.trade_setting, trade_locked: mon.trade_locked}
    // Show the new state straight away. A refused change puts the old one back.
    locking = {key, note: ''}
    record = {...mon, trade_setting: state, trade_locked: state === 'keep'}
    draw()
    let note = ''
    try {
      await MonGrid.saveLock(key, state)
    } catch (error) {
      if (record?.trade_key === key) record = {...record, ...before}
      note = error.message
    }
    locking = {key: `done:${key}`, note}
    if (!open || record?.trade_key !== key) return
    draw()
    load()
  }

  const ready = () => {
    const box = dialog()
    if (!box) return
    $('#mon-close').onclick = () => box.close()
    box.addEventListener('close', () => {
      const opener = open?.opener
      open = null
      record = null
      run++
      locking = {key: '', note: ''}
      opener?.()?.focus?.()
    })
    $('#mon-detail-body').addEventListener('click', event => {
      const button = event.target.closest?.('.lock-toggle')
      if (button) toggle(button)
    })
    // A click on the backdrop closes it, as on the PC page.
    box.addEventListener('click', event => {
      if (event.target !== box) return
      const rect = box.getBoundingClientRect()
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) box.close()
    })
  }
  ready()

  globalThis.PartyPopup = {show, update, isOpen: () => Boolean(dialog()?.open)}
})()
