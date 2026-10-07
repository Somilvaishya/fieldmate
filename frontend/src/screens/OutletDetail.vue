<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { api, ApiError } from '../api/client'
import { localOutlet } from '../stores/outlets'
import { getMeta, setMeta, putRecord } from '../db'
import * as visitStore from '../stores/visit'
import Icon from '../components/Icon.vue'

const route = useRoute()
const outlet = ref(null)
const detail = ref(null)
const note = ref('')
const loading = ref(true)

const openVisit = visitStore.activeVisit

onMounted(async () => {
  // The mirror first, so the screen paints without waiting on the network.
  outlet.value = await localOutlet(route.params.name)
  try {
    const data = await api.outlet(route.params.name)
    detail.value = data
    outlet.value = { ...(outlet.value || {}), ...data.outlet }
    // Kept, so credit headroom and the order-readiness verdict are still here next time
    // the rep opens this shop with no signal - which is when they most need them.
    await setMeta('outletDetail:' + route.params.name, data)
    await putRecord('FieldMate Outlet', { ...data.outlet, name: route.params.name })
  } catch (e) {
    const cached = await getMeta('outletDetail:' + route.params.name)
    if (cached) {
      detail.value = cached
      outlet.value = { ...(outlet.value || {}), ...cached.outlet }
    }
    note.value = e instanceof ApiError && e.code === 'OFFLINE'
      ? (cached ? 'Showing what is saved on this phone.' : 'Offline. Sync once to load this shop.')
      : e.message
  } finally {
    loading.value = false
  }
})

const credit = computed(() => detail.value?.credit || {})
const hasLimit = computed(() => credit.value.credit_limit > 0)
const used = computed(() =>
  hasLimit.value
    ? Math.min(100, Math.round((credit.value.outstanding / credit.value.credit_limit) * 100))
    : 0
)

/**
 * What this shop owes its distributor - a different debt from the one above.
 *
 * The figures at the top are the **distributor's** position with us, read out of ERPNext's
 * receivable. They were drawn under the heading "Credit headroom" on a shop's own screen, so a
 * rep standing in a kirana read the distributor's limit as that kirana's. The two are not the
 * same number and are not even owed to the same party.
 *
 * This one is FieldMate's own count: orders we booked here, less collections allocated against
 * them. There is no ledger to read - we are not a party to that sale - and the label says so.
 * `No Limit Set` means nobody has given this shop a limit, which is not the same as a limit of
 * zero and is the ordinary state of a shop on the day it is onboarded.
 */
const shopCredit = computed(() => credit.value.shop || null)
const shopHasLimit = computed(() => (shopCredit.value?.limit || 0) > 0)
const shopUsed = computed(() =>
  shopHasLimit.value
    ? Math.min(100, Math.round((shopCredit.value.outstanding / shopCredit.value.limit) * 100))
    : 0
)

/** Indian grouping. ₹1,24,500 - not ₹124,500, which reads wrong to everyone using this. */
function rupees(value) {
  if (value === null || value === undefined || value === '') return null
  return '₹' + Number(value).toLocaleString('en-IN', { maximumFractionDigits: 0 })
}

const facts = computed(() => {
  const o = outlet.value || {}
  return [
    ['Status', o.outlet_status],
    ['Approval', o.approval_status],
    ['Type', o.outlet_type],
    ['Class', o.outlet_class],
    ['Route', o.primary_beat],
    ['Area', [o.address_line1, o.city].filter(Boolean).join(', ')],
    ['GSTIN', o.gstin],
    ['Payment terms', o.credit_days ? `${o.credit_days} days` : null],
    ['Weekly off', o.weekly_off],
  ].filter(([, v]) => v)
})

const telHref = (n) => 'tel:' + String(n).replace(/[^\d+]/g, '')
const waHref = (n) => 'https://wa.me/91' + String(n).replace(/\D/g, '').slice(-10)
const mapHref = computed(() =>
  outlet.value?.latitude
    ? `https://www.google.com/maps/search/?api=1&query=${outlet.value.latitude},${outlet.value.longitude}`
    : null
)
</script>

