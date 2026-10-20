<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, DocumentCopy, Plus, Refresh } from '@element-plus/icons-vue'
import { api } from '../api'
import { useOnRefresh } from '../refresh'

const rows = ref([])
const total = ref(0)
const page = ref(1)
const limit = ref(10)
const loading = ref(false)

const saveVisible = ref(false)
const saveBusy = ref(false)
const saveName = ref('')
const saveProfileId = ref(null)
const profiles = ref([])
const profileLoading = ref(false)

const createVisible = ref(false)
const createBusy = ref(false)
const createName = ref('')
const activeTemplate = ref(null)

const title = computed(() => (activeTemplate.value ? `Buat Profil dari "${activeTemplate.value.name}"` : 'Buat Profil'))

async function load() {
  loading.value = true
  try {
    const result = await api.templates({ page: page.value, limit: limit.value })
    rows.value = result.data || []
    total.value = result.total || 0
  } catch (error) {
    ElMessage.error(`Gagal memuat template: ${error.message}`)
  } finally {
    loading.value = false
  }
}

async function loadProfiles() {
  profileLoading.value = true
  try {
    const result = await api.profiles({ page: 1, limit: 200 })
    profiles.value = result.data || []
  } catch (error) {
    ElMessage.error(`Gagal memuat daftar profil: ${error.message}`)
  } finally {
    profileLoading.value = false
  }
}

function openSave() {
  saveName.value = ''
  saveProfileId.value = null
  saveVisible.value = true
  loadProfiles()
}

async function runSave() {
  if (saveBusy.value) return
  if (!saveProfileId.value) {
    ElMessage.warning('Pilih profil sumber')
    return
  }
  if (!saveName.value.trim()) {
    ElMessage.warning('Nama template wajib diisi')
    return
  }
  saveBusy.value = true
  try {
    const result = await api.saveTemplate(saveProfileId.value, saveName.value.trim())
    ElMessage.success(`Template "${result.name}" disimpan`)
    saveVisible.value = false
    page.value = 1
    await load()
  } catch (error) {
    ElMessage.error(`Gagal menyimpan template: ${error.message}`)
  } finally {
    saveBusy.value = false
  }
}

function openCreate(row) {
  activeTemplate.value = row
  createName.value = ''
  createVisible.value = true
}

async function runCreate() {
  if (createBusy.value || !activeTemplate.value) return
  createBusy.value = true
  try {
    const result = await api.createProfileFromTemplate(activeTemplate.value.id, createName.value.trim())
    ElMessage.success(`Profil "${result.name}" dibuat`)
    createVisible.value = false
    await load()
  } catch (error) {
    ElMessage.error(`Gagal membuat profil: ${error.message}`)
  } finally {
    createBusy.value = false
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`Hapus template "${row.name}"?`, 'Hapus Template', {
      type: 'warning',
      confirmButtonText: 'Hapus',
      cancelButtonText: 'Batal',
      confirmButtonClass: 'el-button--danger',
    })
  } catch {
    return
  }
  try {
    await api.deleteTemplate(row.id)
    ElMessage.success('Template dihapus')
    if (rows.value.length === 1 && page.value > 1) page.value -= 1
    await load()
  } catch (error) {
    ElMessage.error(`Gagal menghapus template: ${error.message}`)
  }
}

function profileCountLabel(row) {
  return `${row.profile_count} profil`
}

function timestampLabel(value) {
  if (!value) return '-'
  const [date, time] = String(value).split(' ')
  return `${date || ''} ${(time || '').slice(0, 5)}`.trim() || '-'
}

function onPageChange(value) {
  page.value = value
  load()
}

onMounted(load)
useOnRefresh(() => load())
</script>

<template>
  <div class="templates-page">
    <section class="surface templates-panel">
      <div class="page-toolbar">
        <div class="toolbar-left">
          <el-button type="primary" :icon="Plus" @click="openSave">Simpan Template</el-button>
        </div>
        <div class="toolbar-right">
          <el-tooltip content="Muat ulang daftar" placement="top" :show-after="200">
            <el-button class="icon-action" :icon="Refresh" aria-label="Muat ulang daftar" @click="load" />
          </el-tooltip>
        </div>
      </div>

      <el-table
        v-loading="loading"
        element-loading-text="Memuat template..."
        class="data-table templates-table"
        :data="rows"
        row-key="id"
      >
        <el-table-column label="Nama Template" min-width="220">
          <template #default="{ row }">
            <span class="cell-main" :title="row.name">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Jumlah Profil" width="130">
          <template #default="{ row }">
            <span class="cell-sub">{{ profileCountLabel(row) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Dibuat" width="150">
          <template #default="{ row }">
            <span class="cell-sub">{{ timestampLabel(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Operasi" width="190" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-button size="small" :icon="DocumentCopy" @click="openCreate(row)">Buat Profil</el-button>
              <el-tooltip content="Hapus template" placement="top" :show-after="200">
                <el-button
                  size="small"
                  class="icon-action danger"
                  :icon="Delete"
                  aria-label="Hapus template"
                  @click="remove(row)"
                />
              </el-tooltip>
            </div>
          </template>
        </el-table-column>

        <template #empty>
          <div class="table-empty">
            <div class="empty-title">Belum ada template</div>
            <p class="empty-text">
              Template menyimpan konfigurasi profil agar profil baru dibuat dengan setting yang sama.
            </p>
            <el-button type="primary" :icon="Plus" @click="openSave">Simpan Template</el-button>
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
        />
      </div>
    </section>

    <el-dialog
      v-model="saveVisible"
      title="Simpan Template"
      width="520px"
      top="12vh"
      class="template-dialog"
      :close-on-click-modal="false"
    >
      <el-form label-width="120px" label-position="right" class="dialog-form" @submit.prevent>
        <el-form-item label="Profil Sumber" required>
          <el-select
            v-model="saveProfileId"
            class="field-full"
            filterable
            :loading="profileLoading"
            placeholder="Cari dan pilih profil"
          >
            <el-option
              v-for="profile in profiles"
              :key="profile.profile_id"
              :label="profile.name"
              :value="profile.profile_id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="Nama Template" required>
          <el-input
            v-model="saveName"
            maxlength="80"
            show-word-limit
            placeholder="mis. Template Jualan Utama"
            @keyup.enter="runSave"
          />
        </el-form-item>
        <p class="form-hint">
          Fingerprint, proxy, preferensi, grup, warna, dan catatan profil sumber ikut tersimpan.
        </p>
      </el-form>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="saveVisible = false">Batal</el-button>
          <div class="footer-spacer"></div>
          <el-button type="primary" :loading="saveBusy" @click="runSave">Simpan</el-button>
        </div>
      </template>
    </el-dialog>

    <el-dialog
      v-model="createVisible"
      :title="title"
      width="440px"
      top="14vh"
      class="template-dialog"
      :close-on-click-modal="false"
    >
      <el-form label-width="100px" label-position="right" class="dialog-form" @submit.prevent>
        <el-form-item label="Nama Profil">
          <el-input
            v-model="createName"
            maxlength="100"
            placeholder="Kosongkan untuk memakai nama bawaan"
            @keyup.enter="runCreate"
          />
        </el-form-item>
        <p class="form-hint">
          Seed profil baru dibuat otomatis, jadi hasil fingerprintnya berbeda dari template.
        </p>
      </el-form>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="createVisible = false">Batal</el-button>
          <div class="footer-spacer"></div>
          <el-button type="primary" :loading="createBusy" @click="runCreate">Buat</el-button>
        </div>
      </template>
    </el-dialog>
  </div>
</template>
