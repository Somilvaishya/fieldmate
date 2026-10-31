<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, ApiError } from '../api/client'
import { isSignedOut } from '../lib/session'
import Icon from '../components/Icon.vue'
import { t } from '../lib/i18n'

// A beat from the phone: who walks it, on which day, how often, and the shops in walking order.
//
// Every rule about the shops - inside the territory, not on another active beat - is the Beat
// controller's, and its refusal is shown as it comes. This screen only stops a manager offering a
// shop that is already taken, by listing only free ones.
const route = useRoute()
const router = useRouter()
const isNew = route.params.name === 'new'

const DAYS = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
const FREQUENCIES = computed(() => [
  { key: 'Weekly', label: t('Every week') },
  { key: 'Fortnightly', label: t('Every other week') },
  { key: 'Monthly', label: t('Once a month') },
])
const PATTERNS = computed(() => [
  { key: 'All', label: t('Default') },
  { key: 'W1', label: t('Week 1') },
  { key: 'W2', label: t('Week 2') },
  { key: 'W3', label: t('Week 3') },
  { key: 'W4', label: t('Week 4') },
])

const form = ref({
  name: null, beat_name: '', assigned_to: '', territory: '', distributor: '',
  effective_from: '', notes: '',
  visit_day: 'Monday', frequency: 'Weekly', week_pattern: 'All', is_active: 1,
})

// What a beat for the chosen rep may be set to. The territories are where the manager's
// permission and the rep's own patch overlap - the Beat refuses a route the rep cannot see. The
// distributors are the ones this rep already supplies shops through.
const options = ref({ territories: [], distributors: [], default_territory: null })

async function loadOptions(rep, keepTerritory) {
  if (!rep) {
    options.value = { territories: [], distributors: [], default_territory: null }
    return
  }
  try {
    options.value = await api.planBeatOptions(rep)
    if (!keepTerritory || !options.value.territories.includes(form.value.territory)) {
      form.value.territory = options.value.default_territory || ''
    }
    if (form.value.distributor
        && !options.value.distributors.some((d) => d.name === form.value.distributor)) {
      form.value.distributor = ''
    }
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : t('Could not load the beat. This needs signal.')
  }
}
const shops = ref([])
const reps = ref([])
const loading = ref(true)
const saving = ref(false)
const error = ref('')

// The picker. Shops a new beat can take - in the rep's territory, on no active beat.
const picking = ref(false)
const query = ref('')
const free = ref([])
const searching = ref(false)

onMounted(async () => {
  try {
    const [overview, beat] = await Promise.all([
      api.planOverview(),
      isNew ? Promise.resolve(null) : api.planBeat(route.params.name),
    ])
    reps.value = overview.members || []
    if (beat) {
      form.value = { ...form.value, ...beat, distributor: beat.distributor || '',
                     effective_from: beat.effective_from || '', notes: beat.notes || '' }
      shops.value = beat.outlets.map((o) => ({ name: o.outlet, outlet_name: o.outlet_name }))
    } else if (route.query.rep) {
      form.value.assigned_to = route.query.rep
    }
    await loadOptions(form.value.assigned_to, !!beat)
    // A different rep means a different patch and different depots - and the shops already
    // picked may be outside it, which the server will say on save.
    watch(() => form.value.assigned_to, (rep) => loadOptions(rep, false))
  } catch (e) {
    if (isSignedOut(e)) return router.replace('/login')
    error.value = e instanceof ApiError ? e.message : t('Could not load the beat. This needs signal.')
  } finally {
    loading.value = false
  }
})

const territory = computed(() => form.value.territory)

async function search() {
  if (!territory.value) {
    error.value = t('Pick the rep first - the shops come from their territory.')
    return
  }
  searching.value = true
  error.value = ''
  try {
    const taken = new Set(shops.value.map((s) => s.name))
    const rows = (await api.planFreeOutlets(territory.value, query.value || undefined)).outlets || []
    free.value = rows.filter((r) => !taken.has(r.name))
  } catch (e) {
    error.value = e instanceof ApiError ? e.message : t('Could not load the shops. This needs signal.')
  } finally {
    searching.value = false
  }
}

function openPicker() {
  picking.value = true
  search()
}

function add(shop) {
  shops.value = [...shops.value, { name: shop.name, outlet_name: shop.outlet_name }]
  free.value = free.value.filter((s) => s.name !== shop.name)
}

function move(index, by) {
  const next = index + by
  if (next < 0 || next >= shops.value.length) return
  const list = [...shops.value]
  ;[list[index], list[next]] = [list[next], list[index]]
  shops.value = list
}

function remove(index) {
  shops.value = shops.value.filter((_, i) => i !== index)
}

