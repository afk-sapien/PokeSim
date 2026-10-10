const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const vm = require('node:vm')
const crypto = require('node:crypto').webcrypto
const read = name => fs.readFileSync(`pokesim/web/static/${name}`, 'utf8')
const join = String.fromCharCode(59) + '\n'
const pcSource = [read('types.js'), read('routes.js'), read('trade-offer.js'), read('pc.js')].join(join)
const tradingSource = [read('trade-progress.js'), read('adventure-trading.js')].join(join)
const settle = async () => {
  for (const tick of [1, 2, 3, 4, 5]) await new Promise(resolve => setImmediate(resolve))
}
const FROM = 'a'.repeat(32)
const TO = 'b'.repeat(32)
const json = data => ({ok: true, status: 200, json: async () => data, clone() { return this }})

function elements() {
  const map = new Map()
  const element = selector => {
    if (!map.has(selector)) map.set(selector, {
      value: '', innerHTML: '', textContent: '', hidden: selector === '#pc-offer-banner' || selector === '#trade-offers-section',
      options: [{}, {}], dataset: {}, open: false,
      classList: {add() {}, remove() {}, toggle() {}}, setAttribute() {}, focus() {},
      showModal() { this.open = true }, close() { this.open = false },
    })
    return map.get(selector)
  }
  return element
}

// A click on a control the page rendered, found by its data attribute.
const clickOn = (attribute, dataset) => ({target: {closest: selector => selector === `[${attribute}]` ? {dataset, disabled: false} : null}})

function pc({base = `/games/${FROM}`, adventure = FROM, search = '?scope=all', pokemon, respond = () => null}) {
  const element = elements()
  const calls = []
  const location = {search, href: ''}
  const context = vm.createContext({
    document: {querySelector: selector => selector.startsWith('meta[') ? {content: selector.includes('pokesim-base') ? base : adventure} : element(selector),
      activeElement: null, hidden: false, addEventListener() {}},
    location, URLSearchParams, crypto, Uint8Array,
    history: {replaceState: (_, __, next) => { location.replaced = next }},
    fetch: async (path, options = {}) => {
      calls.push({path, options})
      const custom = respond(path, options)
      if (custom) return custom
      if (path === '/api/v1/session') return json({csrf_token: 'csrf'})
      return json({started: true, version: 'red', party: [], storage: {active_box: 1, box_counts: Array(12).fill(0), pokemon}})
    },
    setInterval() {},
  })
  vm.runInContext(pcSource, context)
  return {element, calls, location, context, open: index => vm.runInContext(`detail(residents[${index}])`, context)}
}

const mon = (key, extra = {}) => ({box: 1, position: 1, level: 30, dex: 25, nick: key, name: 'Pikachu', trade_key: key,
  battle_power: 100, power: 200, dvs: [1, 2, 3, 4, 5], stat_exp: [0, 0, 0, 0, 0], ...extra})
const targets = {adventures: [{id: TO, name: 'Second Red', version: 'red', available: true, reason: ''},
  {id: 'c'.repeat(32), name: 'Stopped Blue', version: 'blue', available: false, reason: 'Start this adventure to trade from it'}], viewer_only: false}

test('the owner sees Offer trade, picks a running adventure and opens its PC in offer mode', async () => {
  const view = pc({pokemon: [mon('box-1')], respond: path => path.startsWith('/api/v1/interactions/trade-offers/targets') ? json(targets) : null})
  await settle()
  assert.ok(view.calls.some(call => call.path === `/api/v1/interactions/trade-offers/targets?from_id=${FROM}`))
  view.open(0)
  assert.match(view.element('#pc-trade-action').innerHTML, /data-offer-trade="box-1"[^>]*>Offer trade</)
  view.element('#pc-trade-action').onclick(clickOn('data-offer-trade', {offerTrade: 'box-1'}))
  assert.equal(view.element('#offer-dialog').open, true)
  assert.match(view.element('#offer-dialog-list').innerHTML, /Checking which games can take this Pokémon/)
  await settle()
  assert.ok(view.calls.some(call => call.path === `/api/v1/interactions/trade-offers/targets?from_id=${FROM}&from_key=box-1`))
  const list = view.element('#offer-dialog-list').innerHTML
  assert.match(list, /data-offer-target="b{32}"><strong>Second Red/)
  assert.match(list, /Stopped Blue.*disabled|disabled.*Stopped Blue/)
  assert.match(list, /Start this adventure to trade from it/)
  view.element('#offer-dialog').onclick(clickOn('data-offer-target', {offerTarget: TO}))
  const next = new URL(view.location.href, 'http://pokesim')
  assert.equal(next.pathname, `/games/${TO}/pc`)
  assert.deepEqual(Object.fromEntries(next.searchParams), {scope: 'all', sort: 'battle_power', order: 'desc', offer_from: FROM, offer_key: 'box-1'})
})

