const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const vm = require('node:vm')
const source = fs.readFileSync('pokesim/web/static/event.js', 'utf8')

function page(fetch) {
  let click
  const button = {dataset: {state: 'event-42.state'}, disabled: false,
    addEventListener(name, handler) {
      assert.equal(name, 'click')
      click = handler
    }}
  const error = {hidden: true, textContent: ''}
  const location = {href: '/events/42'}
  const context = vm.createContext({PokeSim: {fetch, url: path => path}, location, document: {
    querySelector: selector => selector === '#rewind' ? button : error,
  }})
  vm.runInContext(source, context)
  return {button, error, location, click: () => click()}
}

test('rewind sends the saved state and navigates only after acceptance', async () => {
  const view = page(async (url, options) => {
    assert.equal(url, '/api/control')
    assert.equal(options.method, 'POST')
    assert.deepEqual(JSON.parse(options.body), {action: 'load_state', value: 'event-42.state'})
    assert.equal(view.button.disabled, true)
    return {ok: true}
  })
  await view.click()
  assert.equal(view.location.href, '/')
  assert.equal(view.error.hidden, true)
})

test('rejected rewinds stay on the event and permit retry', async () => {
  const view = page(async () => ({ok: false, json: async () => ({detail: 'This save predates the latest completed trade'})}))
  await view.click()
  assert.equal(view.location.href, '/events/42')
  assert.equal(view.error.textContent, 'This save predates the latest completed trade')
  assert.equal(view.error.hidden, false)
  assert.equal(view.button.disabled, false)
})

test('network and non-JSON failures leave a readable error', async () => {
  for (const fetch of [
    async () => { throw new Error('Network unavailable') },
    async () => ({ok: false, json: async () => { throw new Error('Invalid JSON') }}),
  ]) {
    const view = page(fetch)
    await view.click()
    assert.equal(view.location.href, '/events/42')
    assert.ok(view.error.textContent)
    assert.equal(view.error.hidden, false)
    assert.equal(view.button.disabled, false)
  }
})
