const rewind = document.querySelector('#rewind')
if (rewind) rewind.onclick = async () => {
  rewind.disabled = true
  try {
    const response = await PokeSim.fetch('/api/control', {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action: 'load_state', value: rewind.dataset.state})})
    if (!response.ok) throw new Error((await response.json()).detail || 'Could not rewind this adventure')
    location.href = PokeSim.url('/')
  } catch (error) { document.querySelector('#event-status').textContent = error.message
    rewind.disabled = false }
}
