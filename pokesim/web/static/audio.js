(() => {
  const button = document.querySelector('#sound')
  const status = document.querySelector('#sound-status')
  if (!button || !status) return
  let playback = null
  const message = text => {
    status.textContent = text
    status.hidden = !text
  }
  function clearQueue(session) {
    for (const source of session.sources) source.stop()
    session.sources.clear()
    session.next = 0
  }
  function stop(text = '') {
    const session = playback
    playback = null
    if (session) {
      session.request?.abort()
      clearQueue(session)
      session.context.close().catch(() => {})
    }
    button.textContent = 'Sound: Off'
    button.setAttribute('aria-pressed', 'false')
    message(text)
  }
  function play(session, pcm, rate, speed) {
    if (!pcm.byteLength) return
    if (pcm.byteLength % 2 || rate !== 48000 || !Number.isFinite(speed) || speed < 0.1 || speed > 1024) throw new Error('Unsupported audio format')
    const context = session.context
    if (session.next > context.currentTime + 0.35) clearQueue(session)
    // Keep only the live end of a delayed packet, even after a sudden speed change.
    const maxBytes = Math.max(2, Math.floor(rate * speed * 0.25) * 2)
    const samples = new Int8Array(pcm.slice(-maxBytes))
    const buffer = context.createBuffer(2, samples.length / 2, rate)
    for (const channel of [0, 1]) {
      const target = buffer.getChannelData(channel)
      target.forEach((_, index) => { target[index] = samples[index * 2 + channel] / 128 })
    }
    const source = context.createBufferSource()
    source.buffer = buffer
    source.playbackRate.value = speed
    source.connect(session.filter)
    session.sources.add(source)
    source.onended = () => { session.sources.delete(source)
      source.disconnect() }
    const start = Math.max(context.currentTime + 0.04, session.next)
    source.start(start)
    session.next = start + buffer.duration / speed
  }
  async function listen(session) {
    let after = -1
    try {
      while (playback === session) {
        const controller = new AbortController()
        session.request = controller
        const timeout = setTimeout(() => controller.abort(), 3000)
        let response, pcm
        try {
          response = await PokeSim.fetch(`/api/audio?after=${after}`, {signal: controller.signal, cache: 'no-store'})
          if (!response.ok) throw new Error('Audio unavailable')
          pcm = await response.arrayBuffer()
        } finally {
          clearTimeout(timeout)
        }
        if (playback !== session) return
        const sequence = Number(response.headers.get('X-Audio-Sequence'))
        const state = response.headers.get('X-Audio-State')
        if (!Number.isSafeInteger(sequence) || sequence < 0) throw new Error('Invalid audio sequence')
        // A restarted worker has a new sequence. Rejoin at its current live edge.
        if (sequence < after) clearQueue(session)
        after = sequence
        if (state === 'playing') {
          message('')
          play(session, pcm, Number(response.headers.get('X-Audio-Rate')), Number(response.headers.get('X-Audio-Speed') || 1))
        } else if (state === 'paused') {
          clearQueue(session)
          message('Sound paused')
        } else throw new Error('Invalid audio state')
        await new Promise(resolve => setTimeout(resolve, 100))
      }
    } catch (_) {
      if (playback === session) stop('Audio disconnected. Try again.')
    }
  }
  button.addEventListener('click', async () => {
    if (playback) return stop()
    const AudioContext = window.AudioContext || window.webkitAudioContext
    if (!AudioContext) return message('Audio is not supported in this browser.')
    let session
    try {
      const context = new AudioContext()
      const filter = context.createBiquadFilter()
      filter.type = 'highpass'
      filter.frequency.value = 20
      const gain = context.createGain()
      gain.gain.value = 0.5
      filter.connect(gain)
      gain.connect(context.destination)
      session = {context, filter, sources: new Set(), next: 0}
      playback = session
      button.textContent = 'Sound: On'
      button.setAttribute('aria-pressed', 'true')
      message('Connecting audio…')
      await context.resume()
      if (playback === session) listen(session)
    } catch (_) {
      if (!session || playback === session) stop('Could not start audio. Try again.')
    }
  })
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop() })
  window.addEventListener('pagehide', () => stop())
})()
