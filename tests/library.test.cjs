const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const vm = require('node:vm')
const crypto = require('node:crypto').webcrypto
const source = fs.readFileSync('pokesim/web/static/library.js', 'utf8')
const settle = async () => {
  for (const tick of [1, 2, 3, 4]) await new Promise(resolve => setImmediate(resolve))
}

function slot(version, romId = '', extra = {}) {
  const johto = ['gold', 'silver', 'crystal'].includes(version)
  return {version, title: `Pokémon ${version[0].toUpperCase()}${version.slice(1)}`, generation: johto ? 2 : 1, supported: true,
    starters: johto ? ['chikorita', 'cyndaquil', 'totodile'] : version === 'yellow' ? ['pikachu'] : ['bulbasaur', 'charmander', 'squirtle'], installed: Boolean(romId),
    adventures: [], rom: romId ? {id: romId, sha1: 'a'.repeat(40), short_hash: 'aaaaaaaa', size: 1048576, added_at: 1700000000, file_missing: false} : null, ...extra}
}
const SHELF = ['red', 'blue', 'yellow', 'gold', 'silver', 'crystal']

function library(options = {}) {
  const elements = new Map()
  const calls = []
  let poll
  const listeners = {}
  const clicks = []
  const element = selector => {
    if (!elements.has(selector)) elements.set(selector, {
      hidden: selector === '#workspace', value: '', checked: false, files: [], dataset: {}, textContent: '',
      innerHTML: '', classList: {toggle() {}}, setAttribute() {}, toggleAttribute() {}, hasAttribute: () => false, click() {},
      querySelectorAll: () => [], querySelector: () => null, insertAdjacentHTML() {},
      focus() {}, showModal() { this.open = true }, close() { this.open = false }, reset() {},
    })
    return elements.get(selector)
  }
  const location = {hash: options.hash || '', pathname: '/', search: '', replace() {}}
  const context = vm.createContext({
    document: {body: {dataset: {page: options.page || 'library', adventure: options.adventure || ''}}, querySelector: element,
      querySelectorAll: () => [], addEventListener(name, callback) {
      listeners[name] = callback
      if (name === 'click') clicks.push(callback)
    }, hidden: false},
    setTimeout: callback => setImmediate(callback),
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
        : path === '/api/v1/cartridges' ? {slots: options.slots || [slot('red', 'rom')], supported: 'Red, Blue, Yellow, Gold, Silver or Crystal'}
        : path === '/api/v1/adventures' && opts.method === 'POST' ? {id: 'a'.repeat(32)}
        : {adventures: []}
      return {ok: true, json: async () => data}
    },
  })
  vm.runInContext(source, context)
  return {element, calls, context, poll, clicks, click(action, id) { listeners.click({target: {closest: () => ({dataset: {action, id}})}}) }}
}

test('library opens automatically with a GET session and never submits fragment credentials', async () => {
  const view = library({hash: '#token=secret-owner'})
  await settle()
  assert.equal(view.calls[0].path, '/api/v1/session')
  assert.equal(view.calls[0].options.method, undefined)
  assert.equal(view.calls.some(call => call.options?.body?.includes('secret-owner')), false)
  assert.equal(view.element('#workspace').hidden, false)
  assert.equal(view.element('#status').textContent, 'Connected')
  assert.doesNotMatch(fs.readFileSync('pokesim/web/static/library.html', 'utf8'), /owner.key|sign.in/i)
})

