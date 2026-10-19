<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { DocumentCopy, Download, Refresh, Upload } from '@element-plus/icons-vue'
import { api } from '../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  profile: { type: Object, default: null },
  profileOpen: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue'])

const text = ref('')
const loading = ref(false)
const saving = ref(false)
const errorText = ref('')
const fileInput = ref(null)

const title = computed(() => `Cookie: ${props.profile?.name || ''}`)
const fileName = computed(() => {
  const name = String(props.profile?.name || 'profil').replace(/[\\/:*?"<>|]/g, '-')
  return `${name}-cookies.json`
})

const parsed = computed(() => {
  const raw = text.value.trim()
  if (!raw) return { items: [], error: '' }
  try {
    const data = JSON.parse(raw)
    const items = Array.isArray(data) ? data : data?.cookies
    if (!Array.isArray(items)) return { items: [], error: 'JSON harus berupa list cookie' }
    return { items, error: '' }
  } catch {
    return { items: [], error: 'JSON belum valid' }
  }
})

const cookieCount = computed(() => parsed.value.items.length)
const domainCount = computed(
  () => new Set(parsed.value.items.map((item) => item?.domain).filter(Boolean)).size
)

async function load() {
  if (!props.profile) return
  loading.value = true
  errorText.value = ''
  try {
    const result = await api.getCookies(props.profile.profile_id)
    text.value = typeof result === 'string' ? result : JSON.stringify(result || [])
    if (text.value.trim() === '[]') text.value = ''
  } catch (error) {
    text.value = ''
    errorText.value = error.message
  } finally {
    loading.value = false
  }
}

function triggerFile() {
  fileInput.value?.click()
}

async function onFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  try {
    text.value = (await file.text()).trim()
    errorText.value = ''
  } catch (error) {
    errorText.value = `Gagal membaca file: ${error.message}`
  }
}

async function copy() {
  try {
    await navigator.clipboard.writeText(text.value)
    ElMessage.success('Cookie disalin')
  } catch (error) {
    ElMessage.error(`Gagal menyalin: ${error.message}`)
  }
}

function download() {
  const blob = new Blob([text.value.trim() || '[]'], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName.value
  link.click()
  URL.revokeObjectURL(url)
  ElMessage.success('File cookie diunduh')
}

function close() {
  emit('update:modelValue', false)
}

async function save() {
  if (!props.profile || props.profileOpen) return
  const raw = text.value.trim()
  if (raw) {
    let data
    try {
      data = JSON.parse(raw)
    } catch {
      errorText.value = 'JSON belum valid'
      return
    }
    const items = Array.isArray(data) ? data : data?.cookies
    if (!Array.isArray(items)) {
      errorText.value = 'JSON harus berupa list cookie'
      return
    }
    const invalid = items.findIndex(
      (item) => !item || !String(item.domain || '').trim() || !String(item.name || '').trim()
    )
    if (invalid >= 0) {
      errorText.value = `Cookie ke-${invalid + 1} wajib punya domain dan name`
      return
    }
  }
  saving.value = true
  errorText.value = ''
  try {
    await api.updateCookies(props.profile.profile_id, raw)
    ElMessage.success(`Cookie profil "${props.profile.name}" disimpan`)
    close()
  } catch (error) {
    errorText.value = error.message
    ElMessage.error(`Gagal menyimpan cookie: ${error.message}`)
  } finally {
    saving.value = false
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      text.value = ''
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
    width="760px"
    top="5vh"
    class="cookie-dialog"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="cookie-body">
      <el-alert
        v-if="profileOpen"
        class="cookie-alert"
        type="warning"
        :closable="false"
        show-icon
        title="Tutup profil dulu"
        description="Cookie hanya bisa diubah saat profil tertutup."
      />
      <el-alert
        v-if="errorText"
        class="cookie-alert"
        type="error"
        :closable="false"
        show-icon
        :title="errorText"
      />

      <div class="cookie-toolbar">
        <el-button :icon="Refresh" :loading="loading" @click="load">Muat Cookie</el-button>
        <el-button :icon="Upload" @click="triggerFile">Impor dari File</el-button>
        <input
          ref="fileInput"
          type="file"
          accept=".json,.txt,application/json,text/plain"
          class="cookie-file-input"
          @change="onFile"
        />
        <el-button :icon="DocumentCopy" @click="copy">Salin</el-button>
        <el-button :icon="Download" @click="download">Unduh</el-button>
      </div>

      <div class="cookie-meta">
        <span><strong>{{ cookieCount }}</strong> cookie</span>
        <span class="cookie-meta-sep">/</span>
        <span><strong>{{ domainCount }}</strong> domain</span>
        <span v-if="parsed.error" class="cookie-meta-error">{{ parsed.error }}</span>
        <span v-else class="cookie-meta-hint">Kosongkan lalu simpan untuk menghapus semua cookie.</span>
      </div>

      <el-input
        v-model="text"
        type="textarea"
        :rows="16"
        class="cookie-editor"
        spellcheck="false"
        placeholder='[{"domain":"example.com","name":"sesi","value":"..."}]'
      />
    </div>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="close">Batal</el-button>
        <div class="footer-spacer"></div>
        <el-button type="primary" :loading="saving" :disabled="profileOpen" @click="save">
          Simpan Cookie
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>
