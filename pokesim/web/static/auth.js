// Log in, first-run setup and invite pages. All three post JSON with the CSRF token of an
// anonymous browser session, then move on to the page the person asked for.
(() => {
  const $ = selector => document.querySelector(selector)
  const page = document.body.dataset.page
  const token = document.body.dataset.token
  let csrf = ''
  const next = () => {
    const wanted = new URLSearchParams(location.search).get('next') || '/'
    // Only a path on this site. Anything else could send a fresh login to another site.
    return /^\/(?![/\\])/.test(wanted) ? wanted : '/'
  }
  const copy = {
    login: ['Log in', 'Log in to see your adventures.', 'Log in'],
    setup: ['Set up PokeSim', 'Create the first admin account. It owns every adventure that is already here.', 'Create admin'],
    invite: ['Join PokeSim', 'Choose a username and password for your new account.', 'Create account'],
  }[page]
  async function session() {
    const response = await fetch('/api/v1/session', {cache: 'no-store', credentials: 'same-origin'})
    const data = await response.json()
    csrf = data.csrf_token || ''
    return data
  }
  function result(message) {
    $('#auth-result').textContent = message
  }
  async function submit(event) {
    event.preventDefault()
    const password = $('#password').value
    if (page !== 'login' && password !== $('#confirm').value) return result('The two passwords do not match.')
    const body = {username: $('#username').value.trim(), password}
    let path = '/api/v1/auth/login'
    if (page === 'setup') {
      path = '/api/v1/auth/setup'
      body.code = $('#code').value.trim()
    } else if (page === 'invite') {
      path = '/api/v1/auth/invite'
      body.token = token
    }
    $('#auth-submit').disabled = true
    result('')
    try {
      const response = await fetch(path, {method: 'POST', credentials: 'same-origin',
        headers: {'Content-Type': 'application/json', 'X-PokeSim-CSRF': csrf}, body: JSON.stringify(body)})
      let data
      try { data = await response.json() } catch (_) { data = {} }
      if (!response.ok) {
        if (response.status === 403 && data.detail === 'Reload this page before making changes') await session()
        throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`)
      }
      location.replace(page === 'login' ? next() : '/')
    } catch (error) {
      result(error.message)
      $('#auth-submit').disabled = false
    }
  }
  async function start() {
    document.title = `${copy[0]} · PokeSim`
    $('#auth-heading').textContent = copy[0]
    $('#auth-intro').textContent = copy[1]
    $('#auth-submit').textContent = copy[2]
    $('#confirm-field').hidden = page === 'login'
    $('#password').autocomplete = page === 'login' ? 'current-password' : 'new-password'
    $('#auth-form').addEventListener('submit', submit)
    const data = await session()
    if (page === 'login' && data.authenticated) return location.replace(next())
    const methods = data.methods || {}
    $('#oidc-login').hidden = !methods.oidc || page === 'invite'
    $('#auth-form').hidden = page !== 'invite' && methods.password === false
    // A browser on the same network as PokeSim may skip the code, but it cannot tell here, so
    // the field stays and an empty code is fine when the server trusts this address.
    $('#code-field').hidden = page !== 'setup'
  }
  start().catch(error => result(error.message))
})()
