<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { Monitor } from '@element-plus/icons-vue'
import { api } from '../api'
import { useOnRefresh } from '../refresh'

const router = useRouter()
const profiles = ref([])
const totalProfiles = ref(0)
const groups = ref([])
const extensionsTotal = ref(0)
const proxiesTotal = ref(0)
const opened = ref(new Set())
const loading = ref(true)
const loadError = ref('')

const latestProfiles = computed(() => profiles.value.slice(0, 5))
const groupMap = computed(() => new Map(groups.value.map((group) => [group.id, group.title])))
const openedCount = computed(() => opened.value.size)

const lastOpened = computed(() => {
  let latest = null
  for (const profile of profiles.value) {
    if (!profile.last_open_time) continue
    if (!latest || Number(profile.last_open_time) > Number(latest.last_open_time)) latest = profile
  }
  return latest
})

function formatTime(value) {
  if (!value) return ''
  if (typeof value === 'number') {
    const date = new Date(value * 1000)
    if (Number.isNaN(date.getTime())) return ''
    const pad = (part) => String(part).padStart(2, '0')
    return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
  }
  const [date, time] = String(value).split(' ')
  return `${date || ''} ${(time || '').slice(0, 5)}`.trim()
}

function groupTitle(groupId) {
  return groupMap.value.get(groupId) || `Grup ${groupId}`
}

function isOpen(profile) {
  return opened.value.has(profile.profile_id)
}

async function load() {
  loading.value = true
  const [profileResult, groupResult, extensionResult, proxyResult, openedResult] = await Promise.allSettled([
    api.profiles({ page: 1, limit: 1000 }),
    api.groups(),
    api.extensions({ page: 1, limit: 1 }),
    api.proxies({ page: 1, limit: 1 }),
    api.openedList(),
  ])
  const failed = []

  if (profileResult.status === 'fulfilled') {
    profiles.value = profileResult.value.data || []
    totalProfiles.value = profileResult.value.total || 0
  } else {
    failed.push('profil')
  }

  if (groupResult.status === 'fulfilled') {
    groups.value = groupResult.value.data || []
  } else {
    failed.push('grup')
  }

  extensionsTotal.value = extensionResult.status === 'fulfilled' ? extensionResult.value.total || 0 : 0
  if (extensionResult.status === 'rejected') failed.push('extension')

  proxiesTotal.value = proxyResult.status === 'fulfilled' ? proxyResult.value.total || 0 : 0
  if (proxyResult.status === 'rejected') failed.push('proxy')

  if (openedResult.status === 'fulfilled') {
    opened.value = new Set((openedResult.value || []).map((item) => item.profile_id))
  } else {
    failed.push('status buka')
  }

  loadError.value = failed.length ? `Gagal memuat ${failed.join(', ')}.` : ''
  loading.value = false
}

onMounted(load)
useOnRefresh(() => load())
</script>

<template>
  <div v-loading="loading" element-loading-text="Memuat ringkasan..." class="dashboard-page">
    <header class="page-head">
      <div>
        <h1 class="page-title">Ringkasan</h1>
        <p class="page-sub">Kondisi profil browser saat ini.</p>
      </div>
      <el-button type="primary" :icon="Monitor" @click="router.push('/profiles')">Daftar Profil</el-button>
    </header>

    <el-alert v-if="loadError" class="dash-alert" type="error" :title="loadError" :closable="false" show-icon />

    <section class="dash-grid">
      <div class="stat-card">
        <div class="stat-label">Total Profil</div>
        <div class="stat-value">{{ totalProfiles }}</div>
        <div class="stat-foot">di luar keranjang sampah</div>
      </div>

      <div class="stat-card">
        <div class="stat-label">Terbuka</div>
        <div class="stat-value">{{ openedCount }}</div>
        <div class="stat-foot">
          <span :class="['status-dot', openedCount ? 'ok' : 'idle']"></span>
          {{ openedCount ? 'proses Chromium berjalan' : 'tidak ada profil berjalan' }}
        </div>
      </div>

      <div class="stat-card">
        <div class="stat-label">Grup</div>
        <div class="stat-value">{{ groups.length }}</div>
        <div class="stat-foot">pengelompokan profil</div>
      </div>

      <div class="stat-card">
        <div class="stat-label">Extension</div>
        <div class="stat-value">{{ extensionsTotal }}</div>
        <div class="stat-foot">terpasang di penyimpanan</div>
      </div>

      <div class="stat-card">
        <div class="stat-label">Proxy</div>
        <div class="stat-value">{{ proxiesTotal }}</div>
        <div class="stat-foot">proxy tersimpan</div>
      </div>

      <div class="stat-card">
        <div class="stat-label">Terakhir Dibuka</div>
        <div :class="['stat-value', 'stat-name', { 'is-empty': !lastOpened }]">
          {{ lastOpened ? lastOpened.name : 'Belum ada' }}
        </div>
        <div class="stat-foot">{{ lastOpened ? formatTime(lastOpened.last_open_time) : 'Belum ada profil dibuka' }}</div>
      </div>
    </section>

    <section class="surface dash-panel">
      <div class="dash-panel-head">
        <div>
          <h2 class="panel-title">Profil Terbaru</h2>
          <p class="panel-sub">Lima profil dengan ID terbaru.</p>
        </div>
        <el-button link type="primary" @click="router.push('/profiles')">Lihat semua</el-button>
      </div>

      <div v-if="latestProfiles.length" class="dash-list">
        <div v-for="profile in latestProfiles" :key="profile.profile_id" class="dash-row">
          <span class="dash-dot" :style="{ background: profile.color || '#86909c' }"></span>
          <div class="dash-row-main">
            <span class="dash-row-name" :title="profile.name">{{ profile.name }}</span>
            <span class="dash-row-sub">{{ groupTitle(profile.group_id) }}</span>
          </div>
          <span :class="['status-text', isOpen(profile) ? 'is-open' : 'is-closed']">
            <span :class="['status-dot', isOpen(profile) ? 'ok' : 'idle']"></span>
            {{ isOpen(profile) ? 'Terbuka' : 'Tertutup' }}
          </span>
          <span class="dash-row-time" :title="formatTime(profile.created_at)">
            {{ formatTime(profile.created_at) || '-' }}
          </span>
        </div>
      </div>

      <div v-else-if="!loading" class="dash-empty">
        <span>Belum ada profil.</span>
        <el-button link type="primary" @click="router.push('/profiles')">Buat profil pertama</el-button>
      </div>
    </section>
  </div>
</template>
