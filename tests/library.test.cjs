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

test('adventure cards show League wins independently of reward counts', async () => {
  const view = library({respond(path) {
    if (path !== '/api/v1/adventures') return null
    return {ok: true, json: async () => ({adventures: [{
      id: 'a'.repeat(32), name: 'Red', version: 'red', state: 'running',
      summary: {league_rewards: {wins: 300, earned: 2, delivered: 2}},
    }]})}
  }})
  let markup = ''
  view.element('#adventure-list').insertAdjacentHTML = (_, html) => { markup += html }
  await settle()
  assert.match(markup, /300 League wins/)
  assert.doesNotMatch(markup, />2 League wins/)
})

test('settings mutations send only fields accepted by the manager', async () => {
  const view = library()
  await settle()
  view.element('#settings-id').value = 'a'.repeat(32)
  view.element('#settings-name').value = 'Renamed adventure'
  view.element('#settings-autostart').checked = true
  view.element('#adventure-settings-form').onsubmit({preventDefault() {}})
  await settle()
  const request = view.calls.find(call => call.options?.method === 'PATCH')
  assert.deepEqual(JSON.parse(request.options.body), {name: 'Renamed adventure', settings: {auto_start: true}})
})

test('global settings load and save simulation pace without overwriting edits during refresh', async () => {
  const view = library({page: 'settings', respond: path => {
    if (path === '/api/v1/settings') return {ok: true, json: async () => ({max_running: 3, speed: 1})}
  }})
  await settle()
  assert.equal(view.element('#simulation-speed').value, '1')
  assert.equal(view.element('#max-running').value, 3)
  view.element('#simulation-speed').value = '0.5'
  view.element('#max-running').value = '4'
  view.element('#settings-form').oninput()
  view.poll()
  await settle()
  assert.equal(view.element('#simulation-speed').value, '0.5')
  assert.equal(view.element('#max-running').value, '4')
  view.element('#settings-form').onsubmit({preventDefault() {}})
  await settle()
  const request = view.calls.find(call => call.path === '/api/v1/settings' && call.options.method === 'PATCH')
  assert.deepEqual(JSON.parse(request.options.body), {max_running: 4, speed: 0.5})
  assert.equal(request.options.headers['X-PokeSim-CSRF'], 'csrf')
})

test('global pace preserves unlimited zero and protects edits made while initial settings load', async () => {
  let finishSettings
  const view = library({page: 'settings', respond: (path, options) => {
    if (path === '/api/v1/settings' && !options.method) return {ok: true, json: () => new Promise(resolve => { finishSettings = resolve })}
  }})
  await settle()
  view.element('#simulation-speed').value = '0'
  view.element('#max-running').value = '6'
  view.element('#settings-form').onchange()
  finishSettings({speed: 1, max_running: 3})
  await settle()
  assert.equal(view.element('#simulation-speed').value, '0')
  assert.equal(view.element('#max-running').value, '6')
  view.element('#settings-form').onsubmit({preventDefault() {}})
  await settle()
  const request = view.calls.find(call => call.path === '/api/v1/settings' && call.options.method === 'PATCH')
  assert.deepEqual(JSON.parse(request.options.body), {max_running: 6, speed: 0})
})

test('saved settings explain when reconnecting adventures still need the new pace', async () => {
  for (const pace_pending of [[], ['reconnecting-adventure']]) {
    const view = library({page: 'settings', respond: path => {
      if (path === '/api/v1/settings') return {ok: true, json: async () => ({max_running: 3, speed: 1, pace_pending})}
    }})
    await settle()
    view.element('#settings-form').onsubmit({preventDefault() {}})
    await settle()
    assert.equal(view.element('#notice').textContent, pace_pending.length
      ? 'Settings saved. The pace will apply to reconnecting adventures automatically.'
      : 'Application settings saved.')
  }
})

