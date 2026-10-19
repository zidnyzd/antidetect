<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { DocumentCopy, Hide, Lock, Refresh, View } from '@element-plus/icons-vue'
import { api } from '../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  profile: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue'])

const items = ref([])
const revealed = ref(new Set())
const loading = ref(false)
const errorText = ref('')

const title = computed(() => `Password Tersimpan: ${props.profile?.name || ''}`)

async function load() {
  if (!props.profile) return
  loading.value = true
  errorText.value = ''
  revealed.value = new Set()
  try {
    const result = await api.savedPasswords(props.profile.profile_id)
    items.value = Array.isArray(result) ? result : []
  } catch (error) {
    items.value = []
    errorText.value = error.message
  } finally {
    loading.value = false
  }
}

function isRevealed(index) {
  return revealed.value.has(index)
}

function toggle(index) {
  const next = new Set(revealed.value)
  if (next.has(index)) next.delete(index)
  else next.add(index)
  revealed.value = next
}

async function copy(row) {
  if (!row.password) {
    ElMessage.warning('Password tidak terbaca')
    return
  }
  try {
    await navigator.clipboard.writeText(row.password)
    ElMessage.success('Password disalin')
  } catch (error) {
    ElMessage.error(`Gagal menyalin: ${error.message}`)
  }
}

function close() {
  emit('update:modelValue', false)
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      items.value = []
      errorText.value = ''
      load()
    }
  }
)
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    :title="title"
    width="820px"
    top="7vh"
    class="password-dialog"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="data-dialog-body">
      <div class="data-dialog-toolbar">
        <p class="dialog-note">
          <el-icon><Lock /></el-icon>
          Data didekripsi lokal, tidak dikirim ke mana pun
        </p>
        <el-button :icon="Refresh" :loading="loading" @click="load">Muat ulang</el-button>
      </div>

      <el-alert
        v-if="errorText"
        class="cookie-alert"
        type="error"
        :closable="false"
        show-icon
        :title="errorText"
      />

      <el-table v-loading="loading" class="data-table password-table" :data="items" max-height="420">
        <el-table-column label="Situs" min-width="240">
          <template #default="{ row }">
            <span class="cell-main" :title="row.origin_url">{{ row.origin_url || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Username" min-width="160">
          <template #default="{ row }">
            <span class="cell-sub">{{ row.username || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="Password" width="210">
          <template #default="{ row, $index }">
            <div class="password-cell">
              <span
                :class="[
                  'password-value',
                  isRevealed($index) ? (row.password ? 'is-visible' : 'is-empty') : 'is-masked',
                ]"
              >
                {{ isRevealed($index) ? row.password || 'Tidak terbaca' : '••••••••' }}
              </span>
              <el-tooltip
                :content="isRevealed($index) ? 'Sembunyikan password' : 'Tampilkan password'"
                placement="top"
                :show-after="200"
              >
                <el-button
                  class="icon-action"
                  size="small"
                  :icon="isRevealed($index) ? Hide : View"
                  :aria-label="isRevealed($index) ? 'Sembunyikan password' : 'Tampilkan password'"
                  @click="toggle($index)"
                />
              </el-tooltip>
              <el-tooltip content="Salin password" placement="top" :show-after="200">
                <el-button
                  class="icon-action"
                  size="small"
                  :icon="DocumentCopy"
                  aria-label="Salin password"
                  @click="copy(row)"
                />
              </el-tooltip>
            </div>
          </template>
        </el-table-column>
        <template #empty>
          <div class="data-empty">Belum ada password tersimpan</div>
        </template>
      </el-table>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="close">Tutup</el-button>
      </div>
    </template>
  </el-dialog>
</template>
