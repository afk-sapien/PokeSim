// Settings for accounts: your password, people and invites for admins, and sharing for the
// owner of an adventure. Hidden when the Library has no accounts.
(() => {
  const $ = selector => document.querySelector(selector)
  let csrf = ''
  let session = {}
  const ROLE_CHOICES = {viewer: 'Can watch', player: 'Can play', manager: 'Can manage'}
  const ROLE_LABELS = {viewer: 'can watch', player: 'can play', manager: 'can manage'}

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
    $('#invite-made').hidden = true
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
        row.append(button('Delete user', () => attempt('#people-result', () => planDeletion(row, user, users)), true))
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
  // Deleting someone never deletes an adventure: each one they own goes to another person or
  // is archived under the admin who deleted them.
  async function planDeletion(row, user, users) {
    row.querySelector('.delete-plan')?.remove()
    const {adventures} = await call('/api/v1/adventures')
    const owned = adventures.filter(game => game.owner_id === user.id)
    const others = users.filter(other => !other.placeholder && !other.disabled && other.id !== user.id)
    const plan = element('div', undefined, 'delete-plan settings-controls')
    const name = user.display_name || user.username
    plan.append(element('p', owned.length ? `Choose what happens to each adventure ${name} owns.` : `${name} owns no adventures.`, 'note'))
    const choices = owned.map(game => {
      const choice = element('select')
      choice.dataset.adventure = game.id
      choice.setAttribute('aria-label', `New owner of ${game.name}`)
      const archive = element('option', 'Archive it')
      archive.value = 'archive'
      choice.append(archive, ...others.map(other => {
        const option = element('option', `Give to ${other.display_name || other.username}`)
        option.value = other.id
        return option
      }))
      const field = element('label', undefined, 'field')
      field.append(element('span', game.name, 'micro'), choice)
      plan.append(field)
      return choice
    })
    plan.append(button(`Delete ${name}`, () => attempt('#people-result', async () => {
      const chosen = Object.fromEntries(choices.map(choice => [choice.dataset.adventure, choice.value]))
      await call(`/api/v1/users/${user.id}`, {method: 'DELETE', body: JSON.stringify({adventures: chosen})})
      await showPeople()
      report('#people-result', `${name} was deleted.`)
    }), true), button('Keep them', () => plan.remove()))
    row.append(plan)
  }
  async function invite() {
    await attempt('#people-result', async () => {
      const made = await send('POST', '/api/v1/invites', {can_create: $('#invite-can-create').checked})
      await showPeople()
      $('#invite-url').value = made.url
      $('#invite-made').hidden = false
    })
  }

  async function ownedAdventures() {
    const {adventures} = await call('/api/v1/adventures')
    return adventures.filter(row => row.access === 'owner' && !row.archived)
  }
  async function showSharing() {
    const aid = $('#share-adventure').value
    $('#share-details').hidden = !aid
    // A link shows only right after it is made, so a turned-off one never stays on screen.
    $('#share-made').hidden = true
    if (!aid) return
    const sharing = await call(`/api/v1/adventures/${aid}/sharing`)
    const watching = new Set(sharing.grants.map(grant => grant.user_id))
    $('#share-watchers').replaceChildren(...sharing.grants.map(grant => {
      const name = grant.display_name || grant.username
      const row = element('li', `${name} ${ROLE_LABELS[grant.role] || 'can watch'}.`, 'people-row')
      const choice = element('select')
      choice.setAttribute('aria-label', `What ${name} can do`)
      for (const [value, text] of Object.entries(ROLE_CHOICES)) {
        const option = element('option', text)
        option.value = value
        choice.append(option)
      }
      choice.value = grant.role
      choice.addEventListener('change', () => attempt('#share-result', async () => {
        await send('POST', `/api/v1/adventures/${aid}/grants`, {user_id: grant.user_id, role: choice.value})
        await showSharing()
      }))
      row.append(choice)
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
    $('#transfer-person').replaceChildren(element('option', 'Choose a person'), ...sharing.users.map(user => {
      const option = element('option', `${user.display_name || user.username} (${user.username})`)
      option.value = user.id
      return option
    }))
    $('#transfer-person').firstChild.value = ''
    resetTransfer()
    $('#share-links').replaceChildren(...sharing.shares.map(share => {
      const row = element('li', `Link made ${when(share.created_at)}` + (share.expires ? `, open until ${when(share.expires)}.` : ', no end date.'), 'people-row')
      row.append(button('Turn off link', () => attempt('#share-result', async () => {
        await call(`/api/v1/adventures/${aid}/shares/${share.id}`, {method: 'DELETE'})
        await showSharing()
      }), true))
      return row
    }))
    // The /view/ link of an adventure from before accounts stopped working when they turned on.
    $('#share-legacy').hidden = !sharing.legacy
    if (sharing.legacy) {
      $('#share-legacy-note').textContent = `The old view link ${sharing.legacy.path} stopped working when accounts turned on. Make a watch link to share in its place.`
    }
  }
  async function addWatcher() {
    const uid = $('#share-person').value
    if (!uid) return report('#share-result', 'Choose a person first.')
    await attempt('#share-result', async () => {
      await send('POST', `/api/v1/adventures/${$('#share-adventure').value}/grants`, {user_id: uid, role: $('#share-role').value})
      await showSharing()
    })
  }
  async function makeLegacyLink() {
    await attempt('#share-result', async () => {
      const made = await send('POST', `/api/v1/adventures/${$('#share-adventure').value}/shares`, {legacy: true})
      await showSharing()
      $('#share-url').value = made.url
      $('#share-made').hidden = false
    })
  }
  async function makeLink() {
    await attempt('#share-result', async () => {
      const days = Number($('#share-days').value)
      const made = await send('POST', `/api/v1/adventures/${$('#share-adventure').value}/shares`, days ? {seconds: days * 86400} : {})
      await showSharing()
      $('#share-url').value = made.url
      $('#share-made').hidden = false
    })
  }
  // Giving an adventure away takes two clicks: the first asks, the second gives it.
  function resetTransfer() {
    const key = $('#transfer-start')
    delete key.dataset.confirm
    key.textContent = 'Give away'
  }
  async function transfer() {
    const key = $('#transfer-start')
    const choice = $('#transfer-person')
    if (!choice.value) return report('#share-result', 'Choose who gets this adventure first.')
    const name = choice.selectedOptions[0].textContent
    if (!key.dataset.confirm) {
      key.dataset.confirm = 'yes'
      key.textContent = 'Confirm give away'
      return report('#share-result', `${name} will own this adventure. You will lose access unless they share it back. Press Confirm give away to go ahead.`)
    }
    await attempt('#share-result', async () => {
      await send('POST', `/api/v1/adventures/${$('#share-adventure').value}/transfer`, {user_id: choice.value})
      $('#share-adventure').value = ''
      await showAdventures()
      report('#share-result', `${name} owns it now.`)
    })
    resetTransfer()
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
    choice.disabled = !owned.length
    if (!owned.length) report('#share-result', 'You have no adventures to share yet.')
    if (owned.some(row => row.id === kept)) choice.value = kept
    await showSharing()
  }
  function copier(selector) {
    return () => navigator.clipboard?.writeText($(selector).value).catch(() => $(selector).select())
  }

  async function start(event) {
    session = event.detail
    csrf = session.csrf_token || ''
    if (session.auth !== 'accounts' || !session.user) return
    $('#account-panel').hidden = false
    $('#sharing-panel').hidden = false
    if (session.role !== 'admin') {
      // Library-wide settings belong to admins, so members do not see them at all.
      for (const heading of ['nickname', 'backup', 'import', 'quit']) {
        const panel = document.getElementById(`${heading}-settings-heading`)?.closest('section')
        if (panel) panel.hidden = true
      }
    }
    $('#password-form').hidden = session.methods?.password === false
    $('#oidc-link').hidden = !session.methods?.oidc
    $('#password-form').addEventListener('submit', changePassword)
    $('#share-adventure').addEventListener('change', () => attempt('#share-result', showSharing))
    $('#share-add').addEventListener('click', addWatcher)
    $('#share-legacy-make').addEventListener('click', makeLegacyLink)
    $('#share-create').addEventListener('click', makeLink)
    $('#share-copy').addEventListener('click', copier('#share-url'))
    $('#transfer-start').addEventListener('click', transfer)
    $('#transfer-person').addEventListener('change', resetTransfer)
    await attempt('#share-result', showAdventures)
    if (session.role === 'admin') {
      $('#people-panel').hidden = false
      $('#invite-create').addEventListener('click', invite)
      $('#invite-copy').addEventListener('click', copier('#invite-url'))
      await attempt('#people-result', showPeople)
    }
  }
  // The Library page loads the session and hands it over.
  document.addEventListener('pokesim:session', event => start(event).catch(() => {}), {once: true})
})()
