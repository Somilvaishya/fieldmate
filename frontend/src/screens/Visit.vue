<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { getMeta, db } from '../db'
import { compress } from '../lib/image'
import { getPosition } from '../lib/geo'
import * as visitStore from '../stores/visit'
import * as orderStore from '../stores/order'
import { formatPaise } from '../lib/money'
import * as photoQueue from '../sync/photos'
import Icon from '../components/Icon.vue'

const router = useRouter()
const visit = visitStore.activeVisit
const elapsed = ref(0)
const photos = ref(0)
const shelfDone = ref(false)
const cart = ref({ lines: 0, units: 0 })
const stockDone = ref(false)
const error = ref('')
const busy = ref(false)
let ticker = null

// Quick notes a rep would otherwise type one-handed at a counter.
const QUICK_NOTES = ['Cash collected', 'Owner absent', 'Stock damaged', 'Asked for scheme']

const answered = computed(() => {
  if (!visit.value) return { done: 0, total: 0, required: 0 }
  const shown = visitStore.visibleQuestions(visit.value)
  return {
    done: shown.filter((q) => q.is_answered).length,
    total: shown.length,
    required: visitStore.unansweredRequired(visit.value).length,
  }
})

// Taking the order is the reason the rep is standing in the shop, so it sits with the other work
// rather than behind a menu. It reads three ways: an order already booked here, a cart part-built
// and waiting, or nothing yet.
const orderCard = computed(() => {
  const booked = visit.value?.order
  if (booked) {
    return {
      pill: booked.offline ? 'Saved on phone' : 'Booked',
      sub: `₹${formatPaise(booked.net)} — ${booked.offline ? 'will sync by itself' : 'sent to the distributor'}`,
      tone: 'ok',
      pct: 100,
    }
  }
  if (cart.value.lines) {
    return {
      pill: `${cart.value.lines} in cart`,
      sub: 'Started but not punched yet',
      tone: 'warn',
      pct: 50,
    }
  }
  return { pill: 'None yet', sub: 'Catalogue, schemes and credit', tone: 'muted', pct: 0 }
})

const jobs = computed(() => {
  const a = answered.value
  const order = orderCard.value
  return [
    {
      key: 'order', icon: 'cart', title: 'Order',
      sub: order.sub,
      pill: order.pill,
      tone: order.tone,
      pct: order.pct,
      to: { name: 'order-catalogue', params: { outlet: visit.value?.outlet } },
      disabled: !visit.value?.outlet,
    },
    {
      key: 'checklist', icon: 'list', title: 'Checklist',
      sub: 'Store hygiene, banners and display',
      pill: a.total ? `${a.done} of ${a.total}` : 'None set',
      tone: a.total && a.done === a.total ? 'ok' : a.required ? 'warn' : 'muted',
      pct: a.total ? Math.round((a.done / a.total) * 100) : 0,
      to: { name: 'visit-checklist' },
      disabled: !a.total,
    },
    {
      key: 'shelf', icon: 'shelves', title: 'Shelf check',
      sub: 'Facings and competitor pricing',
      pill: shelfDone.value ? 'Done' : 'Pending',
      tone: shelfDone.value ? 'ok' : 'muted',
      pct: shelfDone.value ? 100 : 0,
      to: { name: 'visit-merchandising' },
    },
    {
      key: 'stock', icon: 'shelves', title: 'Stock check',
      sub: stockDone.value ? 'Counted this visit' : 'What he is still holding',
      pill: stockDone.value ? 'Done' : 'None yet',
      tone: stockDone.value ? 'ok' : 'muted',
      pct: stockDone.value ? 100 : 0,
      to: { name: 'stock-check', params: { outlet: visit.value?.outlet } },
      disabled: !visit.value?.outlet,
    },
    {
      key: 'photo', icon: 'camera', title: 'Photos',
      sub: 'Shopfront, shelf, damage',
      pill: photos.value ? `${photos.value} waiting` : 'None yet',
      tone: photos.value ? 'ok' : 'muted',
      pct: photos.value ? 100 : 0,
      photo: true,
    },
  ]
})

const finished = computed(() => jobs.value.filter((j) => j.pct === 100).length)

