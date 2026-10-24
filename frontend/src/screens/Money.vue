<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute } from 'vue-router'
import { api, ApiError } from '../api/client'
import { deviceUuid } from '../db'
import { formatRupees } from '../lib/money'
import Icon from '../components/Icon.vue'
import { t } from '../lib/i18n'

const route = useRoute()

const inHand = ref(null)
const collections = ref([])
const loading = ref(true)
const error = ref('')
// Separate from `error`: cash in hand failing hides the whole screen, a receipt list failing
// only costs the list below it.
const listError = ref('')

const TONE = {
  Collected: 'warn',
  Deposited: 'calm',
  Confirmed: 'ok',
  Bounced: 'crit',
  Cancelled: 'crit',
}

// A shop's cash is the distributor's, passing through the rep's satchel; a distributor's is
// ours. The rep does not need the accounting words, but they do need to know that both are
// money they are carrying and answerable for.
const carrying = computed(() => Number(inHand.value?.total_amount || 0))
const overdue = computed(() => !!inHand.value?.is_overdue)

function day(value) {
  if (!value) return ''
  const [y, m, d] = String(value).slice(0, 10).split('-')
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const month = months[Number(m) - 1]
  return `${d} ${month ? t(month) : ''}`.trim()
}

const PAGE = 50
const receiptCount = ref(0)
const hasMoreReceipts = ref(false)
const loadingMore = ref(false)

/** The next page of receipts.
 *
 * A button rather than an infinite scroll, for the reason the order list gives: on a market
 * uplink a scroll that fetches silently is a scroll that silently fails.
 */
async function moreReceipts() {
  loadingMore.value = true
  try {
    const data = await api.collectionsMine(undefined,
      { limit: PAGE, start: collections.value.length })
    collections.value = [...collections.value, ...(data.collections || [])]
    receiptCount.value = Number(data.total ?? collections.value.length)
    hasMoreReceipts.value = !!data.has_more
  } catch (e) {
    listError.value = e instanceof ApiError
      ? e.message
      : t('Could not load more receipts.')
  } finally {
    loadingMore.value = false
  }
}

async function load() {
  loading.value = true
  error.value = ''
  listError.value = ''
  try {
    // Cash in hand is the figure the rep is answerable for, so it is the one that must load.
    inHand.value = await api.cashInHand()
    try {
      const data = await api.collectionsMine(undefined, { limit: PAGE, start: 0 })
      collections.value = data.collections || []
      receiptCount.value = Number(data.total ?? collections.value.length)
      hasMoreReceipts.value = !!data.has_more
    } catch (e) {
      // Not swallowed. This used to fall through to an empty list, so a broken call and a rep
      // who has genuinely collected nothing looked exactly alike - and the wrong one of those
      // is the one a rep would act on.
      collections.value = []
      listError.value = e instanceof ApiError
        ? e.message
        : t('Could not load your recent receipts.')
    }
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : t('Could not load your collections.')
  } finally {
    loading.value = false
  }
}

// ------------------------------------------------------- money taken from the depot itself

// A shop's cash belongs to its distributor and only passes through the rep's satchel. Money
// taken FROM a distributor is ours, and it is the only kind that ever reaches the ledger
// (ADR-025) - which is exactly why there has to be a way to record it, and until now there was
// not one on the phone at all.
const depots = ref([])
const taking = ref(false)
// `date` and `booking` as well as the rest.
//
// **The date is what makes a cheque a cheque.** A season booking is released only by money that
// has *arrived*, and a cheque dated three weeks out has not - `in_hand_by_order` says so and
// `release_if_paid` honours it. A form with no date field recorded every cheque as cash in all
// but name, so a booking would release on a promise and the office would reserve stock against it.
//
// **The booking is what makes an advance an advance.** `FieldMate Collection.on_submit` tries the
// advance gate again for each order the receipt is allocated to, and nothing else does. Money
// taken from a depot and allocated to nothing is money that pays no booking: the rep collects it,
// the figure on the season book does not move, and nobody can say why.
const form = ref({
  distributor: '', amount: '', mode: 'Cash', reference: '', date: '', from: '', booking: '',
})
const saveError = ref('')
const saving = ref(false)

