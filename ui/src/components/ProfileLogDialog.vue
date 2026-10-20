<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { DocumentCopy, Download, Refresh } from '@element-plus/icons-vue'
import { api } from '../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  profile: { type: Object, default: null },
  kind: { type: String, default: 'chrome' },
})
const emit = defineEmits(['update:modelValue'])

const log = ref(null)
const loading = ref(false)
const errorText = ref('')
const preRef = ref(null)

const kindLabel = computed(() => (props.kind === 'gost' ? 'Proxy' : 'Chrome'))
const title = computed(() => `Log ${kindLabel.value}: ${props.profile?.name || ''}`)
const exists = computed(() => !!log.value?.exists)
const content = computed(() => log.value?.content || '')
const truncated = computed(() => !!log.value?.truncated)
const fileName = computed(() => {
  const name = String(props.profile?.name || 'profil').replace(/[\\/:*?"<>|]/g, '-')
  return `${name}-${props.kind}.log`
})

function formatSize(bytes) {
  const size = Number(bytes || 0)
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(2)} MB`
}

function scrollToEnd() {
  const area = preRef.value
  if (area) area.scrollTop = area.scrollHeight
}

async function load() {
  if (!props.profile) return
  loading.value = true
  errorText.value = ''
  try {
    log.value = await api.profileLogs(props.profile.profile_id, props.kind)
    await nextTick()
    requestAnimationFrame(scrollToEnd)
  } catch (error) {
    log.value = null
    errorText.value = error.message
  } finally {
    loading.value = false
  }
}

async function copy() {
  if (!content.value) {
    ElMessage.info('Isi log kosong')
    return
  }
  try {
    await navigator.clipboard.writeText(content.value)
    ElMessage.success('Isi log disalin')
  } catch {
    const area = document.createElement('textarea')
    area.value = content.value
    area.setAttribute('readonly', '')
    area.style.position = 'fixed'
    area.style.opacity = '0'
    document.body.appendChild(area)
    area.select()
    const copied = document.execCommand('copy')
    area.remove()
    if (copied) ElMessage.success('Isi log disalin')
    else ElMessage.error('Gagal menyalin log')
  }
}

function download() {
  if (!exists.value) return
  const blob = new Blob([content.value], { type: 'text/plain;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName.value
  link.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
  ElMessage.success('File log diunduh')
}

function close() {
  emit('update:modelValue', false)
}

watch(
  () => [props.modelValue, props.kind, props.profile?.profile_id],
  ([open]) => {
    if (open) load()
  }
)

watch(
  () => props.modelValue,
  (open) => {
    if (!open) {
      log.value = null
      errorText.value = ''
    }
  }
)
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="860px"
    top="6vh"
    class="profile-log-dialog"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="profile-log-body" v-loading="loading" element-loading-text="Membaca log...">
      <el-alert
        v-if="errorText"
        class="profile-log-alert"
        type="error"
        :closable="false"
        show-icon
        :title="errorText"
      />

      <div class="profile-log-toolbar">
        <el-button :icon="Refresh" :loading="loading" @click="load">Muat ulang</el-button>
        <el-button :icon="DocumentCopy" :disabled="!exists || !content" @click="copy">Salin</el-button>
        <el-button v-if="exists" :icon="Download" @click="download">Unduh</el-button>
      </div>

      <div v-if="log" class="profile-log-meta">
        <span><strong>{{ formatSize(log.size) }}</strong></span>
        <span><strong>{{ log.lines }}</strong> baris</span>
        <span v-if="truncated" class="profile-log-truncated">Menampilkan bagian terakhir saja</span>
        <span v-else-if="exists" class="profile-log-complete">Isi lengkap</span>
        <span class="profile-log-path" :title="log.path">{{ log.path }}</span>
      </div>

      <pre
        v-if="exists"
        ref="preRef"
        class="profile-log-content"
      >{{ content || 'File log kosong.' }}</pre>
      <div v-else-if="!loading && !errorText" class="profile-log-empty">
        <div class="profile-log-empty-title">File log belum ada</div>
        <p class="profile-log-empty-text">
          File ini dibuat saat profil dibuka. Buka profil lalu muat ulang dialog.
        </p>
      </div>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <div class="footer-spacer"></div>
        <el-button @click="close">Tutup</el-button>
      </div>
    </template>
  </el-dialog>
</template>
