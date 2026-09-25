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

    // The order, which is four views of one cart rather than four screens. The outlet is in the
    // path because a rep walking a beat can have a part-built order at more than one shop, and the
    // cart is keyed by outlet in IndexedDB for exactly that reason - a deep link back into
    // /order/FM-OUT-00042/cart after the app was killed finds the same basket.
    //
    // Loaded on demand, unlike every route above. These four pull in the scheme engine and a
    // catalogue of several hundred SKUs, and a rep opening Today on a four-year-old Android should
    // not be paying for the order screens to get there - the cold-open budget is 2 seconds. It also
    // means a missing screen is a broken route rather than a broken app while these are being built.
    { path: '/order/:outlet', component: () => import('./screens/OrderCatalogue.vue'), name: 'order-catalogue' },
    { path: '/order/:outlet/cart', component: () => import('./screens/OrderCart.vue'), name: 'order-cart' },
    { path: '/order/:outlet/schemes', component: () => import('./screens/OrderSchemes.vue'), name: 'order-schemes' },
    { path: '/order/:outlet/review', component: () => import('./screens/OrderReview.vue'), name: 'order-review' },

    // Phase 5. The stock check belongs to a shop; the van belongs to the day, so it carries no
    // id at all - a rep has one vehicle and one load, and naming either in the URL would invite
    // a stale deep link to open somebody else's morning.
    { path: '/stock/:outlet', component: () => import('./screens/StockCheck.vue'), name: 'stock-check' },
    { path: '/van/load', component: () => import('./screens/VanLoad.vue'), name: 'van-load' },
    { path: '/van/settle', component: () => import('./screens/VanSettle.vue'), name: 'van-settle' },
  ],
})

createApp(App).use(router).mount('#app')
