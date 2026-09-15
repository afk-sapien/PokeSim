const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const vm = require('node:vm')
const source = fs.readFileSync('pokesim/web/static/routes.js', 'utf8') + '\n{}\n' + fs.readFileSync('pokesim/web/static/pc.js', 'utf8')

function pc(pokemon, search = '?scope=all', party = [], base = '') {
  const elements = new Map()
  const element = selector => {
    if (!elements.has(selector)) elements.set(selector, {
      value: '', innerHTML: '', textContent: '', options: [{}, {}],
      classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, showModal() {}, focus() {},
    })
    return elements.get(selector)
  }
  let url
  const context = vm.createContext({
    document: {querySelector: selector => selector.startsWith('meta[') ? {content: selector.includes('pokesim-base') ? base : ''} : element(selector), activeElement: null, hidden: false},
    location: {search}, URLSearchParams,
    history: {replaceState: (_, __, next) => { url = next }},
    fetch: async () => ({ok: true, json: async () => ({started: true, version: 'blue', party,
      storage: {active_box: 1, box_counts: Array(12).fill(20), pokemon}})}),
    setInterval() {},
  })
  vm.runInContext(source, context)
  return {
    async ready() { await new Promise(resolve => setImmediate(resolve)) },
    rows: () => JSON.parse(vm.runInContext('JSON.stringify(residents)', context)),
    element, url: () => url,
    sort(key, order) {
      element('#pc-sort').value = key
      element('#pc-sort').onchange()
      if (order) { element('#pc-order').value = order
        element('#pc-order').onchange() }
    },
    refresh: () => vm.runInContext('refresh()', context),
  }
}

const mon = (box, position, level, extra = {}) => ({box, position, level, dex: 25,
  nick: 'Partner', name: 'Pikachu', experience: level ** 3,
  dvs: [1, 2, 3, 4, 5], stat_exp: [0, 0, 0, 0, 0], ...extra})

test('all-box level sorting happens before pagination and leaves storage order intact', async () => {
  const pokemon = Array.from({length: 25}, (_, i) => mon(Math.floor(i / 20) + 1, i % 20 + 1, i + 1))
  const before = JSON.stringify(pokemon)
  const view = pc(pokemon)
  await view.ready()
  view.sort('level')
  assert.deepEqual(view.rows().map(p => p.level), Array.from({length: 20}, (_, i) => 25 - i))
  view.element('#pc-next').onclick()
  assert.deepEqual(view.rows().map(p => p.level), [5, 4, 3, 2, 1])
  view.sort('level', 'asc')
  assert.equal(view.rows()[0].level, 1)
  assert.equal(view.element('#pc-page').textContent, 'Page 1 of 2')
  assert.equal(JSON.stringify(pokemon), before)
})

test('totals include all five stats and missing values sort last in both directions', async () => {
  const view = pc([
    mon(1, 1, 20, {dvs: [], stat_exp: []}),
    mon(2, 1, 20, {dvs: [0, 0, 0, 0, 0]}),
    mon(3, 1, 20, {dvs: [15, 15, 15, 15, 15], stat_exp: [65535, 65535, 65535, 65535, 65535]}),
  ])
  await view.ready()
  for (const field of ['dvs', 'stat_exp']) {
    view.sort(field)
    assert.deepEqual(view.rows().map(p => p.box), [3, 2, 1])
    view.sort(field, 'asc')
    assert.deepEqual(view.rows().map(p => p.box), [2, 3, 1])
  }
  assert.match(view.element('#pc-grid').innerHTML, /327,675/)
  assert.match(view.element('#pc-grid').innerHTML, /Unavailable/)
})

test('bookmarked sorting survives refresh and composes with search and box selection', async () => {
  const view = pc([mon(2, 1, 50, {nick: 'Berry'}), mon(1, 1, 90, {nick: 'Apple'}),
    mon(2, 2, 80, {nick: 'Apple'})], '?scope=all&sort=nick&order=asc')
  await view.ready()
  assert.deepEqual(view.rows().map(p => p.level), [90, 80, 50])
  assert.equal(new URLSearchParams(view.url().split('?')[1]).get('sort'), 'nick')
  view.element('#pc-search').value = 'apple'
  view.element('#pc-search').oninput()
  assert.deepEqual(view.rows().map(p => p.level), [90, 80])
  view.element('#mobile-box').onchange({target: {value: '2'}})
  assert.deepEqual(view.rows().map(p => p.level), [80])
  await view.refresh()
  assert.deepEqual(view.rows().map(p => p.level), [80])
  assert.match(view.url(), /sort=nick&order=asc/)
})

test('strongest shortcut ranks every box and clears previous filters', async () => {
  const pokemon = Array.from({length: 25}, (_, i) => mon(Math.floor(i / 20) + 1, i % 20 + 1, 100 - i,
    {power: 100 + i, calculated_stats: {HP: 10, Attack: 20, Defense: 30, Speed: 40, Special: i}}))
  pokemon.push(mon(3, 1, 100, {power: null}))
  const view = pc(pokemon, '?box=1&q=missing&sort=level')
  await view.ready()
  assert.equal(view.rows().length, 0)
  view.element('#pc-strongest').onclick()
  assert.equal(view.element('#pc-scope').value, 'all')
  assert.equal(view.element('#pc-search').value, '')
  assert.deepEqual(view.rows().map(p => p.power), Array.from({length: 20}, (_, i) => 124 - i))
  view.element('#pc-next').onclick()
  assert.deepEqual(view.rows().map(p => p.power), [104, 103, 102, 101, 100, null])
  view.sort('power', 'asc')
  assert.equal(view.rows()[0].power, 100)
  view.element('#pc-next').onclick()
  assert.equal(view.rows().at(-1).power, null)
  view.sort('Special')
  assert.equal(view.rows()[0].calculated_stats.Special, 24)
  assert.equal(pokemon[0].power, 100)
})

