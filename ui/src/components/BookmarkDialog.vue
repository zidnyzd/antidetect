<script setup>
import { computed, ref, watch } from 'vue'
import { Link, Refresh, Search } from '@element-plus/icons-vue'
import { api } from '../api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  profile: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue'])

const items = ref([])
const query = ref('')
const loading = ref(false)
const errorText = ref('')

const title = computed(() => `Bookmark: ${props.profile?.name || ''}`)
const filtered = computed(() => {
  const needle = query.value.trim().toLowerCase()
  if (!needle) return items.value
  return items.value.filter((item) =>
    [item.name, item.url, item.folder].some((value) =>
      String(value || '').toLowerCase().includes(needle)
    )
  )
})

function rowKey(row) {
  return `${row.folder}|${row.id}|${row.url}`
}

async function load() {
  if (!props.profile) return
  loading.value = true
  errorText.value = ''
  try {
    const result = await api.bookmarks(props.profile.profile_id)
    items.value = Array.isArray(result) ? result : []
  } catch (error) {
    items.value = []
    errorText.value = error.message
  } finally {
    loading.value = false
  }
}

function openUrl(url) {
  if (!url) return
  window.open(url, '_blank', 'noopener,noreferrer')
}

function close() {
  emit('update:modelValue', false)
}

watch(
  () => props.modelValue,
  (open) => {
    if (open) {
      items.value = []
      query.value = ''
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
    width="780px"
    top="7vh"
    class="bookmark-dialog"
    :close-on-click-modal="false"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <div class="data-dialog-body">
      <div class="data-dialog-toolbar">
        <el-input v-model="query" class="search-input" placeholder="Cari nama atau URL" clearable>
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>
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

      <el-table
        v-loading="loading"
        class="data-table bookmark-table"
        :data="filtered"
        :row-key="rowKey"
        max-height="420"
      >
        <el-table-column label="Nama" min-width="180">
          <template #default="{ row }">
            <span class="cell-main">{{ row.name }}</span>
          </template>
        </el-table-column>
        <el-table-column label="URL" min-width="280">
          <template #default="{ row }">
            <button type="button" class="bookmark-link" :title="row.url" @click="openUrl(row.url)">
              {{ row.url }}
            </button>
          </template>
        </el-table-column>
        <el-table-column label="Folder" width="170">
          <template #default="{ row }">
            <span class="cell-sub">{{ row.folder || '-' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="" width="64" align="right">
          <template #default="{ row }">
            <el-tooltip content="Buka di browser" placement="top" :show-after="200">
              <el-button
                class="icon-action"
                size="small"
                :icon="Link"
                aria-label="Buka URL"
                @click="openUrl(row.url)"
              />
            </el-tooltip>
          </template>
        </el-table-column>
        <template #empty>
          <div class="data-empty">
            {{ items.length ? 'Tidak ada bookmark yang cocok' : 'Belum ada bookmark' }}
          </div>
        </template>
      </el-table>

      <p class="dialog-note">{{ filtered.length }} dari {{ items.length }} bookmark</p>
    </div>

    <template #footer>
      <div class="dialog-footer">
        <el-button @click="close">Tutup</el-button>
      </div>
    </template>
  </el-dialog>
</template>
