(() => {
  const $ = selector => document.querySelector(selector)
  const pokemon = document.body.dataset.ledger === 'pokemon'
  const columns = pokemon
    ? [['wild', 'Wild encounters'], ['trainer', 'Trainer opponents'], ['defeated', 'Defeated'], ['caught', 'Caught'], ['gift', 'Custom gifts'], ['traded_in', 'Traded in'], ['traded_out', 'Traded out'], ['held', 'Held now']]
    : [['bought', 'Purchased'], ['used', 'Used'], ['bag', 'In bag now']]
  const params = new URLSearchParams(location.search)
  let rows = []
  let itemArtwork = null
  let descending = params.get('order') === 'desc'
  let busy = false
  const add = (parent, tag, text = '') => {
    const node = document.createElement(tag)
    node.textContent = text
    parent.append(node)
    return node
  }
  for (const [key, label] of [['id', 'Number'], ['name', 'Name'], ...columns]) {
    const option = add($('#ledger-sort'), 'option', label)
    option.value = key
  }
  $('#ledger-search').value = params.get('q') || ''
  $('#ledger-filter').value = params.get('show') === 'recorded' ? 'recorded' : 'all'
  if ([...$('#ledger-sort').options].some(option => option.value === params.get('sort'))) $('#ledger-sort').value = params.get('sort')
  const head = add($('#ledger-head'), 'tr')
  for (const label of [pokemon ? 'Pokémon' : 'Item', ...columns.map(column => column[1])]) {
    add(head, 'th', label).scope = 'col'
  }
  $('#ledger-help').textContent = pokemon
    ? 'Encounters count each wild Pokémon or trainer opponent entering battle. Defeated includes both. Caught excludes gifts and trades. Custom gifts include PokeSim League rewards. Trades count completed cable and NPC exchanges, using the received form after evolution and the sent form before evolution. Held now includes the party and every PC box.'
    : 'Purchased counts quantities bought at shops and vending machines. Used counts consumed items, including balls thrown, healing items, stones, and TMs. Reusable items show “Not counted”. Moving, selling, discarding, or giving items away does not count as use.'
  function render() {
    const query = $('#ledger-search').value.trim().toLocaleLowerCase().replace(/^#/, '')
    const field = $('#ledger-sort').value
    const sortedColumn = columns.findIndex(column => column[0] === field) + 1
    head.querySelectorAll('th').forEach((cell, index) => {
      if (index === sortedColumn) cell.setAttribute('aria-sort', descending ? 'descending' : 'ascending')
      else cell.removeAttribute('aria-sort')
    })
    const selected = rows.filter(row => (!query || (/^\d+$/.test(query) ? row.id === Number(query) : row.name.toLocaleLowerCase().includes(query)))
      && ($('#ledger-filter').value !== 'recorded' || columns.some(([key]) => row[key] > 0)))
    selected.sort((a, b) => {
      const left = a[field]
      const right = b[field]
      if (left == null && right != null) return 1
      if (right == null && left != null) return -1
      const difference = typeof left === 'string' ? left.localeCompare(right) : (left ?? 0) - (right ?? 0)
      return difference * (descending ? -1 : 1) || a.id - b.id
    })
    const fragment = document.createDocumentFragment()
    for (const row of selected) {
      const tr = add(fragment, 'tr')
      tr.dataset.id = row.id
      const name = add(tr, 'th')
      name.scope = 'row'
      const identity = add(name, 'div')
      identity.className = 'ledger-identity'
      if (pokemon || itemArtwork) {
        const sprite = add(identity, 'img')
        sprite.src = pokemon ? PokeSim.url(`/sprites/${row.id}.png`)
          : `/api/v1/item-artwork/images/${row.id}.png?v=${encodeURIComponent(itemArtwork)}`
        sprite.addEventListener('error', () => { sprite.hidden = true }, {once: true})
        sprite.alt = ''
        sprite.width = sprite.height = 40
        sprite.loading = 'lazy'
      }
      const label = add(identity, 'span', row.name)
      add(label, 'small', `#${String(row.id).padStart(3, '0')}`)
      for (const [key] of columns) {
        const value = row[key]
        const cell = add(tr, 'td', value == null ? 'Not counted' : value.toLocaleString())
        if (value == null) cell.className = 'ledger-unknown'
      }
    }
    if (!selected.length) add(add(fragment, 'tr'), 'td', 'No matching records.').colSpan = columns.length + 1
    $('#ledger-rows').replaceChildren(fragment)
    $('#ledger-status').textContent = `${selected.length} of ${rows.length} ${pokemon ? 'Pokémon' : 'items'}`
    $('#ledger-order').textContent = descending ? 'Descending' : 'Ascending'
    $('#ledger-order').setAttribute('aria-label', descending ? 'Sort ascending' : 'Sort descending')
  }
  function change() {
    const next = new URLSearchParams()
    if ($('#ledger-search').value) next.set('q', $('#ledger-search').value)
    if ($('#ledger-filter').value !== 'all') next.set('show', $('#ledger-filter').value)
    if ($('#ledger-sort').value !== 'id') next.set('sort', $('#ledger-sort').value)
    if (descending) next.set('order', 'desc')
    history.replaceState(null, '', location.pathname + (next.size ? '?' + next : ''))
    render()
  }
  $('#ledger-search').addEventListener('input', change)
  $('#ledger-filter').addEventListener('change', change)
  $('#ledger-sort').addEventListener('change', () => {
    descending = !['id', 'name'].includes($('#ledger-sort').value)
    change()
  })
  $('#ledger-order').addEventListener('click', () => { descending = !descending
    change() })
  async function refresh() {
    if (busy) return
    busy = true
    try {
      const response = await PokeSim.fetch('/api/statistics/activity', {cache: 'no-store'})
      if (!response.ok) throw new Error('Statistics unavailable')
      const data = await response.json()
      rows = data[pokemon ? 'pokemon' : 'items']
      if (!pokemon) {
        try {
          const response = await fetch('/api/v1/item-artwork', {cache: 'no-store'})
          const artwork = response.ok ? await response.json() : null
          itemArtwork = artwork?.active === 'community' ? artwork.revision : null
        } catch (_) { /* Keep the last known artwork setting while reconnecting. */ }
      }
      const shop = data.champion_shop
      const offers = $('#champion-shop')
      offers.hidden = pokemon || !shop
      if (!pokemon && shop) {
        const progress = !shop.available ? 'Walking progress is unavailable for this cartridge.'
          : !shop.started ? 'Each countdown begins after becoming Champion.'
            : shop.offers.map(offer => `${offer.quantity} × ${offer.name}: ${offer.remaining ? offer.remaining.toLocaleString() + ' steps remaining' : 'ready to purchase'} (₽${offer.price.toLocaleString()})`).join(' · ')
        offers.textContent = `Champion shop: ${progress} Each offer holds one purchase and renews after another 1,000,000 steps. The automatic player buys when needed, with bag space and a ₽20,000 reserve.`
      }
      const date = value => new Date(value * 1000).toLocaleString(undefined, {dateStyle: 'medium'})
      let coverage = data.started_at ? `Actions since ${date(data.started_at)}. Earlier activity is not estimated.`
        : 'Action tracking begins when this adventure runs on a supported Red or Blue cartridge.'
      if (data.started_at && !data.available) coverage += ' Action tracking is currently unavailable for this cartridge.'
      if (pokemon && data.captures_available && data.captures_since) coverage += ` Catch records since ${date(data.captures_since)} are included.`
      if (pokemon) {
        coverage += data.trade_records?.npc_since ? ` Trades include verified cable history and NPC exchanges since ${date(data.trade_records.npc_since)}.` : ' Verified cable trades are included. NPC tracking begins when this adventure runs.'
        if (data.trade_records?.missing_history) coverage += ' Older trades with missing species records are excluded.'
      }
      $('#ledger-coverage').textContent = coverage
      render()
    } catch (_) {
      $('#ledger-status').textContent = 'Records are reconnecting. Previously loaded totals are still shown.'
    } finally {
      busy = false
    }
  }
  refresh()
  setInterval(() => { if (!document.hidden) refresh() }, 10000)
})()