test('simulation pace appears only in global settings with a recommended default and testing maximum', async () => {
  const html = fs.readFileSync('pokesim/web/static/library.html', 'utf8')
  const dashboard = fs.readFileSync('pokesim/web/static/index.html', 'utf8')
  const app = fs.readFileSync('pokesim/web/static/app.js', 'utf8')
  assert.match(html, /id="simulation-speed"/)
  assert.match(html, /value="1" selected>1× \(recommended\)/)
  assert.match(html, /value="0">Max \(testing\)/)
  assert.doesNotMatch(html, /settings-speed|The pace applies to this adventure/)
  assert.doesNotMatch(source, /settings-speed/)
  assert.doesNotMatch(dashboard, /id="speed"|speed-label|AI pace/)
  assert.doesNotMatch(app, /\$\('#speed'\)|control\([^\n]*'speed'/)
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
  assert.match(view.element('#trade-active').innerHTML, /Red Sprout/)
  assert.match(view.element('#trade-active').innerHTML, /Blue Ripple/)
  assert.equal(view.element('#trade-active-section').hidden, false)
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

test('global trading shows persistent travel failures instead of saying adventures are ready', async () => {
  const view = library({page: 'trading', respond: path => {
    if (path === '/api/v1/interactions') return {ok: true, json: async () => ({
      participants: ['one', 'two'], active: [], history: [],
      attention: {message: '12 recent trade attempts did not complete. An adventure could not reach the Cable Club.'},
      recent_failures: [{phase: 'aborted', decision: 'ABORT', updated_at: 1000,
        failure_reason: 'An adventure could not reach the Cable Club.', error: '/private/path'}],
    })}
  }})
  await settle()
  assert.match(view.element('#trading-status').textContent, /12 recent.*Cable Club/)
  assert.doesNotMatch(view.element('#trading-status').textContent, /can trade automatically/)
  assert.match(view.element('#trade-active').innerHTML, /try again/)
  assert.equal(view.element('#trade-failures-section').hidden, false)
  assert.match(view.element('#trade-failures').innerHTML, /Trade did not complete/)
  assert.match(view.element('#trade-failures').innerHTML, /could not reach the Cable Club/)
  assert.doesNotMatch(view.element('#trade-failures').innerHTML, /private/)
  assert.match(view.element('#trade-history').innerHTML, /No completed trades yet/)
})

test('shared trade history shows both arrivals, sprites and verified evolutions while hiding idle exchanges', async () => {
  const left = 'a'.repeat(32)
  const right = 'b'.repeat(32)
  const view = library({page: 'trading', respond: path => {
    if (path === '/api/v1/adventures') return {ok: true, json: async () => ({adventures: [
      {id: left, name: 'Red <Sprout>', state: 'running'},
      {id: right, name: 'Blue Ripple', state: 'stopped'}
    ]})}
    if (path === '/api/v1/interactions') return {ok: true, json: async () => ({
      participants: [left, right], active: [], history: [{
        left_id: left, right_id: right, phase: 'completed', decision: 'COMMIT', display: {
          [left]: {received: {name: 'Oddish', nickname: '<SPROUT>', dex: 43, level: 12}},
          [right]: {received: {name: 'Gengar', dex: 94, level: 33, evolved_from: {name: 'Haunter'}}}
        }
      }]
    })}
  }})
  await settle()
  const html = view.element('#trade-history').innerHTML
  assert.equal(view.element('#trade-active-section').hidden, true)
  assert.match(html, new RegExp(`/games/${left}/sprites/43.png`))
  assert.match(html, new RegExp(`/games/${right}/sprites/94.png`))
  assert.match(html, new RegExp(`/games/${right}/trading`))
  assert.match(html, /Haunter → Gengar/)
  assert.match(html, /Received · Lv. 33/)
  assert.match(html, /&lt.*SPROUT.*&gt/)
  assert.doesNotMatch(html, /<SPROUT>/)
  assert.equal(view.element('#trade-history-count').textContent, '1 recent exchange')
})

test('missing historical Pokémon remain unknown and active offers do not claim an evolution', async () => {
  const view = library({page: 'trading', respond: path => {
    if (path === '/api/v1/interactions') return {ok: true, json: async () => ({
      participants: [], active: [{left_id: 'one', right_id: 'two', phase: 'preparing', display: {
        one: {received: {name: 'Haunter', dex: -1, level: 999, evolved_from: {name: 'Gastly'}}}
      }}], history: [{phase: 'completed', decision: 'COMMIT'}]
    })}
  }})
  await settle()
  assert.match(view.element('#trade-history').innerHTML, /Pokémon details unavailable/)
  assert.doesNotMatch(view.element('#trade-history').innerHTML, /<img/)
  assert.match(view.element('#trade-active').innerHTML, /Receiving/)
  assert.doesNotMatch(view.element('#trade-active').innerHTML, /Gastly|Lv. 999|sprites\/-1/)
})