test('power bookmarks survive refresh and details show the five stat breakdown', async () => {
  const view = pc([mon(2, 1, 50, {power: 415,
    calculated_stats: {HP: 110, Attack: 75, Defense: 50, Speed: 110, Special: 70}}),
  mon(1, 1, 100, {power: null})], '?scope=all&sort=power&order=desc')
  await view.ready()
  await view.refresh()
  assert.equal(view.rows()[0].power, 415)
  assert.match(view.url(), /scope=all&sort=power&order=desc/)
  assert.match(view.element('#pc-grid').innerHTML, /Power <b>415/)
  view.element('#pc-grid').onclick({target: {closest: () => ({dataset: {mon: '0'}})}})
  const detail = view.element('#pc-detail-body').innerHTML
  assert.match(detail, /HP<\/th><td>110/)
  assert.match(detail, /Attack<\/th><td>75/)
  assert.match(detail, /Special<\/th><td>70/)
  assert.match(detail, /Power = max HP \+ Attack \+ Defense \+ Speed \+ Special/)
})

test('party joins every combined sort and the strongest shortcut without changing source data', async () => {
  const boxed = Array.from({length: 20}, (_, i) => mon(1, i + 1, 20 + i, {power: 200 + i}))
  const party = [mon(undefined, undefined, 80, {slot: 1, nick: 'Ace', power: 900,
    dvs: [15, 15, 15, 15, 15], stat_exp: [65535, 65535, 65535, 65535, 65535],
    calculated_stats: {HP: 200, Attack: 200, Defense: 200, Speed: 200, Special: 100}})]
  const before = JSON.stringify({boxed, party})
  const view = pc(boxed, '?scope=all', party)
  await view.ready()
  for (const field of ['box', 'power', 'level', 'dvs', 'stat_exp', 'experience', 'dex', 'name', 'nick', 'HP', 'Attack', 'Defense', 'Speed', 'Special']) {
    view.sort(field)
    assert.equal(view.rows()[0].nick, 'Ace', field)
  }
  assert.equal(view.element('#pc-count').textContent, '21 Pokémon')
  assert.match(view.element('#pc-grid').innerHTML, /PARTY · SLOT 1/)
  view.sort('level', 'asc')
  view.element('#pc-next').onclick()
  assert.equal(view.rows()[0].nick, 'Ace')
  view.element('#pc-strongest').onclick()
  assert.equal(view.rows()[0].nick, 'Ace')
  assert.equal(view.element('#pc-page').textContent, 'Page 1 of 2')
  assert.equal(JSON.stringify({boxed, party}), before)
})

test('party selection bookmarks, details, refresh, and box selection remain distinct', async () => {
  const party = [mon(undefined, undefined, 80, {slot: 1, nick: 'Ace', power: 900})]
  const view = pc([mon(2, 1, 90)], '?box=party&sort=power&order=desc', party)
  await view.ready()
  assert.equal(view.rows().length, 1)
  assert.equal(view.rows()[0].box, 0)
  assert.equal(view.element('#pc-heading').textContent, 'Party')
  assert.match(view.url(), /box=party/)
  assert.match(view.element('#box-picker').innerHTML, /data-box="0" aria-pressed="true"/)
  view.element('#pc-grid').onclick({target: {closest: () => ({dataset: {mon: '0'}})}})
  assert.match(view.element('#pc-detail-body').innerHTML, /PARTY · SLOT 1/)
  party[0].level = 81
  await view.refresh()
  assert.match(view.element('#pc-grid').innerHTML, /Lv. 81/)
  view.element('#mobile-box').onchange({target: {value: '2'}})
  assert.deepEqual(view.rows().map(p => p.box), [2])
  view.element('#box-picker').onclick({target: {closest: () => ({dataset: {box: '0'}})}})
  assert.deepEqual(view.rows().map(p => p.box), [0])
  view.element('#pc-search').value = 'missing'
  view.element('#pc-search').oninput()
  assert.equal(view.rows().length, 0)
})

test('box and list modes have separate controls and preserve physical slots', async () => {
  const view = pc([mon(1, 2, 99), mon(1, 1, 10)], '?box=1&sort=level&order=desc')
  await view.ready()
  assert.deepEqual(view.rows().map(mon => mon.position), [1, 2])
  assert.equal(view.element('#pc-sidebar').hidden, false)
  assert.equal(view.element('#pc-sort-control').hidden, true)
  assert.equal(view.element('#pc-pagination').hidden, true)
  assert.match(view.element('#pc-grid').innerHTML, /pc-empty-slot/)
  view.element('#pc-all-view').onclick()
  assert.deepEqual(view.rows().map(mon => mon.level), [99, 10])
  assert.equal(view.element('#pc-sidebar').hidden, true)
  assert.equal(view.element('#pc-sort-control').hidden, false)
  assert.match(view.element('#pc-grid').innerHTML, /pc-list-row/)
  assert.doesNotMatch(view.element('#pc-grid').innerHTML, /pc-empty-slot/)
  view.element('#pc-search').value = 'missing'
  view.element('#pc-search').oninput()
  view.element('#pc-boxes-view').onclick()
  assert.equal(view.element('#pc-search').value, '')
  assert.equal(view.rows().length, 2)
  view.element('#pc-all-view').onclick()
  assert.equal(view.element('#pc-search').value, 'missing')
})


test('PC filters preserve the selected adventure address', async () => {
  const view = pc([mon(1, 1, 20)], '?scope=all', [], '/games/second-red')
  await view.ready()
  view.sort('level')
  assert.match(view.url(), /^\/games\/second-red\/pc\?/)
})
