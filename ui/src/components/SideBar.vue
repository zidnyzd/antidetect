<script setup>
import { useRoute } from 'vue-router'
import { Box, Connection, Delete, Monitor, Setting } from '@element-plus/icons-vue'

defineProps({ collapsed: Boolean })

const route = useRoute()

const browserItems = [
  { path: '/', label: 'Daftar Profil', icon: Monitor },
  { path: '/recycle', label: 'Keranjang Sampah', icon: Delete },
  { path: '/proxies', label: 'Proxy', icon: Connection },
  { path: '/extensions', label: 'Extension', icon: Box },
]
const systemItems = [{ path: '/settings', label: 'Pengaturan', icon: Setting }]

function isActive(path) {
  return route.path === path
}
</script>

<template>
  <aside :class="['ix-sidebar', { collapsed }]">
    <div class="side-logo">
      <div class="brand-mark">A</div>
      <span v-if="!collapsed" class="brand-word">Antidetect</span>
    </div>

    <nav class="side-nav">
      <div v-if="!collapsed" class="side-section">Browser Profile</div>
      <div v-else class="side-divider"></div>

      <el-tooltip
        v-for="item in browserItems"
        :key="item.path"
        :content="item.label"
        placement="right"
        :disabled="!collapsed"
        :show-after="200"
      >
        <router-link :to="item.path" :class="['side-item', { active: isActive(item.path) }]">
          <el-icon class="side-icon"><component :is="item.icon" /></el-icon>
          <span v-if="!collapsed" class="side-label">{{ item.label }}</span>
        </router-link>
      </el-tooltip>

      <div v-if="!collapsed" class="side-section">Sistem</div>
      <div v-else class="side-divider"></div>

      <el-tooltip
        v-for="item in systemItems"
        :key="item.path"
        :content="item.label"
        placement="right"
        :disabled="!collapsed"
        :show-after="200"
      >
        <router-link :to="item.path" :class="['side-item', { active: isActive(item.path) }]">
          <el-icon class="side-icon"><component :is="item.icon" /></el-icon>
          <span v-if="!collapsed" class="side-label">{{ item.label }}</span>
        </router-link>
      </el-tooltip>
    </nav>

    <el-tooltip content="fingerprint-chromium 150, siap" placement="right" :disabled="!collapsed" :show-after="200">
      <div :class="['side-engine', { compact: collapsed }]">
        <template v-if="!collapsed">
          <div class="engine-label">Engine</div>
          <div class="engine-name">fingerprint-chromium 150</div>
        </template>
        <div class="engine-state">
          <span class="engine-dot"></span>
          <span v-if="!collapsed">siap</span>
        </div>
      </div>
    </el-tooltip>
  </aside>
</template>
