<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  profile: { type: Object, default: null },
  groups: { type: Array, default: () => [] },
  tags: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'saved', 'tags-changed'])

const COLORS = ['#2f6fed', '#16a34a', '#f59e0b', '#d92d20', '#a855f7', '#14b8a6', '#e879f9', '#64748b']
const TIMEZONES = [
  'UTC',
  'Asia/Jakarta',
  'Asia/Pontianak',
  'Asia/Makassar',
  'Asia/Jayapura',
  'Asia/Singapore',
  'Asia/Kuala_Lumpur',
  'Asia/Bangkok',
  'Asia/Ho_Chi_Minh',
  'Asia/Manila',
  'Asia/Shanghai',
  'Asia/Hong_Kong',
  'Asia/Taipei',
  'Asia/Tokyo',
  'Asia/Seoul',
  'Asia/Kolkata',
  'Asia/Karachi',
  'Asia/Dubai',
  'Asia/Riyadh',
  'Asia/Tehran',
  'Australia/Perth',
  'Australia/Sydney',
  'Pacific/Auckland',
  'Pacific/Honolulu',
  'Europe/London',
  'Europe/Dublin',
  'Europe/Paris',
  'Europe/Berlin',
  'Europe/Amsterdam',
  'Europe/Madrid',
  'Europe/Rome',
  'Europe/Warsaw',
  'Europe/Istanbul',
  'Europe/Moscow',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Toronto',
  'America/Mexico_City',
  'America/Sao_Paulo',
  'Africa/Cairo',
  'Africa/Lagos',
  'Africa/Johannesburg',
]
const LANGUAGES = [
  'id-ID',
  'en-US',
  'en-GB',
  'en-AU',
  'en-CA',
  'zh-CN',
  'zh-TW',
  'ja-JP',
  'ko-KR',
  'th-TH',
  'vi-VN',
  'ms-MY',
  'fil-PH',
  'hi-IN',
  'es-ES',
  'es-MX',
  'pt-BR',
  'pt-PT',
  'fr-FR',
  'de-DE',
  'it-IT',
  'nl-NL',
  'pl-PL',
  'ru-RU',
  'tr-TR',
  'ar-SA',
  'he-IL',
  'fa-IR',
]
const CPU_CORES = [2, 4, 6, 8, 12, 16]
const MEMORY = [2, 4, 8]
const WINDOWS_VERSIONS = ['11', '10', '8.1', '7']
const MACOS_VERSIONS = ['14', '13', '12']
const GPU_VENDORS = [
  'Google Inc. (NVIDIA)',
  'Google Inc. (Intel)',
  'Google Inc. (AMD)',
  'Google Inc. (Apple)',
]
const CUSTOM_SITE_ID = 22
const ACCOUNT_PRESETS = [
  { key: 'Facebook', site_id: 1, site_url: 'https://www.facebook.com/' },
  { key: 'TikTok', site_id: 2, site_url: 'https://www.tiktok.com/' },
  { key: 'Instagram', site_id: 3, site_url: 'https://www.instagram.com/' },
  { key: 'Shopee', site_id: 4, site_url: 'https://shopee.co.id/' },
  { key: 'Tokopedia', site_id: 5, site_url: 'https://www.tokopedia.com/' },
  { key: 'Google', site_id: 6, site_url: 'https://www.google.com/' },
  { key: 'Lazada', site_id: 7, site_url: 'https://www.lazada.co.id/' },
]

const activeTab = ref('account')
const busy = ref(false)
const seedBusy = ref(false)
const seedOverride = ref(null)
const kernels = ref([])
const kernelPath = ref('')
const kernelError = ref('')
const kernelSavedMissing = ref(false)
const savedProxies = ref([])
const savedProxyId = ref(null)
const extensionOptions = ref([])
const extensionsLoading = ref(false)
const proxyCheck = reactive({ loading: false, ok: null, text: '' })
const errors = reactive({ name: '', group_id: '', proxy_ip: '', proxy_port: '', site_url: '' })

let initialPayload = null

