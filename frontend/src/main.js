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

    // Phase 6. Outstanding belongs to a shop; the deposit belongs to the rep's own satchel and
    // so carries no id - there is one of those, and naming it in a URL would only invite a
    // stale link into somebody else's cash.
    { path: '/outstanding/:outlet', component: () => import('./screens/Outstanding.vue'), name: 'outstanding' },
    { path: '/collect/:outlet', component: () => import('./screens/CollectionEntry.vue'), name: 'collect' },
    { path: '/deposit', component: () => import('./screens/DepositDeclare.vue'), name: 'deposit' },

    // Phase 7. Both belong to the rep rather than to a shop or a day, so neither takes an id.
    // Performance is a read of last night's snapshot; the expense claim reads the trail for
    // whichever day it is asked about, which is why the date is a control on the screen and
    // not a parameter in the URL.
    { path: '/performance', component: () => import('./screens/MyPerformance.vue'), name: 'performance' },
    { path: '/expense', component: () => import('./screens/ExpenseClaim.vue'), name: 'expense' },

    // Phase 8. The cockpit is today's own figures, counted live; everything with a month in it
    // reads the snapshot. It takes no id for the same reason the two above do not - a rep has
    // one day, and naming it in a URL would invite a stale link into yesterday's.
    { path: '/cockpit', component: () => import('./screens/DayCockpit.vue'), name: 'cockpit' },

    // The three the bottom bar needs. None of them takes an id: they are the rep's own lists,
    // and a rep has exactly one of each.
    { path: '/orders', component: () => import('./screens/Orders.vue'), name: 'orders' },
    { path: '/money', component: () => import('./screens/Money.vue'), name: 'money' },
    { path: '/me', component: () => import('./screens/Me.vue'), name: 'me' },
  ],
})

createApp(App).use(router).mount('#app')
