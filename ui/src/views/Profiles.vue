<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, CopyDocument, Delete, Edit, FolderOpened, MoreFilled, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { api } from '../api'
import { useOnRefresh } from '../refresh'
import ProfileDialog from '../components/ProfileDialog.vue'
import GroupManager from '../components/GroupManager.vue'

const POOL_LIMIT = 1000

const rows = ref([])
const pool = ref([])
const total = ref(0)
const groups = ref([])
const tags = ref([])
const opened = ref(new Set())
const loading = ref(false)
const selected = ref([])
const page = ref(1)
const limit = ref(10)
const search = ref('')
const groupFilter = ref('all')
const statusFilter = ref('all')
const busy = ref({})
const bulkBusy = ref(false)
const tableRef = ref(null)
const dialogVisible = ref(false)
const editingProfile = ref(null)
const openAfterSave = ref(false)
const groupManagerVisible = ref(false)

let searchTimer = null
let pollTimer = null

const groupMap = computed(() => new Map(groups.value.map((group) => [group.id, group.title])))
const tagMap = computed(() => new Map(tags.value.map((tag) => [tag.id, tag.title])))
const selectedIds = computed(() => selected.value.map((profile) => profile.profile_id))

function isOpen(profile) {
  return opened.value.has(profile.profile_id)
}

const filteredPool = computed(() => {
  if (statusFilter.value === 'open') return pool.value.filter((profile) => isOpen(profile))
  if (statusFilter.value === 'closed') return pool.value.filter((profile) => !isOpen(profile))
  return pool.value
})

const visibleRows = computed(() => {
  if (statusFilter.value === 'all') return rows.value
  const start = (page.value - 1) * limit.value
  return filteredPool.value.slice(start, start + limit.value)
})

const displayTotal = computed(() => (statusFilter.value === 'all' ? total.value : filteredPool.value.length))

const hasFilter = computed(
  () => !!search.value.trim() || groupFilter.value !== 'all' || statusFilter.value !== 'all'
)

async function loadProfiles() {
  loading.value = true
  try {
    const all = statusFilter.value === 'all'
    const result = await api.profiles({
      page: all ? page.value : 1,
      limit: all ? limit.value : POOL_LIMIT,
      name: search.value.trim() || undefined,
      group_id: groupFilter.value === 'all' ? undefined : groupFilter.value,
    })
    if (all) {
      rows.value = result.data || []
      total.value = result.total || 0
    } else {
      pool.value = result.data || []
    }
  } catch (error) {
    ElMessage.error(`Gagal memuat profil: ${error.message}`)
  } finally {
    loading.value = false
  }
}

async function loadGroups() {
  try {
    const result = await api.groups()
    groups.value = result.data || []
  } catch (error) {
    ElMessage.error(`Gagal memuat grup: ${error.message}`)
  }
}

async function loadTags() {
  try {
    const result = await api.tags()
    tags.value = result.data || []
  } catch (error) {
    ElMessage.error(`Gagal memuat tag: ${error.message}`)
  }
}

async function pollOpened() {
  try {
    const list = await api.openedList()
    opened.value = new Set((list || []).map((item) => item.profile_id))
  } catch {
    // indikator API di topbar yang memberi tahu saat server tidak merespons
  }
}

async function refreshAll() {
  await Promise.all([loadGroups(), loadProfiles(), loadTags(), pollOpened()])
}

function clearSelection() {
  selected.value = []
  tableRef.value?.clearSelection()
}

function onSelectionChange(value) {
  selected.value = value
}

function onPageChange(value) {
  page.value = value
  if (statusFilter.value === 'all') loadProfiles()
}

function onSizeChange(value) {
  limit.value = value
  page.value = 1
  clearSelection()
  if (statusFilter.value === 'all') loadProfiles()
}

watch(search, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    page.value = 1
    clearSelection()
    loadProfiles()
  }, 300)
})

watch(groupFilter, () => {
  page.value = 1
  clearSelection()
  loadProfiles()
})

watch(statusFilter, () => {
  page.value = 1
  clearSelection()
  loadProfiles()
})

watch(displayTotal, (value) => {
  const maxPage = Math.max(1, Math.ceil(value / limit.value))
  if (page.value > maxPage) page.value = maxPage
})

async function openCreate(andOpen = false) {
  editingProfile.value = null
  openAfterSave.value = andOpen
  await loadGroups()
  dialogVisible.value = true
}

