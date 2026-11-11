// Splits the live screen stream (multipart/x-mixed-replace) into its frames. Pure logic with no
// browser objects, so it runs under Node.
(function (root) {
  // A part this large is not a Game Boy frame. Drop what is held rather than grow without end.
  const LIMIT = 4 * 1024 * 1024

  function boundaryOf(contentType) {
    const match = /boundary="?([^";,\s]+)"?/i.exec(contentType || '')
    return match ? match[1] : ''
  }

  const bytes = text => Uint8Array.from(text, character => character.charCodeAt(0))
  const HEAD_END = bytes('\r\n\r\n')

  function find(haystack, needle, from = 0) {
    const last = haystack.length - needle.length
    outer: for (let i = from; i <= last; i += 1) {
      for (let j = 0; j < needle.length; j += 1) {
        if (haystack[i + j] !== needle[j]) continue outer
      }
      return i
    }
    return -1
  }

  function createPartReader(boundary, options = {}) {
    const limit = options.limit || LIMIT
    const start = bytes('--' + boundary)
    const between = bytes('\r\n--' + boundary)
    let held = new Uint8Array(0)

    // The next whole part in what is held, with how many bytes it used, or null to wait for more.
    function next() {
      const at = find(held, start)
      if (at < 0) return null
      const headEnd = find(held, HEAD_END, at + start.length)
      if (headEnd < 0) return null
      const head = String.fromCharCode(...held.subarray(at + start.length, headEnd))
      const field = name => new RegExp(`^${name}:\\s*(.+?)\\s*$`, 'im').exec(head)?.[1]
      const bodyStart = headEnd + HEAD_END.length
      const length = Number.parseInt(field('content-length'), 10)
      let bodyEnd
      if (Number.isInteger(length) && length >= 0) {
        bodyEnd = bodyStart + length
        if (held.length < bodyEnd) return null
      } else {
        // Without a length, a part runs to the next boundary.
        bodyEnd = find(held, between, bodyStart)
        if (bodyEnd < 0) return null
      }
      return {frame: {type: field('content-type') || '', body: held.slice(bodyStart, bodyEnd)}, used: bodyEnd}
    }

    return {
      // Add bytes from the stream. Returns the frames they complete, oldest first.
      push(chunk) {
        const joined = new Uint8Array(held.length + chunk.length)
        joined.set(held)
        joined.set(chunk, held.length)
        held = joined
        const frames = []
        for (let part = next(); part; part = next()) {
          frames.push(part.frame)
          held = held.subarray(part.used)
        }
        if (held.length > limit) held = new Uint8Array(0)
        return frames
      },
    }
  }

  const exported = {boundaryOf, createPartReader}
  if (typeof module !== 'undefined' && module.exports) module.exports = exported
  root.PokeSimFrameStream = exported
})(typeof globalThis !== 'undefined' ? globalThis : this)
