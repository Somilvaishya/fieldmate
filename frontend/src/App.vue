<script setup>
import { computed, onMounted, onUnmounted } from 'vue'
import { useRoute } from 'vue-router'
import OfflineStrip from './components/OfflineStrip.vue'
import * as auto from './sync/auto'

const route = useRoute()

// Started here rather than on a screen: the queue has to drain whether or not the rep is
// looking at Today, and it must survive navigating between screens.
onMounted(() => auto.start())
onUnmounted(() => auto.stop())

// Signed out, every tab is a dead end that bounces back here, so the bar is hidden.
// It also takes 56px off a screen whose whole job is one form and one button.
const chrome = computed(() => route.name !== 'login')
</script>

<template>
  <div class="shell">
    <OfflineStrip />
    <main class="body"><RouterView /></main>
    <nav v-if="chrome" class="tabs">
      <RouterLink to="/today">Today</RouterLink>
      <RouterLink to="/beats">Beats</RouterLink>
      <RouterLink to="/outlets">Outlets</RouterLink>
    </nav>
  </div>
</template>

<style scoped>
.shell { display: flex; flex-direction: column; height: 100%; }
.body { flex: 1; overflow-y: auto; }
.tabs { display: flex; border-top: 1px solid var(--line); background: var(--surface);
        padding-bottom: env(safe-area-inset-bottom, 0px); }
.tabs a { flex: 1; text-align: center; padding: 14px 4px; min-height: 48px;
          text-decoration: none; color: var(--muted); font-size: 14px; }
.tabs a.router-link-active { color: var(--primary); font-weight: 600; }
</style>
