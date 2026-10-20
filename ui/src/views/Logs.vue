<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Download, Refresh, Search } from '@element-plus/icons-vue'
import { api } from '../api'
import { useOnRefresh } from '../refresh'

const LIMIT = 20
const SEARCH_LIMIT = 2000

const KIND_OPTIONS = [
  { value: '', label: 'Semua' },
  { value: 'profile', label: 'Profil' },
  { value: 'proxy', label: 'Proxy' },
  { value: 'extension', label: 'Extension' },
  { value: 'group', label: 'Grup' },
  { value: 'tag', label: 'Tag' },
  { value: 'system', label: 'Sistem' },
]

const KIND_META = {
  profile: { label: 'Profil', tone: 'profile' },
  proxy: { label: 'Proxy', tone: 'proxy' },
  extension: { label: 'Extension', tone: 'extension' },
  group: { label: 'Grup', tone: 'group' },
  tag: { label: 'Tag', tone: 'tag' },
  system: { label: 'Sistem', tone: 'system' },
}

const rows = ref([])
const searchRows = ref([])
const total = ref(0)
const page = ref(1)
const kind = ref('')
const search = ref('')
const dateRange = ref([])
const loading = ref(false)
const clearing = ref(false)
const exporting = ref(false)

let searchTimer = null

const searchTerm = computed(() => search.value.trim().toLowerCase())
const rangeStart = computed(() => dateRange.value?.[0] || '')
const rangeEnd = computed(() => dateRange.value?.[1] || '')
const rangeLabel = computed(() =>
  rangeStart.value && rangeEnd.value ? `${rangeStart.value} sampai ${rangeEnd.value}` : ''
)
const searching = computed(() => !!searchTerm.value)
const hasFilter = computed(() => searching.value || !!kind.value || !!(rangeStart.value && rangeEnd.value))

const filteredRows = computed(() => {
  if (!searching.value) return rows.value
  const needle = searchTerm.value
  return searchRows.value.filter((row) => {
    const haystack = `${row.message || ''} ${row.profile_name || ''}`.toLowerCase()
    return haystack.includes(needle)
  })
})

const visibleRows = computed(() => {
  if (!searching.value) return rows.value
  const start = (page.value - 1) * LIMIT
  return filteredRows.value.slice(start, start + LIMIT)
})

const visibleTotal = computed(() => (searching.value ? filteredRows.value.length : total.value))
const loadedTotal = computed(() => (searching.value ? searchRows.value.length : total.value))

function kindMeta(value) {
  const group = String(value || '').split('-')[0]
  return KIND_META[group] || KIND_META.system
}

function profileLabel(row) {
  if (row.profile_id === null || row.profile_id === undefined) return '-'
  return row.profile_name || `#${row.profile_id}`
}

function timeDate(value) {
  return value ? String(value).slice(0, 10) : '-'
}

function timeClock(value) {
  const text = value ? String(value).slice(11, 19) : ''
  return text || '--:--:--'
}

async function loadPage() {
  loading.value = true
  try {
    const result = await api.events({
      page: page.value,
      limit: LIMIT,
      kind: kind.value || undefined,
      start: rangeStart.value || undefined,
      end: rangeEnd.value || undefined,
    })
    rows.value = result.data || []
    total.value = result.total || 0
    const maxPage = Math.max(1, Math.ceil(total.value / LIMIT))
    if (page.value > maxPage) {
      page.value = maxPage
      return loadPage()
    }
  } catch (error) {
    ElMessage.error(`Gagal memuat log: ${error.message}`)
  } finally {
    loading.value = false
  }
}

async function loadSearch() {
  loading.value = true
  try {
    const result = await api.events({
      page: 1,
      limit: SEARCH_LIMIT,
      kind: kind.value || undefined,
      start: rangeStart.value || undefined,
      end: rangeEnd.value || undefined,
    })
    searchRows.value = result.data || []
    const maxPage = Math.max(1, Math.ceil(filteredRows.value.length / LIMIT))
    if (page.value > maxPage) page.value = maxPage
  } catch (error) {
    ElMessage.error(`Gagal memuat log: ${error.message}`)
  } finally {
    loading.value = false
  }
}

function load() {
  return searching.value ? loadSearch() : loadPage()
}

function onPageChange(value) {
  page.value = value
  if (!searching.value) loadPage()
}

async function clearLog() {
  try {
    await ElMessageBox.confirm(
      'Hapus semua riwayat aktivitas? Tindakan ini tidak bisa dibatalkan.',
      'Bersihkan Log',
      {
        type: 'warning',
        confirmButtonText: 'Bersihkan',
        cancelButtonText: 'Batal',
        confirmButtonClass: 'el-button--danger',
      }
    )
  } catch {
    return
  }
  clearing.value = true
  try {
    const result = await api.clearEvents()
    const count = result?.count ?? 0
    searchRows.value = []
    rows.value = []
    total.value = 0
    page.value = 1
    if (count > 0) ElMessage.success(`${count} aktivitas dihapus`)
    else ElMessage.info('Log sudah kosong')
    await load()
  } catch (error) {
    ElMessage.error(`Gagal membersihkan log: ${error.message}`)
  } finally {
    clearing.value = false
  }
}

