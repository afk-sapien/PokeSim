const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const vm = require('node:vm')
const source = ['types.js', 'routes.js', 'mon-grid.js']
  .map(name => fs.readFileSync(`pokesim/web/static/${name}`, 'utf8')).join('\n{}\n')

function page(base = '/games/gold-one') {
  const context = vm.createContext({document: {
    querySelector: name => ({content: name.includes('pokesim-base') ? base : name.includes('pokesim-sprites') ? 'p123' : ''}),
    addEventListener() {},
  }})
  vm.runInContext(source, context)
  return context
}

const gyarados = (extra = {}) => ({box: 0, position: 1, slot: 1, dex: 130, level: 40, name: 'Gyarados', nick: 'Gyarados',
  type_names: ['Water', 'Flying'], dvs: [0, 14, 10, 10, 10], dv_stars: 3, ...extra})

test('a shiny partner gets the shiny portrait address and a normal one does not', () => {
  const view = page()
  assert.equal(view.PokeSim.sprite(130, true), '/games/gold-one/sprites/shiny/130.png?v=p123')
  assert.equal(view.PokeSim.sprite(130), '/games/gold-one/sprites/130.png?v=p123')
  const shiny = view.MonGrid.card(gyarados({shiny: true}), 1, {all: true})
  assert.match(shiny, /src="\/games\/gold-one\/sprites\/shiny\/130\.png\?v=p123"/)
  assert.match(view.MonGrid.detail(gyarados({shiny: true}), {links: false}), /\/sprites\/shiny\/130\.png/)
  const normal = view.MonGrid.card(gyarados({shiny: false}), 1, {all: true})
  assert.match(normal, /src="\/games\/gold-one\/sprites\/130\.png\?v=p123"/)
  assert.doesNotMatch(normal, /shiny\/130/)
})

test('a portrait address from another adventure is used as given', () => {
  const view = page()
  const card = view.MonGrid.card(gyarados({shiny: true}), 1, {sprite: '/games/other/sprites/shiny/130.png?v=rom-portraits-1'})
  assert.match(card, /src="\/games\/other\/sprites\/shiny\/130\.png\?v=rom-portraits-1"/)
})