function emptyForm() {
  return {
    name: '',
    group_id: props.groups[0]?.id ?? 1,
    tag_id: [],
    color: COLORS[0],
    note: '',
    site_id: CUSTOM_SITE_ID,
    account_preset: 'Custom',
    site_url: '',
    proxy_type: 'direct',
    proxy_ip: '',
    proxy_port: null,
    proxy_user: '',
    proxy_password: '',
    platform: 'Windows',
    system_version: '11',
    hardware_concurrency: 8,
    device_memory: 8,
    gpu_vendor: '',
    gpu_renderer: '',
    disable_gpu_fingerprint: false,
    timezone: 'Asia/Jakarta',
    language: 'id-ID',
    extension_ids: [],
  }
}

const form = reactive(emptyForm())

const isEdit = computed(() => !!props.profile)
const title = computed(() => (isEdit.value ? 'Edit Profil' : 'Buat Profil'))
const colorOptions = computed(() => {
  const colors = [...COLORS]
  const custom = props.profile?.color
  if (custom && !colors.includes(custom)) colors.push(custom)
  return colors
})
const versionOptions = computed(() =>
  form.platform === 'Macos' ? MACOS_VERSIONS : WINDOWS_VERSIONS
)
const versionLabel = computed(() => (form.platform === 'Macos' ? 'Versi macOS' : 'Versi Windows'))
const savedProxyPlaceholder = computed(() =>
  savedProxies.value.length ? 'Manual / isi sendiri' : 'Belum ada proxy tersimpan'
)
const displaySeed = computed(() => seedOverride.value ?? props.profile?.seed ?? null)
const seedText = computed(() => {
  if (!isEdit.value) return 'Seed dibuat saat disimpan'
  return displaySeed.value == null ? 'Seed belum terbaca' : String(displaySeed.value)
})
const builtinKernelPath = computed(() => {
  const list = kernels.value
  const builtin = list.find((kernel) => kernel.builtin) || list.find((kernel) => kernel.active) || list[0]
  return builtin?.path || ''
})
const selectedKernel = computed(
  () => kernels.value.find((kernel) => kernel.path === kernelPath.value) || null
)
const gpuSupport = computed(() => selectedKernel.value?.supports || null)
const gpuFieldHint = computed(() => {
  const support = gpuSupport.value
  if (!support) return ''
  if (!form.gpu_vendor && !form.gpu_renderer) return ''
  const missing = []
  if (!support.gpu_vendor) missing.push('GPU Vendor')
  if (!support.gpu_renderer) missing.push('GPU Renderer')
  if (!missing.length) return ''
  return `Kernel terpilih belum mendukung ${missing.join(' dan ')}, nilainya disimpan tapi tidak diterapkan engine.`
})
const gpuSwitchHint = computed(() => {
  const support = gpuSupport.value
  if (!support) return ''
  if (support.disable_gpu_fingerprint) return 'Jika diaktifkan, kernel memakai --disable-gpu-fingerprint.'
  if (support.disable_spoofing) {
    return 'Jika diaktifkan, kernel memakai --disable-spoofing=gpu: situs membaca GPU asli host.'
  }
  return 'Kernel terpilih tidak punya cara mematikan spoofing GPU.'
})

function proxyTypeValue(raw) {
  const value = String(raw || 'direct').toLowerCase()
  return ['http', 'https', 'socks5'].includes(value) ? value : 'direct'
}

function hostOf(value) {
  try {
    const parsed = new URL(String(value || ''))
    return parsed.hostname.replace(/^www\./, '').toLowerCase()
  } catch {
    return ''
  }
}

function presetFor(siteId, siteUrl) {
  const id = Number(siteId)
  const host = hostOf(siteUrl)
  const byId = ACCOUNT_PRESETS.find((preset) => preset.site_id === id)
  if (byId && (!host || host === hostOf(byId.site_url))) return byId.key
  if (host) {
    const byUrl = ACCOUNT_PRESETS.find((preset) => hostOf(preset.site_url) === host)
    if (byUrl) return byUrl.key
  }
  return 'Custom'
}

