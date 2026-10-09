// The road so far: the journal's headline numbers as step lines on one shared clock.
(() => {
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({'&': '&amp', '<': '&lt', '>': '&gt', '"': '&quot', "'": '&#39'}[char] + String.fromCharCode(59)))
  const WIDTH = 600
  const HEIGHT = 64
  // Keeps a line at zero or at its best clear of the edges, so its stroke is never cut in half.
  const INSET = 3
  // Badges are over within the first day, so the long goals take their place. A series without
  // a max scales to its own best and shows no denominator.
  // The page names its cartridge's Pokédex size: 151 in Kanto, 251 with Johto.
  const dexTotal = () => {
    const size = Number(document.querySelector('meta[name="pokesim-dex-total"]')?.content)
    return Number.isInteger(size) && size > 0 ? size : 151
  }
  const series = (total = dexTotal()) => [
    {key: 'owned', label: 'Pokédex registered', max: total},
    {key: 'level100', label: 'Level 100 species', max: total},
    {key: 'perfect', label: 'Perfect finds'},
    {key: 'league', label: 'League wins'},
  ]

  // A step line holds each value until the next row changes it, then runs on to `until`.
  function stepPath(rows, key, start, until, max, min = 0) {
    const span = Math.max(until - start, 1)
    const x = (ts) => (Math.min(Math.max(ts, start), until) - start) / span * WIDTH
    const y = (value) => HEIGHT - INSET - (Math.min(Math.max(value, min), max) - min) / Math.max(max - min, 1e-9) * (HEIGHT - 2 * INSET)
    let path = ''
    let active = false
    for (const row of rows) {
      if (row[key] == null) {
        if (active) path += `H${x(row.ts).toFixed(1)}`
        active = false
        continue
      }
      const point = `${x(row.ts).toFixed(1)},${y(row[key]).toFixed(1)}`
      path += active ? `H${x(row.ts).toFixed(1)}V${y(row[key]).toFixed(1)}` : `M${point}`
      active = true
    }
    return path + (active ? `H${WIDTH}` : '')
  }

  function describe(rows, until, seriesList = series()) {
    const start = rows[0].ts
    return seriesList.map((series) => {
      const values = rows.map((row) => row[series.key]).filter((value) => value != null)
      const first = values[0] ?? 0
      const last = values.at(-1) ?? 0
      let max = series.max || values.reduce((best, value) => Math.max(best, value), 1)
      let min = 0
      if (series.zoom && values.length) {
        const low = values.reduce((best, value) => Math.min(best, value), values[0])
        const high = values.reduce((best, value) => Math.max(best, value), values[0])
        const padding = Math.max(1, (high - low) * 0.1)
        min = Math.max(0, low - padding)
        max = Math.min(series.max || Infinity, high + padding)
      }
      return {...series, min, available: values.length > 0, first, last, max, fixed: Boolean(series.max), path: stepPath(rows, series.key, start, until, max, min)}
    })
  }

  const day = (ts) => new Date(ts * 1000).toLocaleDateString(undefined, {month: 'short', day: 'numeric'})

  function render(rows, now = Date.now() / 1000) {
    const section = document.querySelector('#road')
    if (!section) return
    section.hidden = !rows.length
    if (!rows.length) return
    const until = Math.max(now, rows.at(-1).ts)
    const days = Math.max(1, Math.round((until - rows[0].ts) / 86400))
    document.querySelector('#road-span').textContent = `Since ${day(rows[0].ts)} · ${days} ${days === 1 ? 'day' : 'days'}`
    document.querySelector('#road-charts').innerHTML = describe(rows, until).map((series) => {
      const summary = series.first === series.last ? `${series.label}: ${series.last} throughout` : `${series.label}: from ${series.first} to ${series.last}`
      return `<div class="progress-row progress-${series.key}"><div class="progress-label"><span class="micro">${esc(series.label)}</span><strong class="readout">${Number(series.last).toLocaleString()}${series.fixed ? `<span class="unit">/${series.max}</span>` : ''}</strong></div><svg class="progress-chart" viewBox="0 0 ${WIDTH} ${HEIGHT}" preserveAspectRatio="none" role="img" aria-label="${esc(summary)}"><path d="${series.path}" vector-effect="non-scaling-stroke"></path></svg></div>`
    }).join('')
  }

  let busy = false
  async function refresh() {
    if (busy || !document.querySelector('#road')) return
    busy = true
    try {
      const response = await PokeSim.fetch('/api/progress', {cache: 'no-store'})
      if (response.ok) render(await response.json())
    } catch (_) {
      // The chart is a companion to the journal; it tries again with the next refresh.
    } finally {
      busy = false
    }
  }

  globalThis.Progress = {stepPath, describe, render, refresh, series, WIDTH, HEIGHT}
  if (document.querySelector('#road')) {
    refresh()
    setInterval(() => { if (!document.hidden) refresh() }, 60000)
  }
})()
