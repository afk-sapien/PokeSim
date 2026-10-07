(() => {
  const button = document.querySelector('#sound')
  const status = document.querySelector('#sound-status')
  const Buffer = window.PokeSimAudioBuffer
  if (!button || !status || !Buffer) return
  const RETRY_WINDOW = 6000
  const REQUEST_TIMEOUT = 3000
  let playback = null
  const message = text => {
    status.textContent = text
    status.hidden = !text
  }
  // Stop everything queued. A short fade avoids a click when audio is cut mid-wave.
  function stopSources(session, fade = true) {
    const now = session.context.currentTime
    for (const [source, gain] of session.sources) {
      try {
        if (fade) {
          gain.gain.cancelScheduledValues(now)
          gain.gain.setValueAtTime(gain.gain.value, now)
          gain.gain.linearRampToValueAtTime(0, now + Buffer.FADE)
          source.stop(now + Buffer.FADE)
        } else source.stop()
      } catch (_) {}
    }
    session.sources.clear()
    session.last = null
  }
  function clearQueue(session, fade = true) {
    stopSources(session, fade)
    session.held = null
    session.buffer.reset()
  }
  function stop(text = '') {
    const session = playback
    playback = null
    if (session) {
      session.request?.abort()
      clearQueue(session, false)
      session.context.close().catch(() => {})
    }
    button.textContent = 'Sound: Off'
    button.setAttribute('aria-pressed', 'false')
    message(text)
  }
  function join(first, second) {
    if (!first) return second
    const joined = new Uint8Array(first.byteLength + second.byteLength)
    joined.set(new Uint8Array(first), 0)
    joined.set(new Uint8Array(second), first.byteLength)
    return joined.buffer
  }
  function schedule(session, pcm, rate, plan) {
    const context = session.context
    let samples = new Int8Array(pcm)
    const skipFrames = Math.min(Math.floor(plan.skip * rate), samples.length / 2 - 1)
    if (skipFrames > 0) samples = samples.subarray(skipFrames * 2)
    const frames = samples.length / 2
    const buffer = context.createBuffer(2, frames, rate)
    for (let channel = 0; channel < 2; channel++) {
      const target = buffer.getChannelData(channel)
      for (let index = 0; index < frames; index++) target[index] = samples[index * 2 + channel] / 128
    }
    const source = context.createBufferSource()
    const gain = context.createGain()
    source.buffer = buffer
    source.playbackRate.value = plan.rate
    source.connect(gain)
    gain.connect(session.filter)
    if (plan.fade) {
      // Skipping forward: close the old tail and open the new head so the join is not a click.
      const last = session.last
      if (last && last.end > context.currentTime) {
        const from = Math.max(context.currentTime, last.end - Buffer.FADE)
        last.gain.gain.setValueAtTime(1, from)
        last.gain.gain.linearRampToValueAtTime(0, last.end)
      }
      gain.gain.setValueAtTime(0, plan.start)
      gain.gain.linearRampToValueAtTime(1, plan.start + Buffer.FADE)
    }
    session.sources.set(source, gain)
    source.onended = () => {
      session.sources.delete(source)
      source.disconnect()
      gain.disconnect()
    }
    source.start(plan.start)
    session.last = {gain, end: plan.start + buffer.duration / plan.rate}
  }
  function play(session, pcm, rate, speed) {
    if (pcm.byteLength % 2 || rate !== 48000) throw new Error('Unsupported audio format')
    const combined = join(session.held, pcm)
    const duration = combined.byteLength / 2 / rate
    if (!duration) return
    const now = session.context.currentTime
    const plan = session.buffer.accept(now, duration, speed)
    if (plan.flush) stopSources(session)
    if (plan.type === 'hold') {
      session.held = combined
    } else {
      session.held = null
      schedule(session, combined, rate, plan)
    }
  }
  const pause = ms => new Promise(resolve => setTimeout(resolve, ms))
  async function listen(session) {
    let after = -1
    let failingSince = 0
    try {
      while (playback === session) {
        const began = performance.now()
        const controller = new AbortController()
        session.request = controller
        const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT)
        let response, pcm
        try {
          response = await PokeSim.fetch(`/api/audio?after=${after}`, {signal: controller.signal, cache: 'no-store'})
          if (!response.ok) throw new Error('Audio unavailable')
          pcm = await response.arrayBuffer()
          failingSince = 0
        } catch (error) {
          if (playback !== session) return
          // A slow or failed request is a hiccup, not the end. Keep the session and retry.
          failingSince = failingSince || performance.now()
          if (performance.now() - failingSince > RETRY_WINDOW) throw error
          await pause(250)
          continue
        } finally {
          clearTimeout(timeout)
        }
        if (playback !== session) return
        const sequence = Number(response.headers.get('X-Audio-Sequence'))
        const state = response.headers.get('X-Audio-State')
        if (!Number.isSafeInteger(sequence) || sequence < 0) throw new Error('Invalid audio sequence')
        // A restarted worker has a new sequence. Rejoin at its current live edge.
        if (sequence < after) clearQueue(session)
        // The server no longer holds frames this page never received, so what is queued is stale.
        // Drop it and let the jitter buffer prime again at the live edge instead of playing a gap.
        if (Number(response.headers.get('X-Audio-Dropped')) > 0) clearQueue(session)
        after = sequence
        const manual = response.headers.get('X-Audio-Mode') === 'manual'
        session.buffer.setMode(manual ? 'manual' : 'watch')
        if (state === 'playing') {
          const speed = Number(response.headers.get('X-Audio-Speed') || 1)
          if (!Number.isFinite(speed) || speed < 0.1) throw new Error('Unsupported audio format')
          if (Buffer.chooseRate(speed, null) === null) {
            // Too fast to be worth hearing. Stay connected so sound returns with the pace.
            clearQueue(session)
            message('Sound is off at this speed')
          } else {
            play(session, pcm, Number(response.headers.get('X-Audio-Rate')), speed)
            const buffer = session.buffer
            message(buffer.problem(session.context.currentTime) ? 'Audio connection is unstable'
              : buffer.primed ? '' : 'Connecting audio…')
          }
        } else if (state === 'paused') {
          clearQueue(session)
          message('Sound paused')
        } else throw new Error('Invalid audio state')
        const period = session.buffer.pollInterval * 1000
        await pause(Math.max(5, period - (performance.now() - began)))
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
      session = {context, filter, sources: new Map(), last: null, held: null, buffer: Buffer.createJitterBuffer()}
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
