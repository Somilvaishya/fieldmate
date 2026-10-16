<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ApiError } from '../api/client'
import { getPosition } from '../lib/geo'
import * as visitStore from '../stores/visit'
import * as photoQueue from '../sync/photos'
import Icon from '../components/Icon.vue'
import { t } from '../lib/i18n'
import { formatPaise } from '../lib/money'

const router = useRouter()
const visit = visitStore.activeVisit

// `value` is what the server stores and must never be translated - it is a Select option on
// FieldMate Visit. Only the label a rep reads changes.
const OUTCOMES = computed(() => [
  { value: 'Order Taken', label: t('Order taken'), icon: 'check' },
  { value: 'No Order', label: t('No order'), icon: 'close' },
  { value: 'Outlet Closed', label: t('Shop closed'), icon: 'store' },
  { value: 'Owner Absent', label: t('Owner away'), icon: 'person' },
  { value: 'Stock Sufficient', label: t('Enough stock'), icon: 'shelves' },
])

const NOTE_LIMIT = 200

const outcome = ref(null)
const reasonName = ref(null)
const reasons = ref([])
const note = ref('')
const busy = ref(false)
const error = ref('')
const photos = ref(0)

const noOrder = computed(() => !!outcome.value && outcome.value !== 'Order Taken')

/**
 * A reason is required only when there is one to pick.
 *
 * **A rep standing in a shop must never be unable to leave.** Where a site has no No Order Reason
 * master — which is most sites on day one — every outcome but "Order Taken" left the check-out
 * button dead for ever, with nothing on the screen saying why. The rep cannot create the master,
 * cannot check out, and the visit stays open until the next check-in closes it as something it
 * was not.
 *
 * The server never asked for one: `visit.check_out` records the reason if it is sent, the field is
 * not mandatory, and the auto-close path falls back to whatever reason exists or to none. This was
 * a gate the app invented and then could not satisfy.
 *
 * With no reasons on the phone a **note** takes the reason's place, because a visit that recorded
 * no order and no explanation is a visit nobody can act on.
 */
const canPickReason = computed(() => reasons.value.length > 0)
const needsReason = computed(() => noOrder.value && canPickReason.value)
const needsWords = computed(() => noOrder.value && !canPickReason.value)
const reason = computed(() => reasons.value.find((r) => r.name === reasonName.value))
const needsNote = computed(() => !!reason.value?.requires_note || needsWords.value)

// A shop that was never open cannot be surveyed, so its unanswered questions are not a block.
const shopWasOpen = computed(
  () => !['Outlet Closed', 'Owner Absent'].includes(outcome.value)
)
const missing = computed(
  () => (shopWasOpen.value ? visitStore.unansweredRequired(visit.value) : [])
)

/**
 * Why the button will not go, in the rep's own words — or an empty string when it will.
 *
 * A disabled button that says nothing is the worst control on a phone: the rep taps it, nothing
 * happens, and they have no idea what the app is waiting for. The order review screen already
 * says what it wants above its send button; this is the same rule in the other place a rep is
 * stopped at a counter.
 */
const blocker = computed(() => {
  if (!outcome.value) return t('Pick what came of this visit.')
  if (needsReason.value && !reasonName.value) return t('Pick why there was no order.')
  if (needsWords.value && !note.value.trim()) {
    return t('No reasons have reached this phone yet, so write what happened in the note instead.')
  }
  if (needsNote.value && !note.value.trim()) return t('This reason needs a note.')
  if (missing.value.length) {
    const n = missing.value.length
    // Whole sentences, not pieces: Hindi puts the count and the verb elsewhere, so there is
    // nothing to glue together in the right order.
    return n === 1
      ? t('Answer {n} required question in the checklist.', { n })
      : t('Answer {n} required questions in the checklist.', { n })
  }
  return ''
})

const ready = computed(() => !blocker.value)

const minutes = computed(() => {
  if (!visit.value?.checkInTime) return null
  const started = new Date(visit.value.checkInTime.replace(' ', 'T'))
  return Math.max(0, Math.round((Date.now() - started.getTime()) / 60000))
})

/** What this visit actually captured, so a rep sees it before committing. */
const captured = computed(() => {
  const v = visit.value
  if (!v) return ''
  const parts = []
  const answered = v.checklist.filter((q) => q.is_answered).length
  if (answered) parts.push(`${answered} answers`)
  if (photos.value) parts.push(`${photos.value} ${photos.value === 1 ? 'photo' : 'photos'}`)
  return parts.join(' · ')
})

onMounted(async () => {
  if (!visit.value) await visitStore.resume()
  if (!visit.value) return router.replace('/today')
  note.value = visit.value.remarks || ''
  reasons.value = await visitStore.noOrderReasons()
  photos.value = await photoQueue.pendingCount(visit.value.clientUuid)
  // The app already knows an order was booked here, so asking is a tap that can only be got
  // wrong. Still a normal selection, not a lock: a rep who books an order and then has it
  // refused at the counter has to be able to say so.
  if (visit.value.order) outcome.value = 'Order Taken'
})

