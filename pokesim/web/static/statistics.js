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
  const raceTime = frames => {
    const seconds = Math.floor(frames / 60)
    return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`
  }
  function render(data) {
    const records = data.collection_records || {}
    const catches = records.catches
    const shiny = records.shiny
    const caught = document.querySelector('#stats-caught')
    caught.textContent = catches?.available ? number(catches.total) : 'Not tracked'
    document.querySelector('#stats-caught-label').textContent = catches?.complete_history ? 'Total caught' : 'Catches tracked'
    document.querySelector('#stats-caught-note').textContent = !catches?.available ? 'Unavailable for this game'
      : catches.complete_history ? 'Every catch this run' : 'Since tracking began'
    const perfect = records.perfect_found
    document.querySelector('#stats-perfect').textContent = Number.isFinite(perfect)
      ? number(perfect) + (perfect && records.perfect_count_is_minimum ? '+' : '') : 'Not tracked'
    document.querySelector('#stats-perfect-note').textContent = records.perfect_count_is_minimum
      ? 'Verified minimum of individual finds' : 'Individual finds'
    document.querySelector('#stats-shiny-seen').textContent = shiny?.available ? number(shiny.seen) : 'Not tracked'
    document.querySelector('#stats-shiny-acquired').textContent = shiny ? number(shiny.acquired) : 'Not tracked'
    document.querySelector('#stats-shiny-held').textContent = shiny ? number(shiny.held) : 'Not tracked'

    const marathon = data.marathon || {}
    document.querySelector('#marathon-best').textContent = marathon.best_frames == null
      ? 'No finish yet' : raceTime(marathon.best_frames)
    const race = marathon.current
    document.querySelector('#marathon-current').textContent = race
      ? (race.started ? raceTime(race.frames) : 'Heading to start') : 'Not racing'
    document.querySelector('#marathon-checkpoints').textContent = race?.started
      ? `${race.checkpoints} of ${marathon.total_checkpoints} checkpoints` : ''
    document.querySelector('#marathon-last').textContent = marathon.last
      ? raceTime(marathon.last.frames) : 'No attempts yet'
    document.querySelector('#marathon-result').textContent = marathon.last
      ? (marathon.last.finished ? (marathon.last.personal_best ? 'Finished · Personal best' : 'Finished') : 'Did not finish') : ''

    const returns = data.legendary_returns
    const panel = document.querySelector('#legendary-returns')
    panel.hidden = !returns?.enabled || !returns.available
    if (!panel.hidden) {
      const names = {144: 'Articuno', 145: 'Zapdos', 146: 'Moltres', 150: 'Mewtwo'}
      document.querySelector('#legendary-remaining').textContent = number(returns.remaining)
      const meter = document.querySelector('#legendary-meter')
      meter.max = returns.interval
      meter.value = returns.progress
      document.querySelector('#legendary-ready').textContent = returns.ready.length
        ? `Ready to revisit: ${returns.ready.map(dex => names[dex]).join(', ')}.`
        : `${number(returns.steps)} completed steps tracked. Previously acquired legendaries return at their original locations.`
    }
    const activities = data.event_returns
    const mew = data.mew_returns
    const activityPanel = document.querySelector('#event-returns')
    activityPanel.hidden = !activities?.enabled && !mew?.enabled
    const activityList = document.querySelector('#event-return-list')
    activityList.replaceChildren()
    const labels = {eevee: 'Eevee', dojo: 'Dojo rematch', fossil: 'Fossil expedition', trade_1: 'Mr. Mime exchange', trade_4: 'Farfetch’d exchange', trade_5: 'Lickitung exchange', trade_6: 'Jynx exchange'}
    const cards = (activities?.enabled ? activities.activities : []).map(row => {
      const remaining = Math.max(0, row.remaining)
      const ready = row.ready
      return {title: labels[row.key] || 'Exchange', key: row.key,
        state: ready ? 'ready' : remaining ? 'walking' : 'pending',
        badge: ready ? 'Ready' : remaining ? 'Walking' : 'Pending',
        value: ready ? 'Ready to revisit' : remaining ? number(remaining) : 'Steps complete',
        detail: ready ? 'Another visit is available.' : remaining ? 'steps remaining' : 'Waiting for the game to reopen this visit.',
        remaining, interval: activities.interval}
    })
    if (mew?.enabled) cards.push({title: 'Mew', key: 'mew',
      state: mew.first_gift || mew.league_required ? 'league' : 'walking',
      badge: mew.first_gift ? 'First gift' : mew.league_required ? 'League win' : 'Walking',
      value: mew.first_gift ? 'Become Champion' : mew.league_required ? 'Win the League' : number(mew.remaining),
      detail: mew.first_gift ? 'Your first Mew awaits a League victory.' : mew.league_required ? 'Claim another Mew with your next victory.' : 'steps remaining, then a League win',
      remaining: mew.remaining, interval: mew.first_gift ? null : mew.interval})
    document.querySelector('#event-return-summary').textContent = `${cards.filter(card => card.state === 'ready').length} ready to revisit`
    for (const card of cards) {
      const element = document.createElement('article')
      element.className = `return-card return-card--${card.state}`
      element.dataset.return = card.key
      const add = (tag, className, text, parent = element) => {
        const node = document.createElement(tag)
        node.className = className
        node.textContent = text
        parent.append(node)
        return node
      }
      const head = add('div', 'return-card-head', '')
      add('h3', 'legend legend--ink', card.title, head)
      add('span', 'return-state micro', card.badge, head)
      add('strong', 'return-value readout', card.value)
      add('p', 'return-detail note', card.detail)
      if (Number.isFinite(card.interval) && card.interval > 0) {
        const completed = Math.min(card.interval, Math.max(0, card.interval - card.remaining))
        const meter = add('progress', 'return-meter', '')
        meter.max = card.interval
        meter.value = completed
        meter.setAttribute('aria-label', `${card.title}: ${number(completed)} of ${number(card.interval)} steps`)
        add('p', 'return-count micro', `${number(completed)} / ${number(card.interval)} steps`)
      }
      activityList.append(element)
    }
    if (!cards.length) {
      document.querySelector('#event-return-summary').textContent = ''
      const empty = document.createElement('p')
      empty.className = 'return-empty note'
      empty.textContent = 'Complete original events to unlock return visits.'
      activityList.append(empty)
    }
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
