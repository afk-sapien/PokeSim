const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const vm = require('node:vm')

const source = fs.readFileSync('pokesim/web/static/screen.js', 'utf8')
const flush = () => new Promise(resolve => setImmediate(resolve))
const response = body => ({ok: true, blob: async () => body})

function viewer(responses, decode) {
  let clock = 0
  let nextId = 0
  let requests = 0
  const timers = new Map()
  const urls = new Map()
  const revoked = []
  const signals = []
  const listeners = new Map()
  const screen = {parentElement: {append(element) { harness.status = element }}}
  const document = {
    hidden: false,
    getElementById: () => screen,
    createElement: () => ({setAttribute() {}}),
    addEventListener: (name, callback) => listeners.set(name, callback),
  }
  const window = {addEventListener: (name, callback) => listeners.set(name, callback)}
  const harness = {
    screen, document, window, timers, revoked, signals,
    requests: () => requests,
    async advance(delay) {
      const entry = [...timers].find(([, timer]) => timer.delay === delay)
      assert.ok(entry, `Expected a ${delay}ms timer`)
      timers.delete(entry[0])
      clock += delay
      entry[1].callback()
      await flush()
    },
    async visible(visible) {
      document.hidden = !visible
      listeners.get('visibilitychange')()
      await flush()
    },
  }
  class Frame {
    async decode() {
      const body = urls.get(this.src)
      if (body === 'invalid') throw new Error('Invalid JPEG')
      if (decode) await decode(body)
    }
  }
  vm.runInNewContext(source, {
    document, window, Image: Frame, AbortController,
    performance: {now: () => clock},
    URL: {
      createObjectURL(blob) {
        const url = `blob:${++nextId}`
        urls.set(url, blob)
        return url
      },
      revokeObjectURL(url) { revoked.push(url)
        urls.delete(url)
      },
    },
    setTimeout(callback, delay) {
      const id = ++nextId
      timers.set(id, {callback, delay})
      return id
    },
    clearTimeout: id => timers.delete(id),
    fetch: (url, options) => {
      assert.equal(url, '/frame.jpg')
      assert.equal(options.cache, 'no-store')
      requests += 1
      signals.push(options.signal)
      const next = responses.shift()
      if (next === 'hang') {
        return new Promise((resolve, reject) => {
          options.signal.addEventListener('abort', () => reject(new Error('Aborted')))
        })
      }
      assert.ok(next, 'Unexpected extra frame request')
      return Promise.resolve(next)
    },
  })
  return harness
}

test('waits for download and decode before requesting another frame', async () => {
  let finishDownload
  let finishDecode
  const download = new Promise(resolve => { finishDownload = resolve })
  const decode = new Promise(resolve => { finishDecode = resolve })
  const view = viewer([download, response('second')], body => body === 'first' ? decode : undefined)
  for (const i of Array.from({length: 10}, (_, index) => index)) view.window.pokesimScreen.reconnect()
  assert.equal(view.requests(), 1)
  finishDownload(response('first'))
  await flush()
  assert.equal(view.screen.src, undefined)
  assert.equal(view.requests(), 1)
  finishDecode()
  await flush()
  const first = view.screen.src
  assert.ok(first)
  await view.advance(100)
  assert.equal(view.requests(), 2)
  assert.notEqual(view.screen.src, first)
  assert.ok(view.revoked.includes(first))
})

test('keeps the last good frame through bad JPEGs and server errors', async () => {
  const view = viewer([response('first'), response('invalid'), {ok: false}, response('recovered')])
  await flush()
  const first = view.screen.src
  await view.advance(100)
  assert.equal(view.screen.src, first)
  assert.equal(view.status.hidden, false)
  await view.advance(1000)
  assert.equal(view.screen.src, first)
  await view.advance(1000)
  assert.notEqual(view.screen.src, first)
  assert.equal(view.status.hidden, true)
})

test('aborts a hung download and recovers without clearing the image', async () => {
  const view = viewer([response('first'), 'hang', response('recovered')])
  await flush()
  const first = view.screen.src
  await view.advance(100)
  await view.advance(5000)
  assert.equal(view.signals[1].aborted, true)
  assert.equal(view.screen.src, first)
  await view.advance(0)
  assert.notEqual(view.screen.src, first)
})

test('stops hidden-tab downloads and resumes when visible', async () => {
  const view = viewer([response('first'), 'hang', response('recovered')])
  await flush()
  const first = view.screen.src
  await view.advance(100)
  await view.visible(false)
  assert.equal(view.signals[1].aborted, true)
  assert.equal(view.screen.src, first)
  assert.equal(view.timers.size, 0)
  await view.visible(true)
  assert.equal(view.requests(), 3)
  assert.notEqual(view.screen.src, first)
})
