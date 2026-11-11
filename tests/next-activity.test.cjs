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
  const made = tag => ({tag, className: '', textContent: '', children: [], append(...children) { this.children.push(...children) }})
  const context = vm.createContext({
    document: {querySelector: element, createElement: made},
    Option: function (label, value = label) { this.label = label; this.value = value },
    JSON, Array, Boolean, Error, Map, String, Date, encodeURIComponent,
    setTimeout: callback => timers.push(callback),
    clearTimeout: () => {},
    PokeSim: {
      fetch: async (url, init = {}) => {
        const body = init.body ? JSON.parse(init.body) : null
        sent.push({url, body})
        if (url.startsWith('/api/goals')) return reply(200, replies.goals || {goals: GOALS, pin: null})
        if (url.startsWith('/api/catalogue')) {
          const answer = typeof replies.catalogue === 'function' ? await replies.catalogue(url) : replies.catalogue
          return reply(...(answer || [200, {goals: [], reason: null}]))
        }
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

test('the picker lists the planner goals, and a view link gets no pin control', async () => {
  const {NextActivity, element, sent, settle} = load()
  NextActivity.update({viewer_only: true, strategy: {pin: null}})
  await settle()
  assert.equal(element('#next-activity').hidden, false)
  assert.equal(element('#next-activity-goal-field').hidden, true)
  assert.equal(element('#next-activity-search-field').hidden, true)
  assert.equal(element('#next-activity-set').hidden, true)
  assert.equal(element('#next-activity-cancel').hidden, true)
  assert.equal(sent.length, 0)
  NextActivity.update({viewer_only: false, strategy: {pin: null}})
  await settle()
  assert.equal(element('#next-activity').hidden, false)
  assert.equal(element('#next-activity-heading').textContent, 'Choose next')
  assert.equal(element('#next-activity-catalogue').hidden, true)
  assert.equal(sent.at(-1).url, '/api/goals')
  assert.deepEqual(element('#next-activity-goal').options.map(option => option.label), ['Choose a goal', 'Find Clefairy', 'Run the League'])
  assert.equal(element('#next-activity-set').hidden, false)
  assert.equal(element('#next-activity-cancel').hidden, true)
})

test('a stopped adventure shows neither the picker nor the goal list', () => {
  const {NextActivity, element} = load()
  NextActivity.update({viewer_only: true, stopped: true, strategy: {pin: null}})
  assert.equal(element('#next-activity').hidden, true)
  NextActivity.update({viewer_only: false, stopped: true, strategy: {pin: null}})
  assert.equal(element('#next-activity').hidden, true)
})

const OPEN = [{key: 'hunt', label: 'Find Clefairy', tier: 'progress', feasible: true, why_not: null},
              {key: 'league', label: 'Run the League', tier: 'filler', feasible: true, why_not: null}]
const WAITING = {key: 'surf', label: 'Catch a Pokemon on the water', tier: 'filler', feasible: false,
                 why_not: {kind: 'needs', detail: 'a Pokemon must learn Surf first'}}

test('when every goal is open the picker reads as before', async () => {
  const {NextActivity, element, settle} = load({goals: {goals: OPEN, pin: null}})
  NextActivity.update({strategy: {pin: null}})
  await settle()
  assert.deepEqual(element('#next-activity-goal').options.map(option => option.label), ['Choose a goal', 'Find Clefairy', 'Run the League'])
  element('#next-activity-goal').value = 'league'
  element('#next-activity-goal').listeners.change()
  assert.equal(element('#next-activity-note').textContent, '')
})

test('a waiting goal says why in the list and when chosen, and can still be set', async () => {
  const pin = {key: 'surf', label: WAITING.label, started: false, parked: WAITING.why_not}
  const {NextActivity, element, sent, settle} = load({goals: {goals: [...OPEN, WAITING], pin: null}, pin_goal: [200, {ok: true, pin}]})
  NextActivity.update({strategy: {pin: null}})
  await settle()
  assert.equal(element('#next-activity-goal').options.at(-1).label, 'Catch a Pokémon on the water (waiting: a Pokémon must learn Surf first)')
  element('#next-activity-goal').value = 'surf'
  element('#next-activity-goal').listeners.change()
  assert.equal(element('#next-activity-note').textContent, 'This goal waits: a Pokémon must learn Surf first. Set keeps it as next, and it runs once it can.')
  assert.equal(element('#next-activity-note').classList.contains('error'), false)
  assert.equal(element('#next-activity-set').hidden, false)
  assert.equal(element('#next-activity-set').disabled, false)
  // Reading the list again on focus keeps the choice and what it says.
  await element('#next-activity-goal').listeners.focus()
  assert.match(element('#next-activity-note').textContent, /^This goal waits/)
  await NextActivity.pick()
  assert.deepEqual(sent.at(-1).body, {action: 'pin_goal', value: 'surf'})
  assert.equal(element('#next-activity-status').textContent, 'Next: Catch a Pokémon on the water (waiting: a Pokémon must learn Surf first)')
  // A waiting row with no words still says it waits, and choosing an open goal clears the note.
  const quiet = load({goals: {goals: [...OPEN, {...WAITING, why_not: null}], pin: null}})
  quiet.NextActivity.update({strategy: {pin: null}})
  await quiet.settle()
  assert.equal(quiet.element('#next-activity-goal').options.at(-1).label, 'Catch a Pokémon on the water (waiting)')
  quiet.element('#next-activity-goal').value = 'surf'
  quiet.element('#next-activity-goal').listeners.change()
  assert.equal(quiet.element('#next-activity-note').textContent, 'This goal waits. Set keeps it as next, and it runs once it can.')
  quiet.element('#next-activity-goal').value = 'hunt'
  quiet.element('#next-activity-goal').listeners.change()
  assert.equal(quiet.element('#next-activity-note').textContent, '')
})

const CATALOGUE = {generation: 1, kinds: [], pin: null, reason: null, goals: [
  {key: 'hunt', kind: 'hunt', params: {}, title: 'Find Clefairy', tier: 'progress', feasible: true, why_not: null},
  {key: 'surf', kind: 'catch', params: {}, title: 'Catch a Pokemon on the water', tier: null, feasible: false,
   why_not: {kind: 'needs', detail: 'a Pokemon must learn Surf first'}}]}

test('a view link reads every goal from the catalogue when it opens the list, never on a refresh', async () => {
  const {NextActivity, element, sent, settle, timers} = load({catalogue: [200, CATALOGUE]})
  const pin = {key: 'hunt', label: 'Find Clefairy', parked: {kind: 'no_route', detail: 'no route found lately'}}
  NextActivity.update({viewer_only: true, strategy: {pin}})
  await settle()
  assert.equal(element('#next-activity-heading').textContent, 'Goals')
  assert.equal(element('#next-activity-status').textContent, 'Next: Find Clefairy (waiting: no route found lately)')
  assert.equal(element('#next-activity-cancel').hidden, true)
  assert.equal(element('#next-activity-catalogue').hidden, false)
  assert.equal(sent.length, 0)
  element('#next-activity-catalogue').open = true
  element('#next-activity-catalogue').listeners.toggle()
  await settle()
  assert.deepEqual(sent.map(request => request.url), ['/api/catalogue?limit=40'])
  const rows = element('#next-activity-catalogue-list').options
  assert.deepEqual(rows.map(row => row.children.map(part => part.textContent)),
    [['Find Clefairy'], ['Catch a Pokémon on the water', 'Waiting: a Pokémon must learn Surf first']])
  assert.equal(rows[1].children[1].className, 'plan-goal-why')
  // The live page refreshes every 2 seconds and the list is not read again.
  NextActivity.update({viewer_only: true, strategy: {pin}})
  NextActivity.update({viewer_only: true, strategy: {pin}})
  await settle()
  assert.equal(sent.length, 1)
  element('#next-activity-catalogue-search').value = ' Mr Mime '
  element('#next-activity-catalogue-search').listeners.input()
  timers.at(-1)()
  await settle()
  assert.equal(sent.at(-1).url, '/api/catalogue?limit=40&q=Mr%20Mime')
  assert.equal(sent.some(request => request.url.startsWith('/api/goals') || request.body), false)
})

test('an empty catalogue shows its reason, and a failed read says so', async () => {
  const none = load({catalogue: [200, {goals: [], reason: 'No goal matches that name'}]})
  none.NextActivity.update({viewer_only: true, strategy: {pin: null}})
  await none.NextActivity.browse()
  assert.deepEqual(none.element('#next-activity-catalogue-list').options, [])
  assert.equal(none.element('#next-activity-catalogue-note').textContent, 'No goal matches that name')
  const down = load({catalogue: [409, {detail: 'not running'}]})
  down.NextActivity.update({viewer_only: true, strategy: {pin: null}})
  await down.NextActivity.browse()
  assert.equal(down.element('#next-activity-catalogue-note').textContent, 'The goals could not be read. Please try again.')
  assert.equal(down.element('#next-activity-catalogue-note').classList.contains('error'), true)
})

test('an older catalogue answer never replaces a newer search', async () => {
  const held = []
  const {NextActivity, element} = load({catalogue: url => new Promise(resolve => held.push({url, resolve}))})
  NextActivity.update({viewer_only: true, strategy: {pin: null}})
  const first = NextActivity.browse()
  element('#next-activity-catalogue-search').value = 'surf'
  const second = NextActivity.browse()
  assert.deepEqual(held.map(read => read.url), ['/api/catalogue?limit=40', '/api/catalogue?limit=40&q=surf'])
  // The search answers first, then the read before it.
  held[1].resolve([200, {...CATALOGUE, goals: [CATALOGUE.goals[1]]}])
  await second
  held[0].resolve([200, CATALOGUE])
  await first
  const rows = element('#next-activity-catalogue-list').options
  assert.deepEqual(rows.map(row => row.children[0].textContent), ['Catch a Pokémon on the water'])
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

test('a pin the planner cannot run now says why, and one without a reason shows only its label', () => {
  const {NextActivity} = load()
  const noRoute = {kind: 'no_route', detail: 'no route found lately'}
  assert.equal(NextActivity.status({key: 'hunt', label: 'Find Clefairy', parked: noRoute}),
    'Next: Find Clefairy (waiting: no route found lately)')
  assert.equal(NextActivity.status({key: 'hunt', label: 'Find Clefairy', parked: {kind: 'no_route', detail: ''}}),
    'Next: Find Clefairy')
  assert.equal(NextActivity.status({key: 'hunt', label: 'Find Clefairy', parked: {kind: 'no_route', detail: '  '}}),
    'Next: Find Clefairy')
  assert.equal(NextActivity.status({key: 'hunt', label: 'Find Clefairy', parked: null}), 'Next: Find Clefairy')
})

test('a waiting pin says why as soon as it is set, and again on each state refresh', async () => {
  const pin = {key: 'league', label: 'Run the League', started: false,
               parked: {kind: 'needs', detail: 'a Pokemon must learn Surf first'}}
  const {NextActivity, element, settle} = load({pin_goal: [200, {ok: true, pin}]})
  NextActivity.update({strategy: {pin: null}})
  await settle()
  element('#next-activity-goal').value = 'league'
  await NextActivity.pick()
  assert.equal(element('#next-activity-status').textContent, 'Next: Run the League (waiting: a Pokémon must learn Surf first)')
  NextActivity.update({strategy: {pin: {...pin, parked: null}}})
  assert.equal(element('#next-activity-status').textContent, 'Next: Run the League')
  NextActivity.update({strategy: {pin: {...pin, parked: {kind: 'no_route', detail: 'no route found lately'}}}})
  assert.equal(element('#next-activity-status').textContent, 'Next: Run the League (waiting: no route found lately)')
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

test('a state refresh keeps a half-typed species name and leaves the lists as drawn', async () => {
  const {NextActivity, element, settle} = load({goals: {goals: [...GOALS, TRAIN], pin: null}})
  NextActivity.update({strategy: {pin: null}})
  await settle()
  element('#next-activity-goal').value = 'train'
  element('#next-activity-goal').listeners.change()
  element('#next-activity-species').value = 'Pik'
  element('#next-activity-stop').value = 'evolved'
  const species = element('#next-activity-species-list').options
  const stops = element('#next-activity-stop').options
  // The live page refreshes its state every 2 seconds while the name is being typed.
  NextActivity.update({strategy: {pin: null}})
  NextActivity.update({strategy: {pin: null}})
  assert.equal(element('#next-activity-species').value, 'Pik')
  assert.equal(element('#next-activity-stop').value, 'evolved')
  assert.equal(element('#next-activity-species-list').options, species)
  assert.equal(element('#next-activity-stop').options, stops)
  // Another goal still draws its own fields.
  element('#next-activity-goal').value = 'hunt'
  element('#next-activity-goal').listeners.change()
  assert.equal(element('#next-activity-species').value, '')
  assert.equal(element('#next-activity-species-field').hidden, true)
})
