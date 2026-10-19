<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import SideBar from './components/SideBar.vue'

const clock = ref('')
const apiOk = ref(false)
let clockTimer
let healthTimer

async function checkHealth() {
  try {
    const res = await fetch('/health')
    apiOk.value = res.ok
  } catch {
    apiOk.value = false
  }
}

onMounted(() => {
  const tick = () => {
    clock.value = new Date().toLocaleTimeString('id-ID', { hour12: false })
  }
  tick()
  clockTimer = setInterval(tick, 1000)
  checkHealth()
  healthTimer = setInterval(checkHealth, 5000)
})

onUnmounted(() => {
  clearInterval(clockTimer)
  clearInterval(healthTimer)
})
</script>

<template>
  <div class="layout">
    <SideBar />
    <main class="content">
      <router-view />
    </main>
    <footer class="statusbar">
      <span :class="['dot', apiOk ? 'ok' : 'bad']"></span>
      <span>API 127.0.0.1:53200 {{ apiOk ? 'tersambung' : 'terputus' }}</span>
      <span class="spacer"></span>
      <span class="clock">{{ clock }}</span>
    </footer>
  </div>
</template>