<template>
  <div class="wrap screen" v-if="outlet">
    <RouterLink to="/outlets" class="back"><Icon name="back" size="20" /> Shops</RouterLink>
    <p v-if="note" class="muted">{{ note }}</p>
    <p v-if="loading" class="muted">Loading the latest…</p>

    <div class="top">
      <!-- Identity -->
      <div class="card">
        <div class="badges">
          <span v-if="outlet.outlet_class" class="tag">{{ outlet.outlet_class }}</span>
          <span v-if="outlet.kyc_verified" class="tag ok">KYC verified</span>
          <span v-if="outlet.outlet_type" class="tag">{{ outlet.outlet_type }}</span>
        </div>
        <div class="identity">
          <div class="who">
            <h2>{{ outlet.outlet_name }}</h2>
            <p class="muted">{{ outlet.city || 'No area recorded' }}</p>
          </div>
          <!-- Labelled, not an icon alone: DESIGN.md requires it, because mixed literacy
               is a real constraint in these markets. -->
          <a v-if="outlet.mobile_no" class="call" :href="telHref(outlet.mobile_no)">
            <Icon name="phone" size="22" />
            <span>Call</span>
          </a>
        </div>
        <div class="quick">
          <a v-if="mapHref" class="ghost" :href="mapHref" target="_blank" rel="noopener">
            <Icon name="directions" size="18" /> Directions
          </a>
          <a v-if="outlet.mobile_no" class="ghost" :href="waHref(outlet.mobile_no)"
             target="_blank" rel="noopener">
            <Icon name="chat" size="18" /> WhatsApp
          </a>
        </div>
      </div>

      <!-- Can this shop be sold to? The first question a rep has. -->
      <div v-if="detail" class="state" :class="detail.can_take_order ? 'good' : 'held'">
        <Icon :name="detail.can_take_order ? 'check' : 'alert'" size="22" />
        <div>
          <b>{{ detail.can_take_order ? 'Ready to take an order' : 'Cannot take an order yet' }}</b>
          <p class="muted" v-if="!detail.can_take_order">{{ detail.blocked_reason }}</p>
        </div>
      </div>

      <!-- This shop's own credit with its distributor. First, because this is the shop's
           screen and this is the shop's debt. -->
      <div v-if="detail && shopCredit" class="card">
        <div class="row">
          <span class="muted">This shop owes {{ credit.party_name || 'its distributor' }}</span>
          <b class="tnum big" :class="{ tight: shopHasLimit && shopUsed >= 80 }">
            {{ shopHasLimit ? rupees(shopCredit.headroom) : 'No limit set' }}
          </b>
        </div>
        <template v-if="shopHasLimit">
          <div class="track"><div class="fill" :style="{ width: shopUsed + '%' }"></div></div>
          <div class="row">
            <span class="muted tnum">Limit {{ rupees(shopCredit.limit) }}</span>
            <span class="muted tnum">{{ shopUsed }}% used</span>
          </div>
        </template>
        <p class="muted foot">
          <template v-if="shopHasLimit">
            Owing {{ rupees(shopCredit.outstanding) }} ·
          </template>
          <b>our own count</b> - orders booked here, less what has been collected. Not a ledger.
          <template v-if="!shopHasLimit">
            Set this shop&rsquo;s credit limit in Desk to measure it.
          </template>
        </p>
      </div>

      <!-- The distributor's position with us. A real receivable, and a different debt from the
           one above - it used to be drawn under "Credit headroom" on this screen, so a rep read
           the distributor's limit as this shop's. -->
      <div v-if="detail && (hasLimit || credit.unlimited)" class="card">
        <div class="row">
          <span class="muted">{{ credit.party_name || 'The distributor' }} owes us</span>
          <b class="tnum big" :class="{ tight: hasLimit && used >= 80 }">
            {{ credit.unlimited ? 'No limit set' : rupees(credit.headroom) }}
          </b>
        </div>
        <template v-if="hasLimit">
          <div class="track"><div class="fill" :style="{ width: used + '%' }"></div></div>
          <div class="row">
            <span class="muted tnum">Limit {{ rupees(credit.credit_limit) }}</span>
            <span class="muted tnum">{{ used }}% used</span>
          </div>
        </template>
      </div>

      <!-- Facts. A plain label/value list, not a card per row. -->
      <div class="card" v-if="facts.length">
        <h3>Shop details</h3>
        <div v-for="[label, value] in facts" :key="label" class="kv">
          <span class="muted">{{ label }}</span>
          <b>{{ value }}</b>
        </div>
      </div>

      <div v-if="detail && detail.contacts.length" class="card">
        <h3>People</h3>
        <div v-for="c in detail.contacts" :key="c.person_name" class="kv contact">
          <span class="person">
            <b>{{ c.person_name }}</b>
            <span class="muted">
              {{ c.role_at_outlet || 'Contact' }}<em v-if="c.is_primary"> · main</em>
            </span>
          </span>
          <a v-if="c.mobile_no" class="call small" :href="telHref(c.mobile_no)">
            <Icon name="phone" size="20" />
            <span>Call</span>
          </a>
        </div>
      </div>

      <div v-if="outlet.shop_photo" class="card">
        <h3>Shopfront</h3>
        <img class="photo" :src="outlet.shop_photo" alt="" loading="lazy" />
      </div>
    </div>

    <div class="bottom">
      <RouterLink v-if="openVisit && openVisit.outlet === outlet.name" class="btn-primary"
                  :to="{ name: 'visit', params: { uuid: openVisit.clientUuid } }">
        Carry on with this visit
      </RouterLink>

      <!-- Still inside another shop. This used to be a live "Check in here" with a note under it
           saying the other visit would be closed - one tap, and it was, stamped "No Order" and
           short. Checking out is how a visit ends, so the way back to that shop is the primary
           action and checking in here is behind it, on a screen that spells out what it costs. -->
      <template v-else-if="openVisit">
        <RouterLink class="btn-primary"
                    :to="{ name: 'visit', params: { uuid: openVisit.clientUuid } }">
          Back to {{ openVisit.outletName }}
        </RouterLink>
        <p class="muted foot">
          You are still checked in at {{ openVisit.outletName }}. Check out from there, then come
          back here.
        </p>
        <RouterLink class="ghost foot"
                    :to="{ name: 'visit-start', params: { name: outlet.name } }">
          I have left {{ openVisit.outletName }}
        </RouterLink>
      </template>

      <RouterLink v-else class="btn-primary"
                  :to="{ name: 'visit-start', params: { name: outlet.name } }">
        <Icon name="store" size="20" /> Check in here
      </RouterLink>
    </div>
  </div>
  <!-- The failure case needs its own branch: the note explaining WHY used to live inside
       the v-if above, so in the one case where it mattered the rep saw only "not found". -->
  <div v-else class="wrap">
    <RouterLink to="/outlets" class="back"><Icon name="back" size="20" /> Shops</RouterLink>
    <p v-if="loading" class="muted">Loading…</p>
    <template v-else>
      <p class="muted"><b>This shop is not on your phone yet.</b></p>
      <p class="muted">{{ note || 'Sync once and it will be here.' }}</p>
    </template>
  </div>
