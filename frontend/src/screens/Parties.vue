<script setup>
/**
 * The parties a rep can sell to directly, and the way into a primary order.
 *
 * A retailer order starts from a shop on a beat, which is a route somebody planned. A primary
 * order does not: the rep is at a distributor's office or godown, and the party is one of the
 * handful they sell through. So this is a list rather than a search, and it comes from the
 * bootstrap payload the phone already stores - `party.counter_facts`, which is there so that
 * delivery days and credit terms can be read out at a counter with no signal.
 *
 * Reading the stored payload rather than calling is the point. A rep standing in a godown with
 * one bar of signal should get this list from the phone, not from a round trip that may not
 * return.
 */
import { computed, onMounted, ref } from 'vue'
import { getMeta } from '../db'
import Icon from '../components/Icon.vue'
import { t } from '../lib/i18n'

const boot = ref(null)
const loading = ref(true)

onMounted(async () => {
  try {
    boot.value = await getMeta('profile')
  } finally {
    loading.value = false
  }
})

const parties = computed(() => (boot.value && boot.value.distributors) || [])

/** Whether this site makes primary sales at all. Switched off is not an error; it is a setting. */
const enabled = computed(() => {
  const modes = (boot.value && boot.value.settings && boot.value.settings.enabled_modes) || null
  return !modes || modes.includes('Primary')
})

function termsFor(party) {
  const bits = []
  if (party.credit_days !== null && party.credit_days !== undefined) {
    bits.push(party.credit_days === 0
      ? t('Payable on delivery')
      : t('{n} day terms', { n: party.credit_days }))
  }
  if (party.delivery_days) {
    bits.push(t('dispatches in {n}', { n: party.delivery_days }))
  }
  return bits.join(' · ')
}
</script>

<template>
  <div class="screen">
    <header class="head">
      <h1>{{ t('Order on a distributor') }}</h1>
      <p class="sub">
        {{ t('A sale we invoice ourselves, not one the distributor bills a shop for.') }}
      </p>
    </header>

    <p v-if="loading" class="muted">{{ t('Loading…') }}</p>

    <!-- Switched off is a setting, not a failure, so it says which and who can change it. -->
    <p v-else-if="!enabled" class="notice">
      {{ t('This company does not book primary sales.') }}
      {{ t('Ask your manager if that is wrong.') }}
    </p>

    <p v-else-if="!parties.length" class="notice">
      {{ t('No distributor is set up against your territory yet, so there is nobody here to order on.') }}
      {{ t('Ask your manager.') }}
    </p>

    <ul v-else class="list">
      <li v-for="party in parties" :key="party.distributor">
        <RouterLink
          class="row"
          :to="{ name: 'order-catalogue',
                 params: { outlet: party.distributor },
                 query: { party: 'Customer' } }">
          <span class="idn">
            <b>{{ party.distributor_name }}</b>
            <em v-if="termsFor(party)" class="muted">{{ termsFor(party) }}</em>
          </span>
          <Icon name="chevron" size="20" />
        </RouterLink>
      </li>
    </ul>
  </div>
</template>

<style scoped>
.head { padding: 16px 16px 8px; }
.sub { margin: 4px 0 0; color: var(--muted, #666); }
.list { list-style: none; margin: 0; padding: 0; }
.row {
  display: flex; align-items: center; justify-content: space-between; gap: 12px;
  /* 48px of target, like every other row a rep taps in a market. */
  min-height: 56px; padding: 12px 16px; text-decoration: none; color: inherit;
  border-bottom: 1px solid var(--line, #eee);
}
.idn { display: flex; flex-direction: column; gap: 2px; }
.muted { color: var(--muted, #666); font-style: normal; font-size: 0.9em; }
.notice { margin: 16px; padding: 12px; border-radius: 8px; background: var(--notice, #fff6e5); }
</style>
