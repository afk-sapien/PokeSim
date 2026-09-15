const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const vm = require('node:vm')
const source = fs.readFileSync('pokesim/web/static/routes.js', 'utf8')

function routes(base = '', id = '', authenticated = true) {
  const calls = []
  const context = vm.createContext({document: {
    querySelector: name => ({content: name.includes('pokesim-base') ? base : id}),
    addEventListener() {},
  }, fetch: async (path, options = {}) => {
    calls.push({path, options})
    return {ok: path !== '/api/v1/session' || authenticated, json: async () => ({csrf_token: 'owner-csrf', role: 'owner'})}
  }})
  vm.runInContext(source, context)
  return {api: context.PokeSim, calls}
}

test('same-version adventures keep independent request and image addresses', async () => {
  const first = routes('/games/red-one', 'red-one')
  const second = routes('/games/red-two', 'red-two')
  for (const path of ['/api/state', '/frame.jpg', '/sprites/25.png', '/shots/42.png', '/events/42', '/feed.xml', '/pc?scope=all']) {
    assert.equal(first.api.url(path), `/games/red-one${path}`)
    assert.equal(second.api.url(path), `/games/red-two${path}`)
  }
  await first.api.fetch('/api/state')
  await second.api.fetch('/api/state')
  assert.equal(first.calls[0].path, '/games/red-one/api/state')
  assert.equal(second.calls[0].path, '/games/red-two/api/state')
})

test('managed mutations obtain a session and attach CSRF without changing payload', async () => {
  const view = routes('/games/a', 'a')
  const options = {method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{"action":"pause"}'}
  await view.api.fetch('/api/control', options)
  await view.api.fetch('/api/control', options)
  assert.equal(view.calls.filter(call => call.path === '/api/v1/session').length, 1)
  assert.equal(view.calls[1].options.headers['X-PokeSim-CSRF'], 'owner-csrf')
  assert.equal(view.calls[1].options.headers['Content-Type'], 'application/json')
  assert.equal(view.calls[1].options.body, options.body)
  assert.equal(view.calls[1].options.credentials, 'same-origin')
  assert.equal(options.headers['X-PokeSim-CSRF'], undefined)
})

test('session failure cannot send an unauthenticated mutation', async () => {
  const view = routes('/games/a', 'a', false)
  await assert.rejects(view.api.fetch('/api/control', {method: 'POST'}), /sign in/)
  assert.equal(view.calls.length, 1)
  assert.equal(view.calls[0].path, '/api/v1/session')
})

test('standalone routes and controls remain at the root without manager requests', async () => {
  const view = routes()
  await view.api.fetch('/api/control', {method: 'POST'})
  assert.equal(view.calls.length, 1)
  assert.equal(view.calls[0].path, '/api/control')
  assert.equal(view.api.url('/feed.xml'), '/feed.xml')
})

test('game routing refuses external addresses and parent traversal', () => {
  const view = routes('/games/a', 'a')
  for (const path of ['https://example.test', '//example.test', '/../api/control', 'api/control']) {
    assert.throws(() => view.api.url(path), /game route/)
  }
})
