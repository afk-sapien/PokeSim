const assert = require('node:assert/strict')
const test = require('node:test')

const {createFrameQueue} = require('../pokesim/web/static/frame-delay.js')

test('frames wait until due and the newest due frame replaces older ones', () => {
  const queue = createFrameQueue()
  queue.push('a', 500)
  queue.push('b', 600)
  queue.push('c', 700)
  assert.deepEqual(queue.take(400), {show: null, drop: []})
  assert.equal(queue.next(), 500)
  assert.deepEqual(queue.take(650), {show: 'b', drop: ['a']})
  assert.equal(queue.next(), 700)
  assert.deepEqual(queue.take(700), {show: 'c', drop: []})
  assert.equal(queue.next(), null)
})

test('a shrinking delay never shows a later frame before an earlier one', () => {
  const queue = createFrameQueue()
  queue.push('old', 1000)
  queue.push('new', 200)
  assert.deepEqual(queue.take(500), {show: null, drop: []})
  assert.deepEqual(queue.take(1000), {show: 'new', drop: ['old']})
})

test('the limit pushes out the oldest frames', () => {
  const queue = createFrameQueue({limit: 2})
  assert.deepEqual(queue.push('a', 1), [])
  assert.deepEqual(queue.push('b', 2), [])
  assert.deepEqual(queue.push('c', 3), ['a'])
  assert.equal(queue.size, 2)
  assert.deepEqual(queue.clear(), ['b', 'c'])
  assert.equal(queue.size, 0)
})
