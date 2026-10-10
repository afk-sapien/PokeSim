const assert = require('node:assert/strict')
const test = require('node:test')

const {createJitterBuffer, chooseRate, MODES, MAX_SPEED} = require('../pokesim/web/static/audio-buffer.js')

const PACKET = 0.1

// Drive the buffer like the page does: a packet of game audio every `interval` seconds, held
// audio is offered again with the next packet.
function drive(buffer, {until, interval = PACKET, speed = 1, delays = () => 0, start = 0}) {
  let held = 0
  let now = start
  const plans = []
  const arrivals = []
  for (let tick = 0; now < until; tick++) {
    arrivals.push(start + tick * interval + delays(tick))
    now = start + (tick + 1) * interval
  }
  // A delayed packet never overtakes an earlier one.
  let previous = -Infinity
  for (const arrival of arrivals) {
    const at = Math.max(arrival, previous)
    previous = at
    const plan = buffer.accept(at, held + interval * speed, speed)
    plans.push({at, plan})
    held = plan.type === 'hold' ? held + interval * speed : 0
  }
  return plans
}

test('playback starts only once the target is buffered', () => {
  const buffer = createJitterBuffer()
  const plans = drive(buffer, {until: 1})
  const held = plans.filter(item => item.plan.type === 'hold')
  assert.equal(held.length, 3)
  const first = plans.find(item => item.plan.type === 'play')
  assert.ok(first.plan.wall >= MODES.watch.base)
  assert.equal(first.plan.rate, 1)
  assert.equal(first.plan.skip, 0)
  assert.equal(buffer.stats.underruns, 0)
})

test('steady delivery never underruns and the lead settles on the target', () => {
  const buffer = createJitterBuffer()
  const plans = drive(buffer, {until: 60})
  assert.equal(buffer.stats.underruns, 0)
  const late = plans.filter(item => item.at > 10 && item.plan.type === 'play')
  for (const {plan} of late) {
    assert.ok(Math.abs(plan.lead - MODES.watch.base) < 0.06, `lead ${plan.lead}`)
    assert.ok(Math.abs(plan.rate - 1) <= 0.02 + 1e-9)
  }
})

test('a stall grows the target and a repeat of the same stall is absorbed', () => {
  const buffer = createJitterBuffer()
  drive(buffer, {until: 10, delays: tick => tick === 50 ? 0.7 : 0})
  assert.equal(buffer.stats.underruns, 1)
  const grown = buffer.target
  assert.ok(grown > MODES.watch.base && grown <= MODES.watch.max)
  assert.ok(buffer.stats.silence > 0.1)
  // The same stall again, soon enough that the buffer has not shrunk back.
  drive(buffer, {until: 20, start: 10, delays: tick => tick === 50 ? 0.7 : 0})
  assert.equal(buffer.stats.underruns, 1)
})

test('the target never exceeds its ceiling however many stalls happen', () => {
  const buffer = createJitterBuffer()
  const delays = tick => tick % 15 === 0 && tick ? 2.5 : 0
  drive(buffer, {until: 120, delays})
  assert.ok(buffer.stats.underruns > 3)
  assert.ok(buffer.target <= MODES.watch.max + 1e-9)
})

test('the target shrinks slowly after a long calm spell and stops at the base', () => {
  const buffer = createJitterBuffer()
  drive(buffer, {until: 30, delays: tick => tick === 40 ? 1 : 0})
  const grown = buffer.target
  assert.ok(grown > MODES.watch.base + 0.1)
  drive(buffer, {until: 40, start: 30})
  assert.ok(buffer.target < grown)
  assert.ok(buffer.target > MODES.watch.base)
  drive(buffer, {until: 400, start: 40})
  assert.equal(buffer.target, MODES.watch.base)
})

test('a large excess skips forward with a fade instead of clearing', () => {
  const buffer = createJitterBuffer()
  drive(buffer, {until: 3})
  // The tab was throttled and a two second burst arrives at once.
  const now = 3.1
  const plan = buffer.accept(now, 2, 1)
  assert.equal(plan.type, 'play')
  assert.ok(plan.skip > 0.9)
  assert.equal(plan.fade, true)
  assert.ok(Math.abs(plan.lead - MODES.watch.base) < 0.06)
  assert.equal(buffer.stats.skips, 1)
})

test('after a long stall the backlog rejoins near the target', () => {
  const buffer = createJitterBuffer()
  drive(buffer, {until: 2})
  const plan = buffer.accept(6, 4, 1)
  assert.equal(plan.type, 'play')
  assert.equal(plan.rebuffered, true)
  assert.ok(plan.fade)
  assert.ok(plan.lead <= buffer.target + 0.1)
  assert.equal(buffer.stats.underruns, 1)
})

