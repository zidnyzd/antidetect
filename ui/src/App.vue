<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { Fold, Expand, Refresh } from '@element-plus/icons-vue'
import SideBar from './components/SideBar.vue'
import { api } from './api'
import { useRefreshSignal } from './refresh'

const STORAGE_KEY = 'antidetect.sidebar.collapsed'

const route = useRoute()
const collapsed = ref(localStorage.getItem(STORAGE_KEY) === '1')
const clock = ref('')
const apiOk = ref(false)
const spinning = ref(false)
const refreshTick = useRefreshSignal()

const crumb = computed(() => route.meta.crumb || 'Daftar Profil')

let clockTimer = null
let healthTimer = null
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

function requestRefresh() {
  spinning.value = true
  clearTimeout(spinTimer)
  spinTimer = setTimeout(() => {
    spinning.value = false
  }, 500)
  refreshTick.value += 1
}

onMounted(() => {
  tickClock()
  clockTimer = setInterval(tickClock, 1000)
  checkHealth()
  healthTimer = setInterval(checkHealth, 5000)
})

onUnmounted(() => {
  clearInterval(clockTimer)
  clearInterval(healthTimer)
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
          <span class="crumb">Dasbor</span>
          <span class="crumb-sep">/</span>
          <span class="crumb">Profil Browser</span>
          <span class="crumb-sep">/</span>
          <span class="crumb current">{{ crumb }}</span>
        </nav>
        <div class="topbar-right">
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
