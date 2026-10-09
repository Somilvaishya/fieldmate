<script setup>
/**
 * Share the range with a party — a link they open in WhatsApp, at their own prices.
 *
 * **What a rep has to understand before they tap this.** A share link is a URL in a chat message,
 * so whoever holds it is whoever it was forwarded to. It carries one party's prices, it expires,
 * and it can be switched off — and this screen says all three out loud, because a rep who thinks
 * a link is private will send one into a market group.
 *
 * It does not pretend to be an order screen. What comes back off a shared catalogue is a **draft**
 * on this phone, for the rep to price properly and submit: a party typing quantities into a web
 * page has been through no credit check, no scheme engine and no MRP check. That draft lands in
 * the orders list like any other.
 *
 * Needs signal, and says so. A link that existed only on the handset would be a URL the server
 * has never heard of, which is a link that answers "not available" to the party it was sent to.
 */
import { ref, computed, onMounted } from 'vue'
import { api, ApiError } from '../api/client'
import { getMeta } from '../db'
import Icon from '../components/Icon.vue'

const parties = ref([])
const links = ref([])
const loading = ref(true)
const error = ref('')

// ------------------------------------------------------------------------------- making one

const party = ref('')
const catalogues = ref([])
const catalogue = ref('')
const validTo = ref('')
const loadingCatalogues = ref(false)
const sharing = ref(false)
const shareError = ref('')
const made = ref(null)
const copied = ref(false)

const partyName = computed(
  () => (parties.value.find((p) => p.distributor === party.value) || {}).distributor_name || ''
)
const canShare = computed(() => !!party.value && !!catalogue.value && !sharing.value)

/**
 * The parties this rep sells to, out of the stored bootstrap payload.
 *
 * The same list `/parties` draws, read from the phone rather than fetched: a rep standing in a
 * godown should get the names from the handset even when the catalogue call behind them fails.
 */
async function loadParties() {
  const boot = (await getMeta('profile')) || {}
  parties.value = boot.distributors || []
  if (parties.value.length === 1) {
    party.value = parties.value[0].distributor
    await loadCatalogues()
  }
}

/**
 * What may be shown to the chosen party, which is not everything.
 *
 * Asked per party because scoping is per party — a catalogue written for one region does not
 * reach a party in another — and because only a catalogue **marked as a showcase** can be
 * shared at all. An ordinary catalogue carries focus flags, minimum order quantities and notes
 * written for the person selling, and putting one in front of a buyer is a leak, not a feature.
 */
async function loadCatalogues() {
  catalogue.value = ''
  catalogues.value = []
  made.value = null
  shareError.value = ''
  if (!party.value) return

  loadingCatalogues.value = true
  try {
    const data = await api.showcaseCatalogues(party.value, 'Customer')
    catalogues.value = data.catalogues || []
    if (catalogues.value.length === 1) catalogue.value = catalogues.value[0].name
  } catch (e) {
    shareError.value =
      e instanceof ApiError ? e.message : 'Could not load what can be shared. This needs signal.'
  } finally {
    loadingCatalogues.value = false
  }
}

async function share() {
  sharing.value = true
  shareError.value = ''
  copied.value = false
  try {
    made.value = await api.showcaseShare({
      catalogue: catalogue.value,
      party: party.value,
      party_type: 'Customer',
      // Blank leaves it to the master's own default. A rep who has a date in mind is the person
      // who knows how long the quotation should stand; a rep who has not should not be made to
      // invent one.
      valid_to: validTo.value || null,
    })
    await loadLinks()
  } catch (e) {
    shareError.value =
      e instanceof ApiError ? e.message : 'Could not make the link. This one needs signal.'
  } finally {
    sharing.value = false
  }
}

/**
 * The address, onto the clipboard.
 *
 * Copy rather than a share sheet: `navigator.share` is missing or refused on a good share of the
 * Android WebViews this runs in, and a button that silently does nothing is worse than one that
 * does one plain thing. The URL is shown as selectable text beside it either way.
 */
