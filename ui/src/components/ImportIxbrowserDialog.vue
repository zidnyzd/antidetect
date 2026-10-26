<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Close, Search, Upload } from '@element-plus/icons-vue'
import { api } from '../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'imported'])

const MAX_ZIP_BYTES = 50 * 1024 * 1024

const cookieInput = ref(null)
const metadataInput = ref(null)
const cookieFile = ref(null)
const metadataFile = ref(null)
const cookieFileName = ref('')
const metadataFileName = ref('')
const cookieBase64 = ref('')
const metadataBase64 = ref('')
const updateExisting = ref(false)
const previewBusy = ref(false)
const importBusy = ref(false)
const previewResult = ref(null)
const importResult = ref(null)

const previewErrors = computed(() => previewResult.value?.errors || [])
const previewErrorSlice = computed(() => previewErrors.value.slice(0, 10))
const duplicateNames = computed(() => previewResult.value?.duplicate_names || [])
const existingNames = computed(() => previewResult.value?.existing_names || [])
const existingNameSlice = computed(() => existingNames.value.slice(0, 10))
const groupCount = computed(() => Object.keys(previewResult.value?.groups || {}).length)

const importErrors = computed(() => importResult.value?.errors || [])
const importErrorSlice = computed(() => importErrors.value.slice(0, 10))

function resetState() {
  cookieFile.value = null
  metadataFile.value = null
  cookieFileName.value = ''
  metadataFileName.value = ''
  cookieBase64.value = ''
  metadataBase64.value = ''
  updateExisting.value = false
  previewBusy.value = false
  importBusy.value = false
  previewResult.value = null
  importResult.value = null
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) resetState()
  }
)

function close() {
  emit('update:modelValue', false)
}

function chooseCookieZip() {
  cookieInput.value?.click()
}

function chooseMetadataZip() {
  metadataInput.value?.click()
}

function clearCookieZip() {
  cookieFile.value = null
  cookieFileName.value = ''
  cookieBase64.value = ''
  previewResult.value = null
  importResult.value = null
}

function clearMetadataZip() {
  metadataFile.value = null
  metadataFileName.value = ''
  metadataBase64.value = ''
  previewResult.value = null
  importResult.value = null
}

function onCookieFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  if (file.size > MAX_ZIP_BYTES) {
    ElMessage.error('Ukuran file ZIP maksimal 50 MB')
    return
  }
  cookieFile.value = file
  cookieFileName.value = file.name
  cookieBase64.value = ''
  previewResult.value = null
  importResult.value = null
}

function onMetadataFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  if (file.size > MAX_ZIP_BYTES) {
    ElMessage.error('Ukuran file ZIP maksimal 50 MB')
    return
  }
  metadataFile.value = file
  metadataFileName.value = file.name
  metadataBase64.value = ''
  previewResult.value = null
  importResult.value = null
}

function readZipBase64(file) {
  return new Promise((resolve, reject) => {
    if (!file) {
      reject(new Error('File belum dipilih'))
      return
    }
    if (file.size > MAX_ZIP_BYTES) {
      reject(new Error('Ukuran file ZIP maksimal 50 MB'))
      return
    }
    const reader = new FileReader()
    reader.onload = () => {
      const raw = String(reader.result || '')
      const comma = raw.indexOf(',')
      resolve(comma >= 0 ? raw.slice(comma + 1) : raw)
    }
    reader.onerror = () => {
      reader.abort()
      reject(new Error('File ZIP tidak bisa dibaca'))
    }
    reader.readAsDataURL(file)
  })
}

async function runPreview() {
  if (!cookieFile.value || previewBusy.value || importBusy.value) return
  if (cookieFile.value.size > MAX_ZIP_BYTES) {
    ElMessage.error('Ukuran file ZIP maksimal 50 MB')
    return
  }
  if (metadataFile.value && metadataFile.value.size > MAX_ZIP_BYTES) {
    ElMessage.error('Ukuran file ZIP maksimal 50 MB')
    return
  }
  previewBusy.value = true
  try {
    const content = await readZipBase64(cookieFile.value)
    const metaContent = metadataFile.value ? await readZipBase64(metadataFile.value) : ''
    cookieBase64.value = content
    metadataBase64.value = metaContent
    const payload = {
      content_base64: content,
      filename: cookieFile.value.name,
      dry_run: true,
    }
    if (metaContent) {
      payload.metadata_base64 = metaContent
    }
    const data = await api.importIxbrowser(payload)
    previewResult.value = data
    importResult.value = null
  } catch (error) {
    previewResult.value = null
    ElMessage.error(`Gagal memuat pratinjau: ${error.message}`)
  } finally {
    previewBusy.value = false
  }
}

