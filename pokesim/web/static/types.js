// Shared type labels use a fixed vocabulary, including a neutral unknown state.
(() => {
  const names = ['Normal', 'Fighting', 'Flying', 'Poison', 'Ground', 'Rock', 'Bug',
    'Ghost', 'Fire', 'Water', 'Grass', 'Electric', 'Psychic', 'Ice', 'Dragon', 'Dark', 'Steel']
  const labels = new Map(names.map(name => [name.toLowerCase(), name]))
  const badges = types => {
    if (!Array.isArray(types)) return ''
    const keys = [...new Set(types.map(type => {
      const key = String(type ?? '').trim().toLowerCase()
      return labels.has(key) ? key : 'unknown'
    }))]
    return keys.map(key => `<span class="tag type-badge type-${key}">${labels.get(key) || 'Unknown'}</span>`).join('')
  }
  const portraitClass = types => {
    const key = Array.isArray(types) ? String(types[0] ?? '').trim().toLowerCase() : ''
    return labels.has(key) ? `type-${key}` : 'type-unknown'
  }
  const shinyBadge = mon => mon?.shiny ? '<span class="tag shiny-badge" title="Gen 2 shiny DVs. Collected shiny partners are protected from automatic release and trading.">★ Shiny</span>' : ''
  // An egg has not hatched, so its species, types, DVs and moves are not shown yet.
  const asEgg = mon => mon?.egg ? {...mon, name: 'Egg', nick: 'Egg', dex: null, type_names: [], shiny: false,
    dvs: null, dv_stars: null, perfect_dvs: false, move_details: [], experience: null, held_item_name: null} : mon
  // Drawn inline so no portrait is requested: a speckled egg like the one the games show.
  const eggPlate = '<span class="egg-plate" role="img" aria-label="Egg"><svg viewBox="0 0 32 32" width="40" height="40" aria-hidden="true">'
    + '<path d="M16 3C9.5 3 6 13 6 19a10 10 0 0 0 20 0C26 13 22.5 3 16 3Z" fill="#F4EFD8" stroke="currentColor" stroke-width="1.5"/>'
    + '<circle cx="12" cy="15" r="2" fill="#8FB070"/><circle cx="19" cy="11" r="1.5" fill="#8FB070"/>'
    + '<circle cx="20" cy="21" r="2.5" fill="#8FB070"/><circle cx="12" cy="24" r="1.5" fill="#8FB070"/></svg></span>'
  globalThis.PokemonTypes = {badges, portraitClass, shinyBadge, asEgg, eggPlate}
})()
