const rewind = document.querySelector('#rewind')
const rewindError = document.querySelector('#rewind-error')

if (rewind) rewind.addEventListener('click', async () => {
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
})

// The server writes the moment in UTC; show it in the reader's own time.
const logged = document.querySelector('#logged')
const when = new Date(logged?.dateTime || '')
if (logged && !Number.isNaN(when.getTime())) {
  logged.textContent = when.toLocaleString(undefined, {dateStyle: 'medium', timeStyle: 'short'})
  logged.title = logged.dateTime
}
