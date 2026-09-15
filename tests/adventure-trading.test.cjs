const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const vm = require('node:vm')
const source = fs.readFileSync('pokesim/web/static/adventure-trading.js', 'utf8')
const settle = async () => {
  for (const tick of [1, 2, 3]) await new Promise(resolve => setImmediate(resolve))
}
function page(id, response) {
  const elements = new Map()
  const calls = []
  let poll
  const element = selector => {
    if (!elements.has(selector)) elements.set(selector, {innerHTML: '', textContent: '', hidden: false, classList: {toggle() {}}})
    return elements.get(selector)
  }
  vm.runInNewContext(source, {
    document: {querySelector: element, hidden: false},
    PokeSim: {adventureId: id, fetch: async path => {
      calls.push(`/games/${id}${path}`)
      return {ok: true, json: async () => response()}
    }}, setInterval(fn) { poll = fn },
  })
  return {element, calls, poll}
}
test('each Red adventure requests only its own trades and renders its own partner history', async () => {
  const create = (id, partner) => page(id, () => ({adventure: {id, version: 'red', state: 'running'}, active: [], history: [
    {phase: 'completed', decision: 'COMMIT', peer_name: partner, updated_at: 1000},
    {phase: 'aborted', decision: 'ABORT', peer_name: 'Failed exchange', updated_at: 1000},
  ]}))
  const first = create('red-one', 'Blue <Ripple>')
  const second = create('red-two', 'Red Ember')
  await settle()
  assert.deepEqual(first.calls, ['/games/red-one/api/interactions'])
  assert.deepEqual(second.calls, ['/games/red-two/api/interactions'])
  assert.match(first.element('#trade-history').innerHTML, /Blue &lt.Ripple&gt./)
  assert.doesNotMatch(first.element('#trade-history').innerHTML, /Red Ember|Failed exchange/)
  assert.match(second.element('#trade-history').innerHTML, /Red Ember/)
})
test('stopped history remains available and failed updates retain it with a reconnect notice', async () => {
  let broken = false
  const view = page('a', () => {
    if (broken) throw new Error('offline')
    return {adventure: {id: 'a', version: 'blue', state: 'stopped'}, active: [], history: [
      {phase: 'completed', decision: 'COMMIT', peer_name: 'First Red', updated_at: 1000},
    ]}
  })
  await settle()
  assert.equal(view.element('#trade-status').textContent, 'Waiting for this adventure')
  const saved = view.element('#trade-history').innerHTML
  broken = true
  view.poll()
  await settle()
  assert.equal(view.element('#trade-history').innerHTML, saved)
  assert.equal(view.element('#trade-connection-note').hidden, false)
})
test('an unexpected adventure response cannot render another game history', async () => {
  const view = page('a', () => ({adventure: {id: 'b'}, active: [], history: []}))
  await settle()
  assert.equal(view.element('#trade-history').innerHTML, '')
  assert.equal(view.element('#trade-connection-note').hidden, false)
})
