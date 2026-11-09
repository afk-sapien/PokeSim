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
        replaceChildren(...children) { this.options = children },
        addEventListener(type, listener) { this.listeners[type] = listener },
      })
    }
    return elements.get(selector)
  }
  const sent = []
  const timers = []
  const reply = (status, body) => ({ok: status < 400, status, json: async () => body})
  const context = vm.createContext({
    document: {querySelector: element},
    Option: function (label, value = label) { this.label = label; this.value = value },
    JSON, Array, Boolean, Error, Map, String, Date, encodeURIComponent,
    setTimeout: callback => timers.push(callback),
    clearTimeout: () => {},
    PokeSim: {
      fetch: async (url, init = {}) => {
        const body = init.body ? JSON.parse(init.body) : null
        sent.push({url, body})
        if (url.startsWith('/api/goals')) return reply(200, replies.goals || {goals: GOALS, pin: null})
        return replies[body.action] ? reply(...replies[body.action]) : reply(200, {ok: true})
      },
    },
  })
  vm.runInContext(source, context)
  const settle = () => new Promise(resolve => setImmediate(resolve))
  return {NextActivity: context.NextActivity, element, sent, settle, timers}
}

test('the search box asks for goals by name, and the select never holds more than the most', async () => {
  const many = Array.from({length: 100}, (_, i) => ({key: `goal:${i}`, label: `Goal ${i}`, tier: 'filler'}))
  const {NextActivity, element, sent, settle, timers} = load({goals: {goals: many, pin: null}})
  NextActivity.update({strategy: {pin: null}})
  await settle()
  assert.equal(element('#next-activity-goal').options.length, NextActivity.MOST + 1)
  element('#next-activity-search').value = ' Mr Mime '
  element('#next-activity-search').listeners.input()
  timers.at(-1)()
  await settle()
  assert.equal(sent.at(-1).url, '/api/goals?q=Mr%20Mime')
})

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
  assert.equal(element('#next-activity-goal-field').hidden, true)
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
  assert.equal(element('#next-activity-goal-field').hidden, true)
  await NextActivity.cancel()
  await settle()
  assert.deepEqual(sent.find(request => request.body?.action === 'unpin_goal').body, {action: 'unpin_goal'})
  assert.equal(element('#next-activity-status').hidden, true)
  assert.equal(element('#next-activity-cancel').hidden, true)
  assert.equal(element('#next-activity-goal-field').hidden, false)
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

const TRAIN = {key: 'train', label: 'Train a Pokemon', tier: 'filler', species: ['Pikachu', 'Farfetch’d', 'Nidoran♀'], stops: [{key: 'level:30', label: 'Until level 30'}, {key: 'evolved', label: 'Until it evolves'}]}

test('a goal without a target shows only the Goal list, and names are spelled Pokémon', async () => {
  const {NextActivity, element, settle} = load({goals: {goals: [...GOALS, TRAIN], pin: null}})
  NextActivity.update({strategy: {pin: null}})
  await settle()
  assert.equal(element('#next-activity-goal-field').hidden, false)
  assert.equal(element('#next-activity-species-field').hidden, true)
  assert.equal(element('#next-activity-stop-field').hidden, true)
  assert.equal(element('#next-activity-goal').options.at(-1).label, 'Train a Pokémon')
  assert.equal(NextActivity.status({key: 'train', label: 'Train a Pokemon'}), 'Next: Train a Pokémon')
})

test('a targeted goal lists only the species it can reach, and when to stop', async () => {
  const {NextActivity, element, settle} = load({goals: {goals: [...GOALS, TRAIN], pin: null}})
  NextActivity.update({strategy: {pin: null}})
  await settle()
  element('#next-activity-goal').value = 'train'
  element('#next-activity-goal').listeners.change()
  assert.equal(element('#next-activity-species-field').hidden, false)
  assert.deepEqual(element('#next-activity-species-list').options.map(option => option.value), ['Pikachu', 'Farfetch’d', 'Nidoran♀'])
  assert.equal(element('#next-activity-stop-field').hidden, false)
  assert.deepEqual(element('#next-activity-stop').options.map(option => option.label), ['Until level 30', 'Until it evolves'])
  // Back to a goal with no target, the fields hide again.
  element('#next-activity-goal').value = 'hunt'
  element('#next-activity-goal').listeners.change()
  assert.equal(element('#next-activity-species-field').hidden, true)
  assert.equal(element('#next-activity-stop-field').hidden, true)
})

test('Set needs a species from the list, matched without case or punctuation', async () => {
  const {NextActivity, element, sent, settle} = load({goals: {goals: [TRAIN], pin: null}, pin_goal: [200, {ok: true, pin: {key: 'train', label: 'Train a Pokemon'}}]})
  NextActivity.update({strategy: {pin: null}})
  await settle()
  element('#next-activity-goal').value = 'train'
  element('#next-activity-goal').listeners.change()
  element('#next-activity-species').value = 'Mewtwo'
  await NextActivity.pick()
  assert.equal(element('#next-activity-note').textContent, 'Choose a Pokémon from the list.')
  assert.equal(sent.some(request => request.body?.action === 'pin_goal'), false)
  element('#next-activity-species').value = 'farfetchd'
  element('#next-activity-stop').value = 'evolved'
  await NextActivity.pick()
  assert.deepEqual(sent.at(-1).body, {action: 'pin_goal', value: 'train', target: {species: 'Farfetch’d', stop: 'evolved'}})
  assert.equal(element('#next-activity-status').textContent, 'Next: Train a Pokémon')
})
