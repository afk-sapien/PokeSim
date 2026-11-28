const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const vm = require('node:vm')
const source = fs.readFileSync('pokesim/web/static/app.js', 'utf8')
const settle = async () => {
  for (const tick of [1, 2, 3, 4, 5, 6]) await new Promise(resolve => setImmediate(resolve))
}

function element() {
  return {innerHTML: '', textContent: '', hidden: false, title: '', dataset: {}, style: {},
    classList: {toggle() {}, add() {}, remove() {}, contains: () => false},
    setAttribute() {}, removeAttribute() {}, addEventListener() {}}
}

// The journal page with an adventure that has logged entries 1 to `count`, newest first like /api/events.
function journal(count) {
  const log = {count}
  const elements = {}
  const timers = []
  const fetch = async url => {
    if (!url.startsWith('/api/events')) return {ok: false, json: async () => ({})}
    const query = new URLSearchParams(url.split('?')[1])
    const before = query.has('before') ? Number(query.get('before')) : Infinity
    const rows = []
    for (let id = Math.min(log.count, before - 1); id >= 1 && rows.length < Number(query.get('limit')); id -= 1) {
      rows.push({id, ts: id, type: 'map', title: `Place ${id}`})
    }
    return {ok: true, json: async () => rows}
  }
  const context = vm.createContext({
    PokeSim: {fetch, url: path => path, base: '', sprite: () => '', setSpeed() {}},
    location: {pathname: '/journal', hash: ''},
    document: {hidden: false, addEventListener() {}, querySelectorAll: () => [],
      querySelector: selector => (elements[selector] ??= element())},
    window: {addEventListener() {}},
    setInterval: (callback, ms) => timers.push([callback, ms]),
    setTimeout, clearTimeout, URLSearchParams, console,
  })
  vm.runInContext(source, context)
  const shown = () => [...elements['#events'].innerHTML.matchAll(/\/events\/(\d+)"/g)].map(match => Number(match[1]))
  const poll = async () => {
    for (const [callback, ms] of timers) if (ms === 15000) callback()
    await settle()
  }
  const more = async () => {
    elements['#load-more'].onclick()
    await settle()
  }
  return {log, shown, poll, more, button: () => elements['#load-more']}
}

const range = (high, low) => Array.from({length: high - low + 1}, (_, index) => high - index)

test('a journal that missed more than a page of entries can still page back through all of them', async () => {
  const page = journal(8)
  await settle()
  assert.deepEqual(page.shown(), range(8, 1))
  page.log.count = 20
  await page.poll()
  while (!page.button().hidden) await page.more()
  assert.deepEqual(page.shown(), range(20, 1))
})

test('an open journal keeps only the entries its viewer asked for', async () => {
  const page = journal(8)
  await settle()
  for (let round = 0; round < 40; round += 1) {
    page.log.count += 3
    await page.poll()
  }
  assert.deepEqual(page.shown(), range(page.log.count, page.log.count - 7))
  assert.equal(page.button().hidden, false)
  await page.more()
  page.log.count += 3
  await page.poll()
  assert.deepEqual(page.shown(), range(page.log.count, page.log.count - 15))
})
