const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const vm = require('node:vm')
const crypto = require('node:crypto').webcrypto
const source = fs.readFileSync('pokesim/web/static/library.js', 'utf8')
const settle = async () => {
  for (const tick of [1, 2, 3, 4]) await new Promise(resolve => setImmediate(resolve))
}

function library(options = {}) {
  const elements = new Map()
  const calls = []
  let poll
  const element = selector => {
    if (!elements.has(selector)) elements.set(selector, {
      hidden: selector === '#workspace', value: '', checked: false, files: [], dataset: {}, textContent: '',
      innerHTML: '', classList: {toggle() {}}, setAttribute() {}, hasAttribute: () => false,
      querySelectorAll: () => [], querySelector: () => null, insertAdjacentHTML() {},
      focus() {}, showModal() { this.open = true }, close() { this.open = false }, reset() {},
    })
    return elements.get(selector)
  }
  const location = {hash: options.hash || '', pathname: '/', search: '', replace() {}}
  const context = vm.createContext({
    document: {body: {dataset: {page: options.page || 'library', adventure: ''}}, querySelector: element,
      querySelectorAll: () => [], addEventListener() {}, hidden: false},
    location, history: {replaceState(_, __, path) { calls.push({path: 'history', next: path})
      location.hash = '' }}, crypto, Uint8Array, URLSearchParams, setInterval(callback) { poll = callback },
    fetch: async (path, opts = {}) => {
      calls.push({path, options: opts})
      if (options.respond) {
        const override = options.respond(path, opts)
        if (override) return override
      }
      const data = path === '/api/v1/session' ? {csrf_token: 'csrf', role: 'owner'}
        : path === '/api/v1/assets' ? {roms: [{id: 'rom', version: 'red'}]}
        : path === '/api/v1/adventures' && opts.method === 'POST' ? {id: 'a'.repeat(32)}
        : {adventures: []}
      return {ok: true, json: async () => data}
    },
  })
  vm.runInContext(source, context)
  return {element, calls, context, poll}
}

test('library opens automatically with a GET session and never submits fragment credentials', async () => {
  const view = library({hash: '#token=secret-owner'})
  await settle()
  assert.equal(view.calls[0].path, '/api/v1/session')
  assert.equal(view.calls[0].options.method, undefined)
  assert.equal(view.calls.some(call => call.options?.body?.includes('secret-owner')), false)
  assert.equal(view.element('#workspace').hidden, false)
  assert.equal(view.element('#connection').textContent, 'Connected')
  assert.doesNotMatch(fs.readFileSync('pokesim/web/static/library.html', 'utf8'), /owner.key|sign.in/i)
})

test('create can reuse a ROM without starting and sends a stable-format idempotency key', async () => {
  const view = library()
  await settle()
  view.element('#new-name').value = 'Second Red'
  view.element('#rom-select').value = 'rom'
  view.element('#starter').value = 'charmander'
  view.element('#start-created').checked = false
  view.element('#create-form').onsubmit({preventDefault() {}})
  await settle()
  const request = view.calls.find(call => call.path === '/api/v1/adventures' && call.options.method === 'POST')
  const payload = JSON.parse(request.options.body)
  assert.equal(payload.name, 'Second Red')
  assert.match(payload.request_id, /^[a-f0-9]{32}$/)
  assert.equal(request.options.headers['X-PokeSim-CSRF'], 'csrf')
  assert.equal(view.calls.some(call => call.path.endsWith('/start')), false)
})

test('settings mutations send only fields accepted by the manager', async () => {
  const view = library()
  await settle()
  view.element('#settings-id').value = 'a'.repeat(32)
  view.element('#settings-name').value = 'Renamed adventure'
  view.element('#settings-speed').value = '4'
  view.element('#settings-autostart').checked = true
  view.element('#adventure-settings-form').onsubmit({preventDefault() {}})
  await settle()
  const request = view.calls.find(call => call.options?.method === 'PATCH')
  assert.deepEqual(JSON.parse(request.options.body), {name: 'Renamed adventure', settings: {speed: 4, auto_start: true}})
})

test('failed creation retains idempotency key for an identical retry and exposes the error in the dialog', async () => {
  let attempts = 0
  const view = library({respond: (path, options) => {
    if (path === '/api/v1/adventures' && options.method === 'POST') {
      attempts += 1
      if (attempts === 1) return {ok: false, status: 503, json: async () => ({detail: 'Retry this request'})}
    }
  }})
  await settle()
  view.element('#new-name').value = 'Red'
  view.element('#rom-select').value = 'rom'
  view.element('#starter').value = 'random'
  view.element('#create-form').onsubmit({preventDefault() {}})
  await settle()
  assert.equal(view.element('dialog[open] .dialog-feedback').textContent, 'Retry this request')
  view.element('#create-form').onsubmit({preventDefault() {}})
  await settle()
  const requests = view.calls.filter(call => call.path === '/api/v1/adventures' && call.options.method === 'POST')
  assert.equal(requests.length, 2)
  assert.equal(JSON.parse(requests[0].options.body).request_id, JSON.parse(requests[1].options.body).request_id)
})

test('expired CSRF renews the session and retries the exact creation once', async () => {
  let sessions = 0
  let attempts = 0
  const view = library({respond: (path, options) => {
    if (path === '/api/v1/session') return {ok: true, json: async () => ({csrf_token: `csrf-${++sessions}`, role: 'owner'})}
    if (path === '/api/v1/adventures' && options.method === 'POST' && ++attempts === 1) {
      return {ok: false, status: 403, json: async () => ({detail: 'Reload this page before making changes'})}
    }
  }})
  await settle()
  view.element('#new-name').value = 'Red'
  view.element('#rom-select').value = 'rom'
  view.element('#starter').value = 'random'
  view.element('#create-form').onsubmit({preventDefault() {}})
  await settle()
  const requests = view.calls.filter(call => call.path === '/api/v1/adventures' && call.options.method === 'POST')
  assert.equal(sessions, 2)
  assert.equal(requests.length, 2)
  assert.equal(requests[0].options.body, requests[1].options.body)
  assert.equal(requests[0].options.headers['X-PokeSim-CSRF'], 'csrf-1')
  assert.equal(requests[1].options.headers['X-PokeSim-CSRF'], 'csrf-2')
})

