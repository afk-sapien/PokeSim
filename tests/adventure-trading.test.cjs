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
    PokeSim: {adventureId: id, base: `/games/${id}`, fetch: async path => {
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

test('failed attempts explain missing trades and remain distinct from completed exchanges', async () => {
  const view = page('red', () => ({
    adventure: {id: 'red', version: 'red', state: 'running'}, active: [], history: [],
    attention: {message: '3 recent trade attempts did not complete. An adventure could not reach the Cable Club.'},
    recent_failures: [{phase: 'aborted', decision: 'ABORT', peer_name: 'Blue <Ripple>', updated_at: 1000,
      failure_reason: 'An adventure could not reach the Cable Club.', error: '/private/worker/path'}],
  }))
  await settle()
  assert.equal(view.element('#trade-status').textContent, 'Trades have not been completing')
  assert.match(view.element('#trade-activity').textContent, /3 recent.*Cable Club/)
  assert.equal(view.element('#trade-failures-section').hidden, false)
  assert.match(view.element('#trade-failures').innerHTML, /Blue &lt.Ripple&gt./)
  assert.match(view.element('#trade-failures').innerHTML, /Trade did not complete/)
  assert.match(view.element('#trade-failures').innerHTML, /could not reach the Cable Club/)
  assert.doesNotMatch(view.element('#trade-failures').innerHTML, /private|Trade completed/)
  assert.doesNotMatch(view.element('#trade-history').innerHTML, /Blue/)
})

test('a new attempt is shown as active even when earlier attempts failed', async () => {
  const view = page('red', () => ({
    adventure: {id: 'red', version: 'red', state: 'running'},
    active: [{phase: 'preparing', peer_name: 'Blue'}], history: [],
    attention: {message: 'A previous attempt did not complete.'}, recent_failures: [],
  }))
  await settle()
  assert.equal(view.element('#trade-status').textContent, 'Exchange in progress')
  assert.match(view.element('#trade-active').innerHTML, /Getting ready for the Cable Club/)
  assert.equal(view.element('#trade-failures-section').hidden, true)
})

test('completed cards show the exact sent and received Pokemon with scoped sprites and evolution', async () => {
  const view = page('red', () => ({
    adventure: {id: 'red', version: 'red', state: 'running'}, active: [],
    history: [{phase: 'completed', decision: 'COMMIT', peer_id: 'b'.repeat(32), peer_name: 'Blue Ripple', updated_at: 1000,
      sent: {name: 'Machoke', nickname: 'STRONG <GUY>', level: 42, dex: 67},
      received: {name: 'Machamp', nickname: 'BIG ARMS', level: 55, dex: 68, evolved_from: {name: 'Machoke', dex: 67}}}],
  }))
  await settle()
  const html = view.element('#trade-history').innerHTML
  assert.match(html, /You sent/)
  assert.match(html, /You received/)
  assert.match(html, /\/sprites\/67.png/)
  assert.match(html, /\/sprites\/68.png/)
  assert.match(html, /src="\/games\/red\/sprites\/68.png" alt="" width="64" height="64"/)
  assert.match(html, /STRONG &lt.GUY&gt./)
  assert.match(html, /BIG ARMS/)
  assert.match(html, /Lv. 42/)
  assert.match(html, /Lv. 55/)
  assert.match(html, /Machoke → Machamp/)
  assert.match(html, /pokedex#68/)
  assert.match(html, /<time datetime="1970-01-01T00:16:40.000Z">/)
  assert.match(html, new RegExp(`/games/${'b'.repeat(32)}/trading`))
  assert.equal(view.element('#trade-history-count').textContent, '1 recent exchange')
})

test('planned and failed trades never claim a Pokemon was received or evolved', async () => {
  const details = {peer_name: 'Blue', sent: {name: 'Abra', nickname: 'Abra', dex: 63, level: 12},
    received: {name: 'Machoke', dex: 67, level: 28, evolved_from: {name: 'Machop'}}}
  const view = page('red', () => ({
    adventure: {id: 'red', version: 'red', state: 'running'},
    active: [{...details, phase: 'preparing'}], history: [],
    recent_failures: [{...details, phase: 'aborted', decision: 'ABORT', updated_at: 1000}],
  }))
  await settle()
  assert.match(view.element('#trade-active').innerHTML, /Sending/)
  assert.match(view.element('#trade-active').innerHTML, /Receiving/)
  assert.match(view.element('#trade-failures').innerHTML, /Planned offer/)
  assert.match(view.element('#trade-failures').innerHTML, /Planned return/)
  for (const area of ['#trade-active', '#trade-failures']) {
    assert.doesNotMatch(view.element(area).innerHTML, /You received|Trade evolution|Saved in both/)
  }
})

test('older trades and invalid sprite identifiers render honest fallbacks without broken image URLs', async () => {
  const view = page('red', () => ({
    adventure: {id: 'red', version: 'red', state: 'running'}, active: [],
    history: [{phase: 'completed', decision: 'COMMIT', peer_name: '<script>', updated_at: 1000,
      sent: null, received: {name: 'Unknown', dex: '../../private', nickname: 'Unknown', level: null}}],
  }))
  await settle()
  const html = view.element('#trade-history').innerHTML
  assert.match(html, /Pokémon details unavailable/)
  assert.doesNotMatch(html, /<img|undefined|Lv. null|<script>/)
})
