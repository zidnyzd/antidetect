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
  recycleList: (params = {}) => call('profile-recycle-list', clean({ page: 1, limit: 10, ...params })),
  restoreProfile: (profileId) => call('profile-restore', { profile_id: profileId }),
  deletePermanent: (profileId) => call('profile-delete-permanent', { profile_id: profileId }),
  emptyRecycleBin: () => call('empty-recycle-bin'),
  openProfile: (profileId) => call('profile-open', { profile_id: profileId }),
  closeProfile: (profileId) => call('profile-close', { profile_id: profileId }),
  closeProfiles: (ids) => call('profile-close-in-batches', { profile_id: [...ids] }),
  openedList: () => call('profile-opened-list'),
  updateGroupsInBatches: (ids, groupId) =>
    call('profile-update-groups-in-batches', { profile_id: [...ids], group_id: groupId }),
  batchUpdate: (ids, fields) => call('profile-batch-update', { profile_id: [...ids], ...fields }),
  arrangeTile: (payload = {}) => call('profile-opened-list-arrange-tile', payload),
  getCookies: (profileId) => call('profile-get-cookies', { profile_id: profileId }),
  updateCookies: (profileId, cookie) => call('profile-update-cookies', { profile_id: profileId, cookie }),
  exportProfile: (profileId) => call('profile-export', { profile_id: profileId }),
  importProfile: (content) => call('profile-import', { content_base64: content }),
  bookmarks: (profileId) => call('profile-bookmarks', { profile_id: profileId }),
  savedPasswords: (profileId) => call('profile-saved-passwords', { profile_id: profileId }),
  clearCache: (profileId) => call('profile-clear-cache', { profile_id: profileId }),
  clearCacheAndCookies: (profileId) => call('profile-clear-cache-and-cookies', { profile_id: profileId }),
  clearCacheKeepExtensions: (profileId) => call('profile-clear-cache-keep-extensions', { profile_id: profileId }),
  clearSavedPassword: (profileId) => call('profile-clear-saved-user-password', { profile_id: profileId }),
  resetSeed: (profileId) => call('profile-reset-seed', { profile_id: profileId }),
  engineInfo: () => call('engine-info'),
  groups: () => call('group-list', { page: 1, limit: 100 }),
  createGroup: (group) => call('group-create', group),
  updateGroup: (group) => call('group-update', group),
  deleteGroup: (id) => call('group-delete', { id }),
  tags: (params = {}) => call('tag-list', { page: 1, limit: 200, ...params }),
  createTag: (title) => call('tag-create', { title }),

  proxies: (params = {}) => call('proxy-list', clean({ page: 1, limit: 10, ...params })),
  createProxy: (proxy) => call('proxy-create', proxy),
  updateProxy: (proxy) => call('proxy-update', proxy),
  deleteProxy: (id) => call('proxy-delete', { id }),
  checkProxy: (payload = {}) => call('proxy-check', payload),

  extensions: (params = {}) => call('extension-list', clean({ page: 1, limit: 10, ...params })),
  uploadExtension: (payload) => call('extension-upload', payload),
  deleteExtension: (id) => call('extension-delete', { id }),

  events: (params = {}) => call('event-list', clean({ page: 1, limit: 20, ...params })),
  clearEvents: () => call('event-clear'),

  health: async () => {
    const res = await fetch('/health')
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    return res.json()
  },
}
