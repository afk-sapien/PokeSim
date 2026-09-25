const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const vm = require('node:vm')
const source = fs.readFileSync('pokesim/web/static/progress.js', 'utf8')

function load(present = false) {
  const elements = new Map()
  const element = selector => {
    if (!elements.has(selector)) elements.set(selector, {hidden: true, textContent: '', innerHTML: ''})
    return elements.get(selector)
  }
  const context = vm.createContext({
    document: {querySelector: selector => present ? element(selector) : null, hidden: false},
    setInterval() {}, Date, Math, Number, String,
    PokeSim: {fetch: async () => ({ok: true, json: async () => []})},
  })
  vm.runInContext(source, context)
  return {Progress: context.Progress, element}
}

test('a step line holds each value until the next change and runs on to now', () => {
  const {Progress} = load()
  const rows = [{ts: 0, owned: 0}, {ts: 50, owned: 151}]
  assert.equal(Progress.stepPath(rows, 'owned', 0, 100, 151), 'M0.0,61.0H300.0V3.0H600')
})

test('rows without a value, like backfilled seen counts, are skipped', () => {
  const {Progress} = load()
  const rows = [{ts: 0, seen: null}, {ts: 10, seen: 4}]
  assert.equal(Progress.stepPath(rows, 'seen', 0, 10, 8), 'M600.0,32.0H600')
  assert.equal(Progress.stepPath([{ts: 0, seen: null}], 'seen', 0, 10, 8), '')
})

test('badges give way to the long goals, which start where their history does', () => {
  const {Progress} = load()
  const rows = [{ts: 0, owned: 10, level100: null, perfect: null, league: 0},
    {ts: 5, owned: 9, level100: 3, perfect: 0, league: 4}]
  const [owned, level100, perfect, league] = Progress.describe(rows, 10)
  assert.deepEqual([owned.first, owned.last, owned.max], [10, 9, 151])
  assert.deepEqual([level100.first, level100.last, level100.max], [3, 3, 151])
  assert.deepEqual([perfect.last, perfect.max, perfect.fixed], [0, 1, false])
  assert.equal(league.max, 4)
  assert.equal(league.path, 'M0.0,61.0H300.0V3.0H600')
})

test('the section stays hidden until there is history, then describes each line', () => {
  const {Progress, element} = load(true)
  Progress.render([])
  assert.equal(element('#road').hidden, true)
  Progress.render([{ts: 0, owned: 1, badges: 0, league: 0}, {ts: 86400 * 3, owned: 40, badges: 3, league: 0, level100: 2, perfect: 1}], 86400 * 3)
  assert.equal(element('#road').hidden, false)
  assert.match(element('#road-span').textContent, /· 3 days$/)
  const html = element('#road-charts').innerHTML
  assert.match(html, /aria-label="Pokédex registered: from 1 to 40"/)
  assert.match(html, /aria-label="League wins: 0 throughout"/)
  assert.match(html, />40<span class="unit">\/151<\/span>/)
  assert.match(html, /aria-label="Perfect finds: 1 throughout"/)
  assert.match(html, />1<\/strong>/)
  assert.doesNotMatch(html, /Badges/)
})
