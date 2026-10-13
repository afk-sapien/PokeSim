const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const vm = require('node:vm')
const source = fs.readFileSync('pokesim/web/static/routes.js', 'utf8') + '\n{}\n' + fs.readFileSync('pokesim/web/static/trade-ui.js', 'utf8')

function ui(overrides = {}, mon = {}) {
  const calls = []
  const toast = {}
  const status = {connected:true, offers:[{trade_key:'partner', name:'Pidgey', listed:true, editable:true, preference:'auto', setting:'auto', ...mon}], ...overrides}
  const context = vm.createContext({document:{querySelector:() => toast}, setTimeout:() => 1, clearTimeout() {},
    fetch:async (url, options) => {
      calls.push({url, options})
      if (options?.method === 'POST') {
        const {state} = JSON.parse(options.body)
        if (state === 'broken') return {ok:false, json:async () => ({detail:'This Pokémon left the collection.'})}
        if (state === 'garbled') return {ok:false, json:async () => { throw new SyntaxError('Unexpected token <') }}
        status.offers[0] = {...status.offers[0], setting:state, listed:state !== 'keep'}
      }
      return {ok:true,json:async () => status}
    }})
  vm.runInContext(source, context)
  return {api:context.TradeUI,calls,toast}
}

test('each Pokémon has one three-way trade setting', async () => {
  const view = ui()
  await view.api.refresh()
  const html = view.api.control('partner')
  assert.match(html, /<select data-trade-key="partner" data-trade-setting="auto">/)
  assert.match(html, /value="auto" selected title="[^"]*">Can trade/)
  assert.match(html, /value="first" title="[^"]*">Prefer to trade/)
  assert.match(html, /value="keep" title="[^"]*">Never trade/)
  assert.match(html, /Trade setting for Pidgey/)
  assert.doesNotMatch(html, /Lock|Withdraw|Kept by|Protected by/)
})

test('changing the setting saves it and only it', async () => {
  const view = ui()
  await view.api.refresh()
  await view.api.change({value:'keep', dataset:{tradeKey:'partner', tradeSetting:'auto'}})
  const mutations = view.calls.filter(call => call.options?.method === 'POST')
  assert.equal(mutations.length, 1)
  assert.equal(mutations[0].url, '/api/trading/preferences')
  assert.deepEqual(JSON.parse(mutations[0].options.body), {key:'partner', state:'keep'})
  assert.match(view.api.control('partner'), /value="keep" selected/)
  assert.match(view.toast.textContent, /Never traded automatically/)
})

test('a refused change shows why and puts the old value back', async () => {
  const view = ui()
  await view.api.refresh()
  const select = {value:'broken', dataset:{tradeKey:'partner', tradeSetting:'auto'}}
  await view.api.change(select)
  assert.equal(select.value, 'auto')
  assert.match(view.toast.textContent, /left the collection/)
})

test('the setting is the one the server names', async () => {
  for (const [setting, expected] of [['first', 'first'], ['keep', 'keep'], [undefined, 'auto']]) {
    const view = ui({}, {preference:'offered', setting})
    await view.api.refresh()
    assert.match(view.api.control('partner'), new RegExp(`value="${expected}" selected`))
  }
})

test('shiny and perfect Pokémon cannot be set to Prefer to trade', async () => {
  for (const flag of [{shiny:true}, {perfect_dvs:true}]) {
    const view = ui({}, flag)
    await view.api.refresh()
    assert.match(view.api.control('partner'), /value="first" disabled title="[^"]*">Prefer to trade/)
  }
})

test('viewer-only and held states disable the setting', async () => {
  for (const state of [{viewer_only:true}, {holding:true}]) {
    const view = ui(state)
    await view.api.refresh()
    assert.match(view.api.control('partner'), /disabled>/)
  }
})

test('the saved setting shows under its own row only', async () => {
  const view = ui()
  await view.api.refresh()
  await view.api.change({value:'keep', dataset:{tradeKey:'partner', tradeSetting:'auto'}})
  assert.match(view.api.control('partner'), /<span class="trade-saved">Never trade\. Never traded automatically\. You can still pick it by hand\.<\/span>$/)
  await view.api.change({value:'broken', dataset:{tradeKey:'partner', tradeSetting:'keep'}})
  assert.match(view.api.control('partner'), /class="trade-saved is-error">This Pokémon left the collection/)
})

test('an error page that is not JSON shows a readable message', async () => {
  const view = ui()
  await view.api.refresh()
  await view.api.change({value:'garbled', dataset:{tradeKey:'partner', tradeSetting:'auto'}})
  const html = view.api.control('partner')
  assert.match(html, /class="trade-saved is-error">Could not save this setting\.</)
  assert.doesNotMatch(html, /Unexpected token/)
})
