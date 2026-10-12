const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const vm = require('node:vm')
const source = fs.readFileSync('pokesim/web/static/event.js', 'utf8')
const settle = async () => {
  for (const tick of [1, 2, 3, 4]) await new Promise(resolve => setImmediate(resolve))
}

function page(control, playtime = '12:30:00') {
  const handlers = {}
  const posts = []
  const button = {dataset: {state: 'event-42.state', playtime: '10:00:00'}, disabled: false, focused: 0,
    focus() { this.focused += 1 },
    addEventListener(name, handler) { handlers[`rewind-${name}`] = handler }}
  const dialog = {open: false, returnValue: '',
    showModal() { this.open = true },
    addEventListener(name, handler) { handlers[`dialog-${name}`] = handler }}
  const now = {hidden: true, textContent: ''}
  const error = {hidden: true, textContent: ''}
  const location = {href: '/events/42'}
  const fetch = async (url, options) => {
    if (url === '/api/state') return {ok: true, json: async () => ({game: {playtime}})}
    posts.push([url, options, button.disabled])
    return control(url, options)
  }
  const elements = {'#rewind': button, '#rewind-dialog': dialog, '#rewind-dialog-now': now, '#rewind-error': error}
  const context = vm.createContext({PokeSim: {fetch, url: path => path}, location, Number, Math, String, Date, document: {
    querySelector: selector => elements[selector] || null,
  }})
  vm.runInContext(source, context)
  const close = async value => {
    dialog.open = false
    dialog.returnValue = value
    handlers['dialog-close']()
    await settle()
  }
  return {button, dialog, now, error, location, posts,
    click: async () => { handlers['rewind-click'](); await settle() }, close}
}

test('rewind asks first and says how much play would be lost', async () => {
  const view = page(async () => ({ok: true}))
  await view.click()
  assert.equal(view.dialog.open, true)
  assert.equal(view.posts.length, 0)
  assert.equal(view.now.hidden, false)
  assert.match(view.now.textContent, /12:30/)
  assert.match(view.now.textContent, /2 hours 30 minutes/)
})

test('keeping play sends nothing and returns focus to the button', async () => {
  const view = page(async () => ({ok: true}))
  await view.click()
  await view.close('cancel')
  assert.equal(view.posts.length, 0)
  assert.equal(view.location.href, '/events/42')
  assert.equal(view.button.focused, 1)
})

test('confirming sends the saved state and navigates only after acceptance', async () => {
  const view = page(async (url, options) => {
    assert.equal(url, '/api/control')
    assert.equal(options.method, 'POST')
    assert.deepEqual(JSON.parse(options.body), {action: 'load_state', value: 'event-42.state'})
    return {ok: true}
  })
  await view.click()
  await view.close('rewind')
  assert.equal(view.posts.length, 1)
  assert.equal(view.posts[0][2], true)
  assert.equal(view.location.href, '/')
  assert.equal(view.error.hidden, true)
})

test('rejected rewinds stay on the event and permit retry', async () => {
  const view = page(async () => ({ok: false, json: async () => ({detail: 'This save predates the latest completed trade'})}))
  await view.click()
  await view.close('rewind')
  assert.equal(view.location.href, '/events/42')
  assert.equal(view.error.textContent, 'This save predates the latest completed trade')
  assert.equal(view.error.hidden, false)
  assert.equal(view.button.disabled, false)
})

test('network and non-JSON failures leave a readable error', async () => {
  for (const control of [
    async () => { throw new Error('Network unavailable') },
    async () => ({ok: false, json: async () => { throw new Error('Invalid JSON') }}),
  ]) {
    const view = page(control)
    await view.click()
    await view.close('rewind')
    assert.equal(view.location.href, '/events/42')
    assert.ok(view.error.textContent)
    assert.equal(view.error.hidden, false)
    assert.equal(view.button.disabled, false)
  }
})