// Minted once when the form opens and kept until it succeeds, never per attempt. If the first
// save reaches the server and the answer does not, tapping again must land as the same receipt -
// a fresh uuid on the retry is how a rep ends up having collected the depot's money twice.
const draftUuid = ref(null)

const MODES = ['Cash', 'UPI', 'Cheque', 'DD', 'Bank Transfer']
const needsReference = computed(() => form.value.mode !== 'Cash')
const isCheque = computed(() => ['Cheque', 'DD'].includes(form.value.mode))

// This rep's open bookings, so a receipt can be put against one. Only the ones still short:
// allocating to a booking whose advance is already in hand is allowed and pointless, and a
// list of twenty where two matter is a list nobody reads.
const bookings = ref([])
const owing = computed(() => bookings.value.filter((b) => Number(b.advance_short) > 0))
const chosenBooking = computed(() =>
  owing.value.find((b) => b.name === form.value.booking) || null
)

/**
 * Picking a booking settles which depot the money came from.
 *
 * Not a convenience. A booking belongs to one party, and a receipt saved against **another**
 * depot while allocated to that booking is money credited to the wrong account and an advance
 * that releases somebody else's order. The rep is choosing the booking, so the booking decides.
 * The shortfall is only suggested, because a part payment is an ordinary thing.
 */
watch(() => form.value.booking, () => {
  const b = chosenBooking.value
  if (!b) return
  form.value.distributor = b.customer || form.value.distributor
  if (!Number(form.value.amount)) form.value.amount = String(b.advance_short || '')
})

/**
 * Is this receipt going to release the booking it is put against?
 *
 * Said out loud because it is the single thing a rep most needs to know while taking the money,
 * and the one thing the form itself cannot change: a post-dated cheque is recorded, allocated
 * and shown against the booking, and the booking stays held until the cheque falls due.
 */
const willRelease = computed(() => {
  const b = chosenBooking.value
  if (!b) return null
  if (isCheque.value && form.value.date && form.value.date > new Date().toISOString().slice(0, 10)) {
    return false
  }
  return Number(form.value.amount || 0) >= Number(b.advance_short || 0)
})

const canSave = computed(() =>
  !!form.value.distributor
  && Number(form.value.amount) > 0
  && (!needsReference.value || !!form.value.reference.trim())
)

async function openTake() {
  taking.value = true
  saveError.value = ''
  draftUuid.value = crypto.randomUUID()
  try {
    if (!depots.value.length) {
      const data = await api.distributors()
      depots.value = data.distributors || []
      if (depots.value.length === 1) form.value.distributor = depots.value[0].distributor
    }
    // Fetched every time the form opens, not once. What a booking is short of moves because
    // somebody else banked a cheque, and a cached figure is wrong in the one direction that
    // matters: it would ask the party for money they have already paid.
    const book = await api.orderBookings()
    bookings.value = book.bookings || []
  } catch (e) {
    // The depots are needed to save at all; the bookings are not. Either way this is one
    // sentence, because a rep cannot act on which of the two calls failed.
    saveError.value = e instanceof ApiError
      ? e.message
      : t('Could not load your depots. This one needs signal.')
  }

  // Walked in from the season book: the booking, its depot and what it is short of are already
  // known, so the rep is not asked to type any of them again.
  const wanted = String(route.query.order || '')
  if (!wanted) return
  const match = bookings.value.find((b) => b.name === wanted)
  if (!match) return
  form.value.booking = match.name
  form.value.distributor = match.customer || form.value.distributor
  if (!Number(form.value.amount)) form.value.amount = String(match.advance_short || '')
}

function closeTake() {
  taking.value = false
  saveError.value = ''
  draftUuid.value = null
  form.value = {
    distributor: '', amount: '', mode: 'Cash', reference: '', date: '', from: '', booking: '',
  }
}

