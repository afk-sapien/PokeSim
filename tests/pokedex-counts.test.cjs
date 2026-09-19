const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const vm = require('node:vm')
const source = fs.readFileSync('pokesim/web/static/pokedex.js', 'utf8')

const entry = (dex, name) => ({dex, name, types: ['Electric'], stats: {HP: 35}, total: 320,
  catch_rate: 190, growth: 'Medium', moves: [], evolves_from: [], evolves_to: [], locations: [],
  hms: [], links: {bulbapedia: 'https://example.com', serebii: 'https://example.com', wikipedia: 'https://example.com'}})
const reference = [entry(1, 'Bulbasaur'), entry(25, 'Pikachu'), entry(150, 'Mewtwo')]
const settle = async () => {
  for (const tick of [1, 2, 3]) await new Promise(resolve => setImmediate(resolve))
}

function page(status) {
  const elements = new Map()
  const element = selector => {
    if (!elements.has(selector)) elements.set(selector, {
      value: ['#type-filter', '#status-filter'].includes(selector) ? 'all' : '',
      innerHTML: '', textContent: '', hidden: false, scrollTop: 0, focus() {},
      classList: {add() {}, remove() {}}, querySelectorAll: () => [],
    })
    return elements.get(selector)
  }
  const context = vm.createContext({
    document: {querySelector: element, activeElement: element('#search'), hidden: false, addEventListener() {}},
    window: {addEventListener() {}}, location: {hash: '', pathname: '/games/red/pokedex'},
    history: {replaceState() {}}, setInterval() {},
    PokeSim: {base: '/games/red', fetch: async path => ({ok: true,
      json: async () => path === '/api/pokedex' ? {entries: reference} : status()})},
  })
  vm.runInContext(source, context)
  return {element, context}
}

function status() {
  return {started: true, owned: [25, 150], seen: [1, 25, 150],
    catches: {counts: {'25': 12}, total: 42, started_at: 1789603200, complete_history: false, available: true},
    party: [{dex: 25, nick: 'SPARK', level: 15, slot: 1}],
    storage: {pokemon: [{dex: 25, nick: 'LIGHT', level: 12, box: 1},
      {dex: 25, nick: 'BOLT', level: 14, box: 2}]}}
}

test('cards show caught and current counts even when a species has zero or no remaining copies', async () => {
  const view = page(status)
  await settle()
  const grid = view.element('#grid').innerHTML
  assert.match(grid, /Caught 12 · Have 3/)
  assert.equal((grid.match(/class="card-counts">Caught 0 · Have 0/g) || []).length, 2)
  assert.match(grid, /aria-label="Pikachu, number 025, In Pokédex, Caught 12 · Have 3"/)
  assert.match(grid, /aria-describedby="catch-tracking-note"/)
  assert.equal(view.element('#sum-caught').textContent, 42)
  assert.equal(view.element('#sum-caught-label').textContent, 'Catches tracked')
  assert.match(view.element('#catch-tracking-note').textContent, /^Catches tracked since .*2026/)
})

test('details show counts, party and PC split, locations, and the same partial-history date', async () => {
  const view = page(status)
  await settle()
  view.context.renderDetail(25)
  const detail = view.element('#detail-body').innerHTML
  assert.match(detail, /<dt>Caught<\/dt><dd>12<\/dd>/)
  assert.match(detail, /<dt>Have<\/dt><dd>3<\/dd>/)
  assert.match(detail, /Party 1 · PC 2/)
  assert.ok(detail.includes(view.element('#catch-tracking-note').textContent))
  assert.match(detail, /Party slot 1/)
  assert.match(detail, /Box 1/)
  assert.match(detail, /Box 2/)
  view.context.renderDetail(150)
  assert.match(view.element('#detail-body').innerHTML, /<dt>Caught<\/dt><dd>0<\/dd>/)
  assert.match(view.element('#detail-body').innerHTML, /<dt>Have<\/dt><dd>0<\/dd>/)
  assert.match(view.element('#detail-body').innerHTML, /Party 0 · PC 0/)
})

test('catch-only updates refresh open details and cards without losing scroll position', async () => {
  const current = status()
  const view = page(() => current)
  await settle()
  view.context.renderDetail(25)
  view.element('#detail').scrollTop = 480
  current.catches = {...current.catches, counts: {'25': 13}, total: 43}
  await view.context.refreshStatus()
  assert.match(view.element('#grid').innerHTML, /Caught 13 · Have 3/)
  assert.match(view.element('#detail-body').innerHTML, /<dt>Caught<\/dt><dd>13<\/dd>/)
  assert.equal(view.element('#sum-caught').textContent, 43)
  assert.equal(view.element('#detail').scrollTop, 480)
  current.storage.pokemon.pop()
  await view.context.refreshStatus()
  assert.match(view.element('#grid').innerHTML, /Caught 13 · Have 2/)
  assert.match(view.element('#detail-body').innerHTML, /Party 1 · PC 1/)
})

test('new adventures with complete history identify the total as tracked from the start', async () => {
  const current = status()
  current.catches.complete_history = true
  const view = page(() => current)
  await settle()
  assert.equal(view.element('#sum-caught-label').textContent, 'Total caught')
  assert.equal(view.element('#catch-tracking-note').textContent, 'Catches tracked from the start of this adventure.')
  view.context.renderDetail(25)
  assert.match(view.element('#detail-body').innerHTML, /Catches tracked from the start of this adventure/)
  assert.doesNotMatch(view.element('#detail-body').innerHTML, /Catches tracked since/)
})

test('missing catch history is not inferred from the registered species or held copies', async () => {
  const current = status()
  delete current.catches
  const view = page(() => current)
  await settle()
  assert.match(view.element('#grid').innerHTML, /Catch count unavailable · Have 3/)
  assert.equal(view.element('#sum-caught').textContent, 'Unavailable')
  assert.equal(view.element('#catch-tracking-note').textContent, 'Catch tracking has not started yet.')
})

test('unsupported games display unavailable catch counts while retaining current ownership', async () => {
  const current = status()
  current.catches = {...current.catches, counts: {}, total: 0, available: false}
  const view = page(() => current)
  await settle()
  assert.match(view.element('#grid').innerHTML, /Catch count unavailable · Have 3/)
  assert.doesNotMatch(view.element('#grid').innerHTML, /Caught 0/)
  assert.equal(view.element('#sum-caught').textContent, 'Unavailable')
  assert.equal(view.element('#catch-tracking-note').textContent, 'Catch tracking is unavailable for this game.')
  view.context.renderDetail(25)
  assert.match(view.element('#detail-body').innerHTML, /<dt>Caught<\/dt><dd class="count-unavailable">Unavailable<\/dd>/)
  assert.match(view.element('#detail-body').innerHTML, /<dt>Have<\/dt><dd>3<\/dd>/)
  assert.match(view.element('#detail-body').innerHTML, /Party 1 · PC 2/)
})
