(() => {
  const groups = [
    {title: 'Collection strength', series: [
      {key: 'collection_power', label: 'Total collection power', zoom: true},
      {key: 'strongest_six_power', label: 'Strongest six power', zoom: true},
      {key: 'average_power', label: 'Average Pokémon power', zoom: true},
      {key: 'held', label: 'Pokémon held'},
      {key: 'average_level', label: 'Average level', max: 100, zoom: true},
    ]},
    {title: 'Potential', series: [
      {key: 'average_dv', label: 'Average DV score', max: 100, unit: '%', deltaUnit: ' pp', zoom: true},
      {key: 'high_quality_held', label: 'Three-star or better held'},
    ]},
    {title: 'Life on the road', series: [
      {key: 'captures', label: 'Pokémon caught'},
      {key: 'steps', label: 'Recorded steps'},
      {key: 'battles', label: 'Battles entered'},
      {key: 'marathons', label: 'Marathons completed'},
      {key: 'recorded_hours', label: 'Recorded game hours'},
    ]},
    {title: 'Battle endurance', series: [
      {key: 'damage_dealt', label: 'Observed damage dealt'},
      {key: 'damage_taken', label: 'Observed damage taken'},
    ]},
  ]
  const number = value => Number(value).toLocaleString(undefined, {maximumFractionDigits: 1})
  function render(data) {
    const status = document.querySelector('#statistics-status')
    const target = document.querySelector('#statistics-charts')
    if (!data.history.length) {
      status.textContent = 'Stats will appear after the adventure starts moving.'
      target.replaceChildren()
      return
    }
    status.textContent = `Activity tracked since ${new Date(data.started_at * 1000).toLocaleDateString()}. Power includes the team and PC. Steps and damage are sampled totals.`
    const until = data.history.at(-1).ts
    const date = ts => new Date(ts * 1000).toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'short'})
    document.querySelector('#statistics-window').textContent = `${date(data.history[0].ts)} → ${date(until)}`
    target.innerHTML = groups.map(group => {
      const rows = Progress.describe(data.history, until, group.series).map(series => {
        const available = data.current[series.key] != null
        const value = available ? number(data.current[series.key]) + (series.unit || '') : 'Not recorded'
        const change = available ? number(data.current[series.key] - series.first) : ''
        const summary = available ? `${series.label}: from ${number(series.first)} to ${number(series.last)}` : `${series.label}: not recorded`
        return `<div class="progress-row"><div class="progress-label"><span class="micro">${series.label}</span><strong class="readout${available ? '' : ' readout--missing'}">${value}</strong>${available ? `<span class="note">${series.last > series.first ? '+' : ''}${change}${series.deltaUnit || series.unit || ''} since first record</span>` : ''}</div><div class="trend">${series.available ? `<span class="trend-scale micro">${number(series.min)} to ${number(series.max)}${series.unit || ''}</span>` : ''}<svg class="progress-chart" viewBox="0 0 ${Progress.WIDTH} ${Progress.HEIGHT}" preserveAspectRatio="none" role="img" aria-label="${summary}"><path d="${series.path}" vector-effect="non-scaling-stroke"></path></svg></div></div>`
      }).join('')
      return `<section class="statistics-section"><div class="column-head"><h2 class="legend legend--ink">${group.title}</h2></div><div class="progress-panel">${rows}</div></section>`
    }).join('')
  }
  let busy = false
  async function refresh() {
    if (busy) return
    busy = true
    try {
      const response = await PokeSim.fetch('/api/statistics', {cache: 'no-store'})
      if (!response.ok) throw new Error('Stats unavailable')
      render(await response.json())
    } catch (_) {
      document.querySelector('#statistics-status').textContent = 'Stats are reconnecting. Saved history is safe.'
    } finally {
      busy = false
    }
  }
  refresh()
  setInterval(() => { if (!document.hidden) refresh() }, 30000)
})()