test('manual control uses a small lead and switching modes converges without clearing', () => {
  const buffer = createJitterBuffer()
  drive(buffer, {until: 10})
  assert.ok(buffer.target >= 0.4)
  assert.equal(buffer.setMode('manual'), true)
  assert.equal(buffer.target, MODES.manual.base)
  assert.equal(buffer.pollInterval, MODES.manual.poll)
  const plans = drive(buffer, {until: 14, start: 10.1, interval: MODES.manual.poll})
  assert.ok(plans.some(item => item.plan.flush))
  assert.equal(buffer.stats.flushes, 1)
  const last = plans.at(-1).plan
  assert.ok(last.lead < 0.2, `lead ${last.lead}`)
  assert.equal(buffer.stats.underruns, 0)
  buffer.setMode('watch')
  assert.equal(buffer.target, MODES.watch.base)
})

test('manual mode starts after one hundred milliseconds', () => {
  const buffer = createJitterBuffer({mode: 'manual'})
  const plans = drive(buffer, {until: 1, interval: MODES.manual.poll})
  const first = plans.findIndex(item => item.plan.type === 'play')
  assert.ok(first <= 3)
  assert.ok(plans[first].plan.lead <= 0.2)
})

test('manual mode can grow only up to its own ceiling', () => {
  const buffer = createJitterBuffer({mode: 'manual'})
  drive(buffer, {until: 60, interval: MODES.manual.poll, delays: tick => tick % 40 === 0 && tick ? 1.2 : 0})
  assert.ok(buffer.target <= MODES.manual.max + 1e-9)
  assert.ok(buffer.stats.underruns > 0)
})

test('pace measurement noise never changes the playback rate', () => {
  assert.equal(chooseRate(1, null), 1)
  let current = chooseRate(1.004, null)
  assert.equal(current, 1)
  for (const noisy of [0.99, 1.01, 0.985, 1.015, 1.019]) assert.equal(chooseRate(noisy, current), 1)
  assert.equal(chooseRate(0.5, null), 0.5)
  assert.equal(chooseRate(2.01, null), 2)
  assert.equal(chooseRate(4, 4), 4)
  assert.equal(chooseRate(1.3, null), 1.3)
  current = 1.3
  assert.equal(chooseRate(1.31, current), 1.3)
})

test('unusable or very fast paces are muted and the queue resets', () => {
  assert.equal(chooseRate(16, null), null)
  assert.equal(chooseRate(MAX_SPEED + 0.1, null), null)
  assert.equal(chooseRate(0.05, null), null)
  assert.equal(chooseRate(NaN, null), null)
  const buffer = createJitterBuffer()
  drive(buffer, {until: 2})
  assert.equal(buffer.accept(2.5, 0.1, 16).type, 'mute')
  assert.equal(buffer.primed, false)
  assert.equal(buffer.stats.underruns, 0)
  // Sound returns by priming again, not as an underrun.
  const plans = drive(buffer, {until: 4, start: 3})
  assert.ok(plans.some(item => item.plan.type === 'play'))
  assert.equal(buffer.stats.underruns, 0)
})

test('a fixed non-unit pace holds one rate and the same lead', () => {
  for (const speed of [0.5, 2, 4]) {
    const buffer = createJitterBuffer()
    const plans = drive(buffer, {until: 30, speed}).filter(item => item.at > 5 && item.plan.type === 'play')
    const rates = plans.map(item => item.plan.rate / speed)
    assert.ok(Math.max(...rates) - Math.min(...rates) <= 0.04 + 1e-9, `speed ${speed}`)
    assert.equal(buffer.stats.underruns, 0)
    for (const {plan} of plans) assert.ok(Math.abs(plan.lead - MODES.watch.base) < 0.08, `speed ${speed} lead ${plan.lead}`)
  }
})

test('the problem flag appears only when the largest buffer keeps underrunning', () => {
  const buffer = createJitterBuffer()
  assert.equal(buffer.problem(0), false)
  drive(buffer, {until: 30, delays: tick => tick === 100 || tick === 150 ? 2 : 0})
  assert.ok(buffer.target >= 1.4)
  assert.equal(buffer.problem(buffer.lastUnderrun + 1), true)
  assert.equal(buffer.problem(buffer.lastUnderrun + 60), false)
})

test('a pause resets without counting an underrun', () => {
  const buffer = createJitterBuffer()
  drive(buffer, {until: 3})
  buffer.reset()
  assert.equal(buffer.primed, false)
  const plans = drive(buffer, {until: 8, start: 7})
  assert.ok(plans.some(item => item.plan.type === 'play'))
  assert.equal(buffer.stats.underruns, 0)
})
