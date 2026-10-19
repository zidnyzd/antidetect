import { createRouter, createWebHashHistory } from 'vue-router'
import Profiles from './views/Profiles.vue'
import Proxies from './views/Proxies.vue'
import RecycleBin from './views/RecycleBin.vue'
import Settings from './views/Settings.vue'

export default createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'profiles', component: Profiles, meta: { crumb: 'Daftar Profil' } },
    { path: '/recycle', name: 'recycle', component: RecycleBin, meta: { crumb: 'Keranjang Sampah' } },
    { path: '/proxies', name: 'proxies', component: Proxies, meta: { crumb: 'Proxy' } },
    { path: '/settings', name: 'settings', component: Settings, meta: { crumb: 'Pengaturan' } },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
