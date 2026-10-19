<script setup>
import { Connection, Monitor, Setting } from '@element-plus/icons-vue'
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <div class="logo">A</div>
      <div class="brand-text">
        <strong>Antidetect</strong>
        <small>prototype v0.1</small>
      </div>
    </div>
    <nav>
      <router-link to="/" class="nav-item"><el-icon><Monitor /></el-icon> Profil</router-link>
      <router-link to="/proxies" class="nav-item"><el-icon><Connection /></el-icon> Proxy</router-link>
      <router-link to="/settings" class="nav-item"><el-icon><Setting /></el-icon> Pengaturan</router-link>
    </nav>
    <div class="sidebar-foot">mirip ixBrowser · Linux</div>
  </aside>
</template>
