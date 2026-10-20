<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, DocumentCopy, Download, Hide, InfoFilled, Lock, Refresh, View } from '@element-plus/icons-vue'
import { api } from '../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  profile: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue'])

const items = ref([])
const revealed = ref(new Set())
const loading = ref(false)
const errorText = ref('')
const deletingRow = ref('')

const title = computed(() => `Password Tersimpan: ${props.profile?.name || ''}`)

async function load() {
  if (!props.profile) return
  loading.value = true
  errorText.value = ''
  revealed.value = new Set()
  try {
    const result = await api.savedPasswords(props.profile.profile_id)
    items.value = Array.isArray(result) ? result : []
  } catch (error) {
    items.value = []
    errorText.value = error.message
  } finally {
    loading.value = false
  }
}

function isRevealed(index) {
  return revealed.value.has(index)
}

function toggle(index) {
  const next = new Set(revealed.value)
  if (next.has(index)) next.delete(index)
  else next.add(index)
  revealed.value = next
}

async function copy(row) {
  if (!row.password) {
    ElMessage.warning('Password tidak terbaca')
    return
  }
  try {
    await navigator.clipboard.writeText(row.password)
    ElMessage.success('Password disalin')
  } catch (error) {
    ElMessage.error(`Gagal menyalin: ${error.message}`)
  }
}

function rowKey(row) {
  return `${row.origin_url}|${row.username}`
}

function csvCell(value) {
  const text = value === null || value === undefined ? '' : String(value)
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

async function exportCsv() {
  if (!items.value.length) {
    ElMessage.info('Belum ada password untuk diekspor')
    return
  }
  try {
    await ElMessageBox.confirm(
      `Ekspor ${items.value.length} password ke CSV? File CSV berisi teks biasa tanpa enkripsi, simpan di tempat aman.`,
      'Ekspor CSV',
      {
        type: 'warning',
        confirmButtonText: 'Ekspor',
        cancelButtonText: 'Batal',
      }
    )
  } catch {
    return
  }
  const lines = ['origin_url,username,password']
  for (const row of items.value) {
    lines.push(
      [csvCell(row.origin_url), csvCell(row.username), csvCell(row.password)].join(',')
    )
  }
  const blob = new Blob([`${lines.join('\r\n')}\r\n`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = `password-${props.profile?.profile_id ?? 'profil'}.csv`
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  ElMessage.success(`${items.value.length} password diekspor`)
}

async function remove(row) {
  if (!props.profile) return
  const username = row.username || '(kosong)'
  try {
    await ElMessageBox.confirm(
      `Hapus password ${row.origin_url} untuk username "${username}"?`,
      'Hapus Password',
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
  deletingRow.value = rowKey(row)
  errorText.value = ''
  try {
    await api.deleteSavedPassword(
      props.profile.profile_id,
      row.origin_url,
      row.username || ''
    )
    ElMessage.success('Password dihapus')
    await load()
  } catch (error) {
    errorText.value = error.message
    ElMessage.error(`Gagal menghapus password: ${error.message}`)
  } finally {
    deletingRow.value = ''
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
      errorText.value = ''
      load()
    }
  }
)
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="860px"
    top="7vh"
    class="password-dialog"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="data-dialog-body">
      <div class="data-dialog-toolbar">
        <p class="dialog-note">
          <el-icon><Lock /></el-icon>
          Didekripsi lokal; ekspor CSV menghasilkan file tanpa enkripsi
        </p>
        <div class="toolbar-actions">
          <el-button :icon="Download" @click="exportCsv">Ekspor CSV</el-button>
          <el-button :icon="Refresh" :loading="loading" @click="load">Muat ulang</el-button>
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

      <el-table v-loading="loading" class="data-table password-table" :data="items" max-height="420">
        <el-table-column label="Situs" min-width="240">
          <template #default="{ row }">
            <span class="cell-main" :title="row.origin_url">{{ row.origin_url || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Username" min-width="160">
          <template #default="{ row }">
            <span class="cell-sub">{{ row.username || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Password" width="210">
          <template #default="{ row, $index }">
            <div class="password-cell">
              <span
                :class="[
                  'password-value',
                  isRevealed($index) ? (row.password ? 'is-visible' : 'is-empty') : 'is-masked',
                ]"
              >
                {{ isRevealed($index) ? row.password || 'Tidak terbaca' : '••••••••' }}
              </span>
              <el-tooltip
                :content="isRevealed($index) ? 'Sembunyikan password' : 'Tampilkan password'"
                placement="top"
                :show-after="200"
              >
                <el-button
                  class="icon-action"
                  size="small"
                  :icon="isRevealed($index) ? Hide : View"
                  :aria-label="isRevealed($index) ? 'Sembunyikan password' : 'Tampilkan password'"
                  @click="toggle($index)"
                />
              </el-tooltip>
              <el-tooltip content="Salin password" placement="top" :show-after="200">
                <el-button
                  class="icon-action"
                  size="small"
                  :icon="DocumentCopy"
                  aria-label="Salin password"
                  @click="copy(row)"
                />
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="" width="64" align="right">
          <template #default="{ row }">
            <el-tooltip content="Hapus password" placement="top" :show-after="200">
              <el-button
                class="icon-action danger"
                size="small"
                :icon="Delete"
                aria-label="Hapus password"
                :loading="deletingRow === rowKey(row)"
                @click="remove(row)"
              />
            </el-tooltip>
          </template>
        </el-table-column>
        <template #empty>
          <div class="data-empty">Belum ada password tersimpan</div>
        </template>
      </el-table>

      <p class="dialog-note">
        <el-icon><InfoFilled /></el-icon>
        Menambah atau mengubah password belum didukung engine; gunakan browser lalu simpan lewat
        halaman login.
      </p>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="close">Tutup</el-button>
      </div>
    </template>
  </el-dialog>
</template>