async function copy(url) {
  try {
    await navigator.clipboard.writeText(url)
    copied.value = true
  } catch {
    // Refused by the browser. The link is on the screen to read off, which is what the rep
    // would fall back to anyway.
    copied.value = false
    shareError.value = 'Could not copy it. The link is above — press and hold to select it.'
  }
}

// -------------------------------------------------------------------------- what was shared

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

function day(value) {
  if (!value) return ''
  const [y, m, d] = String(value).slice(0, 10).split('-')
  return `${Number(d)} ${MONTHS[Number(m) - 1]} ${String(y).slice(2)}`
}

const pulling = ref('')

async function loadLinks() {
  try {
    const data = await api.showcaseLinks()
    links.value = data.links || []
  } catch (e) {
    error.value =
      e instanceof ApiError
        ? e.message
        : 'Could not load what you have shared. This list lives on the server.'
  }
}

/**
 * Switch a link off — the only way a URL is ever taken back.
 *
 * Two taps, because it cannot be undone and because somebody may be reading the page right now.
 * A new link can be made in a moment; the old address is dead for good.
 */
const confirming = ref('')

async function withdraw(link) {
  pulling.value = link.name
  error.value = ''
  try {
    await api.showcaseWithdraw(link.name)
    confirming.value = ''
    await loadLinks()
  } catch (e) {
    error.value =
      e instanceof ApiError ? e.message : 'Could not switch it off. This one needs signal.'
  } finally {
    pulling.value = ''
  }
}

