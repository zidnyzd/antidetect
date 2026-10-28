<script setup>
import { computed, onMounted, onUnmounted, provide, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Fold, Expand, Refresh, Sunny, Moon } from '@element-plus/icons-vue'
import SideBar from './components/SideBar.vue'
import { api } from './api'
import { useRefreshSignal } from './refresh'

const STORAGE_KEY = 'antidetect.sidebar.collapsed'
const THEME_STORAGE_KEY = 'cloakdesk.theme'
const VALID_THEMES = ['auto', 'dark', 'light']

function readStoredTheme() {
  const raw = localStorage.getItem(THEME_STORAGE_KEY)
  return VALID_THEMES.includes(raw) ? raw : 'auto'
}

const mediaQuery =
  typeof window !== 'undefined' && typeof window.matchMedia === 'function'
    ? window.matchMedia('(prefers-color-scheme: dark)')
    : null

const route = useRoute()
const router = useRouter()
const collapsed = ref(localStorage.getItem(STORAGE_KEY) === '1')
const themeMode = ref(readStoredTheme())
const systemDark = ref(mediaQuery ? mediaQuery.matches : false)
const clock = ref('')
const apiOk = ref(false)
const spinning = ref(false)
const syncStatus = ref(null)
const syncSpinning = ref(false)
const refreshTick = useRefreshSignal()

const isDark = computed(
  () => themeMode.value === 'dark' || (themeMode.value === 'auto' && systemDark.value)
)

function syncDocumentTheme() {
  document.documentElement.classList.toggle('dark', isDark.value)
}

function setThemeMode(mode, notify = true) {
  const next = VALID_THEMES.includes(mode) ? mode : 'auto'
  themeMode.value = next
  localStorage.setItem(THEME_STORAGE_KEY, next)
  syncDocumentTheme()
  if (notify && typeof window !== 'undefined') {
    window.dispatchEvent(new CustomEvent('cloakdesk:theme-change', { detail: next }))
  }
}

function toggleTheme() {
  setThemeMode(isDark.value ? 'light' : 'dark')
}

const themeTooltip = computed(() => {
  const activeText =
    themeMode.value === 'auto'
      ? `Otomatis (${isDark.value ? 'Gelap' : 'Terang'})`
      : isDark.value
        ? 'Mode Gelap'
        : 'Mode Terang'
  const actionText = isDark.value ? 'Beralih ke Mode Terang' : 'Beralih ke Mode Gelap'
  return `${activeText} · ${actionText}`
})

syncDocumentTheme()

watch(isDark, () => {
  syncDocumentTheme()
})

provide('cloakdeskTheme', {
  themeMode,
  isDark,
  setThemeMode,
  toggleTheme,
})

const crumb = computed(() => route.meta.crumb || 'Ringkasan')
const section = computed(() => route.meta.section || 'Profil Browser')
const showSection = computed(() => section.value !== 'Dasbor')

const isSyncConfigured = computed(() => Boolean(syncStatus.value && syncStatus.value.configured))
const hasSyncAttention = computed(() =>
  Boolean(
    isSyncConfigured.value &&
      (syncStatus.value.last_sync_error || Number(syncStatus.value.conflict_count || 0) > 0)
  )
)
const outboxCount = computed(() => Number(syncStatus.value?.outbox_count || 0))

const syncDotClass = computed(() => {
  if (!isSyncConfigured.value) return 'idle'
  if (hasSyncAttention.value) return 'bad'
  if (outboxCount.value > 0) return 'warn'
  return 'ok'
})

const syncLabel = computed(() => {
  if (!isSyncConfigured.value) return 'Sync: Nonaktif'
  if (hasSyncAttention.value) return 'Sync: Perhatian'
  if (outboxCount.value > 0) return `Sync (${outboxCount.value})`
  return 'Sync: Aktif'
})

const syncTooltip = computed(() => {
  if (!isSyncConfigured.value) {
    return 'Sinkronisasi belum dikonfigurasi. Klik untuk mengatur di Pengaturan.'
  }
  const devName = syncStatus.value?.device_name || 'Perangkat lokal'
  const lastSync = syncStatus.value?.last_sync_at || 'Belum pernah'
  if (hasSyncAttention.value) {
    if (Number(syncStatus.value?.conflict_count || 0) > 0) {
      return `Perangkat: ${devName} · ${syncStatus.value.conflict_count} konflik sinkronisasi perlu diselesaikan`
    }
    return `Perangkat: ${devName} · Error: ${syncStatus.value?.last_sync_error}`
  }
  if (outboxCount.value > 0) {
    return `Perangkat: ${devName} · ${outboxCount.value} perubahan menunggu kirim · Terakhir sinkron: ${lastSync}`
  }
  return `Perangkat: ${devName} · Terakhir sinkron: ${lastSync}`
})

let clockTimer = null
let healthTimer = null
let syncTimer = null
let spinTimer = null

function toggleSidebar() {
  collapsed.value = !collapsed.value
  localStorage.setItem(STORAGE_KEY, collapsed.value ? '1' : '0')
}

function tickClock() {
  clock.value = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Jakarta',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(new Date())
}

async function checkHealth() {
  try {
    const data = await api.health()
    apiOk.value = data.status === 'ok'
  } catch {
    apiOk.value = false
  }
}

async function checkSyncStatus() {
  try {
    syncStatus.value = await api.syncStatus()
  } catch {
    // Biarkan state sebelumnya jika API sedang tidak terjangkau
  }
}

function goToSyncSettings() {
  router.push('/settings')
}

