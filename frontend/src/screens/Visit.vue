<script setup>
import { ref, onMounted, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { getMeta } from '../db'
import { compress } from '../lib/image'
import { getPosition } from '../lib/geo'
import * as visitStore from '../stores/visit'
import * as orderStore from '../stores/order'
import { api } from '../api/client'
import { formatPaise } from '../lib/money'
import * as photoQueue from '../sync/photos'
import Icon from '../components/Icon.vue'
import { t } from '../lib/i18n'

const router = useRouter()
const visit = visitStore.activeVisit
const elapsed = ref(0)
const photos = ref(0)
const shelfDone = ref(false)
const cart = ref({ lines: 0, units: 0 })
const stockDone = ref(false)
// What the shop owes, or `null` for "we could not ask". Those are different facts and the card
// below says so: a failed read used to fall back to 0, and 0 renders as "Nothing outstanding"
// and a Clear pill - a rep could walk away from a shop that owes money because the app told
// them it was clear. Not knowing is not the same as nothing.
const owed = ref(null)
const collected = ref(false)
const error = ref('')
const busy = ref(false)
let ticker = null

// Quick notes a rep would otherwise type one-handed at a counter.
// Suggestions a rep taps into their own note, so these are text rather than wire values -
// the note goes up as whatever it says here.
const QUICK_NOTES = computed(() => [
  t('Cash collected'), t('Owner absent'), t('Stock damaged'), t('Asked for scheme'),
])

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
      pill: booked.offline ? t('Saved on phone') : t('Booked'),
      // The billed figure, goods plus GST. It used to be the net, so the hub showed a smaller
      // number than the one the rep had read out to the shopkeeper on the review screen thirty
      // seconds earlier - and smaller than the one on the orders list and the season book, which
      // have always printed what the party is billed. `?? net` for a draft an older build saved.
      sub: `₹${formatPaise(booked.total ?? booked.net)} — ${booked.offline ? 'will sync by itself' : 'sent to the distributor'}`,
      tone: 'ok',
      pct: 100,
    }
  }
  if (cart.value.lines) {
    return {
      pill: `${cart.value.lines} in cart`,
      sub: t('Started but not punched yet'),
      tone: 'warn',
      pct: 50,
    }
  }
  return { pill: t('None yet'), sub: t('Catalogue, schemes and credit'), tone: 'muted', pct: 0 }
})