const short = computed(
  () => visit.value?.minVisitMinutes > 0 && elapsed.value < visit.value.minVisitMinutes
)

function clock() {
  if (!visit.value?.checkInTime) return
  const started = new Date(visit.value.checkInTime.replace(' ', 'T'))
  elapsed.value = Math.max(0, Math.round((Date.now() - started.getTime()) / 60000))
}

onMounted(async () => {
  if (!visit.value) await visitStore.resume()
  if (!visit.value) return router.replace('/today')
  photos.value = await photoQueue.pendingCount(visit.value.clientUuid)
  // Read from the phone, never fetched: the hub has to paint while the rep is mid-sentence.
  cart.value = await orderStore.peek(visit.value.outlet)
  // Counted during THIS visit, not ever. A count from last month says nothing about whether
  // the rep has done the job he is standing in the shop to do.
  stockDone.value = !!(visit.value.tasks || [])
    .find((t) => t.task_type === 'Stock Audit' && t.status === 'Done')
  shelfDone.value = !!(visit.value.tasks || [])
    .find((t) => t.task_type === 'Merchandising' && t.status === 'Done')
  clock()
  ticker = setInterval(clock, 20000)
})

onUnmounted(() => clearInterval(ticker))

function addNote(text) {
  const current = (visit.value.remarks || '').trim()
  if (current.includes(text)) return
  visit.value.remarks = current ? `${current}. ${text}` : text
  visitStore.saveProgress()
}

async function onPhoto(event) {
  const file = event.target.files?.[0]
  if (!file) return
  error.value = ''
  busy.value = true
  try {
    const settings = (await getMeta('profile'))?.settings || {}
    const out = await compress(file, {
      maxKb: settings.photo_max_kb || 120,
      maxPx: settings.photo_max_dimension_px || 1280,
    })
    const fix = await getPosition().catch(() => ({}))
    await visitStore.addPhoto({ dataUrl: out.dataUrl, purpose: 'Shelf', kb: out.kb, fix })
    photos.value = await photoQueue.pendingCount(visit.value.clientUuid)
    photoQueue.drain().catch(() => {})
  } catch {
    error.value = 'Could not read that photo. Try taking it again.'
  } finally {
    busy.value = false
    event.target.value = ''
  }
}
</script>

<template>
  <div class="wrap screen" v-if="visit">
    <div class="top">
      <div class="head">
        <div class="who">
          <div class="badges">
            <span v-if="visit.isGeoFenceBreach" class="tag warn">Outside range</span>
            <span v-if="visit.createdOffline" class="tag">Saved on this phone</span>
          </div>
          <h2>{{ visit.outletName }}</h2>
          <p class="muted tnum">
            <Icon name="timer" size="16" /> {{ elapsed }} min in shop
            <span v-if="visit.distanceM !== null"> · {{ Math.round(visit.distanceM) }} m away</span>
          </p>
        </div>
      </div>

      <div v-if="visit.isGeoFenceBreach" class="flag">
        <Icon name="pin" size="20" />
        <span>
          Checked in outside this shop's range. The distance is saved with the visit for
          your manager.
        </span>
      </div>

      <div class="section">
        <h3>What to do here</h3>
        <span class="muted tnum">{{ finished }} of {{ jobs.length }} done</span>
      </div>

      <div class="jobs">
        <component v-for="job in jobs" :key="job.key"
                   :is="job.photo ? 'label' : 'RouterLink'"
                   :to="job.photo ? undefined : job.to"
                   class="job" :class="{ off: job.disabled }">
          <span class="jicon"><Icon :name="job.icon" size="24" /></span>
          <span class="jbody">
            <span class="jtop">
              <b>{{ job.title }}</b>
              <span class="pill" :class="job.tone">{{ job.pill }}</span>
            </span>
            <span class="muted">{{ busy && job.photo ? 'Saving photo…' : job.sub }}</span>
            <span class="track"><span class="fill" :style="{ width: job.pct + '%' }"></span></span>
          </span>
          <Icon v-if="!job.photo" name="chevron" size="20" class="go" />
          <input v-else type="file" accept="image/*" capture="environment" hidden
                 @change="onPhoto" />
        </component>
      </div>

      <div class="card">
        <label class="lbl" for="remarks">Remarks</label>
        <textarea id="remarks" v-model="visit.remarks" rows="3"
                  placeholder="Anything worth telling your manager"
                  @blur="visitStore.saveProgress()" />
        <div class="chips">
          <button v-for="n in QUICK_NOTES" :key="n" type="button" class="chip"
                  @click="addNote(n)">+ {{ n }}</button>
        </div>
      </div>

      <p v-if="error" class="err" role="alert"><Icon name="alert" size="18" /> {{ error }}</p>
    </div>

    <div class="bottom">
      <p v-if="short" class="muted note tnum">
        A visit here usually takes at least {{ visit.minVisitMinutes }} minutes.
      </p>
      <button class="btn-primary" @click="router.push({ name: 'visit-checkout' })">
        Finish visit
      </button>
    </div>
  </div>
