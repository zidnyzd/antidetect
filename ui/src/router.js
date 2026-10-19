import { createRouter, createWebHashHistory } from 'vue-router'
import Profiles from './views/Profiles.vue'
import Proxies from './views/Proxies.vue'
import Settings from './views/Settings.vue'

export default createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', component: Profiles },
    { path: '/proxies', component: Proxies },
    { path: '/settings', component: Settings },
  ],
})
