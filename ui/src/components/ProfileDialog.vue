<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
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

const activeTab = ref('account')
const busy = ref(false)
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

function proxyTypeValue(raw) {
  const value = String(raw || 'direct').toLowerCase()
  return ['http', 'https', 'socks5'].includes(value) ? value : 'direct'
}

function fillFromProfile(profile) {
  const fingerprint = profile.fingerprint_config || {}
  const proxy = profile.proxy_config || {}
  form.name = profile.name || ''
  form.group_id = profile.group_id ?? form.group_id
  form.tag_id = Array.isArray(profile.tab_id) ? [...profile.tab_id] : []
  form.color = profile.color || COLORS[0]
  form.note = profile.note || ''
  form.site_url = profile.site_url || ''
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
  form.timezone = fingerprint.timezone || 'Asia/Jakarta'
  form.language = fingerprint.language || 'id-ID'
  const extensionIds = (profile.preference_config || {}).extension_ids
  form.extension_ids = Array.isArray(extensionIds)
    ? extensionIds.map((id) => Number(id)).filter((id) => Number.isInteger(id))
    : []
}

function clearErrors() {
  for (const key of Object.keys(errors)) errors[key] = ''
}

function resetForm() {
  Object.assign(form, emptyForm())
  savedProxyId.value = null
  proxyCheck.loading = false
  proxyCheck.ok = null
  proxyCheck.text = ''
  clearErrors()
  activeTab.value = 'account'
  if (props.profile) {
    fillFromProfile(props.profile)
    initialPayload = formPayload()
  } else {
    initialPayload = null
  }
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

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      resetForm()
      loadSavedProxies()
      loadExtensions()
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
    firstTab = firstTab || 'preference'
  }
  if (firstTab) activeTab.value = firstTab
  return !firstTab
}

function fingerprintPayload() {
  return {
    platform: form.platform,
    system_version: form.system_version,
    hardware_concurrency: Number(form.hardware_concurrency),
    device_memory: Number(form.device_memory),
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
  return { ...base, extension_ids: [...form.extension_ids] }
}

function formPayload(tagIds = form.tag_id) {
  const url = form.site_url.trim()
  return {
    name: form.name.trim(),
    group_id: form.group_id,
    tag_id: [...(tagIds || [])],
    color: form.color,
    note: form.note.trim() || null,
    site_id: url ? 21 : 22,
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
        </el-form>
        <p class="form-hint">
          Platform, fingerprint, dan proxy diatur di tab berikutnya. Nama, grup, dan tag dipakai untuk mengenali profil di
          daftar.
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
          <el-form-item label="URL Awal" :error="errors.site_url">
            <el-input v-model="form.site_url" placeholder="https://contoh.com" @input="errors.site_url = ''" />
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
