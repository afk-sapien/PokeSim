const element = id => document.getElementById(id)
const token = document.querySelector('meta[name="pokesim-token"]').content
let busy = false
let quitting = false
let finished = false
let navigateWhenReady = new URLSearchParams(window.location.search).has('launch')

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { 'X-PokeSim-Token': token, ...options.headers }
  })
  const data = await response.json()
  if (!response.ok) throw new Error(data.detail || 'PokeSim could not complete that step.')
  return data
}

function showError(error) {
  element('error').textContent = error.message
  element('error').hidden = false
}

element('setup').addEventListener('submit', async event => {
  event.preventDefault()
  const file = element('rom').files[0]
  if (!file || busy) return
  if (file.size > 1024 * 1024) {
    showError(new Error('Choose the .gb game file, no larger than 1 MB.'))
    return
  }
  busy = true
  element('begin').disabled = true
  element('error').hidden = true
  element('message').textContent = 'Checking your game…'
  try {
    await request(`/desktop/rom?starter=${encodeURIComponent(element('starter').value)}`, {
      method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file
    })
    navigateWhenReady = true
  } catch (error) {
    showError(error)
  } finally {
    busy = false
    element('begin').disabled = false
  }
})

element('retry').addEventListener('click', async () => {
  if (busy) return
  busy = true
  element('retry').disabled = true
  element('error').hidden = true
  try {
    await request('/desktop/start', { method: 'POST' })
    navigateWhenReady = true
  } catch (error) {
    showError(error)
  } finally {
    busy = false
    element('retry').disabled = false
  }
})

element('quit').addEventListener('click', async () => {
  if (quitting) return
  quitting = true
  element('quit').disabled = true
  element('message').textContent = 'Finishing setup or saving your adventure…'
  element('open').hidden = true
  element('retry').hidden = true
  element('setup').hidden = true
  try {
    const result = await request('/desktop/quit', { method: 'POST' })
    finished = true
    element('setup-title').textContent = 'See you back in Kanto.'
    element('message').textContent = result.error
      ? 'PokeSim has closed. Check the error below before your next launch.'
      : 'PokeSim has closed. You can close this tab and launch PokeSim again whenever you’re ready.'
    if (result.error) showError(new Error(result.error))
    element('quit').hidden = true
  } catch (error) {
    quitting = false
    element('quit').disabled = false
    showError(error)
  }
})

async function poll() {
  if (finished) return
  try {
    const state = await request('/desktop/status')
    if (!quitting && !busy) {
      element('setup').hidden = state.has_rom
      element('message').textContent = state.message
      element('data-dir').textContent = state.data_dir
      element('open').hidden = state.state !== 'ready'
      element('retry').hidden = !state.has_rom || !['error', 'stopped'].includes(state.state)
      element('quit').textContent = state.state === 'ready' ? 'Save and quit' : 'Quit PokeSim'
      if (state.error) showError(new Error(state.error))
      if (state.state === 'ready') {
        element('setup-title').textContent = 'Your team is out there.'
      }
      if (state.state === 'ready' && navigateWhenReady) {
        navigateWhenReady = false
        window.location.assign('/')
      }
    }
  } catch (error) {
    if (!quitting) {
      element('message').textContent = 'PokeSim is not responding. Relaunch the app if it has closed.'
    }
  } finally {
    if (!finished) window.setTimeout(poll, 750)
  }
}
poll()
