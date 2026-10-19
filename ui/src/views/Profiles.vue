<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Refresh, Search } from '@element-plus/icons-vue'
import { api } from '../api'
import CreateProfileDialog from '../components/CreateProfileDialog.vue'
import ProfileDrawer from '../components/ProfileDrawer.vue'

const profiles = ref([])
const opened = ref(new Set())
const groups = ref([])
const loading = ref(false)
const search = ref('')
const groupFilter = ref('all')
const showCreate = ref(false)
const drawerProfile = ref(null)
let poll

const filtered = computed(() => {
  let list = profiles.value
  if (groupFilter.value !== 'all') list = list.filter((p) => p.group_id === groupFilter.value)
  const q = search.value.trim().toLowerCase()
  if (q) list = list.filter((p) => p.name.toLowerCase().includes(q))
  return list
})

const openedCount = computed(() => profiles.value.filter((p) => opened.value.has(p.profile_id)).length)

async function refresh() {
  loading.value = true
  try {
    const [list, openList, groupList] = await Promise.all([api.profiles(), api.openedList(), api.groups()])
    profiles.value = list.data
    opened.value = new Set(openList.map((o) => o.profile_id))
    groups.value = groupList.data
  } catch (error) {
    ElMessage.error(`Gagal memuat: ${error.message}`)
  } finally {
    loading.value = false
  }
}

function isOpen(p) {
  return opened.value.has(p.profile_id)
}

function proxyLabel(p) {
  const cfg = p.proxy_config || {}
  if (!cfg.proxy_type || cfg.proxy_type === 'direct') return 'Direct'
  return cfg.proxy_type.toUpperCase()
}

async function open(p) {
  try {
    await api.openProfile(p.profile_id)
    ElMessage.success(`"${p.name}" dibuka`)
    refresh()
  } catch (error) {
    ElMessage.error(`Gagal membuka: ${error.message}`)
  }
}

async function close(p) {
  try {
    await api.closeProfile(p.profile_id)
    ElMessage.success(`"${p.name}" ditutup`)
    refresh()
  } catch (error) {
    ElMessage.error(`Gagal menutup: ${error.message}`)
  }
}

async function remove(p) {
  try {
    await ElMessageBox.confirm(`Hapus profil "${p.name}"?`, 'Konfirmasi', {
      type: 'warning',
      confirmButtonText: 'Hapus',
      cancelButtonText: 'Batal',
    })
  } catch {
    return
  }
  try {
    await api.deleteProfile(p.profile_id)
    ElMessage.success('Profil dihapus')
    refresh()
  } catch (error) {
    ElMessage.error(`Gagal menghapus: ${error.message}`)
  }
}

onMounted(() => {
  refresh()
  poll = setInterval(refresh, 5000)
})
onUnmounted(() => clearInterval(poll))
</script>

<template>
  <div class="page">
    <header class="toolbar">
      <el-input v-model="search" placeholder="Cari profil..." clearable style="max-width: 260px">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
      <el-select v-model="groupFilter" style="width: 160px">
        <el-option label="Semua Grup" value="all" />
        <el-option v-for="g in groups" :key="g.id" :label="g.title" :value="g.id" />
      </el-select>
      <span class="counter">{{ openedCount }}/{{ profiles.length }} terbuka</span>
      <span class="spacer"></span>
      <el-button :icon="Refresh" circle title="Muat ulang" @click="refresh" />
      <el-button type="primary" :icon="Plus" @click="showCreate = true">Buat Profil</el-button>
    </header>

    <div v-loading="loading" class="grid">
      <template v-if="filtered.length">
        <article v-for="p in filtered" :key="p.profile_id" class="card" @click="drawerProfile = p">
          <div class="card-head">
            <div class="avatar" :style="{ background: p.color || '#4c7dff' }">
              {{ (p.name || '?').slice(0, 1).toUpperCase() }}
            </div>
            <div class="meta">
              <strong>{{ p.name }}</strong>
              <small>{{ (p.fingerprint_config || {}).platform || 'Windows' }} · {{ proxyLabel(p) }}</small>
            </div>
            <span :class="['status', isOpen(p) ? 'on' : 'off']">{{ isOpen(p) ? 'Terbuka' : 'Tertutup' }}</span>
          </div>
          <div class="card-foot" @click.stop>
            <el-button v-if="!isOpen(p)" type="primary" size="small" @click="open(p)">Buka</el-button>
            <el-button v-else size="small" @click="close(p)">Tutup</el-button>
            <el-button size="small" text type="danger" @click="remove(p)">Hapus</el-button>
          </div>
        </article>
      </template>
      <el-empty v-else description="Belum ada profil" />
    </div>

    <CreateProfileDialog v-model="showCreate" :groups="groups" @created="refresh" />
    <ProfileDrawer v-model="drawerProfile" :opened="drawerProfile ? isOpen(drawerProfile) : false" @changed="refresh" />
  </div>
</template>