const jobs = computed(() => {
  const a = answered.value
  const order = orderCard.value
  return [
    {
      key: 'order', icon: 'cart', title: t('Order'),
      sub: order.sub,
      pill: order.pill,
      tone: order.tone,
      pct: order.pct,
      to: { name: 'order-catalogue', params: { outlet: visit.value?.outlet } },
      disabled: !visit.value?.outlet,
    },
    {
      key: 'checklist', icon: 'list', title: t('Checklist'),
      sub: t('Store hygiene, banners and display'),
      pill: a.total ? t('{done} of {total}', { done: a.done, total: a.total }) : t('None set'),
      tone: a.total && a.done === a.total ? 'ok' : a.required ? 'warn' : 'muted',
      pct: a.total ? Math.round((a.done / a.total) * 100) : 0,
      to: { name: 'visit-checklist' },
      disabled: !a.total,
    },
    {
      key: 'shelf', icon: 'shelves', title: t('Shelf check'),
      sub: t('Facings and competitor pricing'),
      pill: shelfDone.value ? t('Done') : t('Pending'),
      tone: shelfDone.value ? 'ok' : 'muted',
      pct: shelfDone.value ? 100 : 0,
      to: { name: 'visit-merchandising' },
    },
    {
      key: 'stock', icon: 'shelves', title: t('Stock check'),
      sub: stockDone.value ? t('Counted this visit') : t('What he is still holding'),
      pill: stockDone.value ? t('Done') : t('None yet'),
      tone: stockDone.value ? 'ok' : 'muted',
      pct: stockDone.value ? 100 : 0,
      to: { name: 'stock-check', params: { outlet: visit.value?.outlet } },
      disabled: !visit.value?.outlet,
    },
    {
      key: 'money', icon: 'tag', title: t('Collect payment'),
      // Three states, not two. Unknown is its own answer and must not read as nothing owed.
      sub: owed.value === null
        ? t('Could not check what is owed — open it to try again')
        : (owed.value ? formatPaise(owed.value * 100) + ' outstanding' : t('Nothing outstanding')),
      pill: collected.value
        ? t('Taken')
        : (owed.value === null ? t('Not checked') : (owed.value ? t('Due') : t('Clear'))),
      tone: collected.value ? 'ok' : (owed.value ? 'warn' : 'muted'),
      pct: collected.value ? 100 : 0,
      to: { name: 'outstanding', params: { outlet: visit.value?.outlet } },
      disabled: !visit.value?.outlet,
    },
    {
      key: 'photo', icon: 'camera', title: t('Photos'),
      sub: t('Shopfront, shelf, damage'),
      pill: photos.value ? t('{n} waiting', { n: photos.value }) : t('None yet'),
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
  await loadShots()
  // A photo left waiting from earlier in this visit, or from before the app was reopened.
  if (shots.value.some((s) => s.state === 'queued' || s.state === 'failed')) watchShots()
  // Read from the phone, never fetched: the hub has to paint while the rep is mid-sentence.
  cart.value = await orderStore.peek(visit.value.outlet)
  // Counted during THIS visit, not ever. A count from last month says nothing about whether
  // the rep has done the job he is standing in the shop to do.
  stockDone.value = !!(visit.value.tasks || [])
    .find((t) => t.task_type === 'Stock Audit' && t.status === 'Done')
  collected.value = !!(visit.value.tasks || [])
    .find((t) => t.task_type === 'Collection' && t.status === 'Done')
  // Best effort: a rep with no signal still gets the rest of the hub, just without the figure -
  // and the card says it is missing rather than inventing a zero.
  try {
    owed.value = Number((await api.outstanding(visit.value.outlet)).outstanding) || 0
  } catch {
    owed.value = null
  }
  shelfDone.value = !!(visit.value.tasks || [])
    .find((t) => t.task_type === 'Merchandising' && t.status === 'Done')
  clock()
  ticker = setInterval(clock, 20000)
})

onUnmounted(() => {
  clearInterval(ticker)
  clearInterval(watcher)
})

function addNote(text) {
  const current = (visit.value.remarks || '').trim()
  if (current.includes(text)) return
  visit.value.remarks = current ? `${current}. ${text}` : text
  visitStore.saveProgress()
}

// What the server's `purpose` column accepts, in the order a rep meets them. Every photo used to
// go up as "Shelf" whatever it showed, so a damaged-stock picture and a planogram check were the
// same word on the desk and nobody could tell them apart afterwards.
const PURPOSES = computed(() => [
  { key: 'Shelf', label: t('Shelf') },
  { key: 'Shop Front', label: t('Shop front') },
  { key: 'Planogram', label: t('Planogram') },
  { key: 'Competitor', label: t('Competitor') },
  { key: 'Damage', label: t('Damage') },
  { key: 'Expiry', label: t('Expiry') },
  { key: 'Other', label: t('Other') },
])
const purpose = ref('Shelf')
const shots = ref([])

async function loadShots() {
  shots.value = await photoQueue.forVisit(visit.value.clientUuid)
  photos.value = await photoQueue.pendingCount(visit.value.clientUuid)
}

// A photo cannot go up until the visit it belongs to has itself reached the server, so one taken
// at check-in often waits a minute for the record ahead of it. The background sync sends it when
// that happens - but nothing told this screen, so the strip said "Waiting" until the app was
// reloaded and the rep had no way to know the photo was safe.
//
// Only while something is actually waiting, and it stops itself the moment nothing is.
let watcher = null

function watchShots() {
  if (watcher) return
  watcher = setInterval(async () => {
    if (!visit.value) return
    await loadShots()
    if (!shots.value.some((s) => s.state === 'queued' || s.state === 'failed')) {
      clearInterval(watcher)
      watcher = null
    }
  }, 3000)
}

async function onPhoto(event) {
  // Every file, not just the first. The input allows several, and taking only `files[0]` meant a
  // rep who picked four pictures silently sent one.
  const files = Array.from(event.target.files || [])
  if (!files.length) return
  error.value = ''
  busy.value = true
  const chosen = purpose.value
  try {
    const settings = (await getMeta('profile'))?.settings || {}
    const fix = await getPosition().catch(() => ({}))
    for (const file of files) {
      const out = await compress(file, {
        maxKb: settings.photo_max_kb || 120,
        maxPx: settings.photo_max_dimension_px || 1280,
      })
      // A second, tiny pass. This one stays on the phone after the full image has gone up, so
      // the rep can see what they took rather than a count that drops to zero on success.
      const small = await compress(file, { maxKb: 12, maxPx: 160, quality: 0.6 })
      await visitStore.addPhoto({
        dataUrl: out.dataUrl, thumb: small.dataUrl, purpose: chosen, kb: out.kb, fix,
      })
    }
    await loadShots()
    photoQueue.drain().then(loadShots).catch(() => {})
    watchShots()
  } catch {
    error.value = files.length > 1
      ? t('Could not read one of those photos. Try again.')
      : t('Could not read that photo. Try taking it again.')
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
            <span v-if="visit.isGeoFenceBreach" class="tag warn">{{ t('Outside range') }}</span>
            <span v-if="visit.createdOffline" class="tag">{{ t('Saved on this phone') }}</span>
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
          {{ t("Checked in outside this shop's range.") }}
          {{ t('The distance is saved with the visit for your manager.') }}
        </span>
      </div>

      <div class="section">
        <h3>{{ t('What to do here') }}</h3>
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
            <span class="muted">{{ busy && job.photo ? t('Saving photo…') : job.sub }}</span>
            <span class="track"><span class="fill" :style="{ width: job.pct + '%' }"></span></span>
          </span>
          <Icon v-if="!job.photo" name="chevron" size="20" class="go" />
          <input v-else type="file" accept="image/*" capture="environment" multiple hidden
                 @change="onPhoto" />
        </component>
      </div>

      <!-- What the next photo will be filed as. Chosen before the camera opens, because after it
           closes the rep is already looking at the next thing. -->
      <div class="purposes" role="group" :aria-label="t('What the next photo shows')">
        <button v-for="p in PURPOSES" :key="p.key" type="button"
                class="chip" :class="{ on: purpose === p.key }" @click="purpose = p.key">
          {{ p.label }}
        </button>
      </div>

      <!-- Taken so far. A count alone dropped to zero the moment an upload succeeded, which
           reads as the photo having been lost. -->
      <div v-if="shots.length" class="shots">
        <figure v-for="s in shots" :key="s.clientUuid" class="shot" :class="s.state">
          <img v-if="s.thumb" :src="s.thumb" :alt="s.purpose" loading="lazy" />
          <span v-else class="noimg"><Icon name="camera" size="20" /></span>
          <figcaption>
            <b>{{ s.purpose }}</b>
            <em v-if="s.state === 'sent'">{{ t('Sent') }}</em>
            <em v-else-if="s.state === 'blocked'" class="bad">{{ t('Stuck') }}</em>
            <em v-else>{{ t('Waiting') }}</em>
          </figcaption>
        </figure>
      </div>

      <div class="card">
        <label class="lbl" for="remarks">{{ t('Remarks') }}</label>
        <textarea id="remarks" v-model="visit.remarks" rows="3"
                  :placeholder="t('Anything worth telling your manager')"
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
        {{ t('A visit here usually takes at least {n} minutes.',
             { n: visit.minVisitMinutes }) }}
      </p>
      <button class="btn-primary" @click="router.push({ name: 'visit-checkout' })">
        {{ t('Finish visit') }}
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
/* The chosen one is filled, not merely tinted: in sunlight a tint against a tint is no
   difference at all, and this decides what the photo is filed as. */
.chip.on { background: var(--primary); color: var(--on-primary); }

.purposes { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }

.shots { display: grid; grid-template-columns: repeat(auto-fill, minmax(88px, 1fr)); gap: 8px;
         margin-top: 12px; }
.shot { margin: 0; display: grid; gap: 4px; }
.shot img, .shot .noimg { width: 100%; aspect-ratio: 1; object-fit: cover; border-radius: 8px;
                          border: 1px solid var(--line); background: var(--surface); }
.shot .noimg { display: grid; place-items: center; color: var(--muted); }
.shot figcaption { display: grid; gap: 1px; font-size: 12px; line-height: 1.25; }
.shot figcaption em { font-style: normal; color: var(--muted); }
.shot figcaption em.bad { color: var(--crit); font-weight: 600; }
/* A sent photo steps back; one still waiting keeps its edge. */
.shot.sent img { opacity: .85; }
.shot.blocked img { border-color: var(--crit); }

.err { display: flex; align-items: flex-start; gap: 8px; margin: 0; font-size: 14px;
       background: var(--crit-soft); color: var(--crit); border-radius: 6px; padding: 10px 12px; }

.bottom { position: sticky; bottom: 0; padding: 12px 0 4px; margin-top: 16px;
          background: var(--bg); border-top: 1px solid var(--line); }
.note { text-align: center; margin: 0 0 8px; }
.btn-primary { display: flex; align-items: center; justify-content: center; gap: 6px;
               padding: 14px; min-height: 52px; border-radius: 6px; width: 100%; }
</style>
