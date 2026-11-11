const assert = require('node:assert/strict')
const fs = require('node:fs')
const test = require('node:test')
const vm = require('node:vm')

const source = fs.readFileSync('pokesim/web/static/routes.js', 'utf8') + '\n{}\n' + fs.readFileSync('pokesim/web/static/screen.js', 'utf8')
const flush = () => new Promise(resolve => setImmediate(resolve))
const response = body => ({ok: true, blob: async () => body})
const textOf = body => typeof body === 'string' ? body : body?.text
const part = text => Buffer.from(`--pokesimframe\r\nContent-Type: image/png\r\nContent-Length: ${text.length}\r\n\r\n${text}\r\n`)

// A /stream response whose bytes the test sends when it chooses.
function feed() {
  const pending = []
  let waiting = null
  const deliver = item => {
    if (!waiting) return pending.push(item)
    const {resolve, reject} = waiting
    waiting = null
    if (item.error) reject(item.error)
    else resolve(item)
  }
  return {
    response: {
      ok: true,
      headers: {get: name => name === 'content-type' ? 'multipart/x-mixed-replace; boundary=pokesimframe' : null},
      body: {getReader: () => ({read: () => {
        const item = pending.shift()
        if (item) return item.error ? Promise.reject(item.error) : Promise.resolve(item)
        return new Promise((resolve, reject) => { waiting = {resolve, reject} })
      }})},
    },
    send: (...texts) => deliver({done: false, value: Buffer.concat(texts.map(part))}),
    sendBytes: bytes => deliver({done: false, value: bytes}),
    end: () => deliver({done: true}),
    fail: error => deliver({error}),
  }
}

