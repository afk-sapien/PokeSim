const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const vm = require('node:vm')
const source = fs.readFileSync('pokesim/web/static/pc.js', 'utf8')

function pc(pokemon, search = '?scope=all') {
  const elements = new Map()
  const element = selector => {
    if (!elements.has(selector)) elements.set(selector, {
      value: '', innerHTML: '', textContent: '', options: [{}, {}],
      classList: {add() {}, remove() {}}, showModal() {}, focus() {},
    })
    return elements.get(selector)
  }
  let url
  const context = vm.createContext({
    document: {querySelector: element, activeElement: null, hidden: false},
    location: {search}, URLSearchParams,
    history: {replaceState: (_, __, next) => { url = next }},
    fetch: async () => ({ok: true, json: async () => ({started: true, version: 'blue',
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