async function runImport() {
  if (!previewResult.value || !cookieBase64.value || previewBusy.value || importBusy.value) return
  importBusy.value = true
  try {
    const payload = {
      content_base64: cookieBase64.value,
      filename: cookieFileName.value || undefined,
      dry_run: false,
      update_existing: updateExisting.value,
    }
    if (metadataBase64.value) {
      payload.metadata_base64 = metadataBase64.value
    }
    const data = await api.importIxbrowser(payload)
    importResult.value = data
    emit('imported', data)
  } catch (error) {
    ElMessage.error(`Gagal mengimpor ixBrowser: ${error.message}`)
  } finally {
    importBusy.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="Impor ixBrowser"
    width="720px"
    top="8vh"
    class="csv-import-dialog proxy-import-dialog"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="csv-intro">
      <p>
        Unggah ZIP cookie wajib, ZIP metadata opsional (<span class="mono">Export Profile.zip</span>)
        untuk grup, catatan, dan UA. Batas 50 MB per file.
      </p>
    </div>

    <div class="ixb-file-list">
      <div class="csv-actions ixb-file-row">
        <el-button :icon="Upload" @click="chooseCookieZip">Pilih ZIP Cookie</el-button>
        <input
          ref="cookieInput"
          class="profile-file-input"
          type="file"
          accept=".zip,application/zip"
          @change="onCookieFile"
        />
        <template v-if="cookieFileName">
          <span class="csv-file-name mono">{{ cookieFileName }}</span>
          <el-button
            link
            size="small"
            :icon="Close"
            aria-label="Hapus pilihan ZIP Cookie"
            @click="clearCookieZip"
          >
            Hapus
          </el-button>
        </template>
        <span v-else class="form-hint">Wajib (.zip). Belum ada file dipilih.</span>
      </div>

      <div class="csv-actions ixb-file-row">
        <el-button :icon="Upload" @click="chooseMetadataZip">Pilih ZIP Metadata</el-button>
        <input
          ref="metadataInput"
          class="profile-file-input"
          type="file"
          accept=".zip,application/zip"
          @change="onMetadataFile"
        />
        <template v-if="metadataFileName">
          <span class="csv-file-name mono">{{ metadataFileName }}</span>
          <el-button
            link
            size="small"
            :icon="Close"
            aria-label="Hapus pilihan ZIP Metadata"
            @click="clearMetadataZip"
          >
            Hapus
          </el-button>
        </template>
        <span v-else class="form-hint">Opsional (.zip, berisi excel.xlsx).</span>
      </div>

      <div class="csv-actions ixb-preview-row">
        <el-button
          :icon="Search"
          :loading="previewBusy"
          :disabled="!cookieFile || importBusy"
          @click="runPreview"
        >
          Pratinjau
        </el-button>
        <el-checkbox v-model="updateExisting" :disabled="!!importResult">
          Perbarui cookie pada profil yang namanya sudah ada
        </el-checkbox>
      </div>
    </div>

    <div v-if="previewResult && !importResult" class="import-result">
      <div class="import-summary ixb-summary">
        <span><strong>{{ previewResult.total }}</strong> profil</span>
        <span><strong>{{ previewResult.cookies }}</strong> cookie</span>
        <span><strong>{{ groupCount }}</strong> grup</span>
        <span><strong>{{ previewResult.empty_cookie_files }}</strong> file cookie kosong</span>
        <span><strong>{{ previewErrors.length }}</strong> error</span>
        <span>
          Metadata: <strong>{{ previewResult.metadata ? 'Ditemukan' : 'Tidak ditemukan' }}</strong>
        </span>
      </div>

      <div v-if="duplicateNames.length" class="import-errors import-skipped">
        <div class="import-errors-title">Judul duplikat ({{ duplicateNames.length }})</div>
        <ul>
          <li v-for="name in duplicateNames" :key="name">
            <span class="mono">{{ name }}</span>
          </li>
        </ul>
      </div>

      <div v-if="existingNames.length" class="import-errors import-skipped">
        <div class="import-errors-title">
          Nama yang sudah ada di database ({{ existingNames.length }})
        </div>
        <ul>
          <li v-for="name in existingNameSlice" :key="name">
            <span class="mono">{{ name }}</span>
          </li>
        </ul>
        <p v-if="existingNames.length > 10" class="form-hint">
          {{ existingNames.length - 10 }} nama lain tidak ditampilkan.
        </p>
      </div>

      <div v-if="previewErrors.length" class="import-errors">
        <div class="import-errors-title">Masalah pada arsip</div>
        <ul>
          <li v-for="(item, index) in previewErrorSlice" :key="`${item.file}-${index}`">
            <span class="mono">{{ item.file }}</span>
            <span>{{ item.reason }}</span>
          </li>
        </ul>
        <p v-if="previewErrors.length > 10" class="form-hint">
          {{ previewErrors.length - 10 }} error lain tidak ditampilkan.
        </p>
      </div>
    </div>

    <div v-if="importResult" class="import-result">
      <div class="import-summary ixb-summary">
        <span><strong>{{ importResult.created }}</strong> dibuat</span>
        <span><strong>{{ importResult.updated }}</strong> diperbarui</span>
        <span><strong>{{ importResult.skipped }}</strong> dilewati</span>
        <span><strong>{{ importResult.cookies }}</strong> cookie</span>
        <span><strong>{{ importResult.groups_created }}</strong> grup baru</span>
        <span><strong>{{ importErrors.length }}</strong> error</span>
      </div>

      <div v-if="importErrors.length" class="import-errors">
        <div class="import-errors-title">Detail masalah</div>
        <ul>
          <li v-for="(item, index) in importErrorSlice" :key="`${item.file}-${index}`">
            <span class="mono">{{ item.file }}</span>
            <span>{{ item.reason }}</span>
          </li>
        </ul>
        <p v-if="importErrors.length > 10" class="form-hint">
          {{ importErrors.length - 10 }} error lain tidak ditampilkan.
        </p>
      </div>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="close">{{ importResult ? 'Tutup' : 'Batal' }}</el-button>
        <div class="footer-spacer"></div>
        <el-button
          v-if="!importResult"
          type="primary"
          :loading="importBusy"
          :disabled="!previewResult || previewBusy"
          @click="runImport"
        >
          Impor
        </el-button>
        <el-button v-else type="primary" @click="close">Selesai</el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.ixb-file-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin: 12px 0 14px;
}

.ixb-file-row,
.ixb-preview-row {
  margin: 0;
}

.ixb-summary {
  flex-wrap: wrap;
  row-gap: 6px;
}
</style>
