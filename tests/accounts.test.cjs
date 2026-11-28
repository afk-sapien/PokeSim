const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const vm = require('node:vm')
const source = fs.readFileSync('pokesim/web/static/accounts.js', 'utf8')
const settle = async () => {
  for (const tick of [1, 2, 3, 4, 5, 6]) await new Promise(resolve => setImmediate(resolve))
}

function node(tag) {
  const listeners = {}
  return {
    tag, children: [], textContent: '', className: '', value: '', hidden: false, disabled: false, dataset: {},
    get firstChild() { return this.children[0] },
    append(...more) { this.children.push(...more) },
    replaceChildren(...more) { this.children = more },
    addEventListener(name, callback) { listeners[name] = callback },
    setAttribute() {},
    fire(name) { return listeners[name]() },
  }
}

// The settings page's sharing panel for a member who owns adventures a and b.
function accounts(respond) {
  const elements = new Map()
  const calls = []
  const $ = selector => {
    if (!elements.has(selector)) elements.set(selector, node(selector))
    return elements.get(selector)
  }
  const document = {
    querySelector: $, createElement: node, getElementById: () => null, addEventListener() {},
    pokesimSession: {auth: 'accounts', user: {id: 'owner'}, role: 'member', csrf_token: 'csrf', methods: {}},
  }
  const context = vm.createContext({document, fetch: async (path, options = {}) => {
    calls.push({path, method: options.method || 'GET'})
    return {ok: true, json: async () => await respond(path, options) || {}}
  }})
  vm.runInContext(source, context)
  return {$, calls}
}

const OWNED = {adventures: [{id: 'a', name: 'First', access: 'owner'}, {id: 'b', name: 'Second', access: 'owner'}]}
const NAMES = {a: 'Ann', b: 'Bea'}
const sharing = aid => ({grants: [{user_id: `user-${aid}`, username: aid, display_name: NAMES[aid], role: 'viewer'}],
  users: [], shares: [{id: `link-${aid}`, created_at: 1, expires: 0}], legacy: null})

test('a slow answer for the adventure chosen before never draws the sharing panel', async () => {
  const waiting = {}
  let held = true
  const view = accounts(path => {
    if (path === '/api/v1/adventures') return OWNED
    const shown = path.match(/^\/api\/v1\/adventures\/(\w+)\/sharing$/)
    if (shown && !held) return sharing(shown[1])
    if (shown) return new Promise(resolve => { waiting[shown[1]] = () => resolve(sharing(shown[1])) })
  })
  await settle()
  const choice = view.$('#share-adventure')
  choice.value = 'a'
  choice.fire('change')
  choice.value = 'b'
  choice.fire('change')
  await settle()
  // The owner changed their mind before the first answer came, and it comes last.
  waiting.b()
  await settle()
  waiting.a()
  await settle()
  held = false
  const rows = view.$('#share-watchers').children
  assert.deepEqual(Array.from(rows, row => row.textContent), ['Bea can watch.'])
  const stop = rows[0].children.find(child => child.textContent === 'Stop sharing')
  await stop.fire('click')
  const link = view.$('#share-links').children[0].children.find(child => child.textContent === 'Turn off link')
  await link.fire('click')
  assert.deepEqual(Array.from(view.calls.filter(call => call.method === 'DELETE'), call => call.path),
    ['/api/v1/adventures/b/grants/user-b', '/api/v1/adventures/b/shares/link-b'])
})
