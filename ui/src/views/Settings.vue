<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api, UI_VERSION } from '../api'
import { useOnRefresh, useRefreshSignal } from '../refresh'

const health = ref(null)
const healthError = ref('')
const profileTotal = ref(null)
const profilesError = ref('')
const engine = ref(null)
const engineError = ref('')
const syncInfo = ref(null)
const syncError = ref('')
const conflicts = ref([])
const editingSync = ref(false)
const configureBusy = ref(false)
const triggerBusy = ref(false)
const resolvingConflictId = ref('')
const loading = ref(true)
const refreshTick = useRefreshSignal()

const syncForm = reactive({
  server_url: '',
  enrollment_token: '',
  device_name: '',
  passphrase: '',
})

const apiBase = computed(() => `${window.location.origin}/api/v2/`)
const isSyncConfigured = computed(() => Boolean(syncInfo.value && syncInfo.value.configured))
const conflictCount = computed(() => Number(syncInfo.value?.conflict_count || conflicts.value.length || 0))

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

async function loadEngine() {
  try {
    engine.value = await api.engineInfo()
    engineError.value = ''
  } catch (error) {
    engine.value = null
    engineError.value = error.message
  }
}

async function loadSync() {
  try {
    const status = await api.syncStatus()
    syncInfo.value = status
    syncError.value = ''
    if (!syncForm.device_name && status?.device_name) {
      syncForm.device_name = status.device_name
    }
    if (!syncForm.server_url && status?.server_url) {
      syncForm.server_url = status.server_url
    }
    if (Number(status?.conflict_count || 0) > 0) {
      conflicts.value = (await api.syncConflicts()) || []
    } else {
      conflicts.value = []
    }
  } catch (error) {
    syncInfo.value = null
    syncError.value = error.message
    conflicts.value = []
  }
}

async function submitSyncConfigure() {
  const serverUrl = syncForm.server_url.trim()
  const enrollmentToken = syncForm.enrollment_token.trim()
  const deviceName = syncForm.device_name.trim()
  const passphrase = syncForm.passphrase

  if (!serverUrl) {
    ElMessage.warning('URL Server wajib diisi')
    return
  }
  if (!enrollmentToken) {
    ElMessage.warning('Token Pendaftaran wajib diisi')
    return
  }
  if (!passphrase) {
    ElMessage.warning('Frasa Sandi Enkripsi wajib diisi')
    return
  }

  configureBusy.value = true
  try {
    await api.syncConfigure({
      server_url: serverUrl,
      enrollment_token: enrollmentToken,
      device_name: deviceName || undefined,
      passphrase,
    })
    ElMessage.success('Server sinkronisasi berhasil dihubungkan')
    editingSync.value = false
    syncForm.enrollment_token = ''
    syncForm.passphrase = ''
    await loadSync()
    await loadProfileTotal()
    refreshTick.value += 1
  } catch (error) {
    ElMessage.error(`Gagal menghubungkan server: ${error.message}`)
  } finally {
    configureBusy.value = false
  }
}

async function runSyncNow() {
  triggerBusy.value = true
  try {
    const result = await api.syncTrigger()
    ElMessage.success(
      `Sinkronisasi selesai (${result?.pushed ?? 0} dikirim, ${result?.pulled ?? 0} diterima)`
    )
    await loadSync()
    await loadProfileTotal()
    refreshTick.value += 1
  } catch (error) {
    ElMessage.error(`Sinkronisasi gagal: ${error.message}`)
    await loadSync()
  } finally {
    triggerBusy.value = false
  }
}

function openReconfigure() {
  if (syncInfo.value) {
    syncForm.server_url = syncInfo.value.server_url || syncForm.server_url
    syncForm.device_name = syncInfo.value.device_name || syncForm.device_name
  }
  editingSync.value = true
}

function cancelReconfigure() {
  editingSync.value = false
}

