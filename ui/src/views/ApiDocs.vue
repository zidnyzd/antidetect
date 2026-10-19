<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { DocumentCopy } from '@element-plus/icons-vue'
import { api } from '../api'
import { useOnRefresh } from '../refresh'

const BASE_URL = 'http://127.0.0.1:53200/api/v2/'

const ACTIONS = [
  {
    name: 'profile-list',
    summary: 'Daftar profil aktif. Filter opsional: group_id, tab_id (ID tag), name.',
    payload: { page: 1, limit: 10 },
  },
  {
    name: 'profile-create',
    summary: 'Buat profil. site_id 22 dipakai untuk platform Custom.',
    payload: { name: 'Profil Baru', group_id: 1, site_id: 22, site_url: 'https://www.google.com/' },
  },
  {
    name: 'profile-open',
    summary: 'Buka Chromium terisolasi. Hasil berisi debugging_address dan webdriver.',
    payload: { profile_id: 1 },
  },
  {
    name: 'profile-close',
    summary: 'Tutup Chromium milik profil. Aman dipanggil saat profil sudah tertutup.',
    payload: { profile_id: 1 },
  },
  {
    name: 'proxy-check',
    summary: 'Uji proxy dan baca IP keluar. Ganti host dan port dengan proxy Anda.',
    payload: { proxy_type: 'http', proxy_ip: '203.0.113.10', proxy_port: 8080 },
  },
  {
    name: 'extension-list',
    summary: 'Daftar extension terpasang dengan nama, versi, dan path.',
    payload: { page: 1, limit: 20 },
  },
  {
    name: 'profile-export',
    summary: 'Ekspor profil ke base64. Hasil berisi filename dan content_base64.',
    payload: { profile_id: 1 },
  },
  {
    name: 'profile-import',
    summary: 'Impor profil dari content_base64 hasil ekspor.',
    payload: { content_base64: '<base64 file profil>' },
  },
]

const SELENIUM_SNIPPET = `import requests
from selenium import webdriver
from selenium.webdriver.chrome.service import Service

API = "http://127.0.0.1:53200/api/v2"
profile_id = 1

opened = requests.post(f"{API}/profile-open", json={"profile_id": profile_id}).json()["data"]

options = webdriver.ChromeOptions()
options.debugger_address = opened["debugging_address"]
driver = webdriver.Chrome(service=Service(opened["webdriver"]), options=options)
driver.get("https://example.com")
print(driver.title)

requests.post(f"{API}/profile-close", json={"profile_id": profile_id})`

const health = ref(null)
const healthError = ref('')
const copiedKey = ref('')
let copyTimer = null

const healthLabel = computed(() => {
  if (health.value) return 'Tersambung'
  if (healthError.value) return 'Tidak tersambung'
  return 'Memeriksa...'
})

function payloadFor(action) {
  return JSON.stringify(action.payload, null, 2)
}

function curlFor(action) {
  return `curl -s -X POST ${BASE_URL}${action.name} \\\n  -H 'Content-Type: application/json' \\\n  -d '${JSON.stringify(action.payload, null, 2)}'`
}

function fallbackCopy(text) {
  const area = document.createElement('textarea')
  area.value = text
  area.setAttribute('readonly', '')
  area.style.position = 'fixed'
  area.style.opacity = '0'
  document.body.appendChild(area)
  area.select()
  let ok = false
  try {
    ok = document.execCommand('copy')
  } catch {
    ok = false
  }
  area.remove()
  return ok
}

async function copy(key, text) {
  let ok = false
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text)
      ok = true
    }
  } catch {
    ok = false
  }
  if (!ok) ok = fallbackCopy(text)
  if (!ok) return
  copiedKey.value = key
  clearTimeout(copyTimer)
  copyTimer = setTimeout(() => {
    copiedKey.value = ''
  }, 1600)
}

async function loadHealth() {
  try {
    health.value = await api.health()
    healthError.value = ''
  } catch (error) {
    health.value = null
    healthError.value = error.message
  }
}

