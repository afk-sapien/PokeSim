// Holds decoded screen frames until their show time, so the screen can trail cached audio by the
// same amount. Pure logic with no browser objects, so it runs under Node. Times are milliseconds.
(function (root) {
  const LIMIT = 64

  function createFrameQueue(options = {}) {
    const limit = options.limit || LIMIT
    let items = []
    return {
      get size() { return items.length },
      // Queue a frame to show at `due`, never before a frame queued earlier, so a shrinking delay
      // cannot reorder the screen. Returns frames pushed out by the limit, oldest first.
      push(frame, due) {
        if (items.length) due = Math.max(due, items[items.length - 1].due)
        items.push({frame, due})
        return items.length > limit ? items.splice(0, items.length - limit).map(item => item.frame) : []
      },
      // The newest frame that is due by `now`, and the older due frames it replaces.
      take(now) {
        let ready = 0
        while (ready < items.length && items[ready].due <= now) ready += 1
        if (!ready) return {show: null, drop: []}
        const due = items.splice(0, ready).map(item => item.frame)
        return {show: due.pop(), drop: due}
      },
      // When the next queued frame is due, or null when nothing waits.
      next() { return items.length ? items[0].due : null },
      // Empty the queue. Returns every frame, oldest first.
      clear() {
        const all = items.map(item => item.frame)
        items = []
        return all
      },
    }
  }

  const exported = {createFrameQueue, LIMIT}
  if (typeof module !== 'undefined' && module.exports) module.exports = exported
  root.PokeSimFrameDelay = exported
})(typeof globalThis !== 'undefined' ? globalThis : this)