function onCreateCommand(command) {
  openCreate(command === 'open')
}

async function openEdit(profile) {
  editingProfile.value = profile
  openAfterSave.value = false
  await loadGroups()
  dialogVisible.value = true
}

function markBusy(profileId, value) {
  const next = { ...busy.value }
  if (value) next[profileId] = true
  else delete next[profileId]
  busy.value = next
}

function markOpenedLocally(profileId) {
  const stamp = Math.floor(Date.now() / 1000)
  for (const list of [rows.value, pool.value]) {
    const profile = list.find((item) => item.profile_id === profileId)
    if (profile) profile.last_open_time = stamp
  }
}

async function openById(profileId, name) {
  markBusy(profileId, true)
  try {
    await api.openProfile(profileId)
    markOpenedLocally(profileId)
    opened.value = new Set([...opened.value, profileId])
    ElMessage.success(`Profil "${name}" dibuka`)
  } catch (error) {
    ElMessage.error(`Gagal membuka: ${error.message}`)
  } finally {
    markBusy(profileId, false)
    await pollOpened()
  }
}

async function toggleOpen(profile) {
  const wasOpen = isOpen(profile)
  markBusy(profile.profile_id, true)
  try {
    if (wasOpen) {
      await api.closeProfile(profile.profile_id)
      const next = new Set(opened.value)
      next.delete(profile.profile_id)
      opened.value = next
      ElMessage.success(`Profil "${profile.name}" ditutup`)
    } else {
      await api.openProfile(profile.profile_id)
      markOpenedLocally(profile.profile_id)
      opened.value = new Set([...opened.value, profile.profile_id])
      ElMessage.success(`Profil "${profile.name}" dibuka`)
    }
  } catch (error) {
    ElMessage.error(`${wasOpen ? 'Gagal menutup' : 'Gagal membuka'}: ${error.message}`)
  } finally {
    markBusy(profile.profile_id, false)
    await pollOpened()
  }
}

async function duplicateProfile(profile) {
  try {
    await ElMessageBox.confirm(`Duplikat profil "${profile.name}"?`, 'Duplikat Profil', {
      confirmButtonText: 'Duplikat',
      cancelButtonText: 'Batal',
    })
  } catch {
    return
  }
  try {
    await api.copyProfile(profile.profile_id, `${profile.name} copy`)
    ElMessage.success('Profil diduplikasi')
    await loadProfiles()
    await pollOpened()
  } catch (error) {
    ElMessage.error(`Gagal menduplikasi: ${error.message}`)
  }
}