async function requestSync() {
  if (!isSyncConfigured.value) {
    router.push('/settings')
    return
  }
  if (syncSpinning.value) return
  syncSpinning.value = true
  try {
    await api.syncTrigger()
    await checkSyncStatus()
    refreshTick.value += 1
  } catch (error) {
    ElMessage.error(`Sinkronisasi gagal: ${error.message}`)
    await checkSyncStatus()
  } finally {
    syncSpinning.value = false
  }
}

function requestRefresh() {
  spinning.value = true
  clearTimeout(spinTimer)
  spinTimer = setTimeout(() => {
    spinning.value = false
  }, 500)
  refreshTick.value += 1
}

function handleSystemThemeChange(event) {
  systemDark.value = Boolean(event.matches)
  syncDocumentTheme()
}

function handleExternalThemeChange(event) {
  const next = event?.detail || readStoredTheme()
  if (VALID_THEMES.includes(next) && themeMode.value !== next) {
    themeMode.value = next
  }
  syncDocumentTheme()
}

function handleStorageChange(event) {
  if (event.key === THEME_STORAGE_KEY) {
    themeMode.value = readStoredTheme()
    syncDocumentTheme()
  }
}

watch(refreshTick, () => {
  checkSyncStatus()
})

onMounted(() => {
  if (mediaQuery) {
    systemDark.value = mediaQuery.matches
    if (typeof mediaQuery.addEventListener === 'function') {
      mediaQuery.addEventListener('change', handleSystemThemeChange)
    } else if (typeof mediaQuery.addListener === 'function') {
      mediaQuery.addListener(handleSystemThemeChange)
    }
  }
  window.addEventListener('cloakdesk:theme-change', handleExternalThemeChange)
  window.addEventListener('storage', handleStorageChange)
  syncDocumentTheme()
  tickClock()
  clockTimer = setInterval(tickClock, 1000)
  checkHealth()
  healthTimer = setInterval(checkHealth, 5000)
  checkSyncStatus()
  syncTimer = setInterval(checkSyncStatus, 10000)
})

onUnmounted(() => {
  if (mediaQuery) {
    if (typeof mediaQuery.removeEventListener === 'function') {
      mediaQuery.removeEventListener('change', handleSystemThemeChange)
    } else if (typeof mediaQuery.removeListener === 'function') {
      mediaQuery.removeListener(handleSystemThemeChange)
    }
  }
  window.removeEventListener('cloakdesk:theme-change', handleExternalThemeChange)
  window.removeEventListener('storage', handleStorageChange)
  clearInterval(clockTimer)
  clearInterval(healthTimer)
  clearInterval(syncTimer)
  clearTimeout(spinTimer)
})
</script>

<template>
  <div :class="['app-shell', { 'sidebar-collapsed': collapsed }]">
    <SideBar :collapsed="collapsed" />
    <div class="app-main">
      <header class="topbar">
        <el-tooltip :content="collapsed ? 'Buka sidebar' : 'Ciutkan sidebar'" placement="bottom" :show-after="200">
          <button type="button" class="hamburger" :aria-label="collapsed ? 'Buka sidebar' : 'Ciutkan sidebar'" @click="toggleSidebar">
            <el-icon><Expand v-if="collapsed" /><Fold v-else /></el-icon>
          </button>
        </el-tooltip>
        <nav class="breadcrumb" aria-label="Breadcrumb">
          <router-link to="/dashboard" class="crumb crumb-link">Dasbor</router-link>
          <template v-if="showSection">
            <span class="crumb-sep">/</span>
            <span class="crumb">{{ section }}</span>
          </template>
          <span class="crumb-sep">/</span>
          <span class="crumb current">{{ crumb }}</span>
        </nav>
        <div class="topbar-right">
          <div class="sync-topbar">
            <el-tooltip :content="syncTooltip" placement="bottom" :show-after="200">
              <button
                type="button"
                :class="['sync-badge', { 'is-inactive': !isSyncConfigured, 'is-warn': outboxCount > 0 && !hasSyncAttention, 'is-bad': hasSyncAttention }]"
                @click="goToSyncSettings"
              >
                <span :class="['status-dot', syncDotClass]"></span>
                <span>{{ syncLabel }}</span>
              </button>
            </el-tooltip>
            <el-tooltip
              v-if="isSyncConfigured"
              content="Sinkronkan sekarang"
              placement="bottom"
              :show-after="200"
            >
              <button
                type="button"
                class="icon-button sync-now-button"
                aria-label="Sinkronkan sekarang"
                :disabled="syncSpinning"
                @click="requestSync"
              >
                <el-icon :class="{ spinning: syncSpinning }"><Refresh /></el-icon>
              </button>
            </el-tooltip>
          </div>
          <el-tooltip content="Server lokal 127.0.0.1:53200" placement="bottom" :show-after="200">
            <div class="api-state">
              <span :class="['status-dot', apiOk ? 'ok' : 'bad']"></span>
              <span>API 53200</span>
            </div>
          </el-tooltip>
          <div class="topbar-clock">
            <span class="clock-time">{{ clock }}</span>
            <span class="clock-zone">WIB</span>
          </div>
          <el-tooltip :content="themeTooltip" placement="bottom" :show-after="200">
            <button
              type="button"
              class="icon-button theme-toggle-button"
              :aria-label="isDark ? 'Beralih ke mode terang' : 'Beralih ke mode gelap'"
              @click="toggleTheme"
            >
              <el-icon><Sunny v-if="isDark" /><Moon v-else /></el-icon>
            </button>
          </el-tooltip>
          <el-tooltip content="Muat ulang data" placement="bottom" :show-after="200">
            <button type="button" class="icon-button" aria-label="Muat ulang data" @click="requestRefresh">
              <el-icon :class="{ spinning }"><Refresh /></el-icon>
            </button>
          </el-tooltip>
        </div>
      </header>
      <main class="app-content">
        <router-view />
      </main>
    </div>
  </div>
</template>
