<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Edit, Plus, Refresh } from '@element-plus/icons-vue'
import { api } from '../api'
import { useOnRefresh } from '../refresh'

const PROXY_TYPES = ['http', 'https', 'socks5']

const rows = ref([])
const total = ref(0)
const page = ref(1)
const limit = ref(10)
const loading = ref(false)
const dialogVisible = ref(false)
const editing = ref(null)
const busy = ref(false)
const errors = reactive({ proxy_ip: '', proxy_port: '' })

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

async function checkRow(row) {
  checks[row.id] = { loading: true, ok: null, text: '' }
  try {
    const result = await api.checkProxy({ proxy_id: row.id })
    checks[row.id] = { loading: false }
    applyCheck(checks[row.id], result)
  } catch (error) {
    checks[row.id] = { loading: false, ok: false, text: error.message }
  }
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
        </div>
        <div class="toolbar-right">
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
        <el-table-column label="Tipe" width="100">
          <template #default="{ row }">
            <span class="cell-main">{{ typeLabel(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Host:Port" width="240">
          <template #default="{ row }">
            <span class="mono">{{ hostLabel(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Autentikasi" width="120">
          <template #default="{ row }">
            <span :class="authLabel(row) === 'Ya' ? 'cell-main' : 'cell-sub'">{{ authLabel(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Catatan" min-width="200">
          <template #default="{ row }">
            <span class="cell-sub" :title="row.note || ''">{{ row.note || 'Tanpa catatan' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Status" width="250">
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
        <el-table-column label="Operasi" width="120" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
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
      <el-form label-width="120px" label-position="right" class="dialog-form" @submit.prevent>
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
  </div>
</template>
