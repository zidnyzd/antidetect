<script setup>
import { computed } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'

const props = defineProps({
  modelValue: { type: Object, default: null },
  opened: Boolean,
})
const emit = defineEmits(['update:modelValue', 'changed'])

const profile = computed(() => props.modelValue)
const fp = computed(() => props.modelValue?.fingerprint_config || {})
const proxy = computed(() => props.modelValue?.proxy_config || {})

function proxyText() {
  const p = proxy.value
  if (!p.proxy_type || p.proxy_type === 'direct') return 'Direct (tanpa proxy)'
  return `${p.proxy_type.toUpperCase()} · ${p.proxy_ip}:${p.proxy_port}`
}

async function toggle() {
  if (!profile.value) return
  try {
    if (props.opened) await api.closeProfile(profile.value.profile_id)
    else await api.openProfile(profile.value.profile_id)
    ElMessage.success(props.opened ? 'Ditutup' : 'Dibuka')
    emit('changed')
  } catch (error) {
    ElMessage.error(error.message)
  }
}

async function remove() {
  if (!profile.value) return
  try {
    await ElMessageBox.confirm(`Hapus profil "${profile.value.name}"?`, 'Konfirmasi', { type: 'warning' })
  } catch {
    return
  }
  await api.deleteProfile(profile.value.profile_id)
  ElMessage.success('Dihapus')
  emit('changed')
  emit('update:modelValue', null)
}
</script>

<template>
  <el-drawer :model-value="!!profile" size="420px" @update:model-value="emit('update:modelValue', null)">
    <template #header><strong>{{ profile?.name }}</strong></template>
    <template v-if="profile">
      <el-descriptions :column="1" border size="small">
        <el-descriptions-item label="ID">{{ profile.profile_id }}</el-descriptions-item>
        <el-descriptions-item label="Status">{{ opened ? 'Terbuka' : 'Tertutup' }}</el-descriptions-item>
        <el-descriptions-item label="Platform">
          {{ fp.platform || 'Windows' }} {{ fp.system_version || '' }}
        </el-descriptions-item>
        <el-descriptions-item label="Cores / Memory">
          {{ fp.hardware_concurrency || '-' }} / {{ fp.device_memory || '-' }} GB
        </el-descriptions-item>
        <el-descriptions-item label="Timezone">{{ fp.timezone || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Bahasa">{{ fp.language || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Proxy">{{ proxyText() }}</el-descriptions-item>
        <el-descriptions-item label="Dibuat">{{ profile.created_at }}</el-descriptions-item>
      </el-descriptions>
      <div class="drawer-actions">
        <el-button type="primary" @click="toggle">{{ opened ? 'Tutup' : 'Buka' }}</el-button>
        <el-button type="danger" plain @click="remove">Hapus</el-button>
      </div>
    </template>
  </el-drawer>
</template>
