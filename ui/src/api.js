const base = `${import.meta.env.VITE_API_BASE || ''}/api/v2/`

async function call(action, params = {}) {
  const res = await fetch(base + action, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(params),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const payload = await res.json()
  if (payload.error && payload.error.code !== 0) throw new Error(payload.error.message)
  return payload.data
}

export const api = {
  profiles: (params = {}) => call('profile-list', { page: 1, limit: 200, ...params }),
  createProfile: (profile) => call('profile-create', profile),
  openProfile: (profileId) => call('profile-open', { profile_id: profileId }),
  closeProfile: (profileId) => call('profile-close', { profile_id: profileId }),
  deleteProfile: (profileId) => call('profile-delete', { profile_id: profileId }),
  openedList: () => call('profile-opened-list'),
  groups: () => call('group-list', { page: 1, limit: 100 }),
}
