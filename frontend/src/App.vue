<script setup>
import { computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import Icon from './components/Icon.vue'
import OfflineStrip from './components/OfflineStrip.vue'
import * as auto from './sync/auto'
import * as dayStore from './stores/day'

const route = useRoute()

// Started here rather than on a screen: the queue has to drain whether or not the rep is
// looking at Today, and it must survive navigating between screens.
onMounted(() => {
  auto.start()
  // And the day, once, for the whole session. Every screen that asks "has the day started"
  // used to read a store nothing had filled unless the rep happened to arrive via Today, so
  // check-in told people their day had not started when it had.
  dayStore.ensure().catch(() => {})
})
onUnmounted(() => auto.stop())

// Signed out, every tab is a dead end that bounces back here, so the chrome is hidden.
const chrome = computed(() => route.name !== 'login')

// Five, because that is what a rep's day is made of: the day itself, the shops, what they
// sold, what they collected, and their own numbers. Each one opens a screen that exists - a
// tab leading nowhere is worse than one tab fewer.
const TABS = [
  { to: '/today', icon: 'list', label: 'Today' },
  { to: '/outlets', icon: 'store', label: 'Shops' },
  { to: '/orders', icon: 'cart', label: 'Orders' },
  { to: '/money', icon: 'tag', label: 'Collect' },
  { to: '/me', icon: 'person', label: 'Me' },
]
</script>

<template>
  <div class="shell">
    <!-- One instance for the whole app, in the column rather than over it. It used to be a
         full-width band on every screen - and a second copy on nine of them - spending a line
         all day to repeat the state the rep is in almost always. Floating it instead put it
         on top of whatever heading a screen had at its top left, so now it holds its own
         lane: quiet that is a 20px dot, loud it is a band. -->
    <OfflineStrip v-if="chrome" />

    <main class="body"><RouterView /></main>

    <nav v-if="chrome" class="tabs">
      <RouterLink v-for="t in TABS" :key="t.to" :to="t.to" class="tab">
        <span class="mark" aria-hidden="true"></span>
        <Icon :name="t.icon" size="22" />
        <span class="label">{{ t.label }}</span>
      </RouterLink>
    </nav>
  </div>
</template>

<style scoped>
/* Fixed to the viewport rather than sized against it.
 *
 * A height has to be measured, and on a phone every unit that measures one has a case where it
 * is wrong: `100%` includes the strip under the address bar, `100dvh` can be left stale by the
 * on-screen keyboard. Both put the tab bar somewhere other than the bottom edge, which is what
 * a rep reported - the bar mid-page with empty white below it.
 *
 * `inset: 0` is the viewport by definition. Nothing to recompute, and no unit to be wrong. */
.shell { position: fixed; inset: 0; display: flex; flex-direction: column; }
/* The only scroller. The status lane above and the tabs below are chrome, and both stay put
   while a rep scrolls a long beat. */
.body { flex: 1; overflow-y: auto; }

.tabs { display: flex; border-top: 1px solid var(--line); background: var(--surface);
        padding-bottom: env(safe-area-inset-bottom, 0px); }
/* 56px of target before the inset: this is the one control a rep hits with a thumb while
   walking. */
.tab { position: relative; flex: 1; display: flex; flex-direction: column; align-items: center;
       justify-content: center; gap: 2px; min-height: 56px; padding: 8px 2px 10px;
       text-decoration: none; color: var(--muted); }
.label { font-size: 11px; font-weight: 600; letter-spacing: .01em; }
.tab.router-link-active { color: var(--primary); }
/* A bar as well as a colour. Colour on its own is the signal a rep in sunlight is least
   likely to catch. */
.mark { position: absolute; top: 0; width: 26px; height: 3px; border-radius: 0 0 3px 3px;
        background: transparent; }
.tab.router-link-active .mark { background: var(--primary); }
</style>