function applyAccountPreset(key) {
  const preset = ACCOUNT_PRESETS.find((item) => item.key === key)
  if (!preset) {
    form.site_id = CUSTOM_SITE_ID
    return
  }
  form.site_id = preset.site_id
  form.site_url = preset.site_url
  errors.site_url = ''
}

function fillFromProfile(profile) {
  const fingerprint = profile.fingerprint_config || {}
  const proxy = profile.proxy_config || {}
  form.name = profile.name || ''
  form.group_id = profile.group_id ?? form.group_id
  form.tag_id = Array.isArray(profile.tab_id) ? [...profile.tab_id] : []
  form.color = profile.color || COLORS[0]
  form.note = profile.note || ''
  form.site_id = profile.site_id ?? CUSTOM_SITE_ID
  form.site_url = profile.site_url || ''
  form.account_preset = presetFor(form.site_id, form.site_url)
  form.proxy_type = proxyTypeValue(proxy.proxy_type)
  form.proxy_ip = proxy.proxy_ip || ''
  form.proxy_port = proxy.proxy_port ?? null
  form.proxy_user = proxy.proxy_user || ''
  form.proxy_password = proxy.proxy_password || ''
  form.platform = fingerprint.platform === 'Macos' ? 'Macos' : 'Windows'
  const versions = form.platform === 'Macos' ? MACOS_VERSIONS : WINDOWS_VERSIONS
  form.system_version = versions.includes(String(fingerprint.system_version))
    ? String(fingerprint.system_version)
    : versions[0]
  form.hardware_concurrency = CPU_CORES.includes(Number(fingerprint.hardware_concurrency))
    ? Number(fingerprint.hardware_concurrency)
    : 8
  form.device_memory = MEMORY.includes(Number(fingerprint.device_memory)) ? Number(fingerprint.device_memory) : 8
  form.gpu_vendor = String(fingerprint.gpu_vendor || '')
  form.gpu_renderer = String(fingerprint.gpu_renderer || '')
  form.disable_gpu_fingerprint = !!fingerprint.disable_gpu_fingerprint
  form.timezone = fingerprint.timezone || 'Asia/Jakarta'
  form.language = fingerprint.language || 'id-ID'
  const preference = profile.preference_config || {}
  const extensionIds = preference.extension_ids
  form.extension_ids = Array.isArray(extensionIds)
    ? extensionIds.map((id) => Number(id)).filter((id) => Number.isInteger(id))
    : []
  kernelPath.value = String(preference.kernel_path || '')
}

function kernelLabel(kernel) {
  return `${kernel.name} · ${kernel.version || 'versi tidak terbaca'}`
}

function syncKernelPath() {
  if (!kernels.value.length) return
  const saved = kernelPath.value
  const available = kernels.value.some((kernel) => kernel.path === saved)
  kernelSavedMissing.value = !!saved && !available && saved !== builtinKernelPath.value
  if (!available) kernelPath.value = builtinKernelPath.value
}

function clearErrors() {
  for (const key of Object.keys(errors)) errors[key] = ''
}

function resetForm() {
  Object.assign(form, emptyForm())
  savedProxyId.value = null
  seedOverride.value = null
  kernelPath.value = ''
  kernelSavedMissing.value = false
  proxyCheck.loading = false
  proxyCheck.ok = null
  proxyCheck.text = ''
  clearErrors()
  activeTab.value = 'account'
  if (props.profile) fillFromProfile(props.profile)
  syncKernelPath()
  initialPayload = props.profile ? formPayload() : null
}

async function loadSavedProxies() {
  try {
    const result = await api.proxies({ limit: 100 })
    savedProxies.value = result.data || []
  } catch (error) {
    savedProxies.value = []
    ElMessage.error(`Gagal memuat proxy tersimpan: ${error.message}`)
  }
}

async function loadExtensions() {
  extensionsLoading.value = true
  try {
    const result = await api.extensions({ page: 1, limit: 200 })
    extensionOptions.value = result.data || []
  } catch (error) {
    extensionOptions.value = []
    ElMessage.error(`Gagal memuat extension: ${error.message}`)
  } finally {
    extensionsLoading.value = false
  }
}