async function finish() {
  error.value = ''
  busy.value = true
  try {
    const fix = await getPosition().catch(() => ({}))
    await visitStore.checkOut({
      outcome: outcome.value,
      noOrderReason: needsReason.value ? reasonName.value : null,
      remarks: note.value || null,
      fix,
    })
    router.replace('/today')
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : t('Could not finish the visit. Try again.')
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="wrap screen" v-if="visit">
    <h2>Finish at {{ visit.outletName }}</h2>
    <p class="muted tnum" v-if="minutes !== null">
      In the shop {{ minutes }} min<span v-if="captured"> · {{ captured }}</span>
    </p>

    <p class="lead">{{ t(t('What came of this visit?')) }}</p>
    <p v-if="visit?.order" class="booked">
      <Icon :name="visit.order.offline ? 'cloud-off' : 'check'" size="18" />
      <span>
        Order of &#8377;{{ formatPaise(visit.order.net) }} booked here{{
          visit.order.offline ? ', waiting to sync' : '' }}.
      </span>
    </p>

    <div class="outcomes" role="radiogroup" :aria-label="t('Visit outcome')">
      <button v-for="o in OUTCOMES" :key="o.value" type="button" role="radio"
              class="outcome" :class="{ on: outcome === o.value }"
              :aria-checked="outcome === o.value"
              @click="outcome = o.value; reasonName = null">
        <Icon :name="o.icon" size="20" />
        <span>{{ o.label }}</span>
        <Icon v-if="outcome === o.value" name="check" size="20" class="mark" />
      </button>
    </div>

    <template v-if="noOrder">
      <h3>{{ t(t('Why no order?')) }}</h3>
      <p v-if="!reasons.length" class="muted">
        No reasons have reached this phone. Say what happened in the note below instead &mdash; you
        can still check out.
      </p>
      <div class="chips">
        <button v-for="r in reasons" :key="r.name" type="button"
                class="chip" :class="{ on: reasonName === r.name }" @click="reasonName = r.name">
          {{ r.reason }}
        </button>
      </div>
    </template>

    <label class="lbl" for="note">
      <span>
        Note <span class="muted">{{ needsNote ? '(required for this reason)' : '(optional)' }}</span>
      </span>
      <span class="count tnum" :class="{ over: note.length > NOTE_LIMIT }">
        {{ note.length }} / {{ NOTE_LIMIT }}
      </span>
    </label>
    <textarea id="note" v-model="note" rows="3" :maxlength="NOTE_LIMIT"
              :placeholder="t('What actually happened at the shop')" />

    <p v-if="missing.length" class="blocked">
      {{ missing.length === 1
          ? t('Answer {n} required question before you leave.', { n: missing.length })
          : t('Answer {n} required questions before you leave.', { n: missing.length }) }}
      <RouterLink :to="{ name: 'visit-checklist' }">{{ t('Open the checklist') }}</RouterLink>
    </p>

    <p v-if="error" class="err">{{ error }}</p>

    <div class="bottom">
      <p v-if="blocker && !busy" class="gate">{{ blocker }}</p>
      <button class="btn-primary" :disabled="!ready || busy" @click="finish">
        {{ busy ? 'Finishing…' : 'Check out' }}
      </button>
      <button class="btn-plain" @click="router.back()">Back to visit</button>
    </div>
  </div>
</template>

<style scoped>
.screen { display: flex; flex-direction: column; min-height: 100%; }
h2 { margin: 8px 0 4px; }
h3 { margin: 24px 0 8px; font-size: 16px; }
.muted { color: var(--muted); font-size: 14px; }
.lead { margin: 16px 0 0; font-weight: 600; }
.booked { display: flex; align-items: center; gap: 8px; margin: 0 0 14px;
          background: var(--ok-soft); color: var(--ok);
          border-radius: 6px; padding: 10px 12px; font-size: 14px; line-height: 1.45; }

/* Stacked full-width rows rather than wrapped chips: five outcomes wrap raggedly at 360px,
   and this is the one choice on the screen that must be unmistakable. */
.outcomes { display: grid; gap: 8px; margin-top: 10px; }
.outcome { display: flex; align-items: center; gap: 10px; width: 100%; min-height: 52px;
           padding: 0 14px; border-radius: 6px; font-size: 16px; font-weight: 600;
           background: var(--surface); border: 1px solid var(--line); color: var(--ink); }
.outcome.on { background: var(--primary); border-color: var(--primary);
              color: var(--on-primary); }
.outcome span { flex: 1; text-align: left; }
.mark { flex: none; }
.lbl { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
.count { font-size: 14px; color: var(--muted); }
.count.over { color: var(--crit); }

.chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.chip { background: var(--surface); border: 1px solid var(--line); color: var(--ink);
        padding: 0 16px; }
.chip.on { background: var(--primary); border-color: var(--primary); color: var(--on-primary);
           font-weight: 600; }
.lbl { display: block; margin: 20px 0 6px; font-weight: 600; }
textarea { width: 100%; font: inherit; padding: 10px 12px; border: 1px solid var(--line);
           border-radius: 6px; background: var(--surface); color: var(--ink); }
.blocked { margin-top: 14px; padding: 12px; border-radius: 8px; color: var(--warn);
           border: 1px solid var(--warn); background: var(--surface); font-size: 14px; }
.blocked a { color: var(--primary); }
.err { color: var(--crit); margin-top: 14px; }
.bottom { margin-top: auto; padding-top: 16px; display: grid; gap: 8px; }
/* What the button is waiting for. Holds the 16px floor like every other line that gates an
   action — a rep reads this one in a shop, standing, in bad light. */
.gate { margin: 0; text-align: center; font-size: 16px; color: var(--muted); }
.btn-plain { background: none; border: 1px solid var(--line); color: var(--ink); width: 100%; }
</style>
