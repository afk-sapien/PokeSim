// Settings for accounts: your password, people and invites for admins, and sharing for the
// owner of an adventure. Hidden when the Library has no accounts.
(() => {
  const $ = selector => document.querySelector(selector)
  let csrf = ''
  let session = {}

  async function call(path, options = {}) {
    const response = await fetch(path, {cache: 'no-store', credentials: 'same-origin', ...options,
      headers: {'Content-Type': 'application/json', 'X-PokeSim-CSRF': csrf, ...(options.headers || {})}})
    let data
    try { data = await response.json() } catch (_) { data = {} }
    if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : `Request failed (${response.status})`)
    return data
  }
  const send = (method, path, body) => call(path, {method, body: JSON.stringify(body || {})})

  function element(tag, text, className) {
    const node = document.createElement(tag)
    if (text !== undefined) node.textContent = text
    if (className) node.className = className
    return node
  }
  function button(text, action, danger) {
    const node = element('button', text, danger ? 'key key--danger' : 'key')
    node.type = 'button'
    node.addEventListener('click', action)
    return node
  }
  function when(seconds) {
    return seconds ? new Date(seconds * 1000).toLocaleString() : 'never'
  }
  function report(selector, message) {
    $(selector).textContent = message
  }
  async function attempt(selector, work) {
    report(selector, '')
    try { await work() } catch (error) { report(selector, error.message) }
  }

  async function changePassword(event) {
    event.preventDefault()
    if ($('#password-new').value !== $('#password-again').value) return report('#password-result', 'The two new passwords do not match.')
    await attempt('#password-result', async () => {
      await send('POST', '/api/v1/auth/password', {current_password: $('#password-current').value, password: $('#password-new').value})
      event.target.reset()
      report('#password-result', 'Password changed. Your other sessions have ended.')
    })
  }

  async function showPeople() {
    const [{users}, {invites}] = await Promise.all([call('/api/v1/users'), call('/api/v1/invites')])
    const list = $('#people-list')
    list.replaceChildren(...users.filter(user => !user.placeholder).map(user => {
      const row = element('li', undefined, 'people-row')
      const label = `${user.display_name || user.username} (${user.username}), ${user.role}` +
        (user.disabled ? ', turned off' : '') + `. Last login ${when(user.last_login)}.`
      row.append(element('span', label))
      if (user.id !== session.user.id) {
        row.append(button(user.role === 'admin' ? 'Make member' : 'Make admin', () => attempt('#people-result', async () => {
          await send('PATCH', `/api/v1/users/${user.id}`, {role: user.role === 'admin' ? 'member' : 'admin'})
          await showPeople()
        })))
        row.append(button(user.disabled ? 'Turn on' : 'Turn off', () => attempt('#people-result', async () => {
          await send('PATCH', `/api/v1/users/${user.id}`, {disabled: !user.disabled})
          await showPeople()
        }), !user.disabled))
        row.append(button('Log out everywhere', () => attempt('#people-result', async () => {
          await call(`/api/v1/users/${user.id}/sessions`, {method: 'DELETE'})
          report('#people-result', `${user.username} is logged out everywhere.`)
        })))
      }
      return row
    }))
    $('#invite-list').replaceChildren(...invites.map(invite => {
      const row = element('li', `Invite made ${when(invite.created_at)}, open until ${when(invite.expires)}.`, 'people-row')
      row.append(button('Cancel invite', () => attempt('#people-result', async () => {
        await call(`/api/v1/invites/${invite.id}`, {method: 'DELETE'})
        await showPeople()
      }), true))
      return row
    }))
  }
  async function invite() {
    await attempt('#people-result', async () => {
      const made = await send('POST', '/api/v1/invites', {can_create: $('#invite-can-create').checked})
      $('#invite-url').value = made.url
      $('#invite-made').hidden = false
      await showPeople()
    })
  }

  async function ownedAdventures() {
    const {adventures} = await call('/api/v1/adventures')
    return adventures.filter(row => row.access === 'owner' && !row.archived)
  }
  async function showSharing() {
    const aid = $('#share-adventure').value
    $('#share-details').hidden = !aid
    if (!aid) return
    const sharing = await call(`/api/v1/adventures/${aid}/sharing`)
    const watching = new Set(sharing.grants.map(grant => grant.user_id))
    $('#share-watchers').replaceChildren(...sharing.grants.map(grant => {
      const row = element('li', `${grant.display_name || grant.username} can watch.`, 'people-row')
      row.append(button('Stop sharing', () => attempt('#share-result', async () => {
        await call(`/api/v1/adventures/${aid}/grants/${grant.user_id}`, {method: 'DELETE'})
        await showSharing()
      }), true))
      return row
    }))
    $('#share-person').replaceChildren(element('option', 'Choose a person'), ...sharing.users
      .filter(user => !watching.has(user.id)).map(user => {
        const option = element('option', `${user.display_name || user.username} (${user.username})`)
        option.value = user.id
        return option
      }))
    $('#share-person').firstChild.value = ''
    $('#share-links').replaceChildren(...sharing.shares.map(share => {
      const row = element('li', `Link made ${when(share.created_at)}` + (share.expires ? `, open until ${when(share.expires)}.` : ', no end date.'), 'people-row')
      row.append(button('Turn off link', () => attempt('#share-result', async () => {
        await call(`/api/v1/adventures/${aid}/shares/${share.id}`, {method: 'DELETE'})
        await showSharing()
      }), true))
      return row
    }))
  }
  async function addWatcher() {
    const uid = $('#share-person').value
    if (!uid) return report('#share-result', 'Choose a person first.')
    await attempt('#share-result', async () => {
      await send('POST', `/api/v1/adventures/${$('#share-adventure').value}/grants`, {user_id: uid, role: 'viewer'})
      await showSharing()
    })
  }
  async function makeLink() {
    await attempt('#share-result', async () => {
      const days = Number($('#share-days').value)
      const made = await send('POST', `/api/v1/adventures/${$('#share-adventure').value}/shares`, days ? {seconds: days * 86400} : {})
      $('#share-url').value = made.url
      $('#share-made').hidden = false
      await showSharing()
    })
  }
  async function showAdventures() {
    const owned = await ownedAdventures()
    const choice = $('#share-adventure')
    const kept = choice.value
    choice.replaceChildren(element('option', 'Choose an adventure'), ...owned.map(row => {
      const option = element('option', row.name)
      option.value = row.id
      return option
    }))
    choice.firstChild.value = ''
    if (owned.some(row => row.id === kept)) choice.value = kept
    await showSharing()
  }
  function copier(selector) {
    return () => navigator.clipboard?.writeText($(selector).value).catch(() => $(selector).select())
  }

  async function start() {
    session = await (await fetch('/api/v1/session', {cache: 'no-store', credentials: 'same-origin'})).json()
    csrf = session.csrf_token || ''
    if (session.auth !== 'accounts' || !session.user) return
    $('#account-panel').hidden = false
    $('#sharing-panel').hidden = false
    $('#password-form').hidden = session.methods?.password === false
    $('#oidc-link').hidden = !session.methods?.oidc
    $('#password-form').addEventListener('submit', changePassword)
    $('#share-adventure').addEventListener('change', () => attempt('#share-result', showSharing))
    $('#share-add').addEventListener('click', addWatcher)
    $('#share-create').addEventListener('click', makeLink)
    $('#share-copy').addEventListener('click', copier('#share-url'))
    await attempt('#share-result', showAdventures)
    if (session.role === 'admin') {
      $('#people-panel').hidden = false
      $('#invite-create').addEventListener('click', invite)
      $('#invite-copy').addEventListener('click', copier('#invite-url'))
      await attempt('#people-result', showPeople)
    }
  }
  start().catch(() => {})
})()
