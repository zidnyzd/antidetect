<script setup>
import { ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete, Refresh } from '@element-plus/icons-vue'
import { api } from '../api'

const props = defineProps({
  modelValue: Boolean,
  proxy: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'cleared'])

const rows = ref([])
const total = ref(0)
const loading = ref(false)
const clearing = ref(false)

function hostLabel() {
  const proxy = props.proxy
  if (!proxy) return 'proxy'
  return `${proxy.proxy_ip || '-'}:${proxy.proxy_port ?? '-'}`
}

async function load() {
  if (!props.proxy?.id) return
  loading.value = true
  try {
    const result = await api.proxyCheckHistory({ proxy_id: props.proxy.id, limit: 100 })
    rows.value = result.data || []
    total.value = result.total || 0
  } catch (error) {
    ElMessage.error(`Gagal memuat riwayat: ${error.message}`)
  } finally {
    loading.value = false
  }
}

async function clearHistory() {
  if (!props.proxy?.id || clearing.value) return
  try {
    await ElMessageBox.confirm(
      `Hapus semua riwayat cek proxy ${hostLabel()}?`,
      'Bersihkan Riwayat',
      {
        type: 'warning',
        confirmButtonText: 'Hapus',
        cancelButtonText: 'Batal',
        confirmButtonClass: 'el-button--danger',
      }
    )
  } catch {
    return
  }
  clearing.value = true
  try {
    const result = await api.clearProxyCheckHistory(props.proxy.id)
    ElMessage.success(`${result.count} baris riwayat dihapus`)
    await load()
    emit('cleared')
  } catch (error) {
    ElMessage.error(`Gagal membersihkan riwayat: ${error.message}`)
  } finally {
    clearing.value = false
  }
}

function close() {
  emit('update:modelValue', false)
}

watch(
  () => props.modelValue,
  (value) => {
    if (value) load()
  },
  { immediate: true }
)
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    title="Riwayat Cek Proxy"
    width="720px"
    top="10vh"
    class="proxy-history-dialog"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="history-head">
      <span class="mono">{{ hostLabel() }}</span>
      <span class="history-count">{{ total }} pemeriksaan</span>
    </div>

    <el-table
      v-loading="loading"
      element-loading-text="Memuat riwayat..."
      class="data-table proxy-history-table"
      :data="rows"
      row-key="id"
      max-height="360"
    >
      <el-table-column label="Waktu" width="150">
        <template #default="{ row }">
          <span class="cell-sub">{{ row.checked_at || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="Hasil" width="90">
        <template #default="{ row }">
          <span :class="['proxy-check-result', row.ok ? 'is-ok' : 'is-fail']">
            {{ row.ok ? 'Berhasil' : 'Gagal' }}
          </span>
        </template>
      </el-table-column>
      <el-table-column label="IP" width="140">
        <template #default="{ row }">
          <span class="mono">{{ row.ip || '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="Latensi" width="100">
        <template #default="{ row }">
          <span class="mono">{{ row.latency_ms != null ? `${row.latency_ms} ms` : '-' }}</span>
        </template>
      </el-table-column>
      <el-table-column label="Pesan" min-width="200">
        <template #default="{ row }">
          <span class="cell-sub" :title="row.error || ''">{{ row.error || '-' }}</span>
        </template>
      </el-table-column>

      <template #empty>
        <div class="table-empty">
          <div class="empty-title">Belum ada riwayat</div>
          <p class="empty-text">Riwayat terisi setiap kali proxy diuji dari halaman Proxy.</p>
        </div>
      </template>
    </el-table>

    <template #footer>
      <div class="dialog-footer">
        <el-button :icon="Refresh" :loading="loading" @click="load">Muat ulang</el-button>
        <el-button :icon="Delete" :loading="clearing" class="danger-action" @click="clearHistory">
          Bersihkan riwayat
        </el-button>
        <div class="footer-spacer"></div>
        <el-button @click="close">Tutup</el-button>
      </div>
    </template>
  </el-dialog>
</template>
