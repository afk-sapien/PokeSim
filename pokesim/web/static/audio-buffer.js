// Adaptive jitter buffer for live sound. Pure logic with no browser objects, so it runs under Node.
// All times are seconds on the audio clock. Audio arrives in packets of known media duration.
// The buffer decides when a packet should start, how fast it should play and how much of its
// head to skip, so that the queued audio ("lead") holds a target that grows after underruns.
(function (root) {
  // `restart` is how much audio a dropout waits for before sound resumes. The rest of the target
  // is then rebuilt by playing slightly slow, so a short dropout is never a long silence.
  const MODES = {
    // Watching: a deep buffer, with the screen delayed by the same lead so picture and sound match.
    cached: {base: 1, max: 3, excess: 0.6, poll: 0.15, restart: 0.4},
    // Playing by hand: button presses must feel immediate.
    manual: {base: 0.1, max: 0.3, excess: 0.08, poll: 0.04, restart: 0.05},
  }
  const modeName = mode => Object.hasOwn(MODES, mode) ? mode : 'cached'
  const START_DELAY = 0.03
  const UNDERRUN_SLACK = 0.005
  const GROW_PADDING = 0.05
  const MAX_GROW = 0.5
  const STABLE_SECONDS = 10
  const SHRINK_STEP = 0.05
  const TRIM_MAX = 0.02
  // Below the target the lead is rebuilt a little faster, about 0.7 of a semitone at most.
  const REFILL_MAX = 0.04
  const REFILL_GAIN = 0.1
  const TRIM_GAIN = 0.05
  const TRIM_DEADBAND = 0.04
  const TRIM_SMOOTHING = 0.3
  const MIN_KEEP = 0.02
  // Packet durations are summed in floating point, so ten 0.1 second packets can fall just short.
  const EPSILON = 1e-6
  const FADE = 0.006
  // Above this the pitch is meaningless and the server stops sending audio.
  const MAX_SPEED = 4.5
  const MIN_SPEED = 0.1
  const SNAP = [0.25, 0.5, 0.75, 1, 1.5, 2, 3, 4]
  const SNAP_TOLERANCE = 0.02
  const PROBLEM_SECONDS = 10

  const clamp = (value, low, high) => Math.min(high, Math.max(low, value))

  // Pick the playback rate for a measured pace. The rate only moves when the pace leaves a
  // 2% band, and common paces land exactly on 1x, 2x and so on, so a noisy measurement never
  // wobbles the pitch. Returns null when the pace is too fast (or unusable) to be worth hearing.
  function chooseRate(speed, current) {
    if (!Number.isFinite(speed) || speed < MIN_SPEED || speed > MAX_SPEED) return null
    if (current && Math.abs(speed / current - 1) <= SNAP_TOLERANCE) return current
    for (const step of SNAP) if (Math.abs(speed / step - 1) <= SNAP_TOLERANCE) return step
    return Math.round(speed * 100) / 100
  }

  function createJitterBuffer(options = {}) {
    const state = {
      mode: modeName(options.mode),
      targets: Object.fromEntries(Object.entries(MODES).map(([name, mode]) => [name, mode.base])),
      next: 0,
      primed: false,
      // Resume after a dropout or a mode change with a short restart instead of a full prime.
      quick: false,
      rebuffering: false,
      latency: 0,
      rate: null,
      trim: 0,
      lastUnderrun: -Infinity,
      lastChange: 0,
      stats: {underruns: 0, silence: 0, skips: 0, skipped: 0, holds: 0, rebuffers: 0, flushes: 0},
    }
    const config = () => MODES[state.mode]
    const api = {
      get mode() { return state.mode },
      get target() { return state.targets[state.mode] },
      get stats() { return {...state.stats} },
      get rate() { return state.rate },
      get pollInterval() { return config().poll },
      lead(now) { return Math.max(0, state.next - now) },
      // How far behind the live edge the newest packet plays: the lead it joined the queue with.
      get latency() { return state.primed ? state.latency : 0 },
      get primed() { return state.primed },
      get lastUnderrun() { return state.lastUnderrun },
      // True while the connection is recently unreliable even with a nearly full buffer.
      problem(now) {
        return now - state.lastUnderrun < PROBLEM_SECONDS && state.targets[state.mode] >= config().max * 0.9
      },
      setMode(mode) {
        mode = modeName(mode)
        if (mode === state.mode) return false
        state.mode = mode
        return true
      },
      // Forget queued audio (pause, restart, mute) without counting it as a fault.
      reset() {
        state.next = 0
        state.primed = false
        state.quick = false
        state.rebuffering = false
        state.trim = 0
      },
      // Offer a packet that lasts `duration` of game audio. `speed` is the pace the server reports.
      // Held audio stays with the caller, who offers the combined duration next time.
      // Returns {type: 'mute'|'hold'|'play', ...}. A play plan says when to start, the
      // playback rate, how many seconds of game audio to drop from the head, and whether
      // the join needs a fade because audio was skipped.
      accept(now, duration, speed) {
        const base = chooseRate(speed, state.rate)
        if (base === null) {
          state.rate = null
          api.reset()
          return {type: 'mute'}
        }
        if (state.rate !== base) state.rate = base
        const cfg = config()
        let target = state.targets[state.mode]
        // Slowly give the buffer back while the connection stays calm.
        if (state.primed && now - Math.max(state.lastUnderrun, state.lastChange) > STABLE_SECONDS && target > cfg.base) {
          target = Math.max(cfg.base, target - SHRINK_STEP)
          state.targets[state.mode] = target
          state.lastChange = now
        }
        if (target < cfg.base) target = state.targets[state.mode] = cfg.base
        let wall = duration / base
        let rebuffered = false
        let flush = false
        if (state.primed && state.next - now - target > cfg.excess) {
          // The queue itself is far ahead of the target, more than one packet can correct,
          // for instance on taking control.
          // Cut the queue with a fade and rejoin at the target.
          state.primed = false
          state.quick = true
          state.stats.flushes += 1
          flush = true
        }
        if (state.primed && state.next < now - UNDERRUN_SLACK) {
          const gap = now - state.next
          state.stats.underruns += 1
          state.stats.silence += gap
          state.lastUnderrun = now
          target = state.targets[state.mode] = Math.min(cfg.max, target + Math.min(gap, MAX_GROW) + GROW_PADDING)
          state.primed = false
          state.quick = true
          state.rebuffering = true
          state.trim = 0
        } else if (state.primed && state.next < now) {
          state.primed = false
          state.quick = true
        }
        if (!state.primed) {
          // Only the first start waits for the whole target. Afterwards sound resumes quickly
          // and the trim below rebuilds the rest without another silence.
          if (wall + EPSILON < (state.quick ? Math.min(target, cfg.restart) : target)) {
            state.stats.holds += 1
            return {type: 'hold', target, flush}
          }
          if (state.rebuffering) {
            state.stats.rebuffers += 1
            rebuffered = true
            state.rebuffering = false
          }
          const start = now + START_DELAY
          let skip = 0
          let fade = false
          const excess = wall - target - cfg.excess
          if (excess > 0) {
            // A long backlog after a stall: keep the newest audio and rejoin at the target.
            const dropped = Math.min(wall - target, wall - MIN_KEEP)
            skip = dropped * base
            wall -= dropped
            fade = true
            state.stats.skips += 1
            state.stats.skipped += dropped
          }
          state.primed = true
          state.quick = false
          state.next = start + wall
          state.latency = state.next - now
          state.trim = 0
          return {type: 'play', start, rate: base, skip, fade, wall, rebuffered, target, flush, lead: state.latency}
        }
        const lead = state.next - now
        const start = state.next
        let skip = 0
        let fade = false
        let error = lead + wall - target
        // The calm spell that shrinks the target starts only once the lead has been rebuilt.
        if (error < -TRIM_DEADBAND) state.lastChange = now
        if (error > cfg.excess) {
          // Far ahead of the target: skip forward rather than draining slowly or clearing.
          const dropped = Math.min(error, wall - MIN_KEEP)
          if (dropped > 0) {
            skip = dropped * base
            wall -= dropped
            fade = true
            state.stats.skips += 1
            state.stats.skipped += dropped
            error -= dropped
          }
        }
        // Hold the target with a tiny, smoothed speed change, never a hard jump.
        const wanted = Math.abs(error) < TRIM_DEADBAND ? 0
          : error < 0 ? Math.max(error * REFILL_GAIN, -REFILL_MAX) : Math.min(error * TRIM_GAIN, TRIM_MAX)
        state.trim += (wanted - state.trim) * TRIM_SMOOTHING
        const rate = base * (1 + state.trim)
        wall = (duration - skip) / rate
        state.next = start + wall
        state.latency = state.next - now
        return {type: 'play', start, rate, skip, fade, wall, rebuffered: false, target, flush: false, lead: state.latency}
      },
    }
    return api
  }

  const exported = {createJitterBuffer, chooseRate, MODES, MAX_SPEED, FADE}
  if (typeof module !== 'undefined' && module.exports) module.exports = exported
  root.PokeSimAudioBuffer = exported
})(typeof globalThis !== 'undefined' ? globalThis : this)
