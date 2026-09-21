import { createApp } from 'vue'
import { createRouter, createWebHistory } from 'vue-router'
import App from './App.vue'
import Login from './screens/Login.vue'
import Today from './screens/Today.vue'
import './style.css'

const router = createRouter({
  history: createWebHistory('/fieldmate'),
  routes: [
    { path: '/', redirect: '/today' },
    { path: '/login', component: Login, name: 'login' },
    { path: '/today', component: Today, name: 'today' },
  ],
})

createApp(App).use(router).mount('#app')