onMounted(loadHealth)
onUnmounted(() => clearTimeout(copyTimer))
useOnRefresh(() => loadHealth())
</script>

<template>
  <div class="api-page">
    <header class="page-head">
      <div>
        <h1 class="page-title">API</h1>
        <p class="page-sub">Kontrak HTTP lokal untuk otomasi dan integrasi.</p>
      </div>
    </header>

    <section class="api-grid">
      <div class="info-card api-base-card">
        <div class="info-label">Base URL</div>
        <div class="api-base-line">
          <span class="info-value mono">{{ BASE_URL }}</span>
          <el-button size="small" :icon="DocumentCopy" @click="copy('base', BASE_URL)">
            {{ copiedKey === 'base' ? 'Tersalin' : 'Salin' }}
          </el-button>
        </div>
        <p class="info-help">Semua aksi dikirim sebagai POST JSON. Server hanya mendengarkan di 127.0.0.1.</p>
      </div>

      <div class="info-card">
        <div class="info-label">Status /health</div>
        <div class="info-value health-line">
          <span :class="['status-dot', health ? 'ok' : healthError ? 'bad' : 'idle']"></span>
          <span>{{ healthLabel }}</span>
        </div>
        <p class="info-help">
          <template v-if="health">Status {{ health.status }}, {{ health.open }} profil terbuka.</template>
          <template v-else-if="healthError">Permintaan /health gagal: {{ healthError }}</template>
          <template v-else>Menunggu respons /health.</template>
        </p>
      </div>
    </section>

    <section class="surface api-section">
      <div class="api-section-head">
        <div>
          <h2 class="panel-title">Aksi Umum</h2>
          <p class="panel-sub">Contoh payload dan perintah siap pakai. Ganti nilai ID sesuai profil Anda.</p>
        </div>
      </div>

      <div class="api-table">
        <div class="api-row api-row-head" aria-hidden="true">
          <span>Aksi</span>
          <span>Contoh Payload</span>
          <span>Contoh cURL</span>
        </div>
        <div v-for="action in ACTIONS" :key="action.name" class="api-row">
          <div class="api-action">
            <div class="api-name mono">{{ action.name }}</div>
            <p class="api-desc">{{ action.summary }}</p>
          </div>
          <div class="api-code">
            <pre class="code-block">{{ payloadFor(action) }}</pre>
            <el-button
              size="small"
              :icon="DocumentCopy"
              @click="copy(`payload:${action.name}`, payloadFor(action))"
            >{{ copiedKey === `payload:${action.name}` ? 'Tersalin' : 'Salin' }}</el-button>
          </div>
          <div class="api-code">
            <pre class="code-block">{{ curlFor(action) }}</pre>
            <el-button
              size="small"
              :icon="DocumentCopy"
              @click="copy(`curl:${action.name}`, curlFor(action))"
            >{{ copiedKey === `curl:${action.name}` ? 'Tersalin' : 'Salin' }}</el-button>
          </div>
        </div>
      </div>
    </section>

    <section class="surface api-section">
      <div class="api-section-head">
        <div>
          <h2 class="panel-title">Python Selenium</h2>
          <p class="panel-sub">Attach ke Chromium yang sudah dibuka lewat debugging_address.</p>
        </div>
        <el-button size="small" :icon="DocumentCopy" @click="copy('selenium', SELENIUM_SNIPPET)">
          {{ copiedKey === 'selenium' ? 'Tersalin' : 'Salin' }}
        </el-button>
      </div>
      <p class="api-note">
        profile-open mengembalikan debugging_address dan path chromedriver. Snippet ini memakai keduanya, lalu menutup
        profil lewat profile-close.
      </p>
      <pre class="code-block code-wide">{{ SELENIUM_SNIPPET }}</pre>
    </section>

    <span class="sr-only" role="status" aria-live="polite">
      {{ copiedKey ? 'Tersalin ke clipboard' : '' }}
    </span>
  </div>
</template>
