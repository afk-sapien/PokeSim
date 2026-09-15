const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const vm = require('node:vm')
const source = fs.readFileSync('pokesim/web/static/routes.js', 'utf8') + '\n{}\n' + fs.readFileSync('pokesim/web/static/trade-ui.js', 'utf8')

function ui(overrides = {}) {
  const calls = []
  const toast = {}
  const status = {connected:true, offers:[{trade_key:'partner', listed:true, source:'Automatic', editable:true, preference:'auto'}], ...overrides}
  const context = vm.createContext({document:{querySelector:() => toast}, setTimeout:() => 1, clearTimeout() {},
    fetch:async (url, options) => {
      calls.push({url, options})
      if (options?.method === 'POST') {
        const {state} = JSON.parse(options.body)
        status.offers[0] = {...status.offers[0], listed:state === 'offered', preference:state === 'unlocked' ? 'auto' : state,
          locked:state === 'locked',
          can_offer:state === 'withdrawn', reason:'Withdrawn by you'}
      }
      return {ok:true,json:async () => status}
    }})
  vm.runInContext(source, context)
  return {api:context.TradeUI,calls,toast}
}

test('listed automatic offers only have withdrawal controls', async () => {
  const view = ui()
  await view.api.refresh()
  const html = view.api.control('partner')
  assert.match(html, /Withdraw offer/)
  assert.doesNotMatch(html, /Offer for trade/)
})

test('withdrawal persists a preference without executing or approving a trade', async () => {
  const view = ui()
  await view.api.refresh()
  await view.api.change({dataset:{tradeKey:'partner',tradeState:'withdrawn'}})
  const mutations = view.calls.filter(call => call.options?.method === 'POST')
  assert.equal(mutations.length,1)
  assert.equal(mutations[0].url,'/api/trading/preferences')
  assert.deepEqual(JSON.parse(mutations[0].options.body),{key:'partner',state:'withdrawn'})
  assert.match(view.api.control('partner'), /Offer for trade/)
  assert.match(view.toast.textContent,/Automatic trading will skip/)
})

test('viewer-only, held and disconnected states disable mutations', async () => {
  for (const state of [{viewer_only:true},{holding:true},{connected:false}]) {
    const view = ui(state)
    await view.api.refresh()
    assert.match(view.api.control('partner'), /disabled/)
  }
})

test('locks replace trading actions and require an explicit unlock', async () => {
  const view = ui()
  await view.api.refresh()
  await view.api.change({dataset:{tradeKey:'partner',tradeState:'locked'}})
  const html = view.api.control('partner')
  assert.match(html, /Unlock Pokémon/)
  assert.doesNotMatch(html, /Offer for trade|Withdraw offer/)
  assert.match(view.toast.textContent,/automatic release are blocked/)
  await view.api.change({dataset:{tradeKey:'partner',tradeState:'unlocked'}})
  assert.equal(view.api.find('partner').preference, 'auto')
  assert.match(view.api.control('partner'), /Lock Pokémon/)
})

test('local locks remain available when the broker is disconnected', async () => {
  const view = ui({connected:false})
  await view.api.refresh()
  const html = view.api.control('partner')
  assert.match(html, /data-trade-state="withdrawn" disabled/)
  assert.match(html, /data-trade-state="locked" >Lock Pokémon/)
})
