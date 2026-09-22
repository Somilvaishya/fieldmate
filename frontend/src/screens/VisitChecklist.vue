<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import * as visitStore from '../stores/visit'

const router = useRouter()
const visit = visitStore.activeVisit
const saving = ref(false)

// Only questions whose trigger has been met. A rep should never see "Why is it out of stock?"
// above the question asking whether it is in stock.
const questions = computed(() => visitStore.visibleQuestions(visit.value))
const remaining = computed(() => visitStore.unansweredRequired(visit.value))

onMounted(async () => {
  if (!visit.value) await visitStore.resume()
  if (!visit.value) router.replace('/today')
})

function setText(q, value) {
  visitStore.answer(q.question_code, { answer: value === '' ? null : value })
}

function setNumber(q, value) {
  // An empty box is not an answer; a typed 0 is.
  visitStore.answer(q.question_code, {
    answer: null,
    answerNumber: value === '' || value === null ? null : Number(value),
  })
}

function setChoice(q, option) {
  setText(q, option)
  save()
}

function toggleMulti(q, option) {
  const chosen = new Set((q.answer || '').split('\n').filter(Boolean))
  chosen.has(option) ? chosen.delete(option) : chosen.add(option)
  setText(q, [...chosen].join('\n'))
  save()
}

function isChosen(q, option) {
  return (q.answer || '').split('\n').includes(option)
}

function outOfRange(q) {
  if (!q.is_answered || q.answer_type !== 'Number') return false
  if (q.min_value !== null && q.min_value !== undefined && q.answer_number < q.min_value) return true
  if (q.max_value !== null && q.max_value !== undefined && q.answer_number > q.max_value) return true
  return false
}

async function save() {
  saving.value = true
  try {
    await visitStore.saveProgress()
  } finally {
    saving.value = false
  }
}

async function done() {
  await save()
  router.back()
}
</script>

<template>
  <div class="wrap screen" v-if="visit">
    <h2>Checklist</h2>
    <p class="muted">{{ visit.outletName }}</p>

    <p v-if="!questions.length" class="empty">
      No questions are set for this shop today.
    </p>

    <ol class="qs">
      <li v-for="q in questions" :key="q.question_code" class="q">
        <p class="prompt">
          {{ q.question }}
          <span v-if="q.is_required" class="req" aria-label="required">*</span>
        </p>
        <p v-if="q.help_text" class="muted help">{{ q.help_text }}</p>

        <div v-if="q.answer_type === 'Yes/No'" class="chips">
          <button v-for="opt in ['Yes', 'No']" :key="opt" type="button"
                  class="chip" :class="{ on: q.answer === opt }" @click="setChoice(q, opt)">
            {{ opt }}
          </button>
        </div>

        <div v-else-if="q.answer_type === 'Rating'" class="chips">
          <button v-for="n in 5" :key="n" type="button"
                  class="chip" :class="{ on: q.answer_number === n && q.is_answered }"
                  @click="setNumber(q, n); save()">
            {{ n }}
          </button>
        </div>

        <div v-else-if="q.answer_type === 'Single Choice'" class="chips">
          <button v-for="opt in q.options" :key="opt" type="button"
                  class="chip" :class="{ on: q.answer === opt }" @click="setChoice(q, opt)">
            {{ opt }}
          </button>
        </div>

        <div v-else-if="q.answer_type === 'Multi Choice'" class="chips">
          <button v-for="opt in q.options" :key="opt" type="button"
                  class="chip" :class="{ on: isChosen(q, opt) }" @click="toggleMulti(q, opt)">
            {{ opt }}
          </button>
        </div>

        <input v-else-if="q.answer_type === 'Number'" type="number" inputmode="decimal"
               :value="q.is_answered ? q.answer_number : ''"
               @input="setNumber(q, $event.target.value)" @blur="save" />

        <textarea v-else rows="2" :value="q.answer || ''"
                  @input="setText(q, $event.target.value)" @blur="save" />

        <p v-if="outOfRange(q)" class="warn">
          Expected between {{ q.min_value }} and {{ q.max_value }}. Saved anyway — check it is right.
        </p>
      </li>
    </ol>

    <div class="bottom">
      <p v-if="remaining.length" class="muted note">
        {{ remaining.length }} required {{ remaining.length === 1 ? 'question' : 'questions' }} left.
      </p>
      <button class="btn-primary" @click="done">
        {{ saving ? 'Saving…' : 'Back to visit' }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.screen { display: flex; flex-direction: column; min-height: 100%; }
h2 { margin: 8px 0 4px; }
.muted { color: var(--muted); font-size: 14px; }
.empty { margin-top: 24px; padding: 16px; background: var(--surface);
         border: 1px solid var(--line); border-radius: 8px; color: var(--muted); }
.qs { list-style: none; padding: 0; margin: 16px 0 0; display: grid; gap: 14px; }
.q { padding: 14px; background: var(--surface); border: 1px solid var(--line);
     border-radius: 8px; }
.prompt { margin: 0 0 8px; font-weight: 600; }
.req { color: var(--crit); }
.help { margin: -4px 0 8px; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; }
.chip { background: var(--bg); border: 1px solid var(--line); color: var(--ink);
        padding: 0 16px; min-width: 56px; }
.chip.on { background: var(--primary); border-color: var(--primary); color: var(--on-primary);
           font-weight: 600; }
textarea { width: 100%; font: inherit; padding: 10px 12px; border: 1px solid var(--line);
           border-radius: 6px; background: var(--bg); color: var(--ink); }
.warn { color: var(--warn); font-size: 14px; margin: 8px 0 0; }
.bottom { margin-top: auto; padding-top: 16px; }
.note { text-align: center; margin-bottom: 8px; }
</style>
