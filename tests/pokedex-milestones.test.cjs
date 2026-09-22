const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const vm = require('node:vm')
const source = fs.readFileSync('pokesim/web/static/pokedex.js', 'utf8')

function view() {
  const elements = new Map()
  const element = selector => {
    if (!elements.has(selector)) elements.set(selector, {
      value: selector === '#search' ? '' : 'all', innerHTML: '', textContent: '',
      classList: {add() {}, remove() {}},
    })
    return elements.get(selector)
  }
  let payload = {started:true, owned:[1, 2, 3], party:[]}
  const fetch = async () => ({ok:true, json:async () => payload})
  const context = vm.createContext({document:{querySelector:element}, fetch,
    PokeSim:{base:'', fetch}})
  vm.runInContext(source.slice(0, source.indexOf("document.addEventListener('click'")), context)
  vm.runInContext("entries = [1, 2, 3].map(dex => ({dex, name:'Species ' + dex, types:['Grass']}))", context)
  return {element,
    async update(value) { payload = {...payload, ...value}
      await vm.runInContext('refreshStatus()', context) },
    filter(value) { element('#status-filter').value = value
      vm.runInContext('renderGrid()', context) },
  }
}

test('new milestones refresh cached cards without other inventory changes', async () => {
  const ui = view()
  await ui.update({})
  assert.equal(ui.element('#sum-perfect').textContent, '0')
  assert.doesNotMatch(ui.element('#grid').innerHTML, /level 100 reached/)
  await ui.update({milestones:{level_100:[1, 2, 3], perfect_species:[3], perfect_found:1, perfect_held:1}})
  assert.equal(ui.element('#maxed-meter').value, 3)
  assert.equal(ui.element('#sum-perfect').textContent, '1+')
  assert.match(ui.element('#grid').innerHTML, /level 100 reached/)
  assert.match(ui.element('#grid').innerHTML, /perfect DV species found/)
  ui.filter('perfect')
  assert.equal(ui.element('#result-count').textContent, '1 Pokémon')
  assert.match(ui.element('#grid').innerHTML, /data-dex="3"/)
  assert.doesNotMatch(ui.element('#grid').innerHTML, /data-dex="1"/)
  ui.filter('unmastered')
  assert.equal(ui.element('#result-count').textContent, '0 Pokémon')
})

test('three-star filters separate live partners from historical species', async () => {
  const ui = view()
  await ui.update({})
  await ui.update({party: [{dex: 1, dv_stars: 3}],
    milestones: {three_star_held: 1, high_quality_species: [1, 2], perfect_species: [3]}})
  ui.filter('quality')
  assert.equal(ui.element('#result-count').textContent, '3 Pokémon')
  assert.match(ui.element('#grid').innerHTML, /3-star or better DV species found/)
  ui.filter('three-held')
  assert.equal(ui.element('#result-count').textContent, '1 Pokémon')
  await ui.update({party: [], milestones: {high_quality_species: [1, 2], perfect_species: [3]}})
  assert.equal(ui.element('#result-count').textContent, '0 Pokémon')
  ui.filter('quality')
  assert.equal(ui.element('#result-count').textContent, '3 Pokémon')
})
