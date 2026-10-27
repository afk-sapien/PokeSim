const assert = require('node:assert/strict')
const test = require('node:test')

const {createJitterBuffer, chooseRate, MODES, MAX_SPEED} = require('../pokesim/web/static/audio-buffer.js')

const PACKET = 0.1
const CACHED = MODES.cached
const MANUAL = MODES.manual

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

// The emulator stops for a while at each given tick and then carries on at its normal pace, so
// every later packet arrives that much later and no burst refills the queue.
const stalls = list => tick => list.reduce((total, [at, seconds]) => total + (tick >= at ? seconds : 0), 0)

// Silent stretches between scheduled audio, after the first start.
function gaps(plans) {
  const found = []
  let end = null
  for (const {plan} of plans) {
    if (plan.type !== 'play') continue
    if (plan.flush || plan.skip) end = Math.min(end ?? Infinity, plan.start)
    if (end !== null && plan.start > end + 1e-6) found.push(plan.start - end)
    end = plan.start + plan.wall
  }
  return found
}

test('playback starts only once the full second is buffered', () => {
  const buffer = createJitterBuffer()
  assert.equal(buffer.mode, 'cached')
  const plans = drive(buffer, {until: 3})
  const first = plans.find(item => item.plan.type === 'play')
  assert.ok(first.plan.wall >= CACHED.base - 1e-6)
  assert.ok(first.at >= CACHED.base - PACKET)
  assert.equal(first.plan.rate, 1)
  assert.equal(first.plan.skip, 0)
  assert.equal(buffer.target, CACHED.base)
  assert.equal(buffer.stats.underruns, 0)
})

test('steady delivery never underruns and the lead settles on the target', () => {
  const buffer = createJitterBuffer()
  const plans = drive(buffer, {until: 60})
  assert.equal(buffer.stats.underruns, 0)
  assert.deepEqual(gaps(plans), [])
  const late = plans.filter(item => item.at > 5 && item.plan.type === 'play')
  for (const {plan} of late) {
    assert.ok(Math.abs(plan.lead - CACHED.base) < 0.06, `lead ${plan.lead}`)
    assert.ok(Math.abs(plan.rate - 1) <= 0.02 + 1e-9)
  }
})

test('a late packet shorter than the lead is ridden out', () => {
  const buffer = createJitterBuffer()
  drive(buffer, {until: 8, delays: tick => tick === 40 ? 0.7 : 0})
  assert.equal(buffer.stats.underruns, 0)
  assert.equal(buffer.target, CACHED.base)
})

test('a dropout resumes after a short restart instead of priming the whole target again', () => {
  // A full prime would add the whole target as extra silence.
  const buffer = createJitterBuffer()
  const plans = drive(buffer, {until: 60, delays: stalls([[40, 1.4]])})
  assert.equal(buffer.stats.underruns, 1)
  const found = gaps(plans)
  assert.equal(found.length, 1)
  // About 0.4 seconds ran dry, plus the restart and the start delay.
  assert.ok(found[0] < 0.4 + CACHED.restart + 0.1, `gap ${found[0]}`)
  assert.equal(buffer.stats.rebuffers, 1)
  assert.ok(buffer.target > CACHED.base && buffer.target <= CACHED.max)
  // The lead is rebuilt by playing slightly slow, never faster than the refill limit.
  const after = plans.filter(item => item.at > 6 && item.plan.type === 'play')
  for (const {plan} of after) assert.ok(plan.rate >= 1 - 0.04 - 1e-9 && plan.rate <= 1.02 + 1e-9, `rate ${plan.rate}`)
  assert.ok(after.at(-1).plan.lead > buffer.target - 0.1, `lead ${after.at(-1).plan.lead}`)
})

test('a repeat of the same dropout is absorbed once the lead is rebuilt', () => {
  const buffer = createJitterBuffer()
  drive(buffer, {until: 60, delays: stalls([[40, 1.4], [500, 1.3]])})
  assert.equal(buffer.stats.underruns, 1)
})