async function takeFromDepot() {
  saving.value = true
  saveError.value = ''
  try {
    await api.collectionCreate({
      party_type: 'Distributor',
      distributor: form.value.distributor,
      amount: Number(form.value.amount),
      mode: form.value.mode,
      instrument_no: form.value.reference.trim() || null,
      // Only for an instrument that has one. A date on a cash receipt is a field nobody reads;
      // a *missing* date on a cheque is a PDC recorded as money in hand.
      instrument_date: isCheque.value ? form.value.date || null : null,
      collected_from_name: form.value.from.trim() || null,
      // Against the booking, where the rep said so. This is the whole of what makes the advance
      // gate work from the field: `FieldMate Collection.on_submit` reads these rows and tries
      // the gate again for each order named.
      allocations: form.value.booking
        ? [{
            reference_type: 'FieldMate Order',
            reference_name: form.value.booking,
            outstanding_amount: Number(chosenBooking.value?.advance_short || 0),
            allocated_amount: Number(form.value.amount),
          }]
        : [],
      client_uuid: draftUuid.value,
      device_id: await deviceUuid(),
    })
    closeTake()
    await load()
  } catch (e) {
    saveError.value = e instanceof ApiError
      ? e.message
      : t('Could not record it. This one needs signal — nothing was saved.')
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await load()
  // Walked in from the season book with a booking to pay. Opening the form is the whole point of
  // that link, and making the rep hunt for the button again is a step that exists for no reason.
  if (route.query.order) await openTake()
})
</script>

