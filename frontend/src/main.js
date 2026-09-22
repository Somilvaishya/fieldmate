import { createApp } from 'vue'
import { createRouter, createWebHashHistory } from 'vue-router'
import App from './App.vue'
import Login from './screens/Login.vue'
import Today from './screens/Today.vue'
import Outlets from './screens/Outlets.vue'
import OutletDetail from './screens/OutletDetail.vue'
import OutletNew from './screens/OutletNew.vue'
import Beats from './screens/Beats.vue'
import DayStart from './screens/DayStart.vue'
import DayEnd from './screens/DayEnd.vue'
import './style.css'

const router = createRouter({
  // Hash routing: every deep link is still a request for /fieldmate/ itself, so no
  // server-side rewrite is needed and the service worker can serve it offline.
  history: createWebHashHistory(),
  routes: [
    { path: '/', redirect: '/today' },
    { path: '/login', component: Login, name: 'login' },
    { path: '/today', component: Today, name: 'today' },
    { path: '/outlets', component: Outlets, name: 'outlets' },
    { path: '/outlet/new', component: OutletNew, name: 'outlet-new' },
    { path: '/outlet/:name', component: OutletDetail, name: 'outlet' },
    { path: '/beats', component: Beats, name: 'beats' },
    { path: '/day/start', component: DayStart, name: 'day-start' },
    { path: '/day/end', component: DayEnd, name: 'day-end' },
  ],
})

createApp(App).use(router).mount('#app')