test('the target never exceeds its ceiling however many stalls happen', () => {
  const buffer = createJitterBuffer()
  const delays = stalls(Array.from({length: 30}, (_, index) => [30 + index * 30, 2]))
  drive(buffer, {until: 300, delays})
  assert.ok(buffer.stats.underruns > 3)
  assert.ok(buffer.target <= CACHED.max + 1e-9)
})

test('the target shrinks slowly after a long calm spell and stops at the base', () => {
  const buffer = createJitterBuffer()
  drive(buffer, {until: 30, delays: stalls([[40, 1.8]])})
  const grown = buffer.target
  assert.ok(grown > CACHED.base + 0.1)
  drive(buffer, {until: 70, start: 32})
  assert.ok(buffer.target < grown)
  assert.ok(buffer.target > CACHED.base)
  drive(buffer, {until: 400, start: 70})
  assert.equal(buffer.target, CACHED.base)
})

test('a large excess skips forward with a fade instead of clearing', () => {
  const buffer = createJitterBuffer()
  drive(buffer, {until: 3})
  // The tab was throttled and a three second burst arrives at once.
  const plan = buffer.accept(3.1, 3, 1)
  assert.equal(plan.type, 'play')
  assert.ok(plan.skip > 1.5)
  assert.equal(plan.fade, true)
  assert.ok(Math.abs(plan.lead - CACHED.base) < 0.1)
  assert.equal(buffer.stats.skips, 1)
})

test('after a long stall the backlog rejoins near the target', () => {
  const buffer = createJitterBuffer()
  drive(buffer, {until: 3})
  const plan = buffer.accept(8, 5, 1)
  assert.equal(plan.type, 'play')
  assert.equal(plan.rebuffered, true)
  assert.ok(plan.fade)
  assert.ok(plan.lead <= buffer.target + 0.1)
  assert.equal(buffer.stats.underruns, 1)
})

test('taking control drops to the small lead after one short restart', () => {
  const buffer = createJitterBuffer()
  const watching = drive(buffer, {until: 10})
  assert.equal(buffer.setMode('manual'), true)
  assert.equal(buffer.target, MANUAL.base)
  assert.equal(buffer.pollInterval, MANUAL.poll)
  const plans = drive(buffer, {until: 14, start: 10, interval: MANUAL.poll})
  assert.equal(buffer.stats.flushes, 1)
  assert.equal(buffer.stats.underruns, 0)
  // The deep queue is cut and sound resumes after the manual restart, not a full prime.
  const end = watching.at(-1).plan
  const resumed = plans.find(item => item.plan.type === 'play')
  assert.ok(resumed.plan.start - plans.find(item => item.plan.flush).at < MANUAL.restart + 0.1)
  assert.ok(end.start + end.wall > resumed.plan.start - 0.1)
  assert.deepEqual(gaps(plans.slice(plans.indexOf(resumed) + 1)), [])
  const last = plans.at(-1).plan
  assert.ok(last.lead < 0.2, `lead ${last.lead}`)
  assert.ok(buffer.latency < 0.2)
})

test('handing back to the AI grows the lead smoothly with no silence', () => {
  const buffer = createJitterBuffer({mode: 'manual'})
  drive(buffer, {until: 5, interval: MANUAL.poll})
  assert.ok(buffer.latency < 0.2)
  buffer.setMode('cached')
  const plans = drive(buffer, {until: 60, start: 5, interval: CACHED.poll})
  assert.equal(buffer.stats.underruns, 0)
  assert.equal(buffer.stats.flushes, 0)
  assert.ok(plans.every(item => item.plan.type === 'play'))
  assert.deepEqual(gaps(plans), [])
  // The lead, and with it the screen delay, climbs in small steps toward the second.
  const leads = plans.map(item => item.plan.lead)
  for (let index = 1; index < leads.length; index++) assert.ok(leads[index] - leads[index - 1] < 0.02)
  assert.ok(leads.at(-1) > CACHED.base - 0.15, `lead ${leads.at(-1)}`)
  for (const {plan} of plans) assert.ok(plan.rate >= 1 - 0.04 - 1e-9)
})

