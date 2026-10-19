import { createRouter, createWebHashHistory } from 'vue-router'
import Dashboard from './views/Dashboard.vue'
import Profiles from './views/Profiles.vue'
import Proxies from './views/Proxies.vue'
import Extensions from './views/Extensions.vue'
import RecycleBin from './views/RecycleBin.vue'
import Settings from './views/Settings.vue'
import ApiDocs from './views/ApiDocs.vue'
import Logs from './views/Logs.vue'

export default createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/dashboard' },
    {
      path: '/dashboard',
      name: 'dashboard',
      component: Dashboard,
      meta: { section: 'Dasbor', crumb: 'Ringkasan' },
    },
    {
      path: '/profiles',
      name: 'profiles',
      component: Profiles,
      meta: { section: 'Profil Browser', crumb: 'Daftar Profil' },
    },
    {
      path: '/recycle',
      name: 'recycle',
      component: RecycleBin,
      meta: { section: 'Profil Browser', crumb: 'Keranjang Sampah' },
    },
    {
      path: '/proxies',
      name: 'proxies',
      component: Proxies,
      meta: { section: 'Profil Browser', crumb: 'Proxy' },
    },
    {
      path: '/extensions',
      name: 'extensions',
      component: Extensions,
      meta: { section: 'Profil Browser', crumb: 'Extension' },
    },
    {
      path: '/settings',
      name: 'settings',
      component: Settings,
      meta: { section: 'Sistem', crumb: 'Pengaturan' },
    },
    {
      path: '/api-docs',
      name: 'api-docs',
      component: ApiDocs,
      meta: { section: 'Sistem', crumb: 'API' },
    },
    {
      path: '/log',
      name: 'logs',
      component: Logs,
      meta: { section: 'Sistem', crumb: 'Log' },
    },
    { path: '/:pathMatch(.*)*', redirect: '/dashboard' },
  ],
})