test('view links and view-only adventures never show Offer trade', async () => {
  const viewer = pc({base: `/view/${FROM}`, pokemon: [mon('box-1')]})
  await settle()
  viewer.open(0)
  assert.doesNotMatch(viewer.element('#pc-trade-action').innerHTML, /Offer trade/)
  assert.equal(viewer.calls.some(call => call.path.startsWith('/api/v1/')), false)
  const locked = pc({pokemon: [mon('box-1')], respond: path => path.includes('/targets') ? json({...targets, viewer_only: true}) : null})
  await settle()
  locked.open(0)
  assert.doesNotMatch(locked.element('#pc-trade-action').innerHTML, /Offer trade/)
  const egg = pc({pokemon: [mon('egg-1', {egg: true})], respond: path => path.includes('/targets') ? json(targets) : null})
  await settle()
  egg.open(0)
  assert.doesNotMatch(egg.element('#pc-trade-action').innerHTML, /Offer trade/)
})

test('offer mode marks hard limits, keeps its URL and sends the chosen pair', async () => {
  const limits = {from: {adventure_id: FROM, adventure_name: 'First Red', name: 'Ivysaur', nickname: 'IVY', level: 20, battle_power: 95, power: 180,
    sprite_url: `/games/${FROM}/sprites/2.png?v=rom-portraits-1`, key: '0', blocked: ''},
  to: {adventure_id: TO, adventure_name: 'Second Red'}, blocked: {'box-2': 'Eggs cannot be traded'}, viewer_only: false}
  let sent = null
  const view = pc({base: `/games/${TO}`, adventure: TO, search: `?scope=all&offer_from=${FROM}&offer_key=0`,
    pokemon: [mon('box-1', {battle_power: 300}), mon('box-2', {position: 2})],
    respond: (path, options) => {
      if (path.startsWith('/api/v1/interactions/trade-offers/limits')) return json(limits)
      if (path === '/api/v1/interactions/trade-offers' && options.method === 'POST') { sent = {body: JSON.parse(options.body), headers: options.headers}
        return json({id: 'd'.repeat(32), status: 'pending'}) }
      return null
    }})
  await settle()
  assert.ok(view.calls.some(call => call.path === `/api/v1/interactions/trade-offers/limits?from_id=${FROM}&from_key=0&to_id=${TO}`))
  assert.equal(view.element('#pc-offer-banner').hidden, false)
  assert.match(view.element('#pc-offer-banner').innerHTML, /Offering from First Red/)
  assert.match(view.element('#pc-offer-banner').innerHTML, /IVY · Lv. 20/)
  assert.match(view.element('#pc-offer-banner').innerHTML, /Battle Power 95 · Stat Power 180/)
  assert.match(view.element('#pc-offer-banner').innerHTML, new RegExp(`href="/games/${FROM}/pc">Cancel offer`))
  assert.match(view.element('#pc-grid').innerHTML, /Cannot trade/)
  const replaced = new URL(view.location.replaced, 'http://pokesim')
  assert.equal(replaced.searchParams.get('offer_from'), FROM)
  assert.equal(replaced.searchParams.get('offer_key'), '0')
  const rows = JSON.parse(vm.runInContext('JSON.stringify(residents)', view.context))
  view.open(rows.findIndex(row => row.trade_key === 'box-2'))
  assert.match(view.element('#pc-trade-action').innerHTML, /Cannot trade.*Eggs cannot be traded/)
  assert.doesNotMatch(view.element('#pc-trade-action').innerHTML, /data-offer-send/)
  view.open(rows.findIndex(row => row.trade_key === 'box-1'))
  assert.match(view.element('#pc-trade-action').innerHTML, /data-offer-send="box-1"[^>]*>Send offer for box-1/)
  view.element('#pc-trade-action').onclick(clickOn('data-offer-send', {offerSend: 'box-1'}))
  await settle()
  assert.equal(sent.headers['X-PokeSim-CSRF'], 'csrf')
  assert.deepEqual({...sent.body, request_id: undefined}, {from_id: FROM, from_key: '0', to_id: TO, to_key: 'box-1', request_id: undefined})
  assert.match(sent.body.request_id, /^[a-f0-9]{32}$/)
  assert.equal(view.location.href, `/games/${FROM}/trading`)
})

test('a refused offer stays on the page and shows why', async () => {
  const limits = {from: {adventure_id: FROM, adventure_name: 'First Red', name: 'Ivysaur', level: 20, blocked: ''}, to: {adventure_name: 'Second Red'}, blocked: {}, viewer_only: false}
  const view = pc({base: `/games/${TO}`, adventure: TO, search: `?offer_from=${FROM}&offer_key=0`, pokemon: [mon('box-1')],
    respond: (path, options) => path.includes('/limits') ? json(limits)
      : options.method === 'POST' && path.endsWith('/trade-offers') ? {ok: false, status: 409, json: async () => ({detail: 'You already offered this trade'}), clone() { return this }} : null})
  await settle()
  view.open(0)
  view.element('#pc-trade-action').onclick(clickOn('data-offer-send', {offerSend: 'box-1'}))
  await settle()
  assert.equal(view.location.href, '')
  assert.match(view.element('#pc-trade-action').innerHTML, /You already offered this trade/)
})