onMounted(async () => {
  try {
    await loadParties()
    await loadLinks()
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div class="wrap">
    <header class="head">
      <div>
        <h1>Share the range</h1>
        <p class="dim">A link the party opens themselves, at their own prices</p>
      </div>
      <button class="quiet" :disabled="loading" @click="loadLinks" aria-label="Refresh">
        <Icon name="refresh" size="18" />
      </button>
    </header>

    <!-- Said first, before the rep makes one. A link forwarded round a market is still one link,
         and a rep who did not know that is a rep who will find out the expensive way. -->
    <p class="note plain">
      <Icon name="info" size="18" />
      <span>
        Whoever holds the link can open it. It carries <b>one party&rsquo;s</b> prices, it
        expires, and you can switch it off &mdash; nothing else takes a URL back.
      </span>
    </p>

    <p v-if="loading" class="note">Loading…</p>

    <template v-else>
      <!-- ----------------------------------------------------------------- making one -->
      <div class="form">
        <div class="frow"><h2>Send a catalogue</h2></div>

        <label>
          <span class="lbl">To which party</span>
          <select v-model="party" :disabled="sharing" @change="loadCatalogues">
            <option value="">Choose one</option>
            <option v-for="p in parties" :key="p.distributor" :value="p.distributor">
              {{ p.distributor_name }}
            </option>
          </select>
        </label>

        <p v-if="!parties.length" class="dim fine">
          No distributor is set up against your territory yet, so there is nobody here to share
          with. Ask your manager.
        </p>

        <template v-if="party">
          <p v-if="loadingCatalogues" class="dim fine">Looking for what can be shared…</p>

          <!-- Named plainly, because "nothing to share" and "nothing is marked as a showcase"
               are different problems and only one of them is the rep's to report. -->
          <p v-else-if="!catalogues.length" class="dim fine">
            Nothing is marked as a showcase for {{ partyName }}. An ordinary catalogue is written
            for you, not for them, so it cannot be shared. Ask your manager for one.
          </p>

          <label v-else>
            <span class="lbl">Which catalogue</span>
            <select v-model="catalogue" :disabled="sharing">
              <option value="">Choose one</option>
              <option v-for="c in catalogues" :key="c.name" :value="c.name">
                {{ c.catalogue_name }} · {{ c.line_count }} items
              </option>
            </select>
          </label>

          <label v-if="catalogues.length">
            <span class="lbl">Hold the prices until <em class="opt">(optional)</em></span>
            <input v-model="validTo" type="date" :disabled="sharing" />
          </label>
        </template>

        <p v-if="shareError" class="note crit">{{ shareError }}</p>

        <!-- What came back. The address is shown as text as well as copied, because a copy the
             browser refused is a copy the rep has no way to notice. -->
        <div v-if="made" class="made">
          <p class="stamp">
            <Icon name="check" size="18" />
            <span>Link ready for {{ partyName }}</span>
          </p>
          <p class="url">{{ made.url }}</p>
          <button class="btn-plain" @click="copy(made.url)">
            {{ copied ? 'Copied' : 'Copy the link' }}
          </button>
          <p class="dim fine">
            Paste it into a message to them. What they send back arrives here as a
            <b>draft order</b> for you to check and submit &mdash; nothing they do commits
            anything.
          </p>
        </div>

        <button v-if="catalogues.length" class="btn-primary" :disabled="!canShare" @click="share">
          {{ sharing ? 'Making the link…' : 'Make a link' }}
        </button>
      </div>

      <!-- ------------------------------------------------------------ what was shared -->
      <p v-if="error" class="note crit">{{ error }}</p>

      <template v-if="links.length">
        <div class="section"><h2>What you have shared</h2></div>

        <div v-for="link in links" :key="link.name" class="card">
          <div class="row">
            <div class="left">
              <b>{{ link.party_name || link.party }}</b>
              <span class="dim">{{ link.catalogue_name || link.catalogue }}</span>
            </div>
            <span class="pill" :class="link.live ? 'ok' : 'flat'">
              {{ link.live ? 'Live' : 'Closed' }}
            </span>
          </div>

          <!-- How it has been received, which is the only thing a rep can learn from this and
               the reason the screen is worth opening twice. -->
          <div class="meta tnum">
            <span v-if="link.view_count">
              Opened {{ link.view_count }} {{ link.view_count === 1 ? 'time' : 'times' }}
            </span>
            <span v-else>Not opened yet</span>
            <span v-if="link.last_opened">Last {{ day(link.last_opened) }}</span>
            <span v-if="link.valid_to">
              {{ link.live ? 'Prices held until' : 'Expired' }} {{ day(link.valid_to) }}
            </span>
            <span v-if="link.max_views">Capped at {{ link.max_views }} opens</span>
          </div>

          <p v-if="!link.live && link.closed_because" class="dim fine">
            {{ link.closed_because }}
          </p>

          <div v-if="link.live" class="acts">
            <button class="btn-plain" @click="copy(link.url)">Copy the link</button>
            <button v-if="confirming !== link.name" class="undo"
                    @click="confirming = link.name">
              Switch it off
            </button>
          </div>

          <div v-if="confirming === link.name" class="sure">
            <p class="dim">
              The address stops working for everybody, including anybody reading it now. It
              cannot be undone &mdash; but you can make a new link in a moment.
            </p>
            <div class="pair">
              <button class="keep" :disabled="pulling === link.name" @click="confirming = ''">
                Leave it on
              </button>
              <button class="go" :disabled="pulling === link.name" @click="withdraw(link)">
                {{ pulling === link.name ? 'Switching off…' : 'Yes, switch it off' }}
              </button>
            </div>
          </div>
        </div>
      </template>

      <div v-else class="empty">
        <Icon name="tag" size="34" />
        <b>Nothing shared yet</b>
        <p class="dim">Pick a party above and send them the range.</p>
      </div>
    </template>
  </div>
</template>

<style scoped>
.wrap { max-width: 560px; margin: 0 auto; padding: 16px; display: flex;
        flex-direction: column; gap: 12px; }
.head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.head h1 { font-size: 20px; margin: 0; }
.dim { color: var(--muted); font-size: 13px; margin: 2px 0 0; }
.fine { font-size: 13px; }
.quiet { border: 0; background: none; color: var(--muted); min-height: 44px; padding: 0 6px; }

.form { background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
        padding: 14px; display: flex; flex-direction: column; gap: 12px; }
.frow h2 { margin: 0; font-size: 16px; }
.form label { display: flex; flex-direction: column; gap: 6px; }
.lbl { font-size: 13px; text-transform: uppercase; letter-spacing: 0.04em; color: var(--muted); }
.opt { font-style: normal; text-transform: none; letter-spacing: 0; }
.form select, .form input { min-height: 48px; font: inherit; padding: 0 10px;
                            border: 1px solid var(--line); border-radius: 8px;
                            background: var(--surface); color: var(--ink); }

.made { background: var(--ok-soft); border: 1px solid var(--ok); border-radius: 8px;
        padding: 12px; display: flex; flex-direction: column; gap: 8px; }
.stamp { display: flex; align-items: center; gap: 6px; margin: 0; color: var(--ok);
         font-weight: 600; }
/* Selectable and wrapping. A rep whose browser refuses the clipboard reads it off the screen. */
.url { margin: 0; font-family: ui-monospace, Menlo, Consolas, monospace; font-size: 13px;
       word-break: break-all; user-select: all; }

.section h2 { margin: 6px 0 0; font-size: 14px; text-transform: uppercase;
              letter-spacing: 0.04em; color: var(--muted); }

.card { background: var(--surface); border: 1px solid var(--line); border-radius: 10px;
        padding: 12px; display: flex; flex-direction: column; gap: 8px; }
.row { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
.left { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.meta { display: flex; flex-wrap: wrap; gap: 4px 12px; font-size: 12px; color: var(--muted); }

.acts { display: flex; flex-wrap: wrap; gap: 8px; }
.btn-plain { min-height: 44px; padding: 0 14px; border-radius: 8px; border: 1px solid var(--line);
             background: var(--surface); color: var(--primary); font-weight: 600; font-size: 14px; }
.undo { min-height: 44px; padding: 0 12px; border-radius: 8px; border: 1px solid var(--line);
        background: none; color: var(--muted); font-weight: 600; font-size: 14px; }
.sure { display: flex; flex-direction: column; gap: 8px; border-top: 1px solid var(--line);
        padding-top: 10px; }
.sure .dim { margin: 0; }
.pair { display: flex; gap: 8px; }
.pair button { flex: 1; min-height: 48px; border-radius: 8px; font-weight: 600; }
.keep { border: 1px solid var(--line); background: var(--surface); color: var(--ink); }
.go { border: 0; background: var(--crit); color: #fff; }

.btn-primary { display: flex; align-items: center; justify-content: center; min-height: 52px;
               border: 0; border-radius: 8px; background: var(--primary);
               color: var(--on-primary); font-weight: 600; font-size: 16px; }
.btn-primary:disabled { opacity: 0.55; }

.pill { font-size: 11px; font-weight: 700; padding: 2px 8px; border-radius: 6px;
        white-space: nowrap; flex: none; }
.pill.ok { background: var(--ok-soft); color: var(--ok); }
.pill.flat { background: var(--primary-soft); color: var(--primary); }

.note { color: var(--muted); font-size: 14px; text-align: center; padding: 16px 0; }
.note.plain { display: flex; gap: 8px; align-items: flex-start; text-align: left;
              background: var(--primary-soft); color: var(--primary); border-radius: 8px;
              padding: 10px 12px; font-size: 14px; }
.note.crit { color: var(--crit); text-align: left; background: var(--crit-soft);
             border-radius: 8px; padding: 10px 12px; }
.empty { text-align: center; padding: 32px 16px; color: var(--muted); display: flex;
         flex-direction: column; gap: 6px; align-items: center; }
.empty b { color: var(--ink); }
.empty p { margin: 0; }
.tnum { font-variant-numeric: tabular-nums; }
</style>
