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
  globalThis.PokemonTypes = {badges, portraitClass}
})()
