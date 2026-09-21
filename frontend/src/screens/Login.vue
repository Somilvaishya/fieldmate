<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api, ApiError } from '../api/client'
import { deviceUuid, setMeta } from '../db'

const router = useRouter()
const usr = ref('')
const pwd = ref('')
const error = ref('')
const busy = ref(false)

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
    // Errors say what happened in plain words - a rep reads this in a market
    // with no support line available.
    error.value = e instanceof ApiError ? e.message : 'Could not reach the server.'
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="wrap login">
    <h1>FieldMate</h1>
    <p class="sub">Sign in to start your day.</p>
    <form @submit.prevent="submit">
      <label for="usr">User</label>
      <input id="usr" v-model="usr" autocomplete="username" inputmode="email" />
      <label for="pwd">Password</label>
      <input id="pwd" v-model="pwd" type="password" autocomplete="current-password" />
      <p v-if="error" class="err">{{ error }}</p>
      <button class="btn-primary" :disabled="busy">{{ busy ? 'Signing in…' : 'Sign in' }}</button>
    </form>
  </div>
</template>

<style scoped>
.login { display: flex; flex-direction: column; justify-content: flex-end; min-height: 100%; }
h1 { margin: 0 0 4px; font-size: 28px; color: var(--primary); }
.sub { margin: 0 0 24px; color: var(--muted); }
label { display: block; margin: 16px 0 6px; font-weight: 600; }
.err { color: var(--crit); margin: 12px 0 0; }
form > button { margin-top: 24px; }
</style>
