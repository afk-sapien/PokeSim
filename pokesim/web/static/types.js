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
  const eggPlate = '<span class="plate-num egg-plate">EGG</span>'
  globalThis.PokemonTypes = {badges, portraitClass, shinyBadge, asEgg, eggPlate}
})()