async function loadKernels() {
  kernelError.value = ''
  try {
    const result = await api.engineInfo()
    kernels.value = Array.isArray(result?.kernels) ? result.kernels : []
  } catch (error) {
    kernels.value = []
    kernelError.value = error.message
  }
  syncKernelPath()
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      resetForm()
      loadSavedProxies()
      loadExtensions()
      loadKernels()
    }
  }
)

watch(
  () => form.platform,
  (platform) => {
    const versions = platform === 'Macos' ? MACOS_VERSIONS : WINDOWS_VERSIONS
    if (!versions.includes(form.system_version)) form.system_version = versions[0]
  }
)

function isHttpUrl(value) {
  try {
    const parsed = new URL(value)
    return (parsed.protocol === 'http:' || parsed.protocol === 'https:') && !!parsed.hostname
  } catch {
    return false
  }
}

function validateForm() {
  clearErrors()
  let firstTab = ''
  if (!form.name.trim()) {
    errors.name = 'Nama profil wajib diisi'
    firstTab = firstTab || 'account'
  }
  if (!form.group_id) {
    errors.group_id = 'Grup wajib dipilih'
    firstTab = firstTab || 'account'
  }
  if (form.proxy_type !== 'direct') {
    if (!form.proxy_ip.trim()) {
      errors.proxy_ip = 'Host wajib diisi'
      firstTab = firstTab || 'proxy'
    }
    const port = Number(form.proxy_port)
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
      errors.proxy_port = 'Port harus 1 sampai 65535'
      firstTab = firstTab || 'proxy'
    }
  }
  const url = form.site_url.trim()
  if (url && !isHttpUrl(url)) {
    errors.site_url = 'URL harus diawali http:// atau https://'
    firstTab = firstTab || 'account'
  }
  if (firstTab) activeTab.value = firstTab
  return !firstTab
}

function fingerprintPayload() {
  const saved = props.profile?.fingerprint_config
  const base = saved && typeof saved === 'object' && !Array.isArray(saved) ? saved : {}
  return {
    ...base,
    platform: form.platform,
    system_version: form.system_version,
    hardware_concurrency: Number(form.hardware_concurrency),
    device_memory: Number(form.device_memory),
    gpu_vendor: form.gpu_vendor.trim() || null,
    gpu_renderer: form.gpu_renderer.trim() || null,
    disable_gpu_fingerprint: !!form.disable_gpu_fingerprint,
    timezone: form.timezone,
    language: form.language,
  }
}

function proxyPayload() {
  if (form.proxy_type === 'direct') return { proxy_type: 'direct' }
  return {
    proxy_type: form.proxy_type,
    proxy_ip: form.proxy_ip.trim(),
    proxy_port: Number(form.proxy_port),
    proxy_user: form.proxy_user.trim() || null,
    proxy_password: form.proxy_password || null,
  }
}

function preferencePayload() {
  const saved = props.profile?.preference_config
  const base = saved && typeof saved === 'object' && !Array.isArray(saved) ? saved : {}
  const payload = { ...base, extension_ids: [...form.extension_ids] }
  const builtin = builtinKernelPath.value
  if (kernelPath.value && kernelPath.value !== builtin) payload.kernel_path = kernelPath.value
  else delete payload.kernel_path
  return payload
}

function formPayload(tagIds = form.tag_id) {
  const url = form.site_url.trim()
  return {
    name: form.name.trim(),
    group_id: form.group_id,
    tag_id: [...(tagIds || [])],
    color: form.color,
    note: form.note.trim() || null,
    site_id: form.site_id ?? CUSTOM_SITE_ID,
    site_url: url || null,
    proxy_config: proxyPayload(),
    fingerprint_config: fingerprintPayload(),
    preference_config: preferencePayload(),
  }
}

