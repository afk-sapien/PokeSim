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
      const response = await fetch('/frame.jpg', {cache: 'no-store', signal: request.signal})
      if (!response.ok) throw new Error('Frame unavailable')
      const blob = await response.blob()
      candidateUrl = URL.createObjectURL(blob)
      const candidate = new Image()
      candidate.src = candidateUrl
      await candidate.decode()
      if (request.signal.aborted || !pageActive || document.hidden) return

      const previousUrl = displayedUrl
      screen.src = candidateUrl
      displayedUrl = candidateUrl
      candidateUrl = undefined
      if (previousUrl) URL.revokeObjectURL(previousUrl)
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