test('CSRF renewal is bounded and unrelated permission failures are not retried', async () => {
  for (const detail of ['Reload this page before making changes', 'Origin is not allowed']) {
    const view = library({respond: (path, options) => {
      if (options.method === 'PATCH') return {ok: false, status: 403, json: async () => ({detail})}
    }})
    await settle()
    view.element('#max-running').value = '4'
    view.element('#settings-form').onsubmit({preventDefault() {}})
    await settle()
    assert.equal(view.calls.filter(call => call.options.method === 'PATCH').length, detail.startsWith('Reload') ? 2 : 1)
    assert.equal(view.element('#notice').textContent, detail)
  }
})

test('startup connection failure recovers automatically but shutdown stays closed', async () => {
  let attempts = 0
  const view = library({respond: path => {
    if (path === '/api/v1/session' && ++attempts === 1) return {ok: false, status: 503, json: async () => ({detail: 'Starting up'})}
  }})
  await settle()
  assert.equal(view.element('#workspace').hidden, true)
  assert.equal(view.element('#connection').textContent, 'Reconnecting')
  view.poll()
  await settle()
  assert.equal(view.element('#workspace').hidden, false)
  assert.equal(view.element('#connection').textContent, 'Connected')
  view.element('#quit').onclick()
  await settle()
  const count = view.calls.length
  view.poll()
  await settle()
  assert.equal(view.calls.length, count)
  assert.equal(view.element('#workspace').hidden, true)
})

test('automatic trading shows friendly progress and only completed history without mutations or inventory requests', async () => {
  const view = library({page: 'trading', respond: path => {
    if (path === '/api/v1/adventures') return {ok: true, json: async () => ({adventures: [
      {id: 'one', name: 'Red Sprout', state: 'running'},
      {id: 'two', name: 'Blue Ripple', state: 'running'}
    ]})}
    if (path === '/api/v1/interactions') return {ok: true, json: async () => ({
      enabled: true, participants: ['one', 'two'],
      active: [{left_id: 'one', right_id: 'two', phase: 'staging', message: 'manifest technical detail', cancellable: true}],
      history: [
        {left_id: 'one', right_id: 'two', phase: 'completed', decision: 'COMMIT', updated_at: 100},
        {left_id: 'one', right_id: 'two', phase: 'aborted', decision: 'ABORT', error: 'secret worker failure'},
        {left_id: 'one', right_id: 'two', phase: 'completed', decision: 'ABORT'},
        {left_id: 'one', right_id: 'two', phase: 'recovering', decision: 'COMMIT'}
      ]
    })}
  }})
  await settle()
  assert.equal(view.element('#trading-status').textContent, '2 adventures can trade automatically.')
  assert.match(view.element('#trade-active').innerHTML, /Red Sprout ↔ Blue Ripple/)
  assert.match(view.element('#trade-active').innerHTML, /Checking both saves/)
  assert.doesNotMatch(view.element('#trade-active').innerHTML, /staging|manifest|button/)
  assert.equal((view.element('#trade-history').innerHTML.match(/Trade completed/g) || []).length, 1)
  assert.doesNotMatch(view.element('#trade-history').innerHTML, /ABORT|recovering|secret worker/)
  view.poll()
  await settle()
  assert.equal(view.calls.some(call => call.options.method && call.options.method !== 'GET'), false)
  assert.equal(view.calls.some(call => call.path.includes('inventory')), false)
  const html = fs.readFileSync('pokesim/web/static/library.html', 'utf8')
  assert.doesNotMatch(html, /participants-form|trading-enabled|trade-form|trade-left|trade-right|Trading group|Choose an exchange/)
  assert.doesNotMatch(source, /data-trade-action|trade-inventory|participants-form|trading-enabled/)
})

test('automatic trade recovery never shows an aborted exchange as successful or exposes worker errors', async () => {
  for (const decision of ['ABORT', 'COMMIT']) {
    const view = library({page: 'trading', respond: path => {
      if (path === '/api/v1/interactions') return {ok: true, json: async () => ({
        participants: [], active: [{phase: 'recovering', decision, error: 'checkpoint_sha256 wrong /private/path'}],
        history: [{phase: 'aborted', decision: 'ABORT'}]
      })}
    }})
    await settle()
    assert.match(view.element('#trade-active').innerHTML, decision === 'ABORT' ? /Getting ready to try again/ : /Finishing the exchange safely/)
    assert.doesNotMatch(view.element('#trade-active').innerHTML, /checkpoint|private|recovering|Trade completed|button/)
    assert.match(view.element('#trade-history').innerHTML, /No completed trades yet/)
  }
})

test('automatic trade issues show a retry explanation without technical messages', async () => {
  const view = library({page: 'trading', respond: path => {
    if (path === '/api/v1/interactions') return {ok: true, json: async () => ({
      participants: ['one'], active: [], history: [], message: 'Trading needs attention: private exception'
    })}
  }})
  await settle()
  assert.match(view.element('#trade-active').innerHTML, /try again/)
  assert.doesNotMatch(view.element('#trade-active').innerHTML, /private exception/)
  assert.match(view.element('#trading-status').textContent, /two eligible adventures/)
})