async function resolveTagIds() {
  const ids = []
  let created = false
  for (const value of form.tag_id || []) {
    if (typeof value === 'number') {
      if (!ids.includes(value)) ids.push(value)
      continue
    }
    const title = String(value).trim()
    if (!title) continue
    const existing = props.tags.find((tag) => tag.title.toLowerCase() === title.toLowerCase())
    if (existing) {
      if (!ids.includes(existing.id)) ids.push(existing.id)
      continue
    }
    const result = await api.createTag(title)
    if (!ids.includes(result.id)) ids.push(result.id)
    created = true
  }
  form.tag_id = ids
  if (created) emit('tags-changed')
  return ids
}

function stable(value) {
  if (Array.isArray(value)) return value.map(stable)
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map((key) => [key, stable(value[key])]))
  }
  return value
}

function same(a, b) {
  return JSON.stringify(stable(a)) === JSON.stringify(stable(b))
}

function buildChanges(tagIds) {
  const payload = formPayload(tagIds)
  const changes = { profile_id: props.profile.profile_id }
  for (const key of Object.keys(payload)) {
    if (!same(payload[key], initialPayload ? initialPayload[key] : undefined)) changes[key] = payload[key]
  }
  return changes
}

function close() {
  emit('update:modelValue', false)
}

async function submit() {
  if (!validateForm()) return
  busy.value = true
  try {
    const tagIds = await resolveTagIds()
    if (isEdit.value) {
      const changes = buildChanges(tagIds)
      if (Object.keys(changes).length <= 1) {
        ElMessage.info('Tidak ada perubahan untuk disimpan')
        close()
        return
      }
      await api.updateProfile(changes)
      emit('saved', { mode: 'edit', profileId: props.profile.profile_id, name: form.name.trim() })
      close()
    } else {
      const payload = formPayload(tagIds)
      const result = await api.createProfile(payload)
      emit('saved', { mode: 'create', profileId: result.profile_id, name: payload.name })
      close()
    }
  } catch (error) {
    ElMessage.error(`${isEdit.value ? 'Gagal menyimpan perubahan' : 'Gagal membuat profil'}: ${error.message}`)
  } finally {
    busy.value = false
  }
}

async function randomizeSeed() {
  if (!isEdit.value) return
  try {
    await ElMessageBox.confirm(
      'Acak seed fingerprint profil ini? Fingerprint akan berbeda saat profil dibuka berikutnya.',
      'Acak Seed',
      { confirmButtonText: 'Acak', cancelButtonText: 'Batal' }
    )
  } catch {
    return
  }
  seedBusy.value = true
  try {
    const result = await api.resetSeed(props.profile.profile_id)
    seedOverride.value = result.seed
    ElMessage.success('Seed baru disimpan')
    emit('saved', {
      mode: 'seed',
      profileId: props.profile.profile_id,
      name: form.name.trim() || props.profile.name,
      seed: result.seed,
    })
  } catch (error) {
    ElMessage.error(`Gagal mengacak seed: ${error.message}`)
  } finally {
    seedBusy.value = false
  }
}

function clearProxyErrors() {
  errors.proxy_ip = ''
  errors.proxy_port = ''
}

function clearProxyCheck() {
  proxyCheck.ok = null
  proxyCheck.text = ''
}

function proxyLabel(proxy) {
  const type = String(proxy.proxy_type || '').toUpperCase() || '-'
  const note = proxy.note ? ` · ${proxy.note}` : ''
  return `${type} ${proxy.proxy_ip || '-'}:${proxy.proxy_port ?? '-'}${note}`
}

function onSavedProxyChange(value) {
  clearProxyCheck()
  clearProxyErrors()
  const proxy = savedProxies.value.find((item) => item.id === value)
  if (!proxy) return
  form.proxy_type = proxyTypeValue(proxy.proxy_type)
  form.proxy_ip = proxy.proxy_ip || ''
  form.proxy_port = proxy.proxy_port ?? null
  form.proxy_user = proxy.proxy_user || ''
  form.proxy_password = proxy.proxy_password || ''
}

function proxyFormValid() {
  clearProxyErrors()
  if (form.proxy_type === 'direct') return true
  let valid = true
  if (!form.proxy_ip.trim()) {
    errors.proxy_ip = 'Host wajib diisi'
    valid = false
  }
  const port = Number(form.proxy_port)
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    errors.proxy_port = 'Port harus 1 sampai 65535'
    valid = false
  }
  return valid
}

