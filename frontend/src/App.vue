<script setup>
import OfflineStrip from './components/OfflineStrip.vue'
</script>

<template>
  <div class="shell">
    <OfflineStrip />
    <main class="body"><RouterView /></main>
    <nav class="tabs">
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
