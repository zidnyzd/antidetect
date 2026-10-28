import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import id from 'element-plus/es/locale/lang/id'
import 'element-plus/dist/index.css'
import 'element-plus/theme-chalk/dark/css-vars.css'
import App from './App.vue'
import router from './router'
import './styles.css'

createApp(App).use(ElementPlus, { locale: id }).use(router).mount('#app')