<template>
  <div class="wrap">
    <header class="head">
      <div>
        <h1>{{ t('Collections') }}</h1>
        <p class="dim">{{ t('What you took, and what is still with you') }}</p>
      </div>
      <button class="quiet" :disabled="loading" @click="load" :aria-label="t('Refresh')">
        <Icon name="refresh" size="18" />
      </button>
    </header>

    <p v-if="loading" class="note">{{ t('Loading…') }}</p>
    <p v-else-if="error" class="note crit">{{ error }}</p>

    <template v-else>
      <!-- The satchel. Top of the screen because it is the only number here the rep is
           personally answerable for. -->
      <RouterLink to="/deposit" class="hand" :class="{ late: overdue }">
        <Icon name="tag" size="22" />
        <span class="body">
          <b class="tnum">
            {{ t('{amount} with you', { amount: formatRupees(carrying) }) }}
          </b>
          <em v-if="overdue">
            {{ t('Carrying it {days} days — your manager is told',
                 { days: inHand.oldest_days }) }}
          </em>
          <em v-else-if="inHand?.count">
            {{ inHand.count === 1
                ? t('{n} receipt to hand in', { n: inHand.count })
                : t('{n} receipts to hand in', { n: inHand.count }) }}
          </em>
          <em v-else>{{ t('Nothing to hand in right now') }}</em>
        </span>
        <Icon name="chevron" size="18" class="go" />
      </RouterLink>

      <!-- Below the satchel, because handing money in is the commoner errand. -->
      <button v-if="!taking" class="take" @click="openTake">
        <Icon name="tag" size="20" />
        <span>
          <b>{{ t('Take from a depot') }}</b>
          <em>{{ t('Money collected from a distributor, not a shop') }}</em>
        </span>
      </button>

      <div v-else class="form">
        <div class="frow">
          <h2>{{ t('Take from a depot') }}</h2>
          <button class="quiet" @click="closeTake" :aria-label="t('Close')">
            <Icon name="close" size="20" />
          </button>
        </div>

        <label>
          <span class="lbl">{{ t('Which depot') }}</span>
          <select v-model="form.distributor" :disabled="saving">
            <option value="">{{ t('Choose one') }}</option>
            <option v-for="d in depots" :key="d.distributor" :value="d.distributor">
              {{ d.distributor_name }}
            </option>
          </select>
        </label>

        <label>
          <span class="lbl">{{ t('How much') }}</span>
          <input v-model="form.amount" type="number" inputmode="decimal" min="0"
                 :disabled="saving" placeholder="0" />
        </label>

        <label>
          <span class="lbl">{{ t('How it was paid') }}</span>
          <select v-model="form.mode" :disabled="saving">
            <!-- The value stays English; only what the rep reads goes through `t()`. -->
            <option v-for="m in MODES" :key="m" :value="m">{{ t(m) }}</option>
          </select>
        </label>

        <!-- Anything but cash leaves a number on a slip, and a claim with no number on it is
             the first thing anybody disputes. -->
        <label v-if="needsReference">
          <span class="lbl">{{ t('{mode} number', { mode: t(form.mode) }) }}</span>
          <input v-model="form.reference" type="text" :disabled="saving"
                 :placeholder="t('Cheque / UPI reference')" />
        </label>

        <!-- The date on the cheque, which is not today just because today is when it was
             handed over. A later date is a PDC: still recorded, still allocated, and not money
             until it falls due. -->
        <label v-if="isCheque">
          <span class="lbl">
            {{ t('Date on the {mode}', { mode: t(form.mode) }) }}
          </span>
          <input v-model="form.date" type="date" :disabled="saving" />
        </label>

        <!-- What it pays. Only bookings still short of their advance appear, because those are
             the only ones a receipt changes anything for. -->
        <label v-if="owing.length">
          <span class="lbl">
            {{ t('Against a booking') }}
            <em class="opt">{{ t('(optional)') }}</em>
          </span>
          <select v-model="form.booking" :disabled="saving">
            <option value="">{{ t('Not against a booking') }}</option>
            <option v-for="b in owing" :key="b.name" :value="b.name">
              {{ b.customer }} · {{ b.season_name || b.season }} ·
              {{ t('short {amount}',
                   { amount: formatRupees(b.advance_short) }) }}
            </option>
          </select>
        </label>

        <!-- Said while the rep is still standing there, because it is the one thing the form
             cannot fix and the party is waiting to be told. -->
        <p v-if="chosenBooking && willRelease === true" class="note good">
          <Icon name="check" size="18" />
          <span>
            {{ t('This releases the booking. It goes forward to be planned.') }}
          </span>
        </p>
        <p v-else-if="chosenBooking && willRelease === false" class="note warn">
          <Icon name="alert" size="18" />
          <span v-if="isCheque && form.date">
            {{ t('A cheque dated later does not release the booking.') }}
            {{ t('It is recorded and held against it, and the booking goes forward when the cheque falls due.') }}
          </span>
          <span v-else class="tnum">
            {{ t('This is less than the') }}
            <b>{{ formatRupees(chosenBooking.advance_short) }}</b>
            {{ t('still due, so the booking stays held.') }}
            {{ t('Record it anyway — part of an advance counts.') }}
          </span>
        </p>

        <label>
          <span class="lbl">
            {{ t('Who handed it over') }} <em class="opt">{{ t('(optional)') }}</em>
          </span>
          <input v-model="form.from" type="text" :disabled="saving" :placeholder="t('Name')" />
        </label>

        <p v-if="saveError" class="note crit">{{ saveError }}</p>

        <p class="dim fine">
          {{ t('This money is ours.') }}
          {{ t('It reaches the books when somebody at the office confirms your deposit — not now.') }}
        </p>

        <button class="btn-primary" :disabled="!canSave || saving" @click="takeFromDepot">
          {{ saving ? t('Saving…') : t('Record it') }}
        </button>
      </div>

      <template v-if="collections.length">
        <div class="section"><h2>{{ t('Recent receipts') }}</h2></div>
        <div v-for="c in collections" :key="c.name" class="row">
          <div class="left">
            <b>{{ c.party_name || c.outlet || c.distributor || c.party }}</b>
            <span class="dim">{{ day(c.collection_date) }} · {{ t(c.mode) }}
              <template v-if="c.receipt_no"> · {{ c.receipt_no }}</template>
            </span>
          </div>
          <div class="right">
            <b class="tnum">{{ formatRupees(c.amount) }}</b>
            <span class="pill" :class="TONE[c.status] || 'flat'">{{ t(c.status) }}</span>
          </div>
        </div>

        <button v-if="hasMoreReceipts" class="more" type="button"
                :disabled="loadingMore" @click="moreReceipts">
          {{ loadingMore
              ? t('Loading…')
              : t('Show more ({n} left)', { n: receiptCount - collections.length }) }}
        </button>
      </template>

      <p v-else-if="listError" class="note crit">{{ listError }}</p>

      <div v-else class="empty">
        <Icon name="tag" size="34" />
        <b>{{ t('No collections yet') }}</b>
        <p class="dim">{{ t('Take one at a shop and it will show up here.') }}</p>
      </div>

      <p class="dim fine">
        {{ t("Money taken at a shop belongs to that shop's distributor.") }}
        {{ t('You are carrying it, not earning it — hand it in and it is off your name.') }}
      </p>
    </template>
  </div>
