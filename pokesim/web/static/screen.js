(() => {
  const screen = document.getElementById('stream')
  if (!screen) return

  const status = document.createElement('span')
  status.className = 'screen-status'
  status.setAttribute('role', 'status')
  status.textContent = 'Connecting to game screen…'
  screen.parentElement.append(status)

  const frameInterval = 100
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

  async function nextFrame() {
    if (busy || !pageActive || document.hidden) return
    busy = true
    const started = performance.now()
    controller = new AbortController()
    const request = controller
    const timeout = setTimeout(() => request.abort(), 5000)
    let candidateUrl
    let retryDelay = frameInterval
    try {
      const response = await PokeSim.fetch('/frame.jpg', {cache: 'no-store', signal: request.signal})
      if (!response.ok) throw new Error('Frame unavailable')
      const blob = await response.blob()
      candidateUrl = URL.createObjectURL(blob)
      const candidate = new Image()
      candidate.src = candidateUrl
      await candidate.decode()
      if (request.signal.aborted || !pageActive || document.hidden) return

      const wait = delay()
      if (wait > 0) {
        for (const url of queue.push(candidateUrl, performance.now() + wait * 1000)) URL.revokeObjectURL(url)
        candidateUrl = undefined
        showDue()
      } else {
        dropQueued()
        show(candidateUrl)
        candidateUrl = undefined
      }
      status.hidden = true
    } catch (error) {
      if (!request.signal.aborted || (pageActive && !document.hidden)) {
        status.textContent = 'Reconnecting to game screen…'
        status.hidden = false
        retryDelay = 1000
      }
    } finally {
      clearTimeout(timeout)
      if (candidateUrl) URL.revokeObjectURL(candidateUrl)
      controller = undefined
      busy = false
      if (pageActive && !document.hidden) {
        timer = setTimeout(nextFrame, Math.max(0, retryDelay - (performance.now() - started)))
      }
    }
  }

  function reconnect() {
    clearTimeout(timer)
    if (!busy) void nextFrame()
  }

  function suspend() {
    clearTimeout(timer)
    controller?.abort()
    dropQueued()
  }

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) suspend()
    else reconnect()
  })
  window.addEventListener('pagehide', () => {
    pageActive = false
    suspend()
  })
  window.addEventListener('pageshow', () => {
    pageActive = true
    reconnect()
  })
  window.pokesimScreen = {reconnect}
  reconnect()
})()
