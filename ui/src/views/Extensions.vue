<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Refresh, Search, Upload } from '@element-plus/icons-vue'
import { api } from '../api'
import { useOnRefresh } from '../refresh'

const rows = ref([])
const total = ref(0)
const page = ref(1)
const limit = ref(10)
const search = ref('')
const loading = ref(false)
const uploading = ref(false)
const fileInput = ref(null)

let searchTimer = null

function formatSize(bytes) {
  const size = Number(bytes) || 0
  if (size < 1024) return `${size} B`
  const text = (value) => value.toFixed(1).replace('.', ',')
  if (size < 1024 * 1024) return `${text(size / 1024)} KB`
  return `${text(size / (1024 * 1024))} MB`
}

function versionLabel(row) {
  return row.version ? row.version : 'tanpa versi'
}

async function load() {
  loading.value = true
  try {
    const result = await api.extensions({
      page: page.value,
      limit: limit.value,
      name: search.value.trim() || undefined,
    })
    rows.value = result.data || []
    total.value = result.total || 0
  } catch (error) {
    ElMessage.error(`Gagal memuat extension: ${error.message}`)
  } finally {
    loading.value = false
  }
}

function onSearch() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => {
    page.value = 1
    load()
  }, 300)
}

function triggerUpload() {
  fileInput.value?.click()
}

function readAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(reader.result)
    reader.onerror = () => reject(reader.error || new Error('gagal membaca file'))
    reader.readAsDataURL(file)
  })
}

async function onFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  uploading.value = true
  try {
    const dataUrl = await readAsDataUrl(file)
    const base64 = String(dataUrl).split(',')[1] || ''
    const result = await api.uploadExtension({ filename: file.name, content: base64 })
    ElMessage.success(`Extension "${result.title}" diunggah`)
    search.value = ''
    page.value = 1
    await load()
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    uploading.value = false
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(
      `Hapus extension "${row.title}"? Folder extension di disk ikut dihapus.`,
      'Hapus Extension',
      {
        type: 'warning',
        confirmButtonText: 'Hapus',
        cancelButtonText: 'Batal',
        confirmButtonClass: 'el-button--danger',
      }
    )
  } catch {
    return
  }
  try {
    await api.deleteExtension(row.id)
    ElMessage.success('Extension dihapus')
    if (rows.value.length === 1 && page.value > 1) page.value -= 1
    await load()
  } catch (error) {
    ElMessage.error(error.message)
  }
}

function onPageChange(value) {
  page.value = value
  load()
}

function onSizeChange(value) {
  limit.value = value
  page.value = 1
  load()
}

onMounted(load)
useOnRefresh(() => load())
</script>

<template>
  <div class="extensions-page">
    <section class="surface extensions-panel">
      <div class="page-toolbar">
        <div class="toolbar-left">
          <el-button type="primary" :icon="Upload" :loading="uploading" @click="triggerUpload">
            Unggah Extension
          </el-button>
          <input
            ref="fileInput"
            class="extension-file-input"
            type="file"
            accept=".zip,.crx"
            @change="onFile"
          />
          <el-input
            v-model="search"
            class="search-input"
            placeholder="Cari nama extension"
            :prefix-icon="Search"
            clearable
            @input="onSearch"
            @clear="onSearch"
          />
        </div>
        <div class="toolbar-right">
          <el-tooltip content="Muat ulang daftar" placement="top" :show-after="200">
            <el-button class="icon-action" :icon="Refresh" aria-label="Muat ulang daftar" @click="load" />
          </el-tooltip>
        </div>
      </div>

      <el-table
        v-loading="loading || uploading"
        :element-loading-text="uploading ? 'Mengunggah extension...' : 'Memuat extension...'"
        class="data-table extensions-table"
        :data="rows"
        row-key="id"
      >
        <el-table-column label="Nama" min-width="260">
          <template #default="{ row }">
            <div class="cell-stack">
              <span class="cell-main">{{ row.title }}</span>
              <span class="cell-sub" :title="row.path">{{ row.path }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="Versi" width="120">
          <template #default="{ row }">
            <span :class="row.version ? 'mono' : 'cell-sub'">{{ versionLabel(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Ukuran Folder" width="140">
          <template #default="{ row }">
            <span class="cell-sub">{{ formatSize(row.size) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Diunggah" width="180">
          <template #default="{ row }">
            <span class="cell-sub">{{ row.created_at || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Operasi" width="100" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-tooltip content="Hapus extension" placement="top" :show-after="200">
                <el-button
                  size="small"
                  class="icon-action danger"
                  :icon="Delete"
                  aria-label="Hapus extension"
                  @click="remove(row)"
                />
              </el-tooltip>
            </div>
          </template>
        </el-table-column>

        <template #empty>
          <div class="table-empty">
            <div class="empty-title">Belum ada extension</div>
            <p class="empty-text">
              Unggah file .zip atau .crx untuk menyimpan extension secara lokal, lalu pilih di tab Extension pada profil.
            </p>
            <el-button type="primary" :icon="Upload" :loading="uploading" @click="triggerUpload">
              Unggah Extension
            </el-button>
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
          :total="total"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="onPageChange"
          @size-change="onSizeChange"
        />
      </div>
    </section>
  </div>
</template>
