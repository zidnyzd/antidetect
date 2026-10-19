<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  profile: { type: Object, default: null },
  groups: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'saved'])

const COLORS = ['#2f6fed', '#16a34a', '#f59e0b', '#d92d20', '#a855f7', '#14b8a6', '#e879f9', '#64748b']
const TIMEZONES = [
  'Asia/Jakarta',
  'Asia/Makassar',
  'Asia/Jayapura',
  'Asia/Singapore',
  'Asia/Shanghai',
  'America/New_York',
  'America/Los_Angeles',
  'Europe/London',
  'Europe/Berlin',
  'UTC',
]
const LANGUAGES = ['id-ID', 'en-US', 'en-GB', 'zh-CN', 'ja-JP', 'ko-KR', 'es-ES']
const CPU_CORES = [2, 4, 6, 8, 12, 16]
const MEMORY = [2, 4, 8]

const activeTab = ref('account')
const busy = ref(false)
const errors = reactive({ name: '', group_id: '', proxy_ip: '', proxy_port: '', site_url: '' })

let initialPayload = null

function emptyForm() {
  return {
    name: '',
    group_id: props.groups[0]?.id ?? 1,
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

function proxyTypeValue(raw) {
  const value = String(raw || 'direct').toLowerCase()
  return ['http', 'https', 'socks5'].includes(value) ? value : 'direct'
}

function fillFromProfile(profile) {
  const fingerprint = profile.fingerprint_config || {}
  const proxy = profile.proxy_config || {}
  form.name = profile.name || ''
  form.group_id = profile.group_id ?? form.group_id
  form.color = profile.color || COLORS[0]
  form.note = profile.note || ''
  form.site_url = profile.site_url || ''
  form.proxy_type = proxyTypeValue(proxy.proxy_type)
  form.proxy_ip = proxy.proxy_ip || ''
  form.proxy_port = proxy.proxy_port ?? null
  form.proxy_user = proxy.proxy_user || ''
  form.proxy_password = proxy.proxy_password || ''
  form.platform = fingerprint.platform === 'Macos' ? 'Macos' : 'Windows'
  form.system_version = ['11', '10'].includes(String(fingerprint.system_version))
    ? String(fingerprint.system_version)
    : '11'
  form.hardware_concurrency = CPU_CORES.includes(Number(fingerprint.hardware_concurrency))
    ? Number(fingerprint.hardware_concurrency)
    : 8
  form.device_memory = MEMORY.includes(Number(fingerprint.device_memory)) ? Number(fingerprint.device_memory) : 8
  form.timezone = TIMEZONES.includes(fingerprint.timezone) ? fingerprint.timezone : 'Asia/Jakarta'
  form.language = LANGUAGES.includes(fingerprint.language) ? fingerprint.language : 'id-ID'
}

function clearErrors() {
  for (const key of Object.keys(errors)) errors[key] = ''
}

function resetForm() {
  Object.assign(form, emptyForm())
  clearErrors()
  activeTab.value = 'account'
  if (props.profile) {
    fillFromProfile(props.profile)
    initialPayload = formPayload()
  } else {
    initialPayload = null
  }
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) resetForm()
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
  const config = {
    platform: form.platform,
    hardware_concurrency: Number(form.hardware_concurrency),
    device_memory: Number(form.device_memory),
    timezone: form.timezone,
    language: form.language,
  }
  if (form.platform === 'Windows') config.system_version = form.system_version
  return config
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

function formPayload() {
  const url = form.site_url.trim()
  return {
    name: form.name.trim(),
    group_id: form.group_id,
    color: form.color,
    note: form.note.trim() || null,
    site_id: url ? 21 : 22,
    site_url: url || null,
    proxy_config: proxyPayload(),
    fingerprint_config: fingerprintPayload(),
    preference_config: {},
  }
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

function buildChanges() {
  const payload = formPayload()
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
    if (isEdit.value) {
      const changes = buildChanges()
      if (Object.keys(changes).length <= 1) {
        ElMessage.info('Tidak ada perubahan untuk disimpan')
        close()
        return
      }
      await api.updateProfile(changes)
      emit('saved', { mode: 'edit', profileId: props.profile.profile_id, name: form.name.trim() })
      close()
    } else {
      const payload = formPayload()
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
        </el-form>
        <p class="form-hint">
          Platform, fingerprint, dan proxy diatur di tab berikutnya. Nama dan grup dipakai untuk mengenali profil di
          daftar.
        </p>
      </el-tab-pane>

      <el-tab-pane label="Konfigurasi Proxy" name="proxy">
        <el-form label-width="150px" label-position="right" class="dialog-form" @submit.prevent>
          <el-form-item label="Tipe Proxy">
            <el-radio-group v-model="form.proxy_type" @change="clearProxyErrors">
              <el-radio value="direct">Direct</el-radio>
              <el-radio value="http">HTTP</el-radio>
              <el-radio value="https">HTTPS</el-radio>
              <el-radio value="socks5">SOCKS5</el-radio>
            </el-radio-group>
          </el-form-item>
          <template v-if="form.proxy_type !== 'direct'">
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
          </template>
          <p class="form-hint">Kredensial proxy dipakai engine saat profil dibuka.</p>
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
          <el-form-item v-if="form.platform === 'Windows'" label="Versi Windows">
            <el-radio-group v-model="form.system_version">
              <el-radio value="11">Windows 11</el-radio>
              <el-radio value="10">Windows 10</el-radio>
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
          <el-form-item label="Timezone">
            <el-select v-model="form.timezone" filterable class="field-260">
              <el-option v-for="zone in TIMEZONES" :key="zone" :label="zone" :value="zone" />
            </el-select>
          </el-form-item>
          <el-form-item label="Bahasa">
            <el-select v-model="form.language" class="field-180">
              <el-option v-for="lang in LANGUAGES" :key="lang" :label="lang" :value="lang" />
            </el-select>
          </el-form-item>
          <p class="form-hint">Layar dan device scale factor belum didukung engine 150.</p>
        </el-form>
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