async function resolveConflict(conflictId, resolution) {
  resolvingConflictId.value = conflictId
  try {
    await api.syncConflictResolve({
      conflict_id: conflictId,
      resolution,
    })
    ElMessage.success(
      resolution === 'keep_local'
        ? 'Konflik diselesaikan dengan versi lokal'
        : 'Konflik diselesaikan dengan versi server'
    )
    await loadSync()
    refreshTick.value += 1
  } catch (error) {
    ElMessage.error(`Gagal menyelesaikan konflik: ${error.message}`)
  } finally {
    resolvingConflictId.value = ''
  }
}

async function load() {
  loading.value = true
  await Promise.all([loadHealth(), loadProfileTotal(), loadEngine(), loadSync()])
  loading.value = false
}

onMounted(load)
useOnRefresh(() => load())
</script>

<template>
  <div v-loading="loading" element-loading-text="Memuat informasi..." class="settings-page">
    <div class="settings-grid">
      <section class="info-card sync-card">
        <div class="sync-card-head">
          <div class="info-label">Sinkronisasi Antar Perangkat</div>
          <span
            v-if="isSyncConfigured && !editingSync"
            :class="['sync-pill', syncInfo.last_sync_error ? 'is-bad' : 'is-ok']"
          >
            {{ syncInfo.last_sync_error ? 'Perlu Perhatian' : 'Terhubung' }}
          </span>
          <span v-else class="sync-pill is-idle">Belum Dikonfigurasi</span>
        </div>

        <template v-if="!isSyncConfigured || editingSync">
          <p class="info-help sync-intro">
            Hubungkan perangkat ini ke server sinkronisasi menggunakan token pendaftaran satu kali dan frasa sandi enkripsi bersama.
          </p>
          <el-form label-position="top" class="sync-form" @submit.prevent="submitSyncConfigure">
            <div class="sync-form-grid">
              <el-form-item label="URL Server" required>
                <el-input
                  v-model="syncForm.server_url"
                  placeholder="https://sync.example.com atau http://127.0.0.1:53210"
                />
              </el-form-item>
              <el-form-item label="Nama Perangkat">
                <el-input
                  v-model="syncForm.device_name"
                  placeholder="Contoh: Laptop-Utama"
                />
              </el-form-item>
              <el-form-item label="Token Pendaftaran (Enrollment Token)" required>
                <el-input
                  v-model="syncForm.enrollment_token"
                  placeholder="ad_enroll_..."
                />
              </el-form-item>
              <el-form-item label="Frasa Sandi Enkripsi (Passphrase)" required>
                <el-input
                  v-model="syncForm.passphrase"
                  type="password"
                  show-password
                  placeholder="Frasa sandi enkripsi cookie dan proxy"
                />
              </el-form-item>
            </div>
            <div class="sync-actions">
              <el-button type="primary" :loading="configureBusy" @click="submitSyncConfigure">
                Hubungkan Server
              </el-button>
              <el-button v-if="isSyncConfigured && editingSync" @click="cancelReconfigure">
                Batal
              </el-button>
            </div>
          </el-form>
        </template>

        <template v-else>
          <div class="sync-details-grid">
            <div class="sync-detail-item">
              <span class="sync-detail-label">URL Server</span>
              <span class="sync-detail-value mono">{{ syncInfo.server_url || '-' }}</span>
            </div>
            <div class="sync-detail-item">
              <span class="sync-detail-label">Nama Perangkat</span>
              <span class="sync-detail-value">{{ syncInfo.device_name || '-' }}</span>
            </div>
            <div class="sync-detail-item">
              <span class="sync-detail-label">ID Perangkat</span>
              <span class="sync-detail-value mono">{{ syncInfo.device_id || '-' }}</span>
            </div>
            <div class="sync-detail-item">
              <span class="sync-detail-label">Terakhir Sinkron</span>
              <span class="sync-detail-value">{{ syncInfo.last_sync_at || 'Belum pernah' }}</span>
            </div>
            <div class="sync-detail-item">
              <span class="sync-detail-label">Antrean Perubahan Belum Terkirim (Outbox)</span>
              <span class="sync-detail-value">{{ syncInfo.outbox_count ?? 0 }} item</span>
            </div>
            <div class="sync-detail-item">
              <span class="sync-detail-label">Status Koneksi</span>
              <span class="sync-detail-value health-line">
                <span :class="['status-dot', syncInfo.last_sync_error ? 'bad' : 'ok']"></span>
                <span>{{ syncInfo.last_sync_error ? `Gangguan: ${syncInfo.last_sync_error}` : 'Tersambung' }}</span>
              </span>
            </div>
          </div>

          <div class="sync-actions">
            <el-button type="primary" :loading="triggerBusy" @click="runSyncNow">
              Sinkronkan Sekarang
            </el-button>
            <el-button @click="openReconfigure">
              Ubah Konfigurasi / Hubungkan Ulang
            </el-button>
          </div>
        </template>

        <p v-if="syncError" class="info-help is-error">Gagal memuat status sinkronisasi: {{ syncError }}</p>
      </section>

      <section v-if="conflictCount > 0" class="info-card sync-conflict-card">
        <div class="sync-card-head">
          <div class="info-label">Konflik Sinkronisasi ({{ conflictCount }})</div>
          <span class="sync-pill is-bad">Perlu Tindakan</span>
        </div>
        <p class="info-help">
          Terdapat perbedaan perubahan antar perangkat. Pilih versi yang ingin dipertahankan untuk setiap item berikut.
        </p>
        <ul class="conflict-list">
          <li v-for="item in conflicts" :key="item.conflict_id" class="conflict-item">
            <div class="conflict-info">
              <div class="conflict-title">
                <span class="conflict-type">{{ item.entity_type }}</span>
                <strong>{{ item.entity_name || item.entity_uuid }}</strong>
                <span class="conflict-reason">{{ item.reason }}</span>
              </div>
              <div class="conflict-meta">
                <span class="mono">{{ item.entity_uuid }}</span>
                <span>·</span>
                <span>{{ item.created_at }}</span>
              </div>
            </div>
            <div class="conflict-actions">
              <el-button
                size="small"
                type="primary"
                :loading="resolvingConflictId === item.conflict_id"
                @click="resolveConflict(item.conflict_id, 'keep_local')"
              >
                Gunakan Versi Lokal
              </el-button>
              <el-button
                size="small"
                :loading="resolvingConflictId === item.conflict_id"
                @click="resolveConflict(item.conflict_id, 'keep_server')"
              >
                Gunakan Versi Server
              </el-button>
            </div>
          </li>
        </ul>
      </section>

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

      <section class="info-card engine-card">
        <div class="info-label">Engine</div>
        <div class="info-value mono">{{ engine ? engine.path : 'Tidak tersedia' }}</div>
        <p class="info-help">
          <template v-if="engine">
            {{ engine.version || 'Versi tidak terbaca' }} · {{ engine.kernels.length }} kernel terpasang
          </template>
          <template v-else-if="engineError">engine-info gagal: {{ engineError }}</template>
          <template v-else>Menunggu engine-info.</template>
        </p>
        <ul v-if="engine" class="kernel-list">
          <li v-for="kernel in engine.kernels" :key="kernel.id || kernel.path" class="kernel-item">
            <div class="kernel-line">
              <span class="kernel-name">{{ kernel.name || kernel.id }}</span>
              <span class="kernel-version">{{ kernel.version || 'Versi tidak terbaca' }}</span>
              <span v-if="kernel.active" class="kernel-badge">Aktif</span>
            </div>
            <span class="kernel-path mono">{{ kernel.path }}</span>
          </li>
        </ul>
        <p v-if="engine && engine.kernels.length === 1" class="info-help">Hanya satu kernel terpasang.</p>
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