async function save() {
  saving.value = true
  error.value = ''
  try {
    if (!form.value.beat_name.trim() || !form.value.assigned_to || !form.value.territory) {
      error.value = t('A beat needs a name, a rep and a territory.')
      return
    }
    const saved = await api.planSaveBeat({
      ...form.value,
      distributor: form.value.distributor || null,
      effective_from: form.value.effective_from || null,
      week_pattern: form.value.frequency === 'Weekly' ? 'All' : form.value.week_pattern,
      outlets: shops.value.map((s) => s.name),
    })
    router.replace({ name: 'plan', query: { view: 'beats' } })
    return saved
  } catch (e) {
    error.value = e instanceof ApiError && e.code === 'OFFLINE'
      ? t('No signal. Nothing was saved - try again when you have one.')
      : (e?.message || t('That did not go through.'))
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="wrap">
    <header class="head">
      <RouterLink :to="{ name: 'plan', query: { view: 'beats' } }" class="back" :aria-label="t('Back')">
        <Icon name="back" size="20" />
      </RouterLink>
      <h1>{{ isNew ? t('New beat') : form.beat_name }}</h1>
    </header>

    <p v-if="loading" class="note">{{ t('Loading…') }}</p>

    <template v-else>
      <label class="field">
        <span>{{ t('Beat name') }}</span>
        <input v-model="form.beat_name" :placeholder="t('e.g. Rohini Monday')" />
      </label>

      <label class="field">
        <span>{{ t('Rep') }}</span>
        <select v-model="form.assigned_to">
          <option value="" disabled>{{ t('Pick a rep') }}</option>
          <option v-for="r in reps" :key="r.field_user" :value="r.field_user">
            {{ r.full_name }} · {{ r.field_user }}
          </option>
        </select>
      </label>

      <label class="field">
        <span>{{ t('Territory') }}</span>
        <select v-model="form.territory" :disabled="!options.territories.length">
          <option value="" disabled>{{ form.assigned_to ? t('Pick a territory') : t('Pick the rep first') }}</option>
          <option v-for="name in options.territories" :key="name" :value="name">{{ name }}</option>
        </select>
      </label>

      <label class="field">
        <span>{{ t('Distributor') }} <em class="opt">{{ t('optional') }}</em></span>
        <select v-model="form.distributor" :disabled="!options.distributors.length">
          <option value="">{{ options.distributors.length ? t('None') : t('No distributor for this rep') }}</option>
          <option v-for="d in options.distributors" :key="d.name" :value="d.name">{{ d.customer_name }}</option>
        </select>
      </label>

      <div class="field">
        <span>{{ t('Day') }}</span>
        <div class="chips">
          <button v-for="d in DAYS" :key="d" type="button" class="chip"
                  :class="{ on: form.visit_day === d }" @click="form.visit_day = d">
            {{ t(d).slice(0, 3) }}
          </button>
        </div>
      </div>

      <div class="field">
        <span>{{ t('How often') }}</span>
        <div class="chips">
          <button v-for="f in FREQUENCIES" :key="f.key" type="button" class="chip"
                  :class="{ on: form.frequency === f.key }" @click="form.frequency = f.key">
            {{ f.label }}
          </button>
        </div>
      </div>

      <div v-if="form.frequency !== 'Weekly'" class="field">
        <span>{{ t('Which week') }}</span>
        <div class="chips">
          <button v-for="p in PATTERNS" :key="p.key" type="button" class="chip"
                  :class="{ on: form.week_pattern === p.key }" @click="form.week_pattern = p.key">
            {{ p.label }}
          </button>
        </div>
      </div>

      <label class="field">
        <span>{{ t('Starts from') }} <em class="opt">{{ t('optional') }}</em></span>
        <input type="date" v-model="form.effective_from" />
      </label>

      <label class="field">
        <span>{{ t('Notes') }} <em class="opt">{{ t('optional') }}</em></span>
        <textarea v-model="form.notes" rows="2" :placeholder="t('Where to start, what to watch for')"></textarea>
      </label>

      <!-- A beat's day moved does not move a plan already built from it - the plan is a copy of
           dates, not a live rule. Desk says so at the same moment. -->
      <p v-if="!isNew" class="note warn">
        {{ t('Plans already built from this beat keep their old dates. After changing the day, build those months again.') }}
      </p>

      <label v-if="!isNew" class="toggle">
        <input type="checkbox" :checked="!!form.is_active"
               @change="form.is_active = $event.target.checked ? 1 : 0" />
        <span>{{ t('Beat is in use') }}</span>
      </label>

      <section class="shops">
        <h2>{{ shops.length === 1 ? t('1 shop, in walking order') : t('{n} shops, in walking order', { n: shops.length }) }}</h2>
        <ol v-if="shops.length">
          <li v-for="(s, i) in shops" :key="s.name">
            <span class="seq tnum">{{ i + 1 }}</span>
            <span class="sname">{{ s.outlet_name || s.name }}</span>
            <button type="button" class="mini" :disabled="i === 0" @click="move(i, -1)"
                    :aria-label="t('Move up')"><Icon name="chevron-up" size="18" /></button>
            <button type="button" class="mini" @click="remove(i)"
                    :aria-label="t('Remove')"><Icon name="close" size="18" /></button>
          </li>
        </ol>

        <button v-if="!picking" type="button" class="add" @click="openPicker">
          <Icon name="plus" size="18" /><span>{{ t('Add shops') }}</span>
        </button>
        <div v-else class="picker">
          <div class="search">
            <input v-model="query" :placeholder="t('Search shops')" @keyup.enter="search" />
            <button type="button" class="mini" @click="search" :aria-label="t('Search')">
              <Icon name="search" size="18" />
            </button>
          </div>
          <p v-if="searching" class="note">{{ t('Loading…') }}</p>
          <p v-else-if="!free.length" class="dim">{{ t('No free shops here. A shop can be on one active beat at a time.') }}</p>
          <button v-for="f in free" :key="f.name" type="button" class="free" @click="add(f)">
            <Icon name="plus" size="16" />
            <span class="sname">{{ f.outlet_name }}</span>
            <span v-if="f.approval_status !== 'Approved'" class="dim">{{ t('Pending') }}</span>
          </button>
        </div>
      </section>

      <p v-if="error" class="note crit">{{ error }}</p>

      <button class="btn" :disabled="saving" @click="save">
        {{ saving ? t('Saving…') : t('Save beat') }}
      </button>
    </template>
  </div>
</template>

<style scoped>
.wrap { max-width: 560px; margin: 0 auto; padding: 16px 16px 32px; display: flex;
        flex-direction: column; gap: 14px; }
.head { display: flex; align-items: center; gap: 8px; }
.head h1 { font-size: 20px; margin: 0; overflow-wrap: anywhere; }
.back { display: inline-flex; align-items: center; justify-content: center; min-width: 44px;
        min-height: 44px; color: var(--ink); }
.dim { color: var(--muted); font-size: 13px; margin: 0; }

.field { display: flex; flex-direction: column; gap: 6px; }
.field > span { font-size: 13px; font-weight: 700; color: var(--muted); }
.field textarea { font: inherit; padding: 10px; border: 1px solid var(--line); border-radius: 8px;
                  min-height: 64px; resize: vertical; }
.opt { font-style: normal; font-weight: 500; }
.note.warn { color: var(--warn); background: var(--warn-soft); border-radius: 8px;
             padding: 10px 12px; text-align: left; font-size: 13px; }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip { min-height: 44px; padding: 0 14px; border: 1px solid var(--line); border-radius: 999px;
        background: var(--surface); color: var(--ink); font-weight: 600; font-size: 14px; }
.chip.on { background: var(--primary); color: var(--on-primary); border-color: var(--primary); }
.toggle { display: flex; align-items: center; gap: 10px; min-height: 44px; font-weight: 600; }
.toggle input { width: 22px; min-height: 22px; height: 22px; }

.shops { display: flex; flex-direction: column; gap: 8px; }
.shops h2 { font-size: 14px; margin: 0; color: var(--muted); }
.shops ol { list-style: none; margin: 0; padding: 0; background: var(--surface);
            border: 1px solid var(--line); border-radius: 10px; }
.shops li { display: grid; grid-template-columns: 24px minmax(0, 1fr) 44px 44px; gap: 6px;
            align-items: center; padding: 4px 6px 4px 12px; }
.shops li + li { border-top: 1px solid var(--line); }
.seq { font-weight: 700; color: var(--muted); }
.sname { overflow-wrap: anywhere; }
.mini { width: 44px; min-height: 44px; border: 0; background: none; color: var(--ink);
        display: inline-flex; align-items: center; justify-content: center; }
.mini:disabled { color: var(--line); }
.add { display: inline-flex; align-items: center; justify-content: center; gap: 6px;
       min-height: 48px; border-radius: 8px; border: 1px dashed var(--primary);
       background: var(--surface); color: var(--primary); font-weight: 700; }
.picker { display: flex; flex-direction: column; gap: 6px; }
.search { display: grid; grid-template-columns: minmax(0, 1fr) 44px; gap: 6px; }
.free { display: flex; align-items: center; gap: 8px; min-height: 48px; padding: 0 12px;
        border: 1px solid var(--line); border-radius: 8px; background: var(--surface);
        color: var(--ink); text-align: left; }
.free .sname { flex: 1; }

.btn { min-height: 52px; border: 0; border-radius: 8px; background: var(--primary);
       color: var(--on-primary); font-weight: 700; font-size: 16px; }
.btn:disabled { opacity: .6; }
.note { color: var(--muted); font-size: 14px; text-align: center; padding: 12px 0; margin: 0; }
.note.crit { color: var(--crit); text-align: left; background: var(--crit-soft);
             border-radius: 8px; padding: 10px 12px; }
.tnum { font-variant-numeric: tabular-nums; }
</style>
