<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Download, Upload } from '@element-plus/icons-vue'
import { api } from '../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'imported'])

const TEMPLATE_COLUMNS = [
  'name',
  'group',
  'note',
  'platform',
  'system_version',
  'proxy_type',
  'proxy_ip',
  'proxy_port',
  'proxy_user',
  'proxy_password',
  'site_url',
]
const TEMPLATE_ROW = [
  'Contoh Profil',
  'Contoh Grup',
  'Contoh catatan',
  'Windows',
  '11',
  'direct',
  '',
  '',
  '',
  '',
  'https://example.com',
]
const MAX_BYTES = 1024 * 1024

const fileInput = ref(null)
const fileName = ref('')
const fileText = ref('')
const busy = ref(false)
const result = ref(null)
const errors = computed(() => result.value?.errors || [])
const errorPreview = computed(() => errors.value.slice(0, 10))

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      fileName.value = ''
      fileText.value = ''
      result.value = null
      busy.value = false
    }
  }
)

function close() {
  emit('update:modelValue', false)
}

function csvCell(value) {
  const text = String(value ?? '')
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text
}

function downloadTemplate() {
  const content = [TEMPLATE_COLUMNS, TEMPLATE_ROW]
    .map((row) => row.map(csvCell).join(','))
    .join('\r\n')
  const blob = new Blob([`\ufeff${content}\r\n`], { type: 'text/csv;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = 'template-profil.csv'
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function chooseFile() {
  fileInput.value?.click()
}

async function onFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  if (file.size > MAX_BYTES) {
    ElMessage.error('Ukuran file CSV maksimal 1 MB')
    return
  }
  try {
    fileText.value = await file.text()
    fileName.value = file.name
    result.value = null
  } catch {
    ElMessage.error('File CSV tidak bisa dibaca')
  }
}

async function runImport() {
  if (!fileText.value || busy.value) return
  busy.value = true
  try {
    const data = await api.importCsv(fileText.value)
    result.value = data
    emit('imported', data)
  } catch (error) {
    ElMessage.error(`Gagal mengimpor CSV: ${error.message}`)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="Impor Profil CSV"
    width="720px"
    top="8vh"
    class="csv-import-dialog"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="csv-intro">
      <p>
        Satu baris CSV menjadi satu profil. Kolom yang dibaca:
        <span class="mono">name, group, note, platform, system_version, proxy_type, proxy_ip, proxy_port, proxy_user, proxy_password, site_url</span>.
        Kolom lain diabaikan.
      </p>
      <p class="form-hint">Maksimal 1 MB dan 500 baris data. Header wajib memuat kolom name.</p>
    </div>

    <div class="csv-actions">
      <el-button :icon="Download" @click="downloadTemplate">Unduh Template</el-button>
      <el-button :icon="Upload" @click="chooseFile">Pilih File CSV</el-button>
      <input
        ref="fileInput"
        class="profile-file-input csv-file-input"
        type="file"
        accept=".csv,text/csv"
        @change="onFile"
      />
      <span v-if="fileName" class="csv-file-name mono">{{ fileName }}</span>
      <span v-else class="form-hint">Belum ada file dipilih.</span>
    </div>

    <div v-if="result" class="import-result">
      <div class="import-summary">
        <span><strong>{{ result.created }}</strong> profil dibuat</span>
        <span><strong>{{ result.groups_created }}</strong> grup baru</span>
        <span><strong>{{ result.proxies_created }}</strong> proxy baru</span>
        <span><strong>{{ errors.length }}</strong> error</span>
      </div>
      <div v-if="errors.length" class="import-errors">
        <div class="import-errors-title">Baris yang gagal</div>
        <ul>
          <li v-for="item in errorPreview" :key="item.line">
            <span class="mono">baris {{ item.line }}</span>
            <span>{{ item.message }}</span>
          </li>
        </ul>
        <p v-if="errors.length > 10" class="form-hint">
          {{ errors.length - 10 }} error lain tidak ditampilkan.
        </p>
      </div>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="close">{{ result ? 'Tutup' : 'Batal' }}</el-button>
        <div class="footer-spacer"></div>
        <el-button
          v-if="!result"
          type="primary"
          :loading="busy"
          :disabled="!fileText"
          @click="runImport"
        >
          Impor
        </el-button>
        <el-button v-else type="primary" @click="close">Selesai</el-button>
      </div>
    </template>
  </el-dialog>
</template>
