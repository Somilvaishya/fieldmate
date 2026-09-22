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
import VisitCheckIn from './screens/VisitCheckIn.vue'
import Visit from './screens/Visit.vue'
import VisitChecklist from './screens/VisitChecklist.vue'
import VisitMerchandising from './screens/VisitMerchandising.vue'
import VisitCheckOut from './screens/VisitCheckOut.vue'
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

    // The visit is one flow with one open record, so the sub-screens carry no id of their
    // own - they act on whichever visit is currently open. That keeps a reloaded phone from
    // landing on a checklist for a visit it has already closed.
    { path: '/visit/start/:name', component: VisitCheckIn, name: 'visit-start' },
    { path: '/visit/:uuid', component: Visit, name: 'visit' },
    { path: '/visit/:uuid/checklist', component: VisitChecklist, name: 'visit-checklist' },
    { path: '/visit/:uuid/shelf', component: VisitMerchandising, name: 'visit-merchandising' },
    { path: '/visit/:uuid/finish', component: VisitCheckOut, name: 'visit-checkout' },
  ],
})

createApp(App).use(router).mount('#app')