</template>

<style scoped>
.screen { display: flex; flex-direction: column; min-height: 100%; }
.top { flex: 1; display: grid; gap: 12px; align-content: start; }
.head { margin: 8px 0 0; }
.who { min-width: 0; }
h2 { margin: 2px 0 0; font-size: 20px; overflow-wrap: anywhere; }
h3 { margin: 0; font-size: 16px; }
.muted { color: var(--muted); font-size: 14px; font-weight: 400; }
.who p { margin: 4px 0 0; display: flex; align-items: center; gap: 6px; }

.badges { display: flex; flex-wrap: wrap; gap: 6px; }
.tag { font-size: 14px; font-weight: 600; padding: 3px 8px; border-radius: 4px;
       background: var(--primary-soft); color: var(--primary); }
.tag.warn { background: var(--warn-soft); color: var(--warn); }

.flag { display: flex; gap: 8px; align-items: flex-start; padding: 12px;
        border-radius: 6px; background: var(--warn-soft); color: var(--warn);
        border: 1px solid var(--warn); font-size: 14px; }

.section { display: flex; justify-content: space-between; align-items: baseline; gap: 8px;
           margin-top: 4px; }

.jobs { display: grid; gap: 8px; }
.job { display: flex; align-items: center; gap: 10px; padding: 12px; min-height: 76px;
       background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
       text-decoration: none; color: inherit; cursor: pointer; }
.job.off { opacity: 0.6; pointer-events: none; }
.jicon { width: 48px; height: 48px; flex: none; display: grid; place-items: center;
         border-radius: 6px; background: var(--primary-soft); color: var(--primary); }
.jbody { flex: 1; display: grid; gap: 3px; min-width: 0; }
.jtop { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.jtop b { font-size: 16px; }
.pill { flex: none; font-size: 14px; font-weight: 600; padding: 2px 8px; border-radius: 4px;
        background: var(--bg); color: var(--muted); border: 1px solid var(--line); }
.pill.ok { background: var(--ok-soft); color: var(--ok); border-color: var(--ok); }
.pill.warn { background: var(--warn-soft); color: var(--warn); border-color: var(--warn); }
.track { height: 5px; border-radius: 3px; background: var(--primary-soft); overflow: hidden;
         margin-top: 3px; }
.fill { display: block; height: 100%; background: var(--ok); }
.go { color: var(--muted); flex: none; }

.card { background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
        padding: 14px; }
.lbl { display: block; font-weight: 600; font-size: 16px; margin-bottom: 6px; }
textarea { width: 100%; font: inherit; padding: 10px 12px; border: 1px solid var(--line);
           border-radius: 6px; background: var(--bg); color: var(--ink); }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
.chip { min-height: 48px; padding: 0 12px; border-radius: 6px; font-size: 14px;
        font-weight: 600; background: var(--primary-soft); border: 0; color: var(--primary); }

.err { display: flex; align-items: flex-start; gap: 8px; margin: 0; font-size: 14px;
       background: var(--crit-soft); color: var(--crit); border-radius: 6px; padding: 10px 12px; }

.bottom { position: sticky; bottom: 0; padding: 12px 0 4px; margin-top: 16px;
          background: var(--bg); border-top: 1px solid var(--line); }
.note { text-align: center; margin: 0 0 8px; }
.btn-primary { display: flex; align-items: center; justify-content: center; gap: 6px;
               padding: 14px; min-height: 52px; border-radius: 6px; width: 100%; }
</style>
