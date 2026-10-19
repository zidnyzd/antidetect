<script setup>
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

const props = defineProps({
  modelValue: Boolean,
  groups: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:modelValue', 'created'])

const COLORS = ['#4c7dff', '#22c55e', '#f59e0b', '#ef4444', '#a855f7', '#14b8a6', '#e879f9', '#64748b']
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
const LANGS = ['id-ID', 'en-US', 'en-GB', 'zh-CN', 'ja-JP', 'ko-KR', 'es-ES']

const step = ref(0)
const busy = ref(false)
const form = reactive({
  name: '',
  group_id: 1,
  color: COLORS[0],
  site_url: '',
  platform: 'Windows',
  system_version: '11',
  hardware_concurrency: 8,
  device_memory: 8,
  timezone: 'Asia/Jakarta',
  language: 'id-ID',
  proxy_type: 'direct',
  proxy_ip: '',
  proxy_port: null,
  proxy_user: '',
  proxy_password: '',
})

watch(
  () => props.modelValue,
  (value) => {
    if (value) step.value = 0
  }
)

function next() {
  if (step.value === 0 && !form.name.trim()) {
    ElMessage.warning('Nama profil wajib diisi')
    return
  }
  step.value += 1
}

async function submit() {
  busy.value = true
  try {
    const fingerprint_config = {
      platform: form.platform,
      hardware_concurrency: form.hardware_concurrency,
      device_memory: form.device_memory,
      timezone: form.timezone,
      language: form.language,
    }
    if (form.platform === 'Windows') fingerprint_config.system_version = form.system_version
    const proxy_config =
      form.proxy_type === 'direct'
        ? { proxy_type: 'direct' }
        : {
            proxy_type: form.proxy_type,
            proxy_ip: form.proxy_ip.trim(),
            proxy_port: form.proxy_port,
            proxy_user: form.proxy_user || null,
            proxy_password: form.proxy_password || null,
          }
    await api.createProfile({
      name: form.name.trim(),
      group_id: form.group_id,
      color: form.color,
      site_id: form.site_url ? 21 : 22,
      site_url: form.site_url || null,
      fingerprint_config,
      proxy_config,
    })
    ElMessage.success(`Profil "${form.name}" dibuat`)
    emit('created')
    emit('update:modelValue', false)
    Object.assign(form, {
      name: '',
      site_url: '',
      proxy_type: 'direct',
      proxy_ip: '',
      proxy_port: null,
      proxy_user: '',
      proxy_password: '',
    })
  } catch (error) {
    ElMessage.error(`Gagal membuat: ${error.message}`)
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="Buat Profil Baru"
    width="620px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-steps :active="step" finish-status="success" style="margin-bottom: 22px">
      <el-step title="Informasi" />
      <el-step title="Fingerprint" />
      <el-step title="Proxy" />
    </el-steps>

    <div v-show="step === 0" class="form-grid">
      <label>Nama Profil</label>
      <el-input v-model="form.name" placeholder="cth: Shopee Seller 1" />
      <label>Grup</label>
      <el-select v-model="form.group_id">
        <el-option v-for="g in groups" :key="g.id" :label="g.title" :value="g.id" />
      </el-select>
      <label>Warna</label>
      <div class="swatches">
        <span
          v-for="c in COLORS"
          :key="c"
          :class="['swatch', { active: form.color === c }]"
          :style="{ background: c }"
          @click="form.color = c"
        ></span>
      </div>
      <label>Halaman Awal</label>
      <el-input v-model="form.site_url" placeholder="opsional, https://..." />
    </div>

    <div v-show="step === 1" class="form-grid">
      <label>Platform</label>
      <el-radio-group v-model="form.platform">
        <el-radio-button value="Windows">Windows</el-radio-button>
        <el-radio-button value="Macos">macOS</el-radio-button>
      </el-radio-group>
      <template v-if="form.platform === 'Windows'">
        <label>Versi Windows</label>
        <el-radio-group v-model="form.system_version">
          <el-radio-button value="11">11</el-radio-button>
          <el-radio-button value="10">10</el-radio-button>
        </el-radio-group>
      </template>
      <label>CPU Cores</label>
      <el-select v-model="form.hardware_concurrency" style="width: 140px">
        <el-option v-for="n in [2, 4, 6, 8, 12, 16]" :key="n" :label="n" :value="n" />
      </el-select>
      <label>Memory (GB)</label>
      <el-select v-model="form.device_memory" style="width: 140px">
        <el-option v-for="n in [2, 4, 8]" :key="n" :label="n" :value="n" />
      </el-select>
      <label>Timezone</label>
      <el-select v-model="form.timezone">
        <el-option v-for="tz in TIMEZONES" :key="tz" :label="tz" :value="tz" />
      </el-select>
      <label>Bahasa</label>
      <el-select v-model="form.language">
        <el-option v-for="l in LANGS" :key="l" :label="l" :value="l" />
      </el-select>
    </div>

    <div v-show="step === 2" class="form-grid">
      <label>Tipe Proxy</label>
      <el-radio-group v-model="form.proxy_type">
        <el-radio-button value="direct">Direct</el-radio-button>
        <el-radio-button value="http">HTTP</el-radio-button>
        <el-radio-button value="https">HTTPS</el-radio-button>
        <el-radio-button value="socks5">SOCKS5</el-radio-button>
      </el-radio-group>
      <template v-if="form.proxy_type !== 'direct'">
        <label>Host / IP</label>
        <el-input v-model="form.proxy_ip" placeholder="203.0.113.10" />
        <label>Port</label>
        <el-input v-model.number="form.proxy_port" style="width: 140px" />
        <label>Username</label>
        <el-input v-model="form.proxy_user" placeholder="opsional" />
        <label>Password</label>
        <el-input v-model="form.proxy_password" type="password" show-password placeholder="opsional" />
      </template>
    </div>

    <template #footer>
      <el-button v-if="step > 0" @click="step -= 1">Kembali</el-button>
      <el-button v-if="step < 2" type="primary" @click="next">Lanjut</el-button>
      <el-button v-else type="primary" :loading="busy" @click="submit">Buat</el-button>
    </template>
  </el-dialog>
</template>
