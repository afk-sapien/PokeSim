const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const vm = require('node:vm')
const source = fs.readFileSync('pokesim/web/static/next-activity.js', 'utf8')

const GOALS = [{key: 'hunt', label: 'Find Clefairy', tier: 'progress'}, {key: 'league', label: 'Run the League', tier: 'filler'}]

function load(replies = {}) {
  const elements = new Map()
  const element = selector => {
    if (!elements.has(selector)) {
      const classes = new Set()
      elements.set(selector, {
        hidden: false, textContent: '', disabled: false, value: '', options: [], listeners: {},
        classList: {toggle: (name, on) => on ? classes.add(name) : classes.delete(name), contains: name => classes.has(name)},
        set innerHTML(html) { this.options = [] },
        add(option) { this.options.push(option) },
        addEventListener(type, listener) { this.listeners[type] = listener },
      })
    }
    return elements.get(selector)
  }
  const sent = []
  const reply = (status, body) => ({ok: status < 400, status, json: async () => body})
  const context = vm.createContext({
    document: {querySelector: element},
    Option: function (label, value) { this.label = label; this.value = value },
    JSON, Array, Boolean, Error,
    PokeSim: {
      fetch: async (url, init = {}) => {
        const body = init.body ? JSON.parse(init.body) : null
        sent.push({url, body})
        if (url === '/api/goals') return reply(200, replies.goals || {goals: GOALS, pin: null})
        return replies[body.action] ? reply(...replies[body.action]) : reply(200, {ok: true})
      },
    },
  })
  vm.runInContext(source, context)
  const settle = () => new Promise(resolve => setImmediate(resolve))
  return {NextActivity: context.NextActivity, element, sent, settle}
}

test('the status line names the pinned goal', () => {
  const {NextActivity} = load()
  assert.equal(NextActivity.status({key: 'hunt', label: 'Find Clefairy'}), 'Next: Find Clefairy')
  assert.equal(NextActivity.status(null), '')
})

test('the picker lists the planner goals and hides from a view link', async () => {
  const {NextActivity, element, sent, settle} = load()
  NextActivity.update({viewer_only: true, strategy: {pin: null}})
  assert.equal(element('#next-activity').hidden, true)
  NextActivity.update({viewer_only: false, strategy: {pin: null}})
  await settle()
  assert.equal(element('#next-activity').hidden, false)
  assert.equal(sent.at(-1).url, '/api/goals')
  assert.deepEqual(element('#next-activity-goal').options.map(option => option.label), ['Choose a goal', 'Find Clefairy', 'Run the League'])
  assert.equal(element('#next-activity-set').hidden, false)
  assert.equal(element('#next-activity-cancel').hidden, true)
})

test('an empty list shows the reason and cannot be set', async () => {
  const {NextActivity, element, settle} = load({goals: {goals: [], pin: null, reason: 'The story comes first until the Champion is beaten'}})
  NextActivity.update({strategy: {}})
  await settle()
  assert.equal(element('#next-activity-note').textContent, 'The story comes first until the Champion is beaten')
  assert.equal(element('#next-activity-set').disabled, true)
  assert.equal(element('#next-activity-set').hidden, true)
  assert.equal(element('#next-activity-goal').hidden, true)
})

test('setting a goal shows Next and a Cancel button, and Cancel brings the picker back', async () => {
  const {NextActivity, element, sent, settle} = load({pin_goal: [200, {ok: true, pin: {key: 'league', label: 'Run the League', started: false}}]})
  NextActivity.update({strategy: {pin: null}})
  await settle()
  element('#next-activity-goal').value = 'league'
  await NextActivity.pick()
  assert.deepEqual(sent.at(-1), {url: '/api/control', body: {action: 'pin_goal', value: 'league'}})
  assert.equal(element('#next-activity-status').textContent, 'Next: Run the League')
  assert.equal(element('#next-activity-status').hidden, false)
  assert.equal(element('#next-activity-cancel').hidden, false)
  assert.equal(element('#next-activity-goal').hidden, true)
  await NextActivity.cancel()
  await settle()
  assert.deepEqual(sent.find(request => request.body?.action === 'unpin_goal').body, {action: 'unpin_goal'})
  assert.equal(element('#next-activity-status').hidden, true)
  assert.equal(element('#next-activity-cancel').hidden, true)
  assert.equal(element('#next-activity-goal').hidden, false)
})

test('a refusal shows its reason and leaves the picker as it was', async () => {
  const {NextActivity, element, settle} = load({pin_goal: [409, {detail: 'Not available now'}]})
  NextActivity.update({strategy: {pin: null}})
  await settle()
  element('#next-activity-goal').value = 'hunt'
  await NextActivity.pick()
  assert.equal(element('#next-activity-note').textContent, 'Not available now')
  assert.equal(element('#next-activity-note').classList.contains('error'), true)
  assert.equal(element('#next-activity-cancel').hidden, true)
})

test('a pin from the live state shows without a click', () => {
  const {NextActivity, element} = load()
  NextActivity.update({strategy: {pin: {key: 'hunt', label: 'Find Clefairy'}}})
  assert.equal(element('#next-activity-status').textContent, 'Next: Find Clefairy')
  assert.equal(element('#next-activity-cancel').hidden, false)
})