async function testProxy() {
  if (!proxyFormValid()) return
  proxyCheck.loading = true
  proxyCheck.ok = null
  proxyCheck.text = ''
  try {
    const payload =
      form.proxy_type === 'direct'
        ? { proxy_type: 'direct' }
        : {
            proxy_type: form.proxy_type,
            proxy_ip: form.proxy_ip.trim(),
            proxy_port: Number(form.proxy_port),
            proxy_user: form.proxy_user.trim() || null,
            proxy_password: form.proxy_password || null,
          }
    const result = await api.checkProxy(payload)
    if (result?.ok) {
      proxyCheck.ok = true
      proxyCheck.text = `${result.ip} · ${result.latency_ms} ms`
    } else {
      proxyCheck.ok = false
      proxyCheck.text = result?.error || 'Cek proxy gagal'
    }
  } catch (error) {
    proxyCheck.ok = false
    proxyCheck.text = error.message
  } finally {
    proxyCheck.loading = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="880px"
    top="5vh"
    class="profile-dialog"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-tabs v-model="activeTab" type="border-card" class="profile-tabs">
      <el-tab-pane label="Akun Platform" name="account">
        <el-form label-width="150px" label-position="right" class="dialog-form" @submit.prevent>
          <el-form-item label="Nama Profil" required :error="errors.name">
            <el-input v-model="form.name" maxlength="80" placeholder="cth: Toko Utama" @input="errors.name = ''" />
          </el-form-item>
          <el-form-item label="Grup" required :error="errors.group_id">
            <el-select v-model="form.group_id" placeholder="Pilih grup" @change="errors.group_id = ''">
              <el-option v-for="group in groups" :key="group.id" :label="group.title" :value="group.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="Tag">
            <el-select
              v-model="form.tag_id"
              multiple
              filterable
              allow-create
              default-first-option
              placeholder="Pilih atau buat tag"
            >
              <el-option v-for="tag in tags" :key="tag.id" :label="tag.title" :value="tag.id" />
            </el-select>
          </el-form-item>
          <el-form-item label="Platform Akun">
            <el-select
              v-model="form.account_preset"
              class="field-260"
              placeholder="Pilih platform"
              @change="applyAccountPreset"
            >
              <el-option v-for="preset in ACCOUNT_PRESETS" :key="preset.key" :label="preset.key" :value="preset.key" />
              <el-option label="Custom" value="Custom" />
            </el-select>
          </el-form-item>
          <el-form-item label="URL Awal" :error="errors.site_url">
            <el-input
              v-model="form.site_url"
              placeholder="https://contoh.com"
              @input="errors.site_url = ''"
            />
          </el-form-item>
        </el-form>
        <p class="form-hint">
          Preset platform mengisi site_id dan URL awal, URL tetap bisa diedit. Fingerprint dan proxy diatur di tab
          berikutnya. Nama, grup, dan tag dipakai untuk mengenali profil di daftar.
        </p>
      </el-tab-pane>

      <el-tab-pane label="Konfigurasi Proxy" name="proxy">
        <el-form label-width="150px" label-position="right" class="dialog-form" @submit.prevent>
          <el-form-item label="Proxy Tersimpan">
            <el-select
              v-model="savedProxyId"
              :placeholder="savedProxyPlaceholder"
              clearable
              class="field-260"
              @change="onSavedProxyChange"
            >
              <el-option v-if="savedProxies.length" label="Manual / isi sendiri" :value="0" />
              <el-option
                v-for="proxy in savedProxies"
                :key="proxy.id"
                :label="proxyLabel(proxy)"
                :value="proxy.id"
              />
            </el-select>
          </el-form-item>
          <el-form-item label="Tipe Proxy">
            <el-radio-group v-model="form.proxy_type" @change="clearProxyErrors(); clearProxyCheck()">
              <el-radio value="direct">Direct</el-radio>
              <el-radio value="http">HTTP</el-radio>
              <el-radio value="https">HTTPS</el-radio>
              <el-radio value="socks5">SOCKS5</el-radio>
            </el-radio-group>
          </el-form-item>
          <template v-if="form.proxy_type !== 'direct'">
            <el-form-item label="Host" required :error="errors.proxy_ip">
              <el-input
                v-model="form.proxy_ip"
                placeholder="203.0.113.10"
                @input="errors.proxy_ip = ''; clearProxyCheck()"
              />
            </el-form-item>
            <el-form-item label="Port" required :error="errors.proxy_port">
              <el-input
                v-model="form.proxy_port"
                type="number"
                min="1"
                max="65535"
                class="field-180"
                placeholder="8080"
                @input="errors.proxy_port = ''; clearProxyCheck()"
              />
            </el-form-item>
            <el-form-item label="Username">
              <el-input v-model="form.proxy_user" placeholder="opsional" @input="clearProxyCheck" />
            </el-form-item>
            <el-form-item label="Password">
              <el-input
                v-model="form.proxy_password"
                type="password"
                show-password
                placeholder="opsional"
                @input="clearProxyCheck"
              />
            </el-form-item>
          </template>
          <el-form-item label="Tes Koneksi">
            <div class="proxy-check-cell">
              <el-button size="small" :loading="proxyCheck.loading" @click="testProxy">Tes</el-button>
              <span
                v-if="proxyCheck.text"
                :class="['proxy-check-result', proxyCheck.ok ? 'is-ok' : 'is-fail']"
              >{{ proxyCheck.text }}</span>
            </div>
          </el-form-item>
          <p class="form-hint">Kredensial proxy dipakai engine saat profil dibuka. Pilih proxy tersimpan untuk mengisi isian, nilai tetap disimpan di profil ini.</p>
        </el-form>
      </el-tab-pane>

      <el-tab-pane label="Fingerprint" name="fingerprint">
        <div class="seed-bar">
          <div class="seed-cell">
            <span class="seed-label">Seed Fingerprint</span>
            <span class="seed-value mono">{{ seedText }}</span>
          </div>
          <el-button v-if="isEdit" size="small" :loading="seedBusy" @click="randomizeSeed">Acak Seed</el-button>
        </div>
        <el-form label-width="150px" label-position="right" class="dialog-form" @submit.prevent>
          <el-form-item label="Platform">
            <el-radio-group v-model="form.platform">
              <el-radio value="Windows">Windows</el-radio>
              <el-radio value="Macos">macOS</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item :label="versionLabel">
            <el-radio-group v-model="form.system_version">
              <el-radio v-for="version in versionOptions" :key="version" :value="version">{{ version }}</el-radio>
            </el-radio-group>
          </el-form-item>
          <el-form-item label="CPU Cores">
            <el-select v-model="form.hardware_concurrency" class="field-180">
              <el-option v-for="core in CPU_CORES" :key="core" :label="core" :value="core" />
            </el-select>
          </el-form-item>
          <el-form-item label="Memory (GB)">
            <el-select v-model="form.device_memory" class="field-180">
              <el-option v-for="memory in MEMORY" :key="memory" :label="memory" :value="memory" />
            </el-select>
          </el-form-item>
          <el-form-item label="GPU Vendor">
            <el-select
              v-model="form.gpu_vendor"
              filterable
              allow-create
              default-first-option
              clearable
              placeholder="Ikuti seed atau tulis vendor"
              class="field-260"
            >
              <el-option v-for="vendor in GPU_VENDORS" :key="vendor" :label="vendor" :value="vendor" />
            </el-select>
          </el-form-item>
          <el-form-item label="GPU Renderer">
            <el-input
              v-model="form.gpu_renderer"
              placeholder="ANGLE (NVIDIA, NVIDIA GeForce RTX 5060 Direct3D11 vs_5_0 ps_5_0, D3D11)"
            />
          </el-form-item>
          <p v-if="gpuFieldHint" class="form-hint is-warn">{{ gpuFieldHint }}</p>
          <el-form-item label="GPU Host">
            <div class="switch-cell">
              <el-switch v-model="form.disable_gpu_fingerprint" />
              <span class="switch-label">Tampilkan GPU asli</span>
            </div>
          </el-form-item>
          <p v-if="gpuSwitchHint" class="form-hint">{{ gpuSwitchHint }}</p>
          <el-form-item label="Zona Waktu">
            <el-select
              v-model="form.timezone"
              filterable
              allow-create
              default-first-option
              placeholder="Cari atau tulis zona waktu"
              class="field-260"
            >
              <el-option v-for="zone in TIMEZONES" :key="zone" :label="zone" :value="zone" />
            </el-select>
          </el-form-item>
          <el-form-item label="Bahasa">
            <el-select
              v-model="form.language"
              filterable
              allow-create
              default-first-option
              placeholder="Cari atau tulis locale"
              class="field-180"
            >
              <el-option v-for="lang in LANGUAGES" :key="lang" :label="lang" :value="lang" />
            </el-select>
          </el-form-item>
          <p class="form-hint">WebRTC: UDP non-proxy diblokir otomatis oleh engine.</p>
          <p class="form-hint">Layar dan device scale factor belum didukung engine 150.</p>
        </el-form>
      </el-tab-pane>

      <el-tab-pane label="Extension" name="extension">
        <div v-loading="extensionsLoading" element-loading-text="Memuat extension..." class="extension-picker">
          <template v-if="extensionOptions.length">
            <el-checkbox-group v-model="form.extension_ids" class="extension-list">
              <el-checkbox
                v-for="item in extensionOptions"
                :key="item.id"
                :value="item.id"
                class="extension-item"
              >
                <span class="extension-name">{{ item.title }}</span>
                <span class="extension-version">{{ item.version ? `v${item.version}` : 'tanpa versi' }}</span>
              </el-checkbox>
            </el-checkbox-group>
            <p class="form-hint">Extension terpilih dimuat saat profil dibuka. Kosongkan centang untuk menonaktifkan.</p>
          </template>
          <p v-else-if="!extensionsLoading" class="form-hint">Unggah extension di halaman Extension.</p>
        </div>
      </el-tab-pane>

      <el-tab-pane label="Preferensi" name="preference">
        <el-form label-width="150px" label-position="right" class="dialog-form" @submit.prevent>
          <el-form-item label="Versi Kernel">
            <el-select
              v-if="kernels.length > 1"
              v-model="kernelPath"
              class="field-320"
              placeholder="Pilih kernel"
            >
              <el-option
                v-for="kernel in kernels"
                :key="kernel.id"
                :label="kernelLabel(kernel)"
                :value="kernel.path"
              />
            </el-select>
            <div v-else-if="kernels.length === 1" class="kernel-inline">
              <span class="kernel-inline-version mono">{{ kernels[0].version || 'Versi tidak terbaca' }}</span>
              <span class="form-hint">Hanya satu kernel terpasang.</span>
            </div>
            <span v-else class="form-hint">
              {{ kernelError ? `engine-info gagal: ${kernelError}` : 'Memuat kernel...' }}
            </span>
          </el-form-item>
          <p v-if="kernelSavedMissing" class="form-hint is-warn">
            Kernel tersimpan tidak tersedia lagi, profil memakai engine bawaan.
          </p>
          <el-form-item label="Warna Profil">
            <div class="color-swatches">
              <button
                v-for="color in colorOptions"
                :key="color"
                type="button"
                class="color-swatch"
                :class="{ active: form.color === color }"
                :style="{ background: color }"
                :aria-label="`Pilih warna ${color}`"
                @click="form.color = color"
              ></button>
            </div>
          </el-form-item>
          <el-form-item label="Catatan">
            <el-input
              v-model="form.note"
              type="textarea"
              :rows="3"
              maxlength="200"
              show-word-limit
              placeholder="Catatan internal profil"
            />
          </el-form-item>
        </el-form>
      </el-tab-pane>
    </el-tabs>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="close">Batal</el-button>
        <div class="footer-spacer"></div>
        <el-button :disabled="busy" @click="resetForm">Reset</el-button>
        <el-button type="primary" :loading="busy" @click="submit">Simpan</el-button>
      </div>
    </template>
  </el-dialog>
</template>
