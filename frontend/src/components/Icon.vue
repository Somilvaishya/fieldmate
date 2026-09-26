<script setup>
import { computed } from 'vue'

// Inline SVG, never an icon font.
//
// The design export reached for Material Symbols, which is a Google Fonts download of a few
// hundred KB before the first icon renders. DESIGN.md rules out web fonts because a rep is on
// a metered connection in a market, and an icon font also fails *invisibly*: the glyph is a
// ligature, so a blocked request leaves the literal word "visibility_off" sitting in the UI.
//
// These are stroke drawings on a 24px grid, sized in ems so an icon scales with the text it
// is paired with. Per DESIGN.md every icon in this app appears beside a label, never alone.

const ICONS = {
  person: '<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
  lock: '<rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>',
  eye: '<path d="M2 12s3.6-6 10-6 10 6 10 6-3.6 6-10 6-10-6-10-6Z"/><circle cx="12" cy="12" r="3"/>',
  'eye-off': '<path d="M10.6 6.2A9.9 9.9 0 0 1 12 6c6.4 0 10 6 10 6a18 18 0 0 1-3.3 3.9M6.2 7.9A18 18 0 0 0 2 12s3.6 6 10 6a9.8 9.8 0 0 0 3.5-.6"/><path d="m3 3 18 18"/>',
  alert: '<circle cx="12" cy="12" r="9"/><path d="M12 7v6"/><path d="M12 16.5v.01"/>',
  check: '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
  'cloud-off': '<path d="M7.5 18a4.5 4.5 0 0 1-.9-8.9"/><path d="M9 6.3A6 6 0 0 1 18.5 11a4.5 4.5 0 0 1 1.6 7.3"/><path d="M7.5 18h9"/><path d="m3 3 18 18"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  'chevron-up': '<path d="m6 15 6-6 6 6"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  calendar: '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18"/><path d="M8 3v4"/><path d="M16 3v4"/>',
  // A van, not a lorry: the vehicle a route rep actually drives.
  truck: '<path d="M2 7h11v9H2z"/><path d="M13 10h4l3 3v3h-7z"/><circle cx="6" cy="18" r="2"/><circle cx="17" cy="18" r="2"/>',
  copy: '<rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/>',
  edit: '<path d="M4 20h4l10-10-4-4L4 16z"/><path d="m14 6 4 4"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v5"/><path d="M12 8v.01"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/>',
  pin: '<path d="M12 21s7-6.1 7-11a7 7 0 1 0-14 0c0 4.9 7 11 7 11Z"/><circle cx="12" cy="10" r="2.5"/>',
  camera: '<path d="M4 8h3l1.5-2h7L17 8h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1Z"/><circle cx="12" cy="13" r="3.5"/>',
  phone: '<path d="M6 3h3l2 5-2.5 1.5a12 12 0 0 0 5 5L15 12l5 2v3a2 2 0 0 1-2.2 2A16.5 16.5 0 0 1 4 5.2 2 2 0 0 1 6 3Z"/>',
  directions: '<path d="M3 11 21 3l-8 18-2-7-8-3Z"/>',
  refresh: '<path d="M20 12a8 8 0 1 1-2.5-5.8"/><path d="M20 4v4h-4"/>',
  store: '<path d="M4 9h16v10a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V9Z"/><path d="m4 9 1.5-5h13L20 9"/><path d="M9.5 20v-6h5v6"/>',
  close: '<path d="m6 6 12 12"/><path d="m18 6-12 12"/>',
  plus: '<path d="M12 5v14"/><path d="M5 12h14"/>',
  chat: '<path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.4A8 8 0 1 1 21 12Z"/>',
  back: '<path d="M15 6l-6 6 6 6"/>',
  minus: '<path d="M5 12h14"/>',
  timer: '<circle cx="12" cy="13" r="8"/><path d="M12 13V9"/><path d="M9 2h6"/>',
  list: '<path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><path d="M3.5 6h.01"/><path d="M3.5 12h.01"/><path d="M3.5 18h.01"/>',
  shelves: '<rect x="3" y="4" width="18" height="16" rx="1"/><path d="M3 10h18"/><path d="M3 15h18"/>',
  photo: '<rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="8.5" cy="10" r="1.5"/><path d="m21 16-5-5-9 8"/>',
  // Phase 4. A scheme badge and a free-goods line both need a mark beside their words, and the
  // alternative was reusing `check`, which already means "done" everywhere else in the app.
  tag: '<path d="M3 12.5V4a1 1 0 0 1 1-1h8.5L21 11.5 12.5 20 3 12.5Z"/><circle cx="7.5" cy="7.5" r="1.5"/>',
  gift: '<rect x="3" y="9" width="18" height="11" rx="1"/><path d="M3 13h18"/><path d="M12 9v11"/><path d="M12 9S9.5 9 8 8a2.2 2.2 0 1 1 2.2-3.4C11.4 6 12 9 12 9Z"/><path d="M12 9s2.5 0 4-1a2.2 2.2 0 1 0-2.2-3.4C12.6 6 12 9 12 9Z"/>',
  cart: '<circle cx="9.5" cy="19.5" r="1.5"/><circle cx="17.5" cy="19.5" r="1.5"/><path d="M2 3h3l2.6 11.3a1 1 0 0 0 1 .7h8.4a1 1 0 0 0 1-.8L21 7H6"/>',
  // Phase 7. Three marks the performance and expense screens need and nothing else carries:
  // a target to aim at, a line going the right way, and a bill.
  target: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="4"/><circle cx="12" cy="12" r="1"/>',
  trend: '<path d="m3 17 5.5-5.5 3.5 3.5L21 6"/><path d="M15 6h6v6"/>',
  receipt: '<path d="M5 3v18l2.5-1.5L10 21l2.5-1.5L15 21l2.5-1.5L20 21V3z"/><path d="M8.5 8h7"/><path d="M8.5 12h7"/>',
  // A route travelled, for the distance the trail recorded.
  route: '<circle cx="6" cy="18" r="2.5"/><circle cx="18" cy="6" r="2.5"/><path d="M8.5 18H15a3 3 0 0 0 0-6H9a3 3 0 0 1 0-6h6.5"/>',
}

const props = defineProps({
  name: { type: String, required: true },
  size: { type: [String, Number], default: '1.25em' },
})

// `size="18"` in a template is a STRING, so a `typeof size === 'number'` test is false and
// the style became `width: "18"` - a declaration with no unit, which every browser drops.
// The icons then had no width or height at all. Bare numbers get px; anything already
// carrying a unit (1.25em) is passed through.
const dimension = computed(() => {
  const value = String(props.size).trim()
  return /^\d+(\.\d+)?$/.test(value) ? `${value}px` : value
})
</script>

<template>
  <svg
    class="icon"
    :style="{ width: dimension, height: dimension }"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    focusable="false"
    v-html="ICONS[name] || ''"
  />
</template>

<style scoped>
.icon { flex: none; display: block; }
</style>
