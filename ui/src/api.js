const base = `${import.meta.env.VITE_API_BASE || ''}/api/v2/`

export const UI_VERSION = '0.2.0'

function clean(params) {
  const out = {}
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined) out[key] = value
  }
  return out
}

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
  profiles: (params = {}) => call('profile-list', clean({ page: 1, limit: 20, ...params })),
  createProfile: (profile) => call('profile-create', profile),
  updateProfile: (profile) => call('profile-update', profile),
  copyProfile: (profileId, name) => call('profile-copy', { profile_id: profileId, name }),
  deleteProfile: (profileId) => call('profile-delete', { profile_id: profileId }),
  openProfile: (profileId) => call('profile-open', { profile_id: profileId }),
  closeProfile: (profileId) => call('profile-close', { profile_id: profileId }),
  closeProfiles: (ids) => call('profile-close-in-batches', { profile_id: [...ids] }),
  openedList: () => call('profile-opened-list'),
  groups: () => call('group-list', { page: 1, limit: 100 }),

  proxies: (params = {}) => call('proxy-list', clean({ page: 1, limit: 10, ...params })),
  createProxy: (proxy) => call('proxy-create', proxy),
  updateProxy: (proxy) => call('proxy-update', proxy),
  deleteProxy: (id) => call('proxy-delete', { id }),

  health: async () => {
    const res = await fetch('/health')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  },
}