function csvBlob(base64) {
  const binary = atob(base64)
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) {
    bytes[index] = binary.charCodeAt(index)
  }
  return new Blob([bytes], { type: 'text/csv;charset=utf-8' })
}

async function exportCsv() {
  exporting.value = true
  try {
    const result = await api.exportEvents({
      kind: kind.value || undefined,
      start: rangeStart.value || undefined,
      end: rangeEnd.value || undefined,
      q: search.value.trim() || undefined,
    })
    const url = URL.createObjectURL(csvBlob(result.content_base64))
    const link = document.createElement('a')
    link.href = url
    link.download = result.filename || 'log-aktivitas.csv'
    document.body.appendChild(link)
    link.click()
    link.remove()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
    if (result.truncated) {
      ElMessage.warning(`${result.count} baris terbaru diekspor, sebagian data dipotong`)
    } else {
      ElMessage.success(`${result.count} baris diekspor`)
    }
  } catch (error) {
    ElMessage.error(`Gagal mengekspor log: ${error.message}`)
  } finally {
    exporting.value = false
  }
}

watch(kind, () => {
  page.value = 1
  load()
})

watch([rangeStart, rangeEnd], () => {
  page.value = 1
  load()
})

watch(search, () => {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    page.value = 1
    load()
  }, 300)
})

onMounted(load)
onUnmounted(() => clearTimeout(searchTimer))

useOnRefresh(() => load())
</script>

<template>
  <div class="profiles-page logs-page">
    <section class="surface profiles-panel">
      <div class="profiles-toolbar">
        <div class="toolbar-row">
          <div class="toolbar-left">
            <el-select v-model="kind" class="kind-select" placeholder="Semua jenis" aria-label="Filter jenis log">
              <el-option
                v-for="option in KIND_OPTIONS"
                :key="option.value || 'all'"
                :label="option.label"
                :value="option.value"
              />
            </el-select>
            <el-date-picker
              v-model="dateRange"
              class="log-range-picker"
              type="daterange"
              value-format="YYYY-MM-DD"
              format="YYYY-MM-DD"
              range-separator="s/d"
              start-placeholder="Tanggal awal"
              end-placeholder="Tanggal akhir"
              unlink-panels
              aria-label="Filter rentang tanggal"
            />
          </div>
          <div class="toolbar-right">
            <el-input v-model="search" class="search-input" placeholder="Cari pesan" clearable>
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
            <el-tooltip content="Muat ulang log" placement="top" :show-after="200">
              <el-button class="icon-action" :icon="Refresh" aria-label="Muat ulang log" @click="load" />
            </el-tooltip>
            <el-button :icon="Download" :loading="exporting" @click="exportCsv">Ekspor CSV</el-button>
            <el-button type="danger" :icon="Delete" :disabled="!loadedTotal" :loading="clearing" @click="clearLog">
              Bersihkan Log
            </el-button>
          </div>
        </div>
        <div class="toolbar-row log-scope-row">
          <div class="toolbar-left">
            <span v-if="rangeLabel" class="log-range-chip">{{ rangeLabel }}</span>
            <span class="log-hint">Riwayat aksi lokal, maksimal 2000 baris</span>
          </div>
        </div>
      </div>

      <el-table
        v-loading="loading"
        element-loading-text="Memuat log..."
        class="data-table log-table"
        :data="visibleRows"
        row-key="id"
      >
        <el-table-column label="Waktu" width="164">
          <template #default="{ row }">
            <div class="time-stack">
              <span class="time-line is-created">{{ timeDate(row.created_at) }}</span>
              <span class="time-line is-last">{{ timeClock(row.created_at) }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="Jenis" width="116">
          <template #default="{ row }">
            <span :class="['log-badge', `is-${kindMeta(row.kind).tone}`]">{{ kindMeta(row.kind).label }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Profil" width="200">
          <template #default="{ row }">
            <span :class="['log-profile', { 'is-empty': row.profile_id === null || row.profile_id === undefined }]">
              {{ profileLabel(row) }}
            </span>
          </template>
        </el-table-column>
        <el-table-column label="Pesan" min-width="420">
          <template #default="{ row }">
            <span class="log-message" :title="row.message">{{ row.message }}</span>
          </template>
        </el-table-column>

        <template #empty>
          <div class="table-empty">
            <div class="empty-title">{{ hasFilter ? 'Tidak ada aktivitas yang cocok' : 'Belum ada aktivitas' }}</div>
            <p class="empty-text">
              {{
                hasFilter
                  ? 'Ubah jenis atau kata kunci untuk melihat aktivitas lain.'
                  : 'Aksi pada profil, proxy, extension, grup, dan tag akan tercatat di sini.'
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
          :total="visibleTotal"
          layout="total, prev, pager, next"
          @current-change="onPageChange"
        />
      </div>
    </section>
  </div>
</template>
