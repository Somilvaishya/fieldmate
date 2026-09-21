<script setup>
import OfflineStrip from './components/OfflineStrip.vue'
</script>

<template>
  <div class="shell">
    <OfflineStrip />
    <main class="body"><RouterView /></main>
  </div>
</template>

<style scoped>
.shell { display: flex; flex-direction: column; height: 100%; }
.body { flex: 1; overflow-y: auto; }
</style>
