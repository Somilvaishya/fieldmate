<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/client'
import { getMeta, setMeta } from '../db'
import Icon from '../components/Icon.vue'

const router = useRouter()
const profile = ref(null)
const loading = ref(true)

// The screens that belong to the rep rather than to a shop or a day.
const LINKS = [
  { to: '/performance', icon: 'target', title: 'My performance',
    note: 'Targets, and what the month is worth' },
  { to: '/expense', icon: 'receipt', title: 'Claim expenses',
    note: 'Travel, food and what you spent' },
  { to: '/cockpit', icon: 'list', title: 'How today is going',
    note: 'Calls, orders and cash so far' },
  { to: '/deposit', icon: 'tag', title: 'Hand in cash',
    note: 'Declare what you are carrying' },
]

async function load() {
  // The cached profile first, so this screen is never blank on a market connection.
  profile.value = await getMeta('profile')
  try {
    const live = await api.bootstrap()
    await setMeta('profile', live)
    profile.value = live
  } catch {
    // Cached is fine. Nothing on this screen is worth an error message for.
  } finally {
    loading.value = false
  }
}

async function signOut() {
  // Deliberately blunt and deliberately warned about: anything still queued on this phone has
  // not reached the server, and signing out is how a rep loses a morning.
  router.push('/login')
}

onMounted(load)
</script>

<template>
  <div class="wrap">
    <header class="who">
      <div class="avatar"><Icon name="person" size="26" /></div>
      <div>
        <h1>{{ profile?.full_name || profile?.field_user || 'You' }}</h1>
        <p class="dim">
          {{ profile?.designation || 'Field Rep' }}
          <template v-if="profile?.territory"> · {{ profile.territory }}</template>
        </p>
      </div>
    </header>

    <div class="facts" v-if="profile">
      <div class="fact">
        <span class="dim">Selling as</span>
        <b>{{ profile.sales_mode || 'Order Booking' }}</b>
      </div>
      <div class="fact">
        <span class="dim">Calls a day</span>
        <b class="tnum">{{ profile.daily_target_calls || '—' }}</b>
      </div>
    </div>

    <RouterLink v-for="l in LINKS" :key="l.to" :to="l.to" class="row">
      <Icon :name="l.icon" size="20" />
      <span class="body">
        <b>{{ l.title }}</b>
        <em>{{ l.note }}</em>
      </span>
      <Icon name="chevron" size="18" class="go" />
    </RouterLink>

    <div class="foot">
      <p class="dim fine" v-if="profile?.support_contact">
        Stuck? {{ profile.support_contact }}
      </p>
      <button class="out" @click="signOut">Sign out</button>
      <p class="dim fine">
        Anything still waiting to send is saved on this phone. Sync before you sign out.
      </p>
    </div>
  </div>
</template>

<style scoped>
.wrap { max-width: 560px; margin: 0 auto; padding: 16px; display: flex;
        flex-direction: column; gap: 12px; }
.who { display: flex; align-items: center; gap: 12px; }
.who h1 { font-size: 20px; margin: 0; }
.avatar { width: 48px; height: 48px; border-radius: 999px; background: var(--primary-soft);
          color: var(--primary); display: grid; place-items: center; flex: none; }
.dim { color: var(--muted); font-size: 13px; margin: 2px 0 0; }
.fine { font-size: 12px; text-align: center; }

.facts { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
.fact { background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
        padding: 12px; display: flex; flex-direction: column; gap: 2px; }

.row { display: flex; align-items: center; gap: 12px; min-height: 64px; padding: 12px;
       background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
       text-decoration: none; color: var(--ink); }
.row .body { flex: 1; display: flex; flex-direction: column; }
.row em { font-style: normal; font-size: 13px; color: var(--muted); }
.go { color: var(--muted); flex: none; }

.foot { margin-top: 8px; display: flex; flex-direction: column; gap: 8px; }
.out { min-height: 48px; border: 1px solid var(--line); background: var(--surface);
       border-radius: 8px; color: var(--crit); font-weight: 600; }
.tnum { font-variant-numeric: tabular-nums; }
</style>
