<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Clock, Delete, Download, Edit, Menu, Plus, Refresh, Upload } from '@element-plus/icons-vue'
import { api } from '../api'
import { useOnRefresh } from '../refresh'
import ProxyHistoryDialog from '../components/ProxyHistoryDialog.vue'

const PROXY_TYPES = ['http', 'https', 'socks5']
const COLUMN_STORAGE_KEY = 'antidetect.proxies.columns'

function loadColumnSetting() {
  try {
    const saved = JSON.parse(localStorage.getItem(COLUMN_STORAGE_KEY) || '')
    if (typeof saved === 'boolean') return saved
  } catch {
    return true
  }
  return true
}

const rows = ref([])
const total = ref(0)
const page = ref(1)
const limit = ref(10)
const loading = ref(false)
const dialogVisible = ref(false)
const editing = ref(null)
const busy = ref(false)
const errors = reactive({ proxy_ip: '', proxy_port: '' })
const showLastCheck = ref(loadColumnSetting())
const validateBeforeSave = ref(false)
const historyVisible = ref(false)
const historyProxy = ref(null)

const importVisible = ref(false)
const importBusy = ref(false)
const importType = ref('http')
const importText = ref('')
const importResult = ref(null)
const exportVisible = ref(false)
const exportBusy = ref(false)
const exportCredentials = ref(true)

const form = reactive({
  proxy_type: 'http',
  proxy_ip: '',
  proxy_port: null,
  proxy_user: '',
  proxy_password: '',
  note: '',
})

const isEdit = computed(() => !!editing.value)
const title = computed(() => (isEdit.value ? 'Edit Proxy' : 'Tambah Proxy'))
const importLines = computed(
  () =>
    importText.value
      .split(/\r?\n/)
      .filter((line) => line.trim() && !line.trim().startsWith('#')).length
)
const importErrors = computed(() => importResult.value?.errors || [])
const importErrorPreview = computed(() => importErrors.value.slice(0, 10))
const importSkipped = computed(() => importResult.value?.skipped_lines || [])
const checks = reactive({})
const dialogCheck = reactive({ loading: false, ok: null, text: '' })

function applyCheck(target, result) {
  if (result?.ok) {
    target.ok = true
    target.text = `${result.ip} · ${result.latency_ms} ms`
  } else {
    target.ok = false
    target.text = result?.error || 'Cek proxy gagal'
  }
}