function trading({base = `/games/${FROM}`, offers, respond = () => null}) {
  const element = elements()
  const calls = []
  const context = vm.createContext({
    document: {querySelector: element, hidden: false},
    PokeSim: {adventureId: FROM, base,
      fetch: async path => json({adventure: {id: FROM, version: 'red', state: 'running'}, active: [], history: []}),
      api: async (path, options = {}) => {
        calls.push({path, method: options.method || 'GET'})
        return respond(path, options) || json(offers())
      }},
    setInterval() {},
  })
  vm.runInContext(tradingSource, context)
  return {element, calls}
}

const side = (aid, name, mon, extra = {}) => ({adventure_id: aid, adventure_name: name, name: mon, level: 20, power: 180, battle_power: 95,
  sprite_url: `/games/${aid}/sprites/2.png?v=rom-portraits-1`, key: '0', ...extra})
const offer = (id, status, from, to, extra = {}) => ({id: id.repeat(32), status, reason: '', created_at: 1000, updated_at: 1000,
  expires_at: status === 'pending' ? 605800 : null, from, to, manual_id: null, trade: null, ...extra})

test('the trading page lists incoming and outgoing offers with Accept, Decline and Withdraw', async () => {
  const data = {adventure_id: FROM, viewer_only: false,
    incoming: [offer('1', 'pending', side(TO, 'Second <Red>', 'Pikachu'), side(FROM, 'First Red', 'Ivysaur'))],
    outgoing: [offer('2', 'pending', side(FROM, 'First Red', 'Charmander'), side(TO, 'Second <Red>', 'Squirtle')),
      offer('3', 'accepted', side(FROM, 'First Red', 'Rattata'), side(TO, 'Second <Red>', 'Pidgey'),
        {manual_id: 'e'.repeat(32), trade: {id: 'e'.repeat(32), state: 'queued', position: 2, left_id: FROM, right_id: TO}})]}
  const accepted = []
  const view = trading({offers: () => data, respond: (path, options) => {
    if (options.method === 'POST') { accepted.push(path)
      return json({status: 'accepted'}) }
    return null
  }})
  await settle()
  assert.equal(view.calls[0].path, `/api/v1/interactions/trade-offers?adventure_id=${FROM}`)
  assert.equal(view.element('#trade-offers-section').hidden, false)
  const incoming = view.element('#offers-incoming').innerHTML
  assert.match(incoming, /From <a href="\/games\/b{32}\/trading">Second &lt.Red&gt./)
  assert.match(incoming, /You send · Lv. 20.*Ivysaur.*You receive · Lv. 20.*Pikachu/s)
  assert.match(incoming, /Battle Power 95 · Stat Power 180/)
  assert.match(incoming, /sprites\/2\.png/)
  assert.match(incoming, /data-offer-action="accept"[^>]*>Accept</)
  assert.match(incoming, /data-offer-action="decline"[^>]*>Decline</)
  assert.doesNotMatch(incoming, /withdraw/)
  const outgoing = view.element('#offers-outgoing').innerHTML
  assert.match(outgoing, /data-offer-action="withdraw" data-offer-id="2{32}"/)
  assert.doesNotMatch(outgoing, /data-offer-id="3{32}"/)
  assert.match(outgoing, /Accepted · Trading/)
  assert.match(outgoing, /class="manual-steps"/)
  assert.match(outgoing, /Waiting in line. 1 chosen trade goes first./)
  view.element('#trade-offers-section').onclick(clickOn('data-offer-action', {offerAction: 'accept', offerId: '1'.repeat(32)}))
  await settle()
  assert.deepEqual(accepted, [`/api/v1/interactions/trade-offers/${'1'.repeat(32)}/accept`])
})

test('a stale offer explains why on accept and view-only or view-link pages show no buttons', async () => {
  const pending = offer('1', 'pending', side(TO, 'Second Red', 'Pikachu'), side(FROM, 'First Red', 'Ivysaur'))
  const stale = trading({offers: () => ({adventure_id: FROM, viewer_only: false, incoming: [pending], outgoing: []}),
    respond: (path, options) => options.method === 'POST' ? json({status: 'expired', reason: 'Pikachu is no longer in Second Red'}) : null})
  await settle()
  stale.element('#trade-offers-section').onclick(clickOn('data-offer-action', {offerAction: 'accept', offerId: '1'.repeat(32)}))
  await settle()
  assert.equal(stale.element('#offers-note').textContent, 'Pikachu is no longer in Second Red')

  const locked = trading({offers: () => ({adventure_id: FROM, viewer_only: true, incoming: [pending], outgoing: []})})
  await settle()
  assert.match(locked.element('#offers-incoming').innerHTML, /Waiting for an answer/)
  assert.doesNotMatch(locked.element('#offers-incoming').innerHTML, /data-offer-action/)

  const viewer = trading({base: `/view/${FROM}`, offers: () => ({adventure_id: FROM, viewer_only: false, incoming: [pending], outgoing: []})})
  await settle()
  assert.deepEqual(viewer.calls, [])
  assert.equal(viewer.element('#trade-offers-section').hidden, true)
})
