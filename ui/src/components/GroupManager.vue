<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Edit, Plus, Search } from '@element-plus/icons-vue'
import { api } from '../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'changed'])

const groups = ref([])
const totalGroups = ref(0)
const loading = ref(false)
const search = ref('')
const formVisible = ref(false)
const editing = ref(null)
const saving = ref(false)
const nameError = ref('')

const form = reactive({ name: '', sort: 0 })

const filteredGroups = computed(() => {
  const keyword = search.value.trim().toLowerCase()
  if (!keyword) return groups.value
  return groups.value.filter((group) => String(group.title || '').toLowerCase().includes(keyword))
})

const formTitle = computed(() => (editing.value ? 'Edit Grup' : 'Tambah Grup'))

async function load() {
  loading.value = true
  try {
    const result = await api.groups()
    groups.value = result.data || []
    totalGroups.value = result.total ?? groups.value.length
  } catch (error) {
    ElMessage.error(`Gagal memuat grup: ${error.message}`)
  } finally {
    loading.value = false
  }
}

function close() {
  emit('update:modelValue', false)
}

function openCreate() {
  editing.value = null
  form.name = ''
  form.sort = 0
  nameError.value = ''
  formVisible.value = true
}

function openEdit(row) {
  editing.value = row
  form.name = row.title || ''
  form.sort = Number(row.sort) || 0
  nameError.value = ''
  formVisible.value = true
}

async function save() {
  const title = form.name.trim()
  if (!title) {
    nameError.value = 'Nama grup wajib diisi'
    return
  }
  if (title.length > 40) {
    nameError.value = 'Nama grup maksimal 40 karakter'
    return
  }
  saving.value = true
  try {
    const payload = { title, sort: Number(form.sort) || 0 }
    if (editing.value) {
      await api.updateGroup({ id: editing.value.id, ...payload })
      ElMessage.success('Grup diperbarui')
    } else {
      await api.createGroup(payload)
      ElMessage.success('Grup ditambahkan')
    }
    formVisible.value = false
    await load()
    emit('changed')
  } catch (error) {
    ElMessage.error(error.message)
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(
      `Hapus grup "${row.title}"? Grup hanya bisa dihapus jika tidak berisi profil.`,
      'Hapus Grup',
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
    await api.deleteGroup(row.id)
    ElMessage.success(`Grup "${row.title}" dihapus`)
    await load()
    emit('changed')
  } catch (error) {
    ElMessage.error(error.message)
  }
}

function createdLabel(value) {
  if (!value) return '-'
  const [date, time] = String(value).split(' ')
  if (!date) return '-'
  return time ? `${date} ${time.slice(0, 5)}` : date
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      search.value = ''
      load()
    }
  }
)
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="Kelola Grup"
    width="720px"
    top="6vh"
    class="group-manager"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="group-manager-body">
      <div class="group-manager-toolbar">
        <el-input v-model="search" class="search-input group-search" placeholder="Cari nama grup" clearable>
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
        <el-button type="primary" :icon="Plus" @click="openCreate">Tambah Grup</el-button>
      </div>

      <el-table
        v-loading="loading"
        element-loading-text="Memuat grup..."
        class="group-table"
        :data="filteredGroups"
        row-key="id"
        max-height="360"
      >
        <el-table-column label="Nama Grup" min-width="180">
          <template #default="{ row }">
            <span class="cell-main">{{ row.title }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Urutan" width="80">
          <template #default="{ row }">
            <span class="cell-main">{{ row.sort }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Jumlah Profil" width="120">
          <template #default="{ row }">
            <span class="cell-sub">{{ row.profile_count }} profil</span>
          </template>
        </el-table-column>
        <el-table-column label="Dibuat" width="160">
          <template #default="{ row }">
            <span class="cell-sub">{{ createdLabel(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Operasi" width="110" fixed="right">
          <template #default="{ row }">
            <div class="row-actions">
              <el-tooltip content="Edit grup" placement="top" :show-after="200">
                <el-button size="small" class="icon-action" :icon="Edit" aria-label="Edit grup" @click="openEdit(row)" />
              </el-tooltip>
              <el-tooltip content="Grup Default tidak bisa dihapus" placement="top" :show-after="200">
                <span class="group-delete-wrap">
                  <el-button
                    size="small"
                    class="icon-action danger"
                    :icon="Delete"
                    aria-label="Hapus grup"
                    :disabled="row.id === 1"
                    @click="remove(row)"
                  />
                </span>
              </el-tooltip>
            </div>
          </template>
        </el-table-column>

        <template #empty>
          <el-empty description="Belum ada grup" :image-size="72" />
        </template>
      </el-table>

      <div class="group-manager-footer">Total {{ totalGroups }} grup</div>
    </div>

    <el-dialog
      v-model="formVisible"
      :title="formTitle"
      width="420px"
      append-to-body
      class="group-form-dialog"
      :close-on-click-modal="false"
    >
      <el-form label-width="96px" label-position="right" class="dialog-form group-form" @submit.prevent="save">
        <el-form-item label="Nama Grup" required :error="nameError">
          <el-input
            v-model="form.name"
            maxlength="40"
            placeholder="cth: Toko Utama"
            @input="nameError = ''"
          />
        </el-form-item>
        <el-form-item label="Urutan">
          <div>
            <el-input-number v-model="form.sort" :step="1" :precision="0" controls-position="right" class="field-180" />
            <p class="form-hint">Angka lebih besar tampil lebih dahulu.</p>
          </div>
        </el-form-item>
      </el-form>

      <template #footer>
        <div class="dialog-footer">
          <el-button @click="formVisible = false">Batal</el-button>
          <div class="footer-spacer"></div>
          <el-button type="primary" :loading="saving" @click="save">Simpan</el-button>
        </div>
      </template>
    </el-dialog>
  </el-dialog>
</template>
