import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import Login from './screens/Login.vue'
import Today from './screens/Today.vue'
import './style.css'

const router = createRouter({
  // Hash routing: every deep link is still a request for /fieldmate/ itself, so no
  // server-side rewrite is needed and the service worker can serve it offline.
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/today' },
    { path: '/login', component: Login, name: 'login' },
    { path: '/today', component: Today, name: 'today' },
  ],
})

createApp(App).use(router).mount('#app')