function viewer(responses, decode, globals = {}, streams = null) {
  let clock = 0
  let nextId = 0
  let requests = 0
  let streamRequests = 0
  const decoded = []
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
  const window = {addEventListener: (name, callback) => listeners.set(name, callback), ...globals}
  if (streams) window.PokeSimFrameStream = require('../pokesim/web/static/frame-stream.js')
  const harness = {
    screen, document, window, timers, revoked, signals, decoded,
    requests: () => requests,
    streamRequests: () => streamRequests,
    shown: () => textOf(urls.get(screen.src)),
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
      if (textOf(body) === 'invalid') throw new Error('Invalid JPEG')
      decoded.push(textOf(body))
      if (decode) await decode(body)
    }
  }
  class Blob {
    constructor(parts, options) {
      this.text = Buffer.from(parts[0]).toString()
      this.type = options?.type
    }
  }
  const streaming = streams ? {ReadableStream: class {}, Blob} : {}
  vm.runInNewContext(source, {
    ...streaming, document, window, Image: Frame, AbortController,
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
      assert.equal(options.cache, 'no-store')
      if (url === '/stream') {
        streamRequests += 1
        signals.push(options.signal)
        const next = streams.shift()
        assert.ok(next, 'Unexpected extra stream request')
        if (next.response) options.signal.addEventListener('abort', () => next.fail(new Error('Aborted')))
        return Promise.resolve(next.response || next)
      }
      assert.equal(url, '/frame.jpg')
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

test('cached sound holds frames by its delay and realtime shows them at once', async () => {
  const {createFrameQueue} = require('../pokesim/web/static/frame-delay.js')
  let wait = 0.5
  const view = viewer([response('first'), response('second'), response('third')], undefined, {
    PokeSimFrameDelay: {createFrameQueue},
    PokeSimAudioSync: {delay: () => wait},
  })
  await flush()
  assert.equal(view.screen.src, undefined)
  await view.advance(100)
  assert.equal(view.screen.src, undefined)
  await view.advance(400)
  const first = view.screen.src
  assert.ok(first)
  wait = 0
  await view.advance(100)
  assert.notEqual(view.screen.src, first)
  // The first frame was replaced and the second was still waiting, so both are released.
  assert.equal(view.revoked.length, 2)
  assert.ok(view.revoked.includes(first))
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

test('one stream request shows every frame and skips to the newest of a burst', async () => {
  const stream = feed()
  const view = viewer([], undefined, {}, [stream])
  await flush()
  assert.equal(view.streamRequests(), 1)
  stream.send('first')
  await flush()
  assert.equal(view.shown(), 'first')
  assert.equal(view.status.hidden, true)
  stream.send('second', 'third')
  await flush()
  assert.equal(view.shown(), 'third')
  assert.deepEqual(view.decoded, ['first', 'third'])
  // A frame split across reads is joined before it shows.
  const bytes = part('fourth')
  stream.sendBytes(bytes.subarray(0, 20))
  await flush()
  assert.equal(view.shown(), 'third')
  stream.sendBytes(bytes.subarray(20))
  await flush()
  assert.equal(view.shown(), 'fourth')
  assert.equal(view.requests(), 0)
  assert.equal(view.streamRequests(), 1)
  assert.equal(view.timers.size, 0)
})

test('a stream that shows nothing within two seconds gives way to polling', async () => {
  const stream = feed()
  const view = viewer([response('polled'), response('again')], undefined, {}, [stream])
  await flush()
  await view.advance(2000)
  assert.equal(view.signals[0].aborted, true)
  assert.equal(view.requests(), 1)
  assert.equal(view.shown(), 'polled')
  await view.advance(100)
  assert.equal(view.requests(), 2)
  assert.equal(view.streamRequests(), 1)
})

test('a refused stream polls at once', async () => {
  const view = viewer([response('polled')], undefined, {}, [{ok: false}])
  await flush()
  assert.equal(view.streamRequests(), 1)
  assert.equal(view.requests(), 1)
  assert.equal(view.shown(), 'polled')
})

test('a stream that ends after frames opens again and keeps the picture', async () => {
  const first = feed()
  const second = feed()
  const view = viewer([], undefined, {}, [first, second])
  await flush()
  first.send('first')
  await flush()
  first.end()
  await flush()
  assert.equal(view.shown(), 'first')
  await view.advance(100)
  assert.equal(view.streamRequests(), 2)
  second.send('second')
  await flush()
  assert.equal(view.shown(), 'second')
  assert.equal(view.requests(), 0)
})

test('a bad frame in the stream is skipped', async () => {
  const stream = feed()
  const view = viewer([], undefined, {}, [stream])
  await flush()
  stream.send('first')
  await flush()
  stream.send('invalid')
  await flush()
  assert.equal(view.shown(), 'first')
  stream.send('second')
  await flush()
  assert.equal(view.shown(), 'second')
  assert.equal(view.streamRequests(), 1)
})

test('a hidden tab closes the stream and showing it opens a new one', async () => {
  const first = feed()
  const second = feed()
  const view = viewer([], undefined, {}, [first, second])
  await flush()
  first.send('first')
  await flush()
  await view.visible(false)
  assert.equal(view.signals[0].aborted, true)
  assert.equal(view.timers.size, 0)
  assert.equal(view.shown(), 'first')
  await view.visible(true)
  assert.equal(view.streamRequests(), 2)
  assert.equal(view.requests(), 0)
})

test('polling that rides out an outage tries the stream again', async () => {
  const later = feed()
  const view = viewer([{ok: false}, response('back')], undefined, {}, [{ok: false}, later])
  await flush()
  assert.equal(view.status.hidden, false)
  await view.advance(1000)
  assert.equal(view.shown(), 'back')
  await view.advance(100)
  assert.equal(view.streamRequests(), 2)
  later.send('streamed')
  await flush()
  assert.equal(view.shown(), 'streamed')
})

test('cached sound holds every streamed frame by its delay', async () => {
  const {createFrameQueue} = require('../pokesim/web/static/frame-delay.js')
  const stream = feed()
  const view = viewer([], undefined, {
    PokeSimFrameDelay: {createFrameQueue},
    PokeSimAudioSync: {delay: () => 0.5},
  }, [stream])
  await flush()
  stream.send('first', 'second')
  await flush()
  assert.deepEqual(view.decoded, ['first', 'second'])
  assert.equal(view.screen.src, undefined)
  await view.advance(500)
  assert.equal(view.shown(), 'second')
})

test('the frame reader splits parts with and without a length', () => {
  const {boundaryOf, createPartReader} = require('../pokesim/web/static/frame-stream.js')
  assert.equal(boundaryOf('multipart/x-mixed-replace; boundary=pokesimframe'), 'pokesimframe')
  assert.equal(boundaryOf('multipart/x-mixed-replace; boundary="frame"'), 'frame')
  assert.equal(boundaryOf('image/png'), '')
  const reader = createPartReader('frame')
  // The library's trade preview sends JPEG parts with no length.
  assert.deepEqual(reader.push(Buffer.from('--frame\r\nContent-Type: image/jpeg\r\n\r\nab')), [])
  const [frame] = reader.push(Buffer.from('cd\r\n--frame\r\nContent-Type: image/jpeg\r\n\r\nef'))
  assert.equal(frame.type, 'image/jpeg')
  assert.equal(Buffer.from(frame.body).toString(), 'abcd')
  const sized = createPartReader('pokesimframe')
  const frames = sized.push(Buffer.concat([part('one'), part('two')]))
  assert.deepEqual(frames.map(item => Buffer.from(item.body).toString()), ['one', 'two'])
})
