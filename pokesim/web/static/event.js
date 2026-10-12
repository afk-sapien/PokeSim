const rewind = document.querySelector('#rewind')
const rewindError = document.querySelector('#rewind-error')
const rewindDialog = document.querySelector('#rewind-dialog')
const rewindNow = document.querySelector('#rewind-dialog-now')

// Hours and minutes from an "H:MM:SS" play time, for the loss it would cause.
function clockMinutes(text) {
  const parts = String(text || '').split(':').map(Number)
  if (parts.length < 2 || parts.some(Number.isNaN)) return null
  return parts[0] * 60 + parts[1]
}
function span(minutes) {
  const hours = Math.floor(minutes / 60)
  const rest = minutes % 60
  if (!hours) return `${rest} minute${rest === 1 ? '' : 's'}`
  return `${hours} hour${hours === 1 ? '' : 's'}${rest ? ` ${rest} minute${rest === 1 ? '' : 's'}` : ''}`
}

async function describeLoss() {
  if (!rewindNow) return
  rewindNow.hidden = true
  try {
    const response = await PokeSim.fetch('/api/state')
    if (!response.ok) return
    const state = await response.json()
    const now = state?.game?.playtime
    const then = rewind.dataset.playtime
    const lost = clockMinutes(now) - clockMinutes(then)
    if (!now || Number.isNaN(lost) || clockMinutes(now) === null || clockMinutes(then) === null) return
    rewindNow.textContent = lost > 0
      ? `The game is now at ${now.split(':').slice(0, 2).join(':')}, so about ${span(lost)} of play would be lost.`
      : `The game is now at ${now.split(':').slice(0, 2).join(':')}.`
    rewindNow.hidden = false
  } catch (_) {
    // The dialog still says what is lost without the current clock.
  }
}

async function rewindNowConfirmed() {
  rewind.disabled = true
  rewindError.hidden = true
  try {
    const response = await PokeSim.fetch('/api/control', {
      method: 'POST',
      headers: {'content-type': 'application/json'},
      body: JSON.stringify({action: 'load_state', value: rewind.dataset.state}),
    })
    if (!response.ok) {
      const result = await response.json().catch(() => ({}))
      throw new Error(typeof result.detail === 'string' ? result.detail : 'Could not rewind the game. Please try again.')
    }
    location.href = PokeSim.url('/')
  } catch (error) {
    rewindError.textContent = error.message || 'Could not reach the game. Please try again.'
    rewindError.hidden = false
    rewind.disabled = false
  }
}

if (rewind && rewindDialog) {
  rewind.addEventListener('click', () => {
    rewindError.hidden = true
    describeLoss()
    rewindDialog.showModal()
  })
  rewindDialog.addEventListener('close', () => {
    if (rewindDialog.returnValue === 'rewind') rewindNowConfirmed()
    rewindDialog.returnValue = ''
    rewind.focus()
  })
}

// The server writes the moment in UTC; show it in the reader's own time.
const logged = document.querySelector('#logged')
const when = new Date(logged?.dateTime || '')
if (logged && !Number.isNaN(when.getTime())) {
  logged.textContent = when.toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'short'})
  logged.title = logged.dateTime
}