test('manual mode starts after one hundred milliseconds', () => {
  const buffer = createJitterBuffer({mode: 'manual'})
  const plans = drive(buffer, {until: 1, interval: MANUAL.poll})
  const first = plans.findIndex(item => item.plan.type === 'play')
  assert.ok(first <= 3)
  assert.ok(plans[first].plan.lead <= 0.2)
})

test('manual mode can grow only up to its own ceiling', () => {
  const buffer = createJitterBuffer({mode: 'manual'})
  drive(buffer, {until: 60, interval: MANUAL.poll, delays: tick => tick % 40 === 0 && tick ? 1.2 : 0})
  assert.ok(buffer.target <= MANUAL.max + 1e-9)
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
  assert.equal(buffer.latency, 0)
  assert.equal(buffer.stats.underruns, 0)
  // Sound returns by priming again, not as an underrun.
  const plans = drive(buffer, {until: 5, start: 3})
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
    for (const {plan} of plans) assert.ok(Math.abs(plan.lead - CACHED.base) < 0.08, `speed ${speed} lead ${plan.lead}`)
  }
})

test('a stall and catch-up burst at a steady reported 4x keeps the 4x rate', () => {
  const buffer = createJitterBuffer()
  const speed = 4
  const plans = []
  let held = 0
  // The worker stalls for 0.8 seconds, so those polls come back empty and the page skips them.
  // The next poll brings everything it missed in one burst.
  for (let tick = 0; tick < 100; tick++) {
    if (tick >= 30 && tick < 38) continue
    const fresh = (tick === 38 ? 9 : 1) * PACKET * speed
    const plan = buffer.accept(tick * PACKET, held + fresh, speed)
    plans.push(plan)
    held = plan.type === 'hold' ? held + fresh : 0
  }
  assert.ok(plans.every(plan => plan.type !== 'mute'))
  const played = plans.filter(plan => plan.type === 'play')
  for (const plan of played) assert.ok(Math.abs(plan.rate / speed - 1) <= 0.02 + 1e-9, `rate ${plan.rate}`)
  assert.equal(buffer.rate, speed)
  assert.equal(buffer.stats.underruns, 0)
})

test('the problem flag appears only when the largest buffer keeps underrunning', () => {
  const buffer = createJitterBuffer()
  assert.equal(buffer.problem(0), false)
  drive(buffer, {until: 60, delays: stalls([[100, 3], [200, 3], [300, 3], [400, 3]])})
  assert.ok(buffer.target >= CACHED.max * 0.9)
  assert.equal(buffer.problem(buffer.lastUnderrun + 1), true)
  assert.equal(buffer.problem(buffer.lastUnderrun + 60), false)
})

test('latency reports the lead the newest packet joined with', () => {
  const buffer = createJitterBuffer()
  assert.equal(buffer.latency, 0)
  const plans = drive(buffer, {until: 5})
  assert.equal(buffer.latency, plans.at(-1).plan.lead)
  assert.ok(Math.abs(buffer.latency - CACHED.base) < 0.06)
})

test('unknown modes fall back to cached', () => {
  const buffer = createJitterBuffer({mode: 'bogus'})
  assert.equal(buffer.mode, 'cached')
  assert.equal(buffer.setMode('manual'), true)
  assert.equal(buffer.setMode('watch'), true)
  assert.equal(buffer.mode, 'cached')
})

test('a pause resets without counting an underrun', () => {
  const buffer = createJitterBuffer()
  drive(buffer, {until: 3})
  buffer.reset()
  assert.equal(buffer.primed, false)
  const plans = drive(buffer, {until: 9, start: 7})
  assert.ok(plans.some(item => item.plan.type === 'play'))
  assert.equal(buffer.stats.underruns, 0)
})