test('create can reuse a ROM without starting and sends a stable-format idempotency key', async () => {
  const view = library()
  await settle()
  view.element('#new-name').value = 'Second Red'
  await view.element('#new-adventure').onclick()
  await settle()
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

test('a running adventure that reports a stall says so on its card', async () => {
  const games = [{id: 'a'.repeat(32), name: 'Red', version: 'red', state: 'running', summary: {stalled: true}},
    {id: 'b'.repeat(32), name: 'Blue', version: 'blue', state: 'running', summary: {}},
    {id: 'c'.repeat(32), name: 'Old', version: 'red', state: 'stopped', summary: {stalled: true}}]
  const view = library({respond(path) {
    return path === '/api/v1/adventures' ? {ok: true, json: async () => ({adventures: games})} : null
  }})
  const cards = []
  view.element('#adventure-list').insertAdjacentHTML = (_, html) => { cards.push(html) }
  await settle()
  assert.deepEqual(cards.map(html => /Stuck\?/.test(html)), [true, false, false])
})

test('stopped and failed cards say so and start in one click, translating raw network errors', async () => {
  const games = [{id: 'a'.repeat(32), name: 'Cozy Escape', version: 'silver', state: 'failed', desired_state: 'running',
    error: '<urlopen error [Errno -5] No address associated with hostname>'},
    {id: 'b'.repeat(32), name: 'Quiet Cove', version: 'red', state: 'stopped', desired_state: 'stopped'}]
  const view = library({respond(path) {
    return path === '/api/v1/adventures' ? {ok: true, json: async () => ({adventures: games})} : null
  }})
  const cards = []
  view.element('#adventure-list').insertAdjacentHTML = (_, html) => { cards.push(html) }
  await settle()
  assert.match(cards[0], /state-pill"><i[^>]*><\/i>Failed</)
  assert.match(cards[0], /data-action="start"[^>]*>Retry</)
  assert.match(cards[0], /Couldn&#39;t download the Pokémon Silver game data \(no network\)\. Retry\./)
  assert.doesNotMatch(cards[0], /urlopen/)
  assert.match(cards[1], />Stopped</)
  assert.match(cards[1], /key key--primary" data-action="start"[^>]*>Start</)
  assert.doesNotMatch(cards[1], />View adventure</)
})

test('the page for a failed adventure explains the failure and is not a library', async () => {
  const id = 'a'.repeat(32)
  const view = library({page: 'stopped', adventure: id, respond(path) {
    return path === '/api/v1/adventures' ? {ok: true, json: async () => ({adventures: [{id, name: 'Cozy Escape', version: 'silver',
      state: 'failed', error: '<urlopen error timed out>', summary: {next_retry: Date.now() / 1000 + 120}}]})} : null
  }})
  await settle()
  const page = view.element('#stopped-card').innerHTML
  assert.match(page, /Failed to start/)
  assert.match(page, /\(no network\)\. Retry\./)
  assert.match(page, /Technical details/)
  assert.match(page, /try again by itself in about 2 minutes/)
  assert.match(page, /data-action="start"[^>]*>Retry</)
  assert.doesNotMatch(page, /No adventures yet|Create an adventure/)
  assert.match(view.element('#stopped-lede').textContent, /could not start/)
})

test('settings mutations send only fields accepted by the manager', async () => {
  const view = library()
  await settle()
  view.element('#settings-id').value = 'a'.repeat(32)
  view.element('#settings-name').value = 'Renamed adventure'
  view.element('#settings-autostart').checked = true
  view.element('#settings-speed').value = '4'
  view.element('#adventure-settings-form').onsubmit({preventDefault() {}})
  await settle()
  const request = view.calls.find(call => call.options?.method === 'PATCH')
  assert.deepEqual(JSON.parse(request.options.body), {name: 'Renamed adventure', settings: {auto_start: true, speed: 4, palette: 'original'}})
})

test('speed lives in adventure settings and global limits are absent', async () => {
  const html = fs.readFileSync('pokesim/web/static/library.html', 'utf8')
  assert.match(html, /id="settings-speed"/)
  assert.match(html, /value="0">Max/)
  assert.doesNotMatch(html, /id="simulation-speed"|id="max-running"|id="settings-form"/)
})

test('an individual unlimited speed is saved and reconnecting workers are explained', async () => {
  for (const pace_pending of [false, true]) {
    const view = library({respond: (path, options) => {
      if (options.method === 'PATCH') return {ok: true, json: async () => ({pace_pending})}
    }})
    await settle()
    view.element('#settings-id').value = 'a'.repeat(32)
    view.element('#settings-name').value = 'Red'
    view.element('#settings-speed').value = '0'
    view.element('#adventure-settings-form').onsubmit({preventDefault() {}})
    await settle()
    const request = view.calls.find(call => call.options.method === 'PATCH')
    assert.equal(request.path, '/api/v1/adventures/' + 'a'.repeat(32))
    assert.equal(JSON.parse(request.options.body).settings.speed, 0)
    assert.equal(view.element('#notice').textContent, pace_pending
      ? 'Settings saved. The speed will apply when this adventure reconnects.'
      : 'Adventure settings saved.')
  }
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
  await view.element('#new-adventure').onclick()
  await settle()
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
  await view.element('#new-adventure').onclick()
  await settle()
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
    view.element('#settings-speed').value = '4'
    view.element('#settings-id').value = 'a'.repeat(32)
    view.element('#settings-name').value = 'Red'
    view.element('#adventure-settings-form').onsubmit({preventDefault() {}})
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
  assert.equal(view.element('#status').textContent, 'Reconnecting…')
  view.poll()
  await settle()
  assert.equal(view.element('#workspace').hidden, false)
  assert.equal(view.element('#status').textContent, 'Connected')
  view.element('#quit').onclick()
  await settle()
  const count = view.calls.length
  view.poll()
  await settle()
  assert.equal(view.calls.length, count)
  assert.equal(view.element('#workspace').hidden, true)
})

test('the library has three tabs and no trading view of its own', () => {
  const html = fs.readFileSync('pokesim/web/static/library.html', 'utf8')
  const nav = html.match(/<nav aria-label="Application">(.*?)<\/nav>/)[1]
  assert.deepEqual([...nav.matchAll(/data-nav="([a-z]+)"/g)].map(match => match[1]), ['library', 'notifications', 'settings'])
  assert.doesNotMatch(html, /data-view="trading"|trade-progress\.js|href="\/trading"/)
  assert.doesNotMatch(fs.readFileSync('pokesim/web/static/library.js', 'utf8'), /\/api\/v1\/interactions['`?]|refreshTrades|data-cancel-trade/)
})

function notificationsView(overrides = {}, extra = () => null) {
  const saved = {enabled: true, categories: [], integrations: [
    {id: 'one', name: '<League chat>', provider: 'discord', enabled: true,
      categories: {league: true}, adventures: {red: true}, include_new_adventures: false},
    {id: 'two', name: 'Phone', provider: 'telegram', enabled: false,
      categories: {badges: true}, adventures: {}, include_new_adventures: true}
  ], ...overrides}
  const view = library({page: 'notifications', respond(path, options) {
    const override = extra(path, options)
    if (override) return override
    if (path === '/api/v1/notifications') return {ok: true, json: async () => ({...saved, pending: []})}
    return null
  }})
  return view
}

test('notification list escapes names and shows independent subscriptions', async () => {
  const view = notificationsView()
  await settle()
  const html = view.element('#notify-integrations').innerHTML
  assert.match(html, /&lt.*League chat&gt/)
  assert.doesNotMatch(html, /<League chat>/)
  assert.match(html, /1 event type/)
  assert.match(html, /1 selected adventure/)
  assert.match(html, /plus new adventures/)
  assert.match(html, /data-id="one"/)
  assert.match(html, /data-id="two"/)
  assert.equal(view.element('#notify-enabled').checked, true)
})

test('empty notification list explains adding multiple destinations', async () => {
  const view = notificationsView({enabled: false, integrations: []})
  await settle()
  assert.match(view.element('#notify-integrations').innerHTML, /No integrations yet/)
  assert.match(view.element('#notify-delivery-state').textContent, /paused/)
})

test('global pause sends only the master switch', async () => {
  const view = notificationsView()
  await settle()
  view.element('#notify-enabled').checked = false
  await view.element('#notify-enabled').onchange()
  const request = view.calls.find(call => call.path === '/api/v1/notifications' && call.options.method === 'PATCH')
  assert.deepEqual(JSON.parse(request.options.body), {enabled: false})
})

test('failed master switch update restores the saved state', async () => {
  const view = notificationsView({}, (path, options) => path === '/api/v1/notifications' && options.method === 'PATCH'
    ? {ok: false, status: 409, json: async () => ({detail: 'Try again'})} : null)
  await settle()
  view.element('#notify-enabled').checked = false
  await view.element('#notify-enabled').onchange()
  assert.equal(view.element('#notify-enabled').checked, true)
  assert.equal(view.element('#notice').textContent, 'Try again')
})

function removalView(action, states) {
  const id = 'a'.repeat(32)
  let state = states[0]
  let stopping = false
  let reads = 0
  const view = library({respond(path, options) {
    if (path.endsWith('/stop')) {
      stopping = true
      return {ok: true, json: async () => ({})}
    }
    if (path === `/api/v1/adventures/${id}` && !options.method) {
      if (stopping) state = states[Math.min(++reads, states.length - 1)]
      return {ok: true, json: async () => ({id, name: 'Red', ...state})}
    }
    if (path === '/api/v1/adventures') return {ok: true, json: async () => ({adventures: [{id, name: 'Red', version: 'red', ...state}]})}
  }})
  return {view, id, async submit(confirmation = 'Red') {
    await settle()
    if (action === 'archive') view.click('archive', id)
    else {
      view.element('#delete-id').value = id
      view.element('#delete-confirmation').value = confirmation
      view.element('#adventure-delete-form').onsubmit({preventDefault() {}})
    }
    await settle()
    await settle()
    return view.calls.filter(call => call.options.method).map(call => [call.path, call.options.method])
  }}
}

for (const action of ['archive', 'delete']) {
  test(`${action} waits for the running adventure to stop before removal`, async () => {
    const {view, id, submit} = removalView(action, [
      {state: 'running', desired_state: 'running'},
      {state: 'waiting_for_trade', desired_state: 'stopped'},
      {state: 'stopping', desired_state: 'stopped'},
      {state: 'stopped', desired_state: 'stopped'}
    ])
    assert.deepEqual(await submit(), [
      [`/api/v1/adventures/${id}/stop`, 'POST'],
      [action === 'archive' ? `/api/v1/adventures/${id}/archive` : `/api/v1/adventures/${id}`, action === 'archive' ? 'POST' : 'DELETE']
    ])
    assert.equal(view.calls.filter(call => call.path === `/api/v1/adventures/${id}` && !call.options.method).length, 4)
  })

  test(`${action} preserves the adventure when saving or stopping fails`, async () => {
    const {view, submit} = removalView(action, [
      {state: 'running', desired_state: 'running'},
      {state: 'failed', desired_state: 'stopped', error: 'Save failed'}
    ])
    assert.equal((await submit()).length, 1)
    assert.match(view.element('#notice').textContent, /could not stop safely/)
  })

  test(`${action} does not stop an adventure that is already stopped`, async () => {
    const {submit} = removalView(action, [{state: 'stopped', desired_state: 'stopped'}])
    const requests = await submit()
    assert.equal(requests.length, 1)
    assert.equal(requests.some(([path]) => path.endsWith('/stop')), false)
  })
}

test('incorrect deletion confirmation cannot stop a running adventure', async () => {
  const {view, submit} = removalView('delete', [{state: 'running', desired_state: 'running'}])
  assert.deepEqual(await submit('Wrong name'), [])
  assert.match(view.element('#notice').textContent, /Type the adventure name/)
})

test('a concurrent restart cancels removal', async () => {
  const {view, submit} = removalView('archive', [{state: 'running', desired_state: 'running'}])
  assert.equal((await submit()).length, 1)
  assert.match(view.element('#notice').textContent, /was restarted/)
})

test('running adventure settings allow palettes and explain deferred application', async () => {
  const game = {id: 'a'.repeat(32), name: 'Red', state: 'running', settings: {palette: 'blue'}}
  const view = library({respond(path, options) {
    if (path === '/api/v1/adventures') return {ok: true, json: async () => ({adventures: [game]})}
    if (options.method === 'PATCH') return {ok: true, json: async () => ({palette_pending: true})}
  }})
  await settle()
  for (const name of ['league-rewards', 'mew-event', 'celebi-event']) view.element(`#settings-${name}`).toggleAttribute = () => {}
  for (const name of ['legendary-steps', 'event-steps', 'fossil-preference', 'dojo-preference']) view.element(`#settings-${name}`).closest = () => ({})
  view.click('settings', game.id)
  assert.equal(view.element('#settings-palette').value, 'blue')
  assert.notEqual(view.element('#settings-palette').disabled, true)
  view.element('#settings-palette').value = 'green'
  view.element('#adventure-settings-form').onsubmit({preventDefault() {}})
  await settle()
  const settings = JSON.parse(view.calls.find(call => call.options.method === 'PATCH').options.body).settings
  assert.equal(settings.palette, 'green')
  assert.equal(settings.league_rewards, undefined)
  assert.equal(view.element('#notice').textContent, 'Settings saved. The palette will apply when this adventure reconnects.')
})

test('Gold, Silver and Crystal adventures hide the palette and never send one', async () => {
  const game = {id: 'c'.repeat(32), name: 'Johto', version: 'gold', state: 'stopped', settings: {}}
  const view = library({respond(path, options) {
    if (path === '/api/v1/adventures') return {ok: true, json: async () => ({adventures: [game]})}
    if (options.method === 'PATCH') return {ok: true, json: async () => ({})}
  }})
  await settle()
  for (const name of ['league-rewards', 'mew-event', 'celebi-event']) view.element(`#settings-${name}`).toggleAttribute = () => {}
  for (const name of ['legendary-steps', 'event-steps', 'fossil-preference', 'dojo-preference']) view.element(`#settings-${name}`).closest = () => ({})
  view.click('settings', game.id)
  assert.equal(view.element('#settings-palette-label').hidden, true)
  assert.equal(view.element('#settings-palette-note').hidden, true)
  assert.equal(view.element('#settings-event-steps-label').textContent, 'Steps between Sudowoodo and Snorlax returns')
  view.element('#settings-legendary-steps').value = '500'
  view.element('#settings-event-steps').value = '200'
  view.element('#adventure-settings-form').onsubmit({preventDefault() {}})
  await settle()
  const settings = JSON.parse(view.calls.find(call => call.options.method === 'PATCH').options.body).settings
  assert.equal('palette' in settings, false)
  assert.equal(settings.legendary_return_steps, 500)
  assert.equal(settings.event_return_steps, 200)
  assert.equal('fossil_preference' in settings, false)
})

test('settings render existing backups without an adventure variable', async () => {
  const view = library({page: 'settings', respond(path) {
    if (path === '/api/v1/backups') return {ok: true, json: async () => ({backups: [
      {id: 'b'.repeat(32), created_at: 1700000000, size_bytes: 1024},
    ]})}
  }})
  await settle()
  assert.match(view.element('#backups').innerHTML, /data-delete-backup="b{32}" data-owner aria-label="Delete the backup from [^"]+">Delete/)
  assert.match(view.element('#backup-summary').textContent, /1 backup/)
})

test('one installed cartridge is preselected and narrows the starters', async () => {
  const view = library({slots: SHELF.map(version => slot(version, version === 'gold' ? 'gold-rom' : ''))})
  await settle()
  await view.element('#new-adventure').onclick()
  await settle()
  assert.equal(view.element('#rom-id').value, 'gold-rom')
  const cards = view.element('#game-choices').innerHTML
  assert.match(cards, /value="gold-rom" data-version="gold" checked/)
  assert.match(cards, /href="\/settings#cartridge-red">Add cartridge/)
  assert.match(cards, /href="\/settings#cartridge-yellow">Add cartridge/)
  assert.doesNotMatch(cards, /Coming in this release/)
  assert.ok(cards.indexOf('gold-rom') < cards.indexOf('cartridge-red'))
  const html = view.element('#starter').innerHTML
  assert.ok(html.includes('value="chikorita"') && !html.includes('value="squirtle"'))
  assert.equal(view.element('#create-needs-cartridge').hidden, true)
  assert.equal(view.element('#create-submit').hidden, false)
})

test('several cartridges need a choice and the choice sets the game and starters', async () => {
  const view = library({slots: SHELF.map(version => slot(version, ['red', 'crystal'].includes(version) ? `${version}-rom` : ''))})
  await settle()
  await view.element('#new-adventure').onclick()
  await settle()
  assert.equal(view.element('#rom-id').value, '')
  assert.doesNotMatch(view.element('#game-choices').innerHTML, /checked/)
  view.element('#new-name').value = 'Undecided'
  view.element('#create-form').onsubmit({preventDefault() {}})
  await settle()
  assert.equal(view.calls.some(call => call.path === '/api/v1/adventures' && call.options.method === 'POST'), false)
  assert.match(view.element('dialog[open] .dialog-feedback').textContent, /Choose the game/)
  view.element('#game-choices').onchange({target: {name: 'game', value: 'crystal-rom'}})
  assert.equal(view.element('#rom-id').value, 'crystal-rom')
  assert.ok(view.element('#starter').innerHTML.includes('value="totodile"'))
  view.element('#starter').value = 'totodile'
  view.element('#create-form').onsubmit({preventDefault() {}})
  await settle()
  const request = view.calls.find(call => call.path === '/api/v1/adventures' && call.options.method === 'POST')
  assert.deepEqual([JSON.parse(request.options.body).rom_id, JSON.parse(request.options.body).starter], ['crystal-rom', 'totodile'])
})

test('with no cartridges the library and the dialog both point to Settings', async () => {
  const view = library({slots: SHELF.map(version => slot(version))})
  await settle()
  assert.equal(view.element('#empty-needs-cartridge').hidden, false)
  assert.equal(view.element('#empty-ready').hidden, true)
  await view.element('#new-adventure').onclick()
  await settle()
  assert.equal(view.element('#create-needs-cartridge').hidden, false)
  assert.equal(view.element('#create-submit').hidden, true)
  assert.equal(view.element('#rom-id').value, '')
  assert.equal(view.element('#create-supported').textContent, 'Red, Blue, Yellow, Gold, Silver or Crystal')
})

test('a starter from the wrong game is refused before the adventure is created', async () => {
  const view = library()
  await settle()
  await view.element('#new-adventure').onclick()
  await settle()
  view.element('#new-name').value = 'Mismatch'
  view.element('#starter').value = 'cyndaquil'
  view.element('#create-form').onsubmit({preventDefault() {}})
  await settle()
  assert.equal(view.calls.some(call => call.path === '/api/v1/adventures' && call.options.method === 'POST'), false)
  assert.match(view.element('dialog[open] .dialog-feedback').textContent, /different game/)
})

test('settings shows every slot and a wrong-slot upload reports where it went', async () => {
  let shelf = SHELF.map(version => slot(version))
  const view = library({page: 'settings', respond(path, opts) {
    if (path === '/api/v1/cartridges') return {ok: true, json: async () => ({slots: shelf, supported: 'Red, Blue, Yellow, Gold, Silver or Crystal'})}
    if (path.startsWith('/api/v1/cartridges?slot=')) shelf = SHELF.map(version => slot(version, version === 'blue' ? 'blue-rom' : ''))
    if (path.startsWith('/api/v1/cartridges?slot=') && opts.method === 'POST') return {ok: true, json: async () => ({
      version: 'blue', title: 'Pokémon Blue', moved: true, message: 'That file is Pokémon Blue, not Pokémon Red, so it went into the Blue slot.',
      rom: {id: 'blue-rom'}, slots: shelf})}
  }})
  await settle()
  const grid = view.element('#cartridge-grid')
  for (const version of SHELF) assert.match(grid.innerHTML, new RegExp(`id="cartridge-${version}"`))
  assert.match(grid.innerHTML, /data-slot="yellow" data-state="empty"/)
  view.element('#cartridge-grid').onclick({target: {closest: selector => selector === '[data-cartridge-upload]' ? {dataset: {cartridgeUpload: 'red'}} : null}})
  view.element('#cartridge-file').files = [{name: 'blue.gb', size: 1024}]
  view.element('#cartridge-file').onchange()
  await settle()
  const upload = view.calls.find(call => call.path === '/api/v1/cartridges?slot=red')
  assert.equal(upload.options.method, 'POST')
  assert.match(grid.innerHTML, /data-slot="blue" data-state="installed"/)
  assert.match(grid.innerHTML, /went into the Blue slot/)
})

test('a game paused for a trade shows Paused rather than a measured 0.0× speed', async () => {
  const resources = {cpu_percent: 2.1, memory_bytes: 160 * 1048576, observed_speed: 0, speed_status: 'ready'}
  const games = [
    {id: 'a'.repeat(32), name: 'Trading', version: 'silver', state: 'running', resources, summary: {paused: true}},
    {id: 'b'.repeat(32), name: 'Held', version: 'red', state: 'waiting_for_trade', resources, summary: {}},
    {id: 'c'.repeat(32), name: 'Walking', version: 'gold', state: 'running', resources: {...resources, observed_speed: 2.3}, summary: {paused: false}},
  ]
  const view = library({respond: path => path === '/api/v1/adventures' ? {ok: true, json: async () => ({adventures: games})} : null})
  const labels = {}
  view.element('#adventure-list').querySelector = selector => {
    const id = selector.match(/data-adventure-id="(\w+)"/)?.[1]
    return id && {querySelector: usage => {
      const key = usage.match(/data-usage="(\w+)"/)[1]
      return {set textContent(value) { labels[`${id[0]}-${key}`] = value }, get textContent() { return labels[`${id[0]}-${key}`] }, classList: {toggle() {}}}
    }}
  }
  await settle()
  view.poll()
  await settle()
  assert.equal(labels['a-speed'], 'Paused')
  // A game held for a trade says so rather than a bare Paused.
  assert.equal(labels['b-speed'], 'Trading')
  assert.equal(labels['c-speed'], '2.3×')
  assert.equal(labels['a-cpu'], '2.1%')
})