function localTimestamp() {
  const now = new Date()
  const pad = (value) => String(value).padStart(2, '0')
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())} ${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}`
}

function localCheck(result) {
  return {
    checked_at: localTimestamp(),
    ok: !!result?.ok,
    ip: result?.ip || null,
    latency_ms: result?.latency_ms ?? null,
    error: result?.error || null,
  }
}

function lastCheck(row) {
  return row.last_check || null
}

function lastCheckText(row) {
  const check = lastCheck(row)
  if (!check) return 'Belum pernah'
  if (check.ok) {
    const latency = check.latency_ms != null ? `${check.latency_ms} ms` : 'latensi tidak diketahui'
    return `${check.ip || 'IP tidak diketahui'} · ${latency}`
  }
  return `Gagal: ${check.error || 'cek proxy gagal'}`
}

function toggleLastCheck(value) {
  showLastCheck.value = value
  localStorage.setItem(COLUMN_STORAGE_KEY, JSON.stringify(value))
}

async function checkRow(row) {
  checks[row.id] = { loading: true, ok: null, text: '' }
  try {
    const result = await api.checkProxy({ proxy_id: row.id })
    checks[row.id] = { loading: false }
    applyCheck(checks[row.id], result)
    row.last_check = localCheck(result)
  } catch (error) {
    checks[row.id] = { loading: false, ok: false, text: error.message }
  }
}

function openHistory(row) {
  historyProxy.value = row
  historyVisible.value = true
}

async function testConnection() {
  if (!validate()) return
  dialogCheck.loading = true
  dialogCheck.ok = null
  dialogCheck.text = ''
  try {
    const result = await api.checkProxy({
      proxy_type: form.proxy_type,
      proxy_ip: form.proxy_ip.trim(),
      proxy_port: Number(form.proxy_port),
      proxy_user: form.proxy_user.trim() || null,
      proxy_password: form.proxy_password || null,
    })
    applyCheck(dialogCheck, result)
  } catch (error) {
    dialogCheck.ok = false
    dialogCheck.text = error.message
  } finally {
    dialogCheck.loading = false
  }
}

async function load() {
  loading.value = true
  try {
    const result = await api.proxies({ page: page.value, limit: limit.value })
    rows.value = result.data || []
    total.value = result.total || 0
  } catch (error) {
    ElMessage.error(`Gagal memuat proxy: ${error.message}`)
  } finally {
    loading.value = false
  }
}

function clearErrors() {
  errors.proxy_ip = ''
  errors.proxy_port = ''
}

function openCreate() {
  editing.value = null
  Object.assign(form, {
    proxy_type: 'http',
    proxy_ip: '',
    proxy_port: null,
    proxy_user: '',
    proxy_password: '',
    note: '',
  })
  dialogCheck.loading = false
  dialogCheck.ok = null
  dialogCheck.text = ''
  validateBeforeSave.value = false
  clearErrors()
  dialogVisible.value = true
}

function openEdit(row) {
  editing.value = row
  const type = String(row.proxy_type || '').toLowerCase()
  Object.assign(form, {
    proxy_type: PROXY_TYPES.includes(type) ? type : 'http',
    proxy_ip: row.proxy_ip || '',
    proxy_port: row.proxy_port ?? null,
    proxy_user: row.proxy_user || '',
    proxy_password: row.proxy_password || '',
    note: row.note || '',
  })
  dialogCheck.loading = false
  dialogCheck.ok = null
  dialogCheck.text = ''
  validateBeforeSave.value = false
  clearErrors()
  dialogVisible.value = true
}

function validate() {
  clearErrors()
  if (!form.proxy_ip.trim()) errors.proxy_ip = 'Host wajib diisi'
  const port = Number(form.proxy_port)
  if (!Number.isInteger(port) || port < 1 || port > 65535) errors.proxy_port = 'Port harus 1 sampai 65535'
  return !errors.proxy_ip && !errors.proxy_port
}

async function submit() {
  if (!validate()) return
  busy.value = true
  try {
    const payload = {
      proxy_type: form.proxy_type,
      proxy_ip: form.proxy_ip.trim(),
      proxy_port: Number(form.proxy_port),
      proxy_user: form.proxy_user.trim() || null,
      proxy_password: form.proxy_password || null,
      note: form.note.trim() || null,
    }
    if (validateBeforeSave.value) {
      const result = await api.validateProxy({
        proxy_type: payload.proxy_type,
        proxy_ip: payload.proxy_ip,
        proxy_port: payload.proxy_port,
        proxy_user: payload.proxy_user,
        proxy_password: payload.proxy_password,
      })
      if (!result?.ok) {
        ElMessage.error(`Proxy gagal diuji: ${result?.error || 'cek proxy gagal'}`)
        return
      }
    }
    if (isEdit.value) {
      await api.updateProxy({ id: editing.value.id, ...payload })
      ElMessage.success('Proxy diperbarui')
    } else {
      await api.createProxy(payload)
      ElMessage.success('Proxy ditambahkan')
    }
    dialogVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(`Gagal menyimpan proxy: ${error.message}`)
  } finally {
    busy.value = false
  }
}

function openImport() {
  importType.value = 'http'
  importText.value = ''
  importResult.value = null
  importVisible.value = true
}

async function runImport() {
  if (!importLines.value || importBusy.value) return
  importBusy.value = true
  try {
    const result = await api.importProxies(importText.value, importType.value)
    importResult.value = result
    const problems = importErrors.value.length
    if (problems) {
      ElMessage.warning(
        `Impor selesai dengan ${problems} masalah: ${result.created} dibuat, ${result.skipped} duplikat dilewati, ${problems} gagal`
      )
    } else if (result.skipped) {
      ElMessage.success(
        `Impor selesai: ${result.created} dibuat, ${result.skipped} duplikat dilewati`
      )
    } else {
      ElMessage.success(`Impor selesai: ${result.created} proxy dibuat`)
    }
    if (result.created) {
      page.value = 1
      await load()
    }
  } catch (error) {
    ElMessage.error(`Gagal mengimpor proxy: ${error.message}`)
  } finally {
    importBusy.value = false
  }
}

function openExport() {
  exportCredentials.value = true
  exportVisible.value = true
}

function downloadText(filename, contentBase64) {
  const binary = atob(contentBase64 || '')
  const bytes = new Uint8Array(binary.length)
  for (let index = 0; index < binary.length; index += 1) bytes[index] = binary.charCodeAt(index)
  const blob = new Blob([bytes], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename || 'proxy-export.txt'
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

async function runExport() {
  exportBusy.value = true
  try {
    const result = await api.exportProxies(exportCredentials.value)
    if (!result.count) {
      ElMessage.info('Belum ada proxy untuk diekspor')
      return
    }
    downloadText(result.filename, result.content_base64)
    ElMessage.success(`${result.count} proxy diekspor`)
    exportVisible.value = false
  } catch (error) {
    ElMessage.error(`Gagal mengekspor proxy: ${error.message}`)
  } finally {
    exportBusy.value = false
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`Hapus proxy ${hostLabel(row)}?`, 'Hapus Proxy', {
      type: 'warning',
      confirmButtonText: 'Hapus',
      cancelButtonText: 'Batal',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return
  }
  try {
    await api.deleteProxy(row.id)
    ElMessage.success('Proxy dihapus')
    if (rows.value.length === 1 && page.value > 1) page.value -= 1
    await load()
  } catch (error) {
    ElMessage.error(`Gagal menghapus proxy: ${error.message}`)
  }
}

function typeLabel(row) {
  return String(row.proxy_type || '-').toUpperCase()
}

function hostLabel(row) {
  return `${row.proxy_ip || '-'}:${row.proxy_port ?? '-'}`
}

function authLabel(row) {
  return row.proxy_user || row.proxy_password ? 'Ya' : 'Tidak'
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
  <div class="proxies-page">
    <section class="surface proxies-panel">
      <div class="page-toolbar">
        <div class="toolbar-left">
          <el-button type="primary" :icon="Plus" @click="openCreate">Tambah Proxy</el-button>
          <el-button :icon="Upload" @click="openImport">Impor Massal</el-button>
          <el-button :icon="Download" @click="openExport">Ekspor</el-button>
        </div>
        <div class="toolbar-right">
          <el-dropdown trigger="click" :hide-on-click="false">
            <el-button :icon="Menu" aria-label="Pilih kolom">Pilih Kolom</el-button>
            <template #dropdown>
              <div class="column-picker">
                <el-checkbox
                  :model-value="showLastCheck"
                  @change="toggleLastCheck"
                >Cek Terakhir</el-checkbox>
              </div>
            </template>
          </el-dropdown>
          <el-tooltip content="Muat ulang daftar" placement="top" :show-after="200">
            <el-button class="icon-action" :icon="Refresh" aria-label="Muat ulang daftar" @click="load" />
          </el-tooltip>
        </div>
      </div>

      <el-table
        v-loading="loading"
        element-loading-text="Memuat proxy..."
        class="data-table proxies-table"
        :data="rows"
        row-key="id"
      >
        <el-table-column label="Tipe" width="96">
          <template #default="{ row }">
            <span class="cell-main">{{ typeLabel(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Host:Port" width="200">
          <template #default="{ row }">
            <span class="mono">{{ hostLabel(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Autentikasi" width="104">
          <template #default="{ row }">
            <span :class="authLabel(row) === 'Ya' ? 'cell-main' : 'cell-sub'">{{ authLabel(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Catatan" min-width="160">
          <template #default="{ row }">
            <span class="cell-sub" :title="row.note || ''">{{ row.note || 'Tanpa catatan' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Status" width="206">
          <template #default="{ row }">
            <div class="proxy-check-cell">
              <el-button size="small" :loading="checks[row.id]?.loading" @click="checkRow(row)">Tes</el-button>
              <span
                v-if="checks[row.id]?.text"
                :class="['proxy-check-result', checks[row.id].ok ? 'is-ok' : 'is-fail']"
                :title="checks[row.id].text"
              >{{ checks[row.id].text }}</span>
            </div>
          </template>
        </el-table-column>
        <el-table-column v-if="showLastCheck" label="Cek Terakhir" width="186">
          <template #default="{ row }">
            <span
              v-if="lastCheck(row)"
              :class="['proxy-check-result', lastCheck(row).ok ? 'is-ok' : 'is-fail']"
              :title="lastCheckText(row)"
            >{{ lastCheckText(row) }}</span>
            <span v-else class="cell-sub">Belum pernah</span>
          </template>
        </el-table-column>
        <el-table-column label="Operasi" width="156" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-tooltip content="Riwayat cek proxy" placement="top" :show-after="200">
                <el-button
                  size="small"
                  class="icon-action"
                  :icon="Clock"
                  aria-label="Riwayat cek proxy"
                  @click="openHistory(row)"
                />
              </el-tooltip>
              <el-tooltip content="Edit proxy" placement="top" :show-after="200">
                <el-button size="small" class="icon-action" :icon="Edit" aria-label="Edit proxy" @click="openEdit(row)" />
              </el-tooltip>
              <el-tooltip content="Hapus proxy" placement="top" :show-after="200">
                <el-button
                  size="small"
                  class="icon-action danger"
                  :icon="Delete"
                  aria-label="Hapus proxy"
                  @click="remove(row)"
                />
              </el-tooltip>
            </div>
          </template>
        </el-table-column>

        <template #empty>
          <div class="table-empty">
            <div class="empty-title">Belum ada proxy tersimpan</div>
            <p class="empty-text">Kelola daftar proxy terpisah dari profil. Konfigurasi proxy per profil diatur di tab Konfigurasi Proxy.</p>
            <el-button type="primary" :icon="Plus" @click="openCreate">Tambah Proxy</el-button>
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

    <el-dialog
      v-model="dialogVisible"
      :title="title"
      width="560px"
      top="8vh"
      class="proxy-dialog"
      :close-on-click-modal="false"
    >
      <el-form label-width="160px" label-position="right" class="dialog-form" @submit.prevent>
        <el-form-item label="Tipe">
          <el-select v-model="form.proxy_type" class="field-180">
            <el-option v-for="type in PROXY_TYPES" :key="type" :label="type.toUpperCase()" :value="type" />
          </el-select>
        </el-form-item>
        <el-form-item label="Host" required :error="errors.proxy_ip">
          <el-input v-model="form.proxy_ip" placeholder="203.0.113.10" @input="errors.proxy_ip = ''" />
        </el-form-item>
        <el-form-item label="Port" required :error="errors.proxy_port">
          <el-input
            v-model="form.proxy_port"
            type="number"
            min="1"
            max="65535"
            class="field-180"
            placeholder="8080"
            @input="errors.proxy_port = ''"
          />
        </el-form-item>
        <el-form-item label="Username">
          <el-input v-model="form.proxy_user" placeholder="opsional" />
        </el-form-item>
        <el-form-item label="Password">
          <el-input v-model="form.proxy_password" type="password" show-password placeholder="opsional" />
        </el-form-item>
        <el-form-item label="Tes Koneksi">
          <div class="proxy-check-cell">
            <el-button size="small" :loading="dialogCheck.loading" @click="testConnection">Tes Koneksi</el-button>
            <span
              v-if="dialogCheck.text"
              :class="['proxy-check-result', dialogCheck.ok ? 'is-ok' : 'is-fail']"
            >{{ dialogCheck.text }}</span>
          </div>
        </el-form-item>
        <el-form-item label="Tes sebelum menyimpan">
          <div class="proxy-switch-cell">
            <el-switch v-model="validateBeforeSave" />
            <span class="form-hint">Proxy diuji dulu. Kalau gagal, proxy tidak disimpan.</span>
          </div>
        </el-form-item>
        <el-form-item label="Catatan">
          <el-input v-model="form.note" type="textarea" :rows="3" maxlength="200" show-word-limit placeholder="opsional" />
        </el-form-item>
      </el-form>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="dialogVisible = false">Batal</el-button>
          <div class="footer-spacer"></div>
          <el-button type="primary" :loading="busy" @click="submit">Simpan</el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="importVisible"
      title="Impor Massal Proxy"
      width="640px"
      top="8vh"
      class="proxy-import-dialog"
      :close-on-click-modal="false"
    >
      <el-form label-width="120px" label-position="right" class="dialog-form" @submit.prevent>
        <el-form-item label="Tipe Default">
          <el-select v-model="importType" class="field-180">
            <el-option v-for="type in PROXY_TYPES" :key="type" :label="type.toUpperCase()" :value="type" />
          </el-select>
        </el-form-item>
        <el-form-item label="Daftar Proxy">
          <el-input
            v-model="importText"
            type="textarea"
            :rows="9"
            class="import-textarea"
            placeholder="http://user:pass@203.0.113.10:8080&#10;socks5://198.51.100.7:1080&#10;203.0.113.20:3128&#10;203.0.113.21:3128:user:pass&#10;user:pass@203.0.113.22:8000"
          />
          <div class="import-meta">
            <span :class="{ 'is-over': importLines > 500 }">{{ importLines }} baris siap diimpor</span>
            <span class="form-hint">Maksimal 500 baris. Baris kosong dan berawalan # diabaikan.</span>
          </div>
        </el-form-item>
      </el-form>

      <div v-if="importResult" class="import-result">
        <div class="import-summary">
          <span><strong>{{ importResult.created }}</strong> dibuat</span>
          <span><strong>{{ importResult.skipped }}</strong> dilewati</span>
          <span><strong>{{ importErrors.length }}</strong> error</span>
        </div>
        <div v-if="importErrors.length" class="import-errors">
          <div class="import-errors-title">Baris yang gagal</div>
          <ul>
            <li v-for="item in importErrorPreview" :key="item.line">
              <span class="mono">baris {{ item.line }}</span>
              <span>{{ item.message }}</span>
            </li>
          </ul>
          <p v-if="importErrors.length > 10" class="form-hint">
            {{ importErrors.length - 10 }} error lain tidak ditampilkan.
          </p>
        </div>
        <div v-if="importSkipped.length" class="import-errors import-skipped">
          <div class="import-errors-title">Duplikat, dilewati</div>
          <ul>
            <li v-for="item in importSkipped.slice(0, 10)" :key="item.line">
              <span class="mono">baris {{ item.line }}</span>
              <span>{{ item.message }}</span>
            </li>
          </ul>
          <p v-if="importSkipped.length > 10" class="form-hint">
            {{ importSkipped.length - 10 }} duplikat lain tidak ditampilkan.
          </p>
        </div>
      </div>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="importVisible = false">{{ importResult ? 'Tutup' : 'Batal' }}</el-button>
          <div class="footer-spacer"></div>
          <el-button
            v-if="!importResult"
            type="primary"
            :loading="importBusy"
            :disabled="!importLines || importLines > 500"
            @click="runImport"
          >
            Impor
          </el-button>
          <el-button v-else type="primary" @click="importVisible = false">Selesai</el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="exportVisible"
      title="Ekspor Proxy"
      width="440px"
      class="proxy-export-dialog"
      :close-on-click-modal="false"
    >
      <el-checkbox v-model="exportCredentials">Sertakan kredensial</el-checkbox>
      <p class="form-hint">File teks berisi satu proxy per baris. Catatan tidak disertakan.</p>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="exportVisible = false">Batal</el-button>
          <div class="footer-spacer"></div>
          <el-button type="primary" :loading="exportBusy" @click="runExport">Unduh</el-button>
        </div>
      </template>
    </el-dialog>

    <ProxyHistoryDialog v-model="historyVisible" :proxy="historyProxy" @cleared="load" />
  </div>
</template>