</template>

<style scoped>
.wrap { max-width: 560px; margin: 0 auto; padding: 16px; display: flex;
        flex-direction: column; gap: 12px; }
.head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.head h1 { font-size: 20px; margin: 0; }
.dim { color: var(--muted); font-size: 13px; margin: 2px 0 0; }
.fine { font-size: 12px; }
.quiet { border: 0; background: none; color: var(--muted); min-height: 44px; padding: 0 6px; }

.hand { display: flex; align-items: center; gap: 10px; text-decoration: none;
        background: var(--ok-soft); color: var(--ok); border-radius: 10px; padding: 14px;
        min-height: 64px; }
.hand.late { background: var(--warn-soft); color: var(--warn); }
.hand .body { flex: 1; display: flex; flex-direction: column; gap: 2px; }
.hand em { font-style: normal; font-size: 13px; color: var(--muted); }
.go { flex: none; }

.section h2 { font-size: 15px; margin: 4px 0 0; }

.take { display: flex; align-items: center; gap: 10px; text-align: left; min-height: 64px;
        padding: 12px 14px; background: var(--surface); border: 1px solid var(--line);
        border-radius: 10px; color: var(--ink); }
.take > span { display: grid; gap: 2px; }
.take em { font-style: normal; font-size: 13px; color: var(--muted); }

.form { display: flex; flex-direction: column; gap: 10px; background: var(--surface);
        border: 1px solid var(--line); border-radius: 10px; padding: 14px; }
.frow { display: flex; align-items: center; justify-content: space-between; }
.frow h2 { font-size: 16px; margin: 0; }
.form label { display: grid; gap: 4px; }
.lbl { font-size: 13px; font-weight: 600; color: var(--muted); }
.lbl .opt { font-style: normal; font-weight: 400; }
.form select { min-height: 48px; padding: 0 12px; border: 1px solid var(--line);
               border-radius: 6px; background: var(--surface); color: var(--ink);
               font: inherit; width: 100%; }
.fine { font-size: 12px; margin: 0; }
.row { display: flex; align-items: center; justify-content: space-between; gap: 10px;
       background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
       padding: 12px; }
.left { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.right { display: flex; flex-direction: column; align-items: flex-end; gap: 4px; flex: none; }
.pill { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 6px; }
.pill.ok { background: var(--ok-soft); color: var(--ok); }
.pill.warn { background: var(--warn-soft); color: var(--warn); }
.pill.crit { background: var(--crit-soft); color: var(--crit); }
.pill.calm, .pill.flat { background: var(--primary-soft); color: var(--primary); }
.note { color: var(--muted); font-size: 14px; text-align: center; padding: 20px 0; }
.note.good { color: var(--ok); text-align: left; background: var(--ok-soft);
             border-radius: 8px; padding: 10px 12px; display: flex; gap: 8px;
             align-items: flex-start; }
.note.warn { color: var(--warn); text-align: left; background: var(--warn-soft);
             border-radius: 8px; padding: 10px 12px; display: flex; gap: 8px;
             align-items: flex-start; }
.note.crit { color: var(--crit); text-align: left; background: var(--crit-soft);
             border-radius: 8px; padding: 10px 12px; }
.empty { text-align: center; padding: 32px 16px; color: var(--muted); display: flex;
         flex-direction: column; gap: 6px; align-items: center; }
.empty b { color: var(--ink); }
.empty p { margin: 0; }
.tnum { font-variant-numeric: tabular-nums; }
.more { width: 100%; min-height: 48px; border-radius: 8px; font-weight: 600; font-size: 15px;
        border: 1px solid var(--primary); background: var(--surface); color: var(--primary); }
.more:disabled { color: var(--muted); border-color: var(--line); }
</style>
