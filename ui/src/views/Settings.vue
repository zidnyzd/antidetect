<script setup>
import { computed, onMounted, ref } from 'vue'
import { api, UI_VERSION } from '../api'
import { useOnRefresh } from '../refresh'

const health = ref(null)
const healthError = ref('')
const profileTotal = ref(null)
const profilesError = ref('')
const loading = ref(true)

const apiBase = computed(() => `${window.location.origin}/api/v2/`)

async function loadHealth() {
  try {
    health.value = await api.health()
    healthError.value = ''
  } catch (error) {
    health.value = null
    healthError.value = error.message
  }
}

async function loadProfileTotal() {
  try {
    const result = await api.profiles({ page: 1, limit: 1 })
    profileTotal.value = result.total ?? 0
    profilesError.value = ''
  } catch (error) {
    profileTotal.value = null
    profilesError.value = error.message
  }
}

async function load() {
  loading.value = true
  await Promise.all([loadHealth(), loadProfileTotal()])
  loading.value = false
}

onMounted(load)
useOnRefresh(() => load())
</script>

<template>
  <div v-loading="loading" element-loading-text="Memuat informasi..." class="settings-page">
    <div class="settings-grid">
      <section class="info-card">
        <div class="info-label">API Base</div>
        <div class="info-value mono">{{ apiBase }}</div>
        <p class="info-help">Permintaan aplikasi memakai origin ini. Dev server mem-proxy /api dan /health ke 127.0.0.1:53200.</p>
      </section>

      <section class="info-card">
        <div class="info-label">Status API</div>
        <div class="info-value health-line">
          <span :class="['status-dot', health ? 'ok' : healthError ? 'bad' : 'idle']"></span>
          <span>{{ health ? 'Tersambung' : healthError ? 'Tidak tersambung' : 'Memeriksa...' }}</span>
        </div>
        <p class="info-help">
          <template v-if="health">
            GET /health mengembalikan status {{ health.status }} dengan {{ health.open }} profil terbuka.
          </template>
          <template v-else-if="healthError">Permintaan /health gagal: {{ healthError }}</template>
          <template v-else>Menunggu respons /health.</template>
        </p>
      </section>

      <section class="info-card">
        <div class="info-label">Jumlah Profil</div>
        <div class="info-value">{{ profileTotal === null ? 'Tidak tersedia' : `${profileTotal} profil` }}</div>
        <p class="info-help">
          <template v-if="profilesError">profile-list gagal: {{ profilesError }}</template>
          <template v-else>Total dari profile-list dengan limit 1.</template>
        </p>
      </section>

      <section class="info-card">
        <div class="info-label">Versi UI</div>
        <div class="info-value">{{ UI_VERSION }}</div>
        <p class="info-help">Versi antarmuka di folder ui/.</p>
      </section>
    </div>
  </div>
</template>
