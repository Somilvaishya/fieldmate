<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError } from '../api/client'
import { deviceUuid, setMeta } from '../db'
import Icon from '../components/Icon.vue'

const router = useRouter()
const usr = ref('')
const pwd = ref('')
const reveal = ref(false)
const error = ref('')
const busy = ref(false)

const logo = import.meta.env.BASE_URL + 'icon-192.png'

async function submit() {
  error.value = ''
  busy.value = true
  try {
    const device = await deviceUuid()
    const data = await api.login(usr.value, pwd.value, device, {
      platform: 'Web',
      app_version: '0.0.1',
      device_name: navigator.userAgent.slice(0, 60),
    })
    await setMeta('profile', data)
    router.push('/today')
  } catch (e) {
    // Errors say what happened in plain words - a rep reads this in a market with no
    // support line available. Signing in is the one action that genuinely needs the
    // network, so the generic "your work is saved on this phone" would be nonsense here.
    error.value = e instanceof ApiError && e.code === 'OFFLINE'
      ? 'You need a signal to sign in the first time. Once you have, the app works offline.'
      : e instanceof ApiError
        ? e.message
        : 'Could not reach the server.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="wrap screen">
    <div class="top">
      <div class="brand">
        <img class="mark" :src="logo" alt="" width="64" height="64" />
        <h1>FieldMate</h1>
        <p class="tagline">Field force automation</p>
      </div>

      <form id="signin" class="card" @submit.prevent="submit">
        <div class="field">
          <label for="usr"><Icon name="person" /> Mobile number or email</label>
          <input
            id="usr"
            v-model="usr"
            autocomplete="username"
            autocapitalize="none"
            spellcheck="false"
            placeholder="9876543210"
          />
        </div>

        <div class="field">
          <label for="pwd"><Icon name="lock" /> Password</label>
          <div class="with-action">
            <input
              id="pwd"
              v-model="pwd"
              :type="reveal ? 'text' : 'password'"
              autocomplete="current-password"
            />
            <!-- Typing a password blind, one-handed, in sunlight is how reps get locked out.
                 The toggle is a 48px target like everything else. -->
            <button
              type="button"
              class="reveal"
              :aria-label="reveal ? 'Hide password' : 'Show password'"
              :aria-pressed="reveal"
              @click="reveal = !reveal"
            >
              <Icon :name="reveal ? 'eye-off' : 'eye'" />
            </button>
          </div>
        </div>

        <p v-if="error" class="err" role="alert">
          <Icon name="alert" />
          <span>{{ error }}</span>
        </p>
      </form>
    </div>

    <div class="bottom">
      <button form="signin" class="btn-primary" :disabled="busy">
        {{ busy ? 'Signing in…' : 'Sign in' }}
      </button>
      <p class="assurance">
        <Icon name="cloud-off" />
        <span>Works offline once you have signed in</span>
      </p>
    </div>
  </div>
</template>

<style scoped>
.screen { display: flex; flex-direction: column; min-height: 100%; }
.top { flex: 1; display: flex; flex-direction: column; justify-content: center; }

.brand { text-align: center; margin-bottom: 28px; }
.mark { width: 64px; height: 64px; border-radius: 14px; }
h1 { margin: 12px 0 2px; font-size: 24px; letter-spacing: -0.01em; color: var(--ink); }
.tagline { margin: 0; font-size: 14px; color: var(--muted); }

.card { background: var(--surface); border: 1px solid var(--line); border-radius: 6px;
        padding: 16px; display: grid; gap: 16px; }
.field { display: grid; gap: 6px; }
label { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 16px; }
label :deep(.icon) { color: var(--primary); }

.with-action { position: relative; display: flex; align-items: center; }
.with-action input { padding-right: 52px; }
.reveal { position: absolute; right: 0; width: 48px; height: 48px; min-height: 48px;
          display: grid; place-items: center; background: none; border: 0;
          color: var(--muted); }

.err { display: flex; align-items: flex-start; gap: 8px; margin: 0;
       background: var(--crit-soft); color: var(--crit);
       border-radius: 6px; padding: 10px 12px; font-size: 14px; line-height: 1.45; }
.err :deep(.icon) { margin-top: 1px; }

.bottom { padding-top: 24px; }
.assurance { display: flex; align-items: center; justify-content: center; gap: 8px;
             margin: 12px 0 0; color: var(--muted); font-size: 14px; }
</style>
