(() => {
  const screen = document.getElementById('stream')
  if (!screen) return

  const status = document.createElement('span')
  status.className = 'screen-status'
  status.setAttribute('role', 'status')
  status.textContent = 'Connecting to game screen…'
  screen.parentElement.append(status)

  const frameInterval = 100
  // A stream that shows no frame this soon is being held back on the way, usually by a proxy
  // that buffers it. The page then polls for frames instead.
  const streamGrace = 2000
  const parts = window.PokeSimFrameStream
  const canStream = Boolean(parts && typeof ReadableStream === 'function' && typeof Blob === 'function')
  // One open stream sends every frame the game draws. Polling is the fallback.
  let streaming = canStream
  let pollFailed = false
  let timer
  let controller
  let busy = false
  let pageActive = true
  let displayedUrl
  // Cached sound plays behind the live edge. Frames wait the same time so picture and sound match.
  const queue = window.PokeSimFrameDelay?.createFrameQueue()
  let showTimer
  const delay = () => (queue && window.PokeSimAudioSync?.delay()) || 0

  function show(url) {
    const previousUrl = displayedUrl
    screen.src = url
    displayedUrl = url
    if (previousUrl) URL.revokeObjectURL(previousUrl)
  }

  function showDue() {
    clearTimeout(showTimer)
    const {show: frame, drop} = queue.take(performance.now())
    for (const url of drop) URL.revokeObjectURL(url)
    if (frame) show(frame)
    const next = queue.next()
    if (next !== null) showTimer = setTimeout(showDue, Math.max(0, next - performance.now()))
  }

  function dropQueued() {
    if (!queue?.size) return
    clearTimeout(showTimer)
    for (const url of queue.clear()) URL.revokeObjectURL(url)
  }

  // Decode a frame before it replaces the picture, then show it now or when cached sound reaches
  // it. Returns whether the frame was kept. A frame that cannot be decoded throws.
  async function present(blob, signal) {
    const url = URL.createObjectURL(blob)
    try {
      const candidate = new Image()
      candidate.src = url
      await candidate.decode()
    } catch (error) {
      URL.revokeObjectURL(url)
      throw error
    }
    if (signal.aborted || !pageActive || document.hidden) {
      URL.revokeObjectURL(url)
      return false
    }
    const wait = delay()
    if (wait > 0) {
      for (const old of queue.push(url, performance.now() + wait * 1000)) URL.revokeObjectURL(old)
      showDue()
    } else {
      dropQueued()
      show(url)
    }
    status.hidden = true
    return true
  }

  async function nextFrame() {
    if (busy || !pageActive || document.hidden) return
    busy = true
    const started = performance.now()
    controller = new AbortController()
    const request = controller
    const timeout = setTimeout(() => request.abort(), 5000)
    let retryDelay = frameInterval
    try {
      const response = await PokeSim.fetch('/frame.jpg', {cache: 'no-store', signal: request.signal})
      if (!response.ok) throw new Error('Frame unavailable')
      if (await present(await response.blob(), request.signal) && pollFailed) {
        // Back after an outage, so the stream is worth another try.
        pollFailed = false
        streaming = canStream
      }
    } catch (error) {
      if (!request.signal.aborted || (pageActive && !document.hidden)) {
        status.textContent = 'Reconnecting to game screen…'
        status.hidden = false
        retryDelay = 1000
        pollFailed = true
      }
    } finally {
      clearTimeout(timeout)
      controller = undefined
      busy = false
      if (pageActive && !document.hidden) {
        timer = setTimeout(connect, Math.max(0, retryDelay - (performance.now() - started)))
      }
    }
  }

  async function openStream() {
    if (busy || !pageActive || document.hidden) return
    busy = true
    controller = new AbortController()
    const request = controller
    let shown = 0
    let held = false
    const grace = setTimeout(() => {
      held = true
      request.abort()
    }, streamGrace)
    try {
      const response = await PokeSim.fetch('/stream', {cache: 'no-store', signal: request.signal})
      const boundary = parts.boundaryOf(response.headers?.get('content-type'))
      const reader = response.ok && boundary ? response.body?.getReader() : null
      if (!reader) throw new Error('Stream unavailable')
      const split = parts.createPartReader(boundary)
      while (true) {
        const {done, value} = await reader.read()
        if (done) break
        const frames = split.push(value)
        // Frames shown at once only need the newest. Frames held for cached sound all keep their turn.
        for (const frame of delay() > 0 ? frames : frames.slice(-1)) {
          try {
            if (!await present(new Blob([frame.body], {type: frame.type || 'image/png'}), request.signal)) continue
          } catch (error) {
            continue
          }
          shown += 1
          clearTimeout(grace)
        }
      }
    } catch (error) {
      // Polling takes over below, or the stream opens again.
    } finally {
      clearTimeout(grace)
      controller = undefined
      busy = false
    }
    // A hidden tab or a page left behind stops here. Showing it again reconnects.
    if (!pageActive || document.hidden || (request.signal.aborted && !held)) return
    if (!shown) {
      // Nothing came through. Poll as before. A held stream will not do better on a retry.
      streaming = false
      connect()
    } else {
      timer = setTimeout(connect, frameInterval)
    }
  }

  function connect() {
    clearTimeout(timer)
    if (busy) return
    void (streaming ? openStream() : nextFrame())
  }

  function suspend() {
    clearTimeout(timer)
    controller?.abort()
    dropQueued()
  }

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) suspend()
    else connect()
  })
  window.addEventListener('pagehide', () => {
    pageActive = false
    suspend()
  })
  window.addEventListener('pageshow', () => {
    pageActive = true
    connect()
  })
  window.pokesimScreen = {reconnect: connect}
  connect()
})()