async function removeProfile(profile) {
  try {
    await ElMessageBox.confirm(`Hapus profil "${profile.name}"? Tindakan ini tidak bisa dibatalkan.`, 'Hapus Profil', {
      type: 'warning',
      confirmButtonText: 'Hapus',
      cancelButtonText: 'Batal',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return
  }
  try {
    await api.deleteProfile(profile.profile_id)
    ElMessage.success('Profil dihapus')
    clearSelection()
    if (visibleRows.value.length === 1 && page.value > 1) page.value -= 1
    await loadProfiles()
    await pollOpened()
  } catch (error) {
    ElMessage.error(`Gagal menghapus: ${error.message}`)
  }
}

function onRowCommand(command, profile) {
  if (command === 'delete') removeProfile(profile)
}

async function runBulk(command) {
  const chosen = [...selected.value]
  if (!chosen.length) return

  if (command === 'delete') {
    try {
      await ElMessageBox.confirm(`Hapus ${chosen.length} profil terpilih? Tindakan ini tidak bisa dibatalkan.`, 'Hapus Profil', {
        type: 'warning',
        confirmButtonText: 'Hapus',
        cancelButtonText: 'Batal',
        confirmButtonClass: 'el-button--danger',
      })
    } catch {
      return
    }
    bulkBusy.value = true
    let ok = 0
    let fail = 0
    for (const profile of chosen) {
      try {
        await api.deleteProfile(profile.profile_id)
        ok += 1
      } catch {
        fail += 1
      }
    }
    bulkBusy.value = false
    clearSelection()
    await loadProfiles()
    await pollOpened()
    if (ok) ElMessage.success(`${ok} profil dihapus`)
    if (fail) ElMessage.error(`${fail} profil gagal dihapus`)
    return
  }

  if (command === 'open') {
    const targets = chosen.filter((profile) => !isOpen(profile))
    if (!targets.length) {
      ElMessage.info('Semua profil terpilih sudah terbuka')
      return
    }
    bulkBusy.value = true
    let ok = 0
    let fail = 0
    const next = new Set(opened.value)
    for (const profile of targets) {
      try {
        await api.openProfile(profile.profile_id)
        next.add(profile.profile_id)
        ok += 1
      } catch {
        fail += 1
      }
    }
    opened.value = next
    bulkBusy.value = false
    clearSelection()
    await pollOpened()
    if (ok) ElMessage.success(`${ok} profil dibuka`)
    if (fail) ElMessage.error(`${fail} profil gagal dibuka`)
    return
  }

  if (command === 'close') {
    const targets = chosen.filter((profile) => isOpen(profile))
    if (!targets.length) {
      ElMessage.info('Tidak ada profil terpilih yang terbuka')
      return
    }
    bulkBusy.value = true
    try {
      await api.closeProfiles(targets.map((profile) => profile.profile_id))
      const next = new Set(opened.value)
      for (const profile of targets) next.delete(profile.profile_id)
      opened.value = next
      ElMessage.success(`${targets.length} profil ditutup`)
    } catch (error) {
      ElMessage.error(`Gagal menutup profil terpilih: ${error.message}`)
    } finally {
      bulkBusy.value = false
      clearSelection()
      await pollOpened()
    }
  }
}

async function onGroupsChanged() {
  await loadGroups()
  if (groupFilter.value !== 'all' && !groups.value.some((group) => group.id === groupFilter.value)) {
    groupFilter.value = 'all'
    return
  }
  await loadProfiles()
}

async function onSaved({ mode, profileId, name }) {
  dialogVisible.value = false
  clearSelection()
  await Promise.all([loadProfiles(), loadTags()])
  await pollOpened()
  ElMessage.success(mode === 'create' ? `Profil "${name}" dibuat` : `Profil "${name}" diperbarui`)
  if (openAfterSave.value && mode === 'create') {
    openAfterSave.value = false
    await openById(profileId, name)
  }
}

function groupTitle(groupId) {
  return groupMap.value.get(groupId) || `Grup ${groupId}`
}

function profileTags(profile) {
  const ids = Array.isArray(profile.tab_id) ? profile.tab_id : []
  return ids.map((id) => tagMap.value.get(id)).filter(Boolean)
}

function platformLabel(profile) {
  const config = profile.fingerprint_config || {}
  const platform = config.platform === 'Macos' ? 'macOS' : config.platform || 'Windows'
  if (platform === 'Windows' && config.system_version) return `${platform} ${config.system_version}`
  return platform
}

function proxyTypeLabel(profile) {
  const config = profile.proxy_config || {}
  const type = String(config.proxy_type || 'direct').toLowerCase()
  if (!type || type === 'direct') return 'Direct'
  return type.toUpperCase()
}

function proxyHostLabel(profile) {
  const config = profile.proxy_config || {}
  const type = String(config.proxy_type || 'direct').toLowerCase()
  if (!type || type === 'direct' || !config.proxy_ip) return 'Tanpa proxy'
  return `${config.proxy_ip}:${config.proxy_port ?? ''}`
}

function timestampLabel(value) {
  if (!value) return ''
  if (typeof value === 'number') {
    const date = new Date(value * 1000)
    if (Number.isNaN(date.getTime())) return ''
    const pad = (part) => String(part).padStart(2, '0')
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
  }
  const [date, time] = String(value).split(' ')
  return `${date || ''} ${(time || '').slice(0, 5)}`.trim()
}

function createdLabel(value) {
  return timestampLabel(value) || '-'
}

function lastOpenedLabel(profile) {
  return timestampLabel(profile.last_open_time) || 'Belum dibuka'
}

function lastOpenedTitle(profile) {
  return profile.last_open_time
    ? `Terakhir dibuka: ${lastOpenedLabel(profile)}`
    : 'Belum pernah dibuka'
}

function noteLabel(profile) {
  return profile.note ? `Catatan: ${profile.note}` : 'Tanpa catatan'
}

function badgeTextColor(hex) {
  const raw = String(hex || '').replace('#', '')
  const full = raw.length === 3 ? raw.split('').map((char) => char + char).join('') : raw
  const value = Number.parseInt(full, 16)
  if (full.length !== 6 || Number.isNaN(value)) return '#ffffff'
  const [r, g, b] = [16, 8, 0].map((shift) => {
    const channel = ((value >> shift) & 255) / 255
    return channel <= 0.03928 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  })
  const luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
  const contrastWhite = 1.05 / (luminance + 0.05)
  const contrastDark = (luminance + 0.05) / 0.0637
  return contrastWhite >= contrastDark ? '#ffffff' : '#1d2129'
}

function sortByProfileId(a, b) {
  return a.profile_id - b.profile_id
}

onMounted(() => {
  refreshAll()
  pollTimer = setInterval(pollOpened, 5000)
})

onUnmounted(() => {
  clearInterval(pollTimer)
  clearTimeout(searchTimer)
})

useOnRefresh(() => refreshAll())
</script>

<template>
  <div class="profiles-page">
    <section class="surface profiles-panel">
      <div class="profiles-toolbar">
        <div class="toolbar-row">
          <div class="toolbar-left">
            <div class="split-button">
              <el-button type="primary" :icon="Plus" @click="openCreate(false)">Buat Profil</el-button>
              <el-dropdown trigger="click" @command="onCreateCommand">
                <el-button type="primary" class="split-caret" :icon="ArrowDown" aria-label="Opsi buat profil" />
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="create">Buat Profil</el-dropdown-item>
                    <el-dropdown-item command="open">Buat dan Buka</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </div>
          <div class="toolbar-right">
            <el-input v-model="search" class="search-input" placeholder="Cari nama profil" clearable>
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
            <el-select v-model="groupFilter" class="group-select" placeholder="Semua Grup">
              <el-option label="Semua Grup" value="all" />
              <el-option v-for="group in groups" :key="group.id" :label="group.title" :value="group.id" />
            </el-select>
            <el-tooltip content="Kelola grup" placement="top" :show-after="200">
              <el-button
                class="icon-action"
                :icon="FolderOpened"
                aria-label="Kelola grup"
                @click="groupManagerVisible = true"
              />
            </el-tooltip>
            <el-tooltip content="Muat ulang daftar" placement="top" :show-after="200">
              <el-button class="icon-action" :icon="Refresh" aria-label="Muat ulang daftar" @click="refreshAll" />
            </el-tooltip>
          </div>
        </div>
        <div class="toolbar-row">
          <div class="toolbar-left">
            <el-dropdown :disabled="!selectedIds.length" trigger="click" @command="runBulk">
              <el-button :disabled="!selectedIds.length" :loading="bulkBusy">
                Operasi Massal
                <el-icon class="el-icon--right"><ArrowDown /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="open">Buka terpilih</el-dropdown-item>
                  <el-dropdown-item command="close">Tutup terpilih</el-dropdown-item>
                  <el-dropdown-item command="delete" divided>Hapus terpilih</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-radio-group v-model="statusFilter" size="small" class="status-segment">
              <el-radio-button value="all">Semua</el-radio-button>
              <el-radio-button value="open">Terbuka</el-radio-button>
              <el-radio-button value="closed">Tertutup</el-radio-button>
            </el-radio-group>
          </div>
          <div class="toolbar-right">
            <span v-if="selectedIds.length" class="selection-count">{{ selectedIds.length }} dipilih</span>
          </div>
        </div>
      </div>

      <el-table
        ref="tableRef"
        v-loading="loading"
        element-loading-text="Memuat profil..."
        class="profiles-table"
        :data="visibleRows"
        row-key="profile_id"
        @selection-change="onSelectionChange"
      >
        <el-table-column type="selection" width="44" />
        <el-table-column label="No." width="76" sortable :sort-method="sortByProfileId">
          <template #default="{ row }">
            <span
              class="profile-badge"
              :style="{ background: row.color || '#86909c', color: badgeTextColor(row.color || '#86909c') }"
            >{{ row.profile_id }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Grup / Platform" width="120">
          <template #default="{ row }">
            <div class="cell-stack">
              <span class="cell-main">{{ groupTitle(row.group_id) }}</span>
              <span class="cell-sub">{{ platformLabel(row) }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="Tag" width="170">
          <template #default="{ row }">
            <div class="tag-cell" role="button" tabindex="0" @click="openEdit(row)" @keydown.enter="openEdit(row)">
              <template v-if="profileTags(row).length">
                <span
                  v-for="tag in profileTags(row).slice(0, 2)"
                  :key="tag"
                  class="tag-chip"
                  :title="tag"
                >{{ tag }}</span>
                <span v-if="profileTags(row).length > 2" class="tag-more">+{{ profileTags(row).length - 2 }}</span>
              </template>
              <span v-else class="tag-add">Tambah tag</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="Judul Profil" min-width="180">
          <template #default="{ row }">
            <div class="cell-stack">
              <button type="button" class="profile-name" @click="openEdit(row)">{{ row.name }}</button>
              <span class="cell-sub" :title="noteLabel(row)">{{ noteLabel(row) }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="Proxy" width="160">
          <template #default="{ row }">
            <div class="cell-stack">
              <span class="cell-main">{{ proxyTypeLabel(row) }}</span>
              <span class="cell-sub" :title="proxyHostLabel(row)">{{ proxyHostLabel(row) }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="Status" width="90">
          <template #default="{ row }">
            <span :class="['status-text', isOpen(row) ? 'is-open' : 'is-closed']">
              <span :class="['status-dot', isOpen(row) ? 'ok' : 'idle']"></span>
              {{ isOpen(row) ? 'Terbuka' : 'Tertutup' }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="Waktu" width="140">
          <template #default="{ row }">
            <div class="time-cell">
              <el-tooltip :content="`Dibuat: ${createdLabel(row.created_at)}`" placement="top" :show-after="200">
                <span class="time-line is-created">{{ createdLabel(row.created_at) }}</span>
              </el-tooltip>
              <el-tooltip :content="lastOpenedTitle(row)" placement="bottom" :show-after="200">
                <span :class="['time-line', row.last_open_time ? 'is-last' : 'is-empty']">
                  {{ lastOpenedLabel(row) }}
                </span>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="Operasi" width="210" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button
                size="small"
                :type="isOpen(row) ? 'default' : 'primary'"
                :loading="!!busy[row.profile_id]"
                class="open-button"
                @click="toggleOpen(row)"
              >
                {{ isOpen(row) ? 'Tutup' : 'Buka' }}
              </el-button>
              <el-tooltip content="Edit profil" placement="top" :show-after="200">
                <el-button size="small" class="icon-action" :icon="Edit" aria-label="Edit profil" @click="openEdit(row)" />
              </el-tooltip>
              <el-tooltip content="Duplikat profil" placement="top" :show-after="200">
                <el-button
                  size="small"
                  class="icon-action"
                  :icon="CopyDocument"
                  aria-label="Duplikat profil"
                  @click="duplicateProfile(row)"
                />
              </el-tooltip>
              <el-dropdown trigger="click" @command="(command) => onRowCommand(command, row)">
                <el-button size="small" class="icon-action" :icon="MoreFilled" aria-label="Operasi lain" />
                <template #dropdown>
                  <el-dropdown-menu>
                    <el-dropdown-item command="delete" :icon="Delete">Hapus</el-dropdown-item>
                  </el-dropdown-menu>
                </template>
              </el-dropdown>
            </div>
          </template>
        </el-table-column>

        <template #empty>
          <div class="table-empty">
            <div class="empty-title">{{ hasFilter ? 'Tidak ada profil yang cocok' : 'Belum ada profil' }}</div>
            <p class="empty-text">
              {{
                hasFilter
                  ? 'Ubah kata kunci atau filter grup untuk melihat profil lain.'
                  : 'Profil menyimpan fingerprint dan proxy untuk membuka Chromium terisolasi.'
              }}
            </p>
            <el-button v-if="!hasFilter" type="primary" :icon="Plus" @click="openCreate(false)">Buat Profil</el-button>
          </div>
        </template>
      </el-table>

      <div class="table-footer">
        <el-pagination
          class="pagination"
          background
          :current-page="page"
          :page-size="limit"
          :page-sizes="[10, 20, 50]"
          :total="displayTotal"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="onPageChange"
          @size-change="onSizeChange"
        />
      </div>
    </section>

    <ProfileDialog
      v-model="dialogVisible"
      :profile="editingProfile"
      :groups="groups"
      :tags="tags"
      @saved="onSaved"
      @tags-changed="loadTags"
    />

    <GroupManager v-model="groupManagerVisible" @changed="onGroupsChanged" />
  </div>
</template>
