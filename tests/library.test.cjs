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
    document: {body: {dataset: {page: 'library', adventure: ''}}, querySelector: element,
      querySelectorAll: () => [], addEventListener() {}, hidden: false},
    location, history: {replaceState(_, __, path) { calls.push({path: 'history', next: path})
      location.hash = '' }}, crypto, Uint8Array, URLSearchParams, setInterval() {},
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
  return {element, calls, context}
}

test('owner bootstrap consumes fragment before sending token and clears it from the URL', async () => {
  const view = library({hash: '#token=secret-owner'})
  await settle()
  assert.equal(view.calls[0].path, 'history')
  const login = view.calls.find(call => call.path === '/api/v1/session' && call.options.method === 'POST')
  assert.deepEqual(JSON.parse(login.options.body), {token: 'secret-owner'})
  assert.equal(view.context.location.hash, '')
  assert.equal(view.element('#workspace').hidden, false)
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
