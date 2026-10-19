<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Refresh, Search } from '@element-plus/icons-vue'
import { api } from '../api'
import { useOnRefresh } from '../refresh'

const LIMIT = 10

const rows = ref([])
const groups = ref([])
const total = ref(0)
const page = ref(1)
const search = ref('')
const loading = ref(false)
const emptying = ref(false)
const busy = ref({})

let searchTimer = null

const groupMap = computed(() => new Map(groups.value.map((group) => [group.id, group.title])))
const hasFilter = computed(() => !!search.value.trim())

async function load() {
  loading.value = true
  try {
    const result = await api.recycleList({
      page: page.value,
      limit: LIMIT,
      name: search.value.trim() || undefined,
    })
    rows.value = result.data || []
    total.value = result.total || 0
    const maxPage = Math.max(1, Math.ceil(total.value / LIMIT))
    if (page.value > maxPage) {
      page.value = maxPage
      return load()
    }
  } catch (error) {
    ElMessage.error(`Gagal memuat keranjang sampah: ${error.message}`)
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

function markBusy(profileId, value) {
  const next = { ...busy.value }
  if (value) next[profileId] = true
  else delete next[profileId]
  busy.value = next
}

async function restore(row) {
  markBusy(row.profile_id, true)
  try {
    await api.restoreProfile(row.profile_id)
    ElMessage.success(`Profil "${row.name}" dipulihkan`)
    if (rows.value.length === 1 && page.value > 1) page.value -= 1
    await load()
  } catch (error) {
    ElMessage.error(`Gagal memulihkan profil: ${error.message}`)
  } finally {
    markBusy(row.profile_id, false)
  }
}

async function removePermanent(row) {
  try {
    await ElMessageBox.confirm(
      `Hapus permanen profil "${row.name}"? Tindakan ini tidak bisa dibatalkan.`,
      'Hapus Permanen',
      {
        type: 'warning',
        confirmButtonText: 'Hapus Permanen',
        cancelButtonText: 'Batal',
        confirmButtonClass: 'el-button--danger',
      }
    )
  } catch {
    return
  }
  markBusy(row.profile_id, true)
  try {
    await api.deletePermanent(row.profile_id)
    ElMessage.success(`Profil "${row.name}" dihapus permanen`)
    if (rows.value.length === 1 && page.value > 1) page.value -= 1
    await load()
  } catch (error) {
    ElMessage.error(`Gagal menghapus permanen: ${error.message}`)
  } finally {
    markBusy(row.profile_id, false)
  }
}

async function emptyBin() {
  try {
    await ElMessageBox.confirm('Hapus permanen semua profil di keranjang?', 'Kosongkan Keranjang', {
      type: 'warning',
      confirmButtonText: 'Kosongkan',
      cancelButtonText: 'Batal',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return
  }
  emptying.value = true
  try {
    const result = await api.emptyRecycleBin()
    const count = result?.count ?? 0
    if (count > 0) ElMessage.success(`${count} profil dihapus permanen`)
    else ElMessage.info('Keranjang sampah sudah kosong')
    page.value = 1
    await load()
  } catch (error) {
    ElMessage.error(`Gagal mengosongkan keranjang: ${error.message}`)
  } finally {
    emptying.value = false
  }
}

function onPageChange(value) {
  page.value = value
  load()
}

watch(search, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    page.value = 1
    load()
  }, 300)
})

function groupTitle(groupId) {
  return groupMap.value.get(groupId) || `Grup ${groupId}`
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

function deletedLabel(value) {
  if (!value) return '-'
  return String(value).slice(0, 16)
}

function deletedTitle(value) {
  return value ? `Dihapus: ${value}` : ''
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

onMounted(() => {
  loadGroups()
  load()
})

onUnmounted(() => clearTimeout(searchTimer))

useOnRefresh(() => Promise.all([loadGroups(), load()]))
</script>

<template>
  <div class="profiles-page recycle-page">
    <section class="surface profiles-panel">
      <div class="profiles-toolbar">
        <div class="toolbar-row">
          <div class="toolbar-left">
            <span class="recycle-hint">Profil di keranjang disimpan sampai kamu hapus permanen</span>
          </div>
          <div class="toolbar-right">
            <el-input v-model="search" class="search-input" placeholder="Cari nama profil" clearable>
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
            <el-tooltip content="Muat ulang daftar" placement="top" :show-after="200">
              <el-button class="icon-action" :icon="Refresh" aria-label="Muat ulang daftar" @click="load" />
            </el-tooltip>
            <el-button type="danger" :icon="Delete" :disabled="!total" :loading="emptying" @click="emptyBin">
              Kosongkan Keranjang
            </el-button>
          </div>
        </div>
      </div>

      <el-table
        v-loading="loading"
        element-loading-text="Memuat keranjang sampah..."
        class="profiles-table recycle-table"
        :data="rows"
        row-key="profile_id"
      >
        <el-table-column label="No." width="76">
          <template #default="{ row }">
            <span
              class="profile-badge"
              :style="{ background: row.color || '#86909c', color: badgeTextColor(row.color || '#86909c') }"
            >{{ row.profile_id }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Grup / Platform" width="130">
          <template #default="{ row }">
            <div class="cell-stack">
              <span class="cell-main">{{ groupTitle(row.group_id) }}</span>
              <span class="cell-sub">{{ platformLabel(row) }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="Judul Profil" min-width="220">
          <template #default="{ row }">
            <div class="cell-stack">
              <span class="cell-main">{{ row.name }}</span>
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
        <el-table-column label="Dihapus" width="150">
          <template #default="{ row }">
            <el-tooltip :content="deletedTitle(row.deleted_at)" placement="top" :show-after="200">
              <span class="time-line is-created">{{ deletedLabel(row.deleted_at) }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="Operasi" width="190" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button
                size="small"
                type="primary"
                :loading="!!busy[row.profile_id]"
                class="restore-button"
                @click="restore(row)"
              >
                Pulihkan
              </el-button>
              <el-tooltip content="Hapus permanen" placement="top" :show-after="200">
                <el-button
                  size="small"
                  class="icon-action danger"
                  :icon="Delete"
                  aria-label="Hapus permanen"
                  @click="removePermanent(row)"
                />
              </el-tooltip>
            </div>
          </template>
        </el-table-column>

        <template #empty>
          <div class="table-empty">
            <div class="empty-title">{{ hasFilter ? 'Tidak ada profil yang cocok' : 'Keranjang sampah kosong' }}</div>
            <p class="empty-text">
              {{
                hasFilter
                  ? 'Ubah kata kunci pencarian untuk melihat profil lain.'
                  : 'Profil yang dihapus dari daftar akan muncul di sini sampai kamu hapus permanen.'
              }}
            </p>
          </div>
        </template>
      </el-table>

      <div class="table-footer">
        <el-pagination
          class="pagination"
          background
          :current-page="page"
          :page-size="LIMIT"
          :total="total"
          layout="total, prev, pager, next"
          @current-change="onPageChange"
        />
      </div>
    </section>
  </div>
</template>
