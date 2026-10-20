<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Link, Plus, Refresh, Search } from '@element-plus/icons-vue'
import { api } from '../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  profile: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue'])

const items = ref([])
const query = ref('')
const loading = ref(false)
const errorText = ref('')
const formVisible = ref(false)
const saving = ref(false)
const deletingId = ref('')
const form = reactive({ name: '', url: '', folder: 'Bookmarks bar' })

const title = computed(() => `Bookmark: ${props.profile?.name || ''}`)
const filtered = computed(() => {
  const needle = query.value.trim().toLowerCase()
  if (!needle) return items.value
  return items.value.filter((item) =>
    [item.name, item.url, item.folder].some((value) =>
      String(value || '').toLowerCase().includes(needle)
    )
  )
})
const folderOptions = computed(() => {
  const folders = new Set(['Bookmarks bar', 'Other bookmarks', 'Mobile bookmarks'])
  for (const item of items.value) {
    if (item.folder) folders.add(item.folder)
  }
  return [...folders].sort((left, right) => left.localeCompare(right))
})

function rowKey(row) {
  return `${row.folder}|${row.id}|${row.url}`
}

async function load() {
  if (!props.profile) return
  loading.value = true
  errorText.value = ''
  try {
    const result = await api.bookmarks(props.profile.profile_id)
    items.value = Array.isArray(result) ? result : []
  } catch (error) {
    items.value = []
    errorText.value = error.message
  } finally {
    loading.value = false
  }
}

function openUrl(url) {
  if (!url) return
  window.open(url, '_blank', 'noopener,noreferrer')
}

function cancelForm() {
  formVisible.value = false
  form.name = ''
  form.url = ''
  form.folder = 'Bookmarks bar'
}

function startForm() {
  errorText.value = ''
  formVisible.value = true
}

async function submit() {
  if (!props.profile) return
  if (!form.name.trim() || !form.url.trim()) {
    ElMessage.warning('Nama dan URL wajib diisi')
    return
  }
  saving.value = true
  errorText.value = ''
  try {
    const result = await api.addBookmark(props.profile.profile_id, {
      name: form.name.trim(),
      url: form.url.trim(),
      folder: form.folder.trim() || 'Bookmarks bar',
    })
    ElMessage.success(`Bookmark "${result?.name || form.name.trim()}" ditambahkan`)
    cancelForm()
    await load()
  } catch (error) {
    errorText.value = error.message
    ElMessage.error(`Gagal menambah bookmark: ${error.message}`)
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  if (!props.profile) return
  try {
    await ElMessageBox.confirm(
      `Hapus bookmark "${row.name}" (${row.url})?`,
      'Hapus Bookmark',
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
  deletingId.value = row.id
  errorText.value = ''
  try {
    await api.deleteBookmark(props.profile.profile_id, row.id)
    ElMessage.success(`Bookmark "${row.name}" dihapus`)
    await load()
  } catch (error) {
    errorText.value = error.message
    ElMessage.error(`Gagal menghapus bookmark: ${error.message}`)
  } finally {
    deletingId.value = ''
  }
}

function close() {
  emit('update:modelValue', false)
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      items.value = []
      query.value = ''
      errorText.value = ''
      cancelForm()
      load()
    }
  }
)
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="780px"
    top="7vh"
    class="bookmark-dialog"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="data-dialog-body">
      <div class="data-dialog-toolbar">
        <el-input v-model="query" class="search-input" placeholder="Cari nama atau URL" clearable>
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <div class="toolbar-actions">
          <el-button :icon="Plus" @click="startForm">Tambah Bookmark</el-button>
          <el-button :icon="Refresh" :loading="loading" @click="load">Muat ulang</el-button>
        </div>
      </div>

      <div v-if="formVisible" class="bookmark-form">
        <div class="bookmark-form-grid">
          <label class="bookmark-field">
            <span class="bookmark-field-label">Nama</span>
            <el-input
              v-model="form.name"
              maxlength="200"
              placeholder="Judul bookmark"
              @keyup.enter="submit"
            />
          </label>
          <label class="bookmark-field">
            <span class="bookmark-field-label">URL</span>
            <el-input
              v-model="form.url"
              placeholder="https://contoh.net/halaman"
              @keyup.enter="submit"
            />
          </label>
          <label class="bookmark-field">
            <span class="bookmark-field-label">Folder</span>
            <input
              v-model="form.folder"
              class="bookmark-folder-input"
              list="bookmark-folder-options"
              placeholder="Bookmarks bar"
              @keyup.enter="submit"
            />
            <datalist id="bookmark-folder-options">
              <option v-for="folder in folderOptions" :key="folder" :value="folder" />
            </datalist>
          </label>
        </div>
        <div class="bookmark-form-actions">
          <span class="bookmark-form-hint">Folder baru dibuat otomatis.</span>
          <el-button size="small" @click="cancelForm">Batal</el-button>
          <el-button size="small" type="primary" :loading="saving" @click="submit">
            Simpan
          </el-button>
        </div>
      </div>

      <el-alert
        v-if="errorText"
        class="cookie-alert"
        type="error"
        :closable="false"
        show-icon
        :title="errorText"
      />

      <el-table
        v-loading="loading"
        class="data-table bookmark-table"
        :data="filtered"
        :row-key="rowKey"
        max-height="420"
      >
        <el-table-column label="Nama" min-width="180">
          <template #default="{ row }">
            <span class="cell-main">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="URL" min-width="280">
          <template #default="{ row }">
            <button type="button" class="bookmark-link" :title="row.url" @click="openUrl(row.url)">
              {{ row.url }}
            </button>
          </template>
        </el-table-column>
        <el-table-column label="Folder" width="170">
          <template #default="{ row }">
            <span class="cell-sub">{{ row.folder || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="" width="88" align="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-tooltip content="Buka di browser" placement="top" :show-after="200">
                <el-button
                  class="icon-action"
                  size="small"
                  :icon="Link"
                  aria-label="Buka URL"
                  @click="openUrl(row.url)"
                />
              </el-tooltip>
              <el-tooltip content="Hapus bookmark" placement="top" :show-after="200">
                <el-button
                  class="icon-action danger"
                  size="small"
                  :icon="Delete"
                  aria-label="Hapus bookmark"
                  :loading="deletingId === row.id"
                  @click="remove(row)"
                />
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
        <template #empty>
          <div class="data-empty">
            {{ items.length ? 'Tidak ada bookmark yang cocok' : 'Belum ada bookmark' }}
          </div>
        </template>
      </el-table>

      <p class="dialog-note">{{ filtered.length }} dari {{ items.length }} bookmark</p>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="close">Tutup</el-button>
      </div>
    </template>
  </el-dialog>
</template>