</template>

<style scoped>
.screen { display: flex; flex-direction: column; min-height: 100%; }
.top { flex: 1; display: grid; gap: 12px; align-content: start; }
.back { display: inline-flex; align-items: center; gap: 4px; min-height: 48px;
        color: var(--primary); text-decoration: none; font-weight: 600; }
h2 { margin: 0; font-size: 20px; overflow-wrap: anywhere; }
h3 { margin: 0 0 8px; font-size: 16px; }
.muted { color: var(--muted); font-size: 14px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
        padding: 14px; }

.badges { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 8px; }
.tag { font-size: 14px; font-weight: 600; padding: 3px 8px; border-radius: 4px;
       background: var(--primary-soft); color: var(--primary); }
.tag.ok { background: var(--ok-soft); color: var(--ok); }

.identity { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.who { min-width: 0; }
.who p { margin: 2px 0 0; }
.call { min-width: 48px; min-height: 48px; flex: none; display: flex; flex-direction: column;
        align-items: center; justify-content: center; gap: 2px; padding: 4px 10px;
        border-radius: 6px; background: var(--primary-soft); color: var(--primary);
        text-decoration: none; font-size: 14px; font-weight: 600; }
.call.small { padding: 4px 8px; }

.quick { display: flex; gap: 8px; margin-top: 12px; padding-top: 12px;
         border-top: 1px solid var(--line); }
.ghost { flex: 1; display: flex; align-items: center; justify-content: center; gap: 6px;
         min-height: 48px; border-radius: 6px; background: var(--surface);
         border: 1px solid var(--primary); color: var(--primary); font-weight: 600;
         text-decoration: none; font-size: 16px; }

.state { display: flex; gap: 10px; align-items: flex-start; padding: 14px;
         border-radius: 6px; border: 1px solid; }
.state div { min-width: 0; }
.state p { margin: 2px 0 0; }
.state.good { background: var(--ok-soft); border-color: var(--ok); color: var(--ok); }
.state.held { background: var(--warn-soft); border-color: var(--warn); color: var(--warn); }

.row { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.big { font-size: 20px; }
.tight { color: var(--crit); }
.track { height: 10px; border-radius: 5px; background: var(--primary-soft); overflow: hidden;
         margin: 8px 0; }
.fill { height: 100%; background: var(--primary); }

.kv { display: flex; justify-content: space-between; align-items: baseline; gap: 12px;
      padding: 10px 0; border-bottom: 1px solid var(--line); }
.kv:last-child { border-bottom: 0; padding-bottom: 0; }
.kv b { text-align: right; overflow-wrap: anywhere; }
.contact { align-items: center; }
.person { display: grid; gap: 1px; min-width: 0; text-align: left; }
em { font-style: normal; }

.photo { width: 100%; max-width: 100%; height: 160px; object-fit: cover; border-radius: 6px;
         display: block; }

.bottom { position: sticky; bottom: 0; padding: 12px 0 4px; margin-top: 12px;
          background: var(--bg); border-top: 1px solid var(--line); }
.btn-primary { display: flex; align-items: center; justify-content: center; gap: 6px;
               text-decoration: none; padding: 14px; min-height: 52px; border-radius: 6px; }
.foot { text-align: center; margin: 8px 0 0; }
</style>
