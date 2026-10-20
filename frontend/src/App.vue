<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import AppOverlay from './components/AppOverlay.vue'
import AppWallpaper from './components/AppWallpaper.vue'
import AvatarMenu from './components/AvatarMenu.vue'
import CardCollectionOverlay from './components/CardCollectionOverlay.vue'
import ScreenBoundary from './components/ScreenBoundary.vue'
import ToastHost from './components/ToastHost.vue'
import { routeLoading } from './router'
import { useCollectionStore } from './stores/collection'
import { useUiStore } from './stores/ui'

/**
 * Application shell (ticket #42).
 *
 * Four destinations (开战 / 大厅 / 图鉴 / 排行) plus the friends icon and the
 * avatar menu close the eleven frozen routes down to one obvious place per
 * intent. Flow screens (placement / rps / game / game-over) switch to the
 * immersive toolbar: the destinations disappear, exit and settings stay, and
 * exit asks for confirmation first. Overlays, the notice queue and the three
 * themes live at this level so every screen inherits them.
 */
const route = useRoute()
const router = useRouter()
const collection = useCollectionStore()
const ui = useUiStore()

/** Flow screens are reached from a match, not from the bar. */
const FLOW_ROUTE_NAMES = new Set(['placement', 'rps', 'game', 'game-over'])
const screenFailed = ref(false)
// A failed flow screen falls back to the normal bar: with the destinations
// hidden the player would have no way to leave the error screen.
const immersive = computed(() => FLOW_ROUTE_NAMES.has(String(route.name)) && !screenFailed.value)

const destinations = [
  { name: 'start', label: '开战' },
  { name: 'lobby', label: '大厅' },
  { name: 'leaderboard', label: '排行' },
]

const loading = computed(() => routeLoading.value)

const menuOpen = ref(false)
const avatarButton = ref<HTMLButtonElement | null>(null)
const collectionButton = ref<HTMLButtonElement | null>(null)

function toggleMenu(): void {
  menuOpen.value = !menuOpen.value
}

function closeMenu(): void {
  const wasOpen = menuOpen.value
  menuOpen.value = false
  // Keyboard users land back on the trigger, never on a detached node.
  if (wasOpen) avatarButton.value?.focus()
}

function openCollection(): void {
  menuOpen.value = false
  collection.open()
}

function exitMatch(): void {
  ui.cancelExit()
  void router.push({ name: 'lobby' })
}
</script>

<template>
  <!-- Applied wallpaper layer (spec story 2); renders nothing until applied. -->
  <AppWallpaper />

  <!-- Single-overlay root: the card archive opens above the shell. -->
  <CardCollectionOverlay
    v-if="collection.isOpen"
    :return-focus="() => collectionButton"
    @close="collection.close()"
  />

  <div class="app-shell" data-testid="app-shell" :data-route-loading="loading ? 'true' : 'false'" :data-immersive="immersive ? 'true' : 'false'">
    <nav class="app-nav" :class="{ 'app-nav--flow': immersive }" data-testid="app-nav" aria-label="主屏导航">
      <component
        :is="immersive ? 'div' : 'router-link'"
        class="app-brand"
        :to="immersive ? undefined : '/'"
        :aria-label="immersive ? undefined : '回到首页'"
      >
        <span class="app-brand__mark" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
            <path d="M12 3v18M5 8l7-4 7 4M4 14h16l-3 6H7z" />
          </svg>
        </span>
        <span class="app-brand__text">
          <b class="app-brand__title">战舰棋 · 作战室</b>
          <small class="app-brand__sub">深海作战室</small>
        </span>
      </component>

      <div v-if="immersive" class="app-nav__links app-nav__links--flow">
        <button type="button" class="app-nav__flow" data-testid="nav-exit" @click="ui.requestExit()">
          退出对局
        </button>
        <router-link class="app-nav__flow" :to="{ name: 'settings' }" data-testid="nav-settings">设置</router-link>
      </div>

      <template v-else>
        <div class="app-nav__links">
          <router-link
            v-for="item in destinations.filter((entry) => entry.name !== 'leaderboard')"
            :key="item.name"
            :to="{ name: item.name }"
            class="app-nav__link"
            :data-testid="'nav-' + item.name"
          >
            {{ item.label }}
          </router-link>
          <button
            ref="collectionButton"
            type="button"
            class="app-nav__link"
            :class="{ 'is-active': collection.isOpen }"
            :aria-pressed="collection.isOpen"
            data-testid="nav-collection"
            @click="openCollection"
          >
            图鉴
          </button>
          <router-link
            v-for="item in destinations.filter((entry) => entry.name === 'leaderboard')"
            :key="item.name"
            :to="{ name: item.name }"
            class="app-nav__link"
            :data-testid="'nav-' + item.name"
          >
            {{ item.label }}
          </router-link>
        </div>

        <div class="app-nav__meta">
          <button type="button" class="app-nav__icon" data-testid="nav-friends" aria-label="好友">
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
              <circle cx="9" cy="8" r="3.2" />
              <path d="M3.5 20c.6-3.4 2.9-5 5.5-5s4.9 1.6 5.5 5" />
              <path d="M16 5.5a3 3 0 0 1 0 5.6M17.5 15.4c1.8.6 2.9 2.1 3.2 4.6" />
            </svg>
          </button>

          <div class="app-avatar">
            <button
              ref="avatarButton"
              type="button"
              class="app-nav__icon app-avatar__trigger"
              :aria-expanded="menuOpen"
              aria-haspopup="menu"
              data-testid="nav-avatar"
              @click="toggleMenu"
            >
              <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true">
                <circle cx="12" cy="9" r="3.6" />
                <path d="M4.5 20c.9-3.9 3.9-5.6 7.5-5.6s6.6 1.7 7.5 5.6" />
              </svg>
            </button>
            <AvatarMenu v-if="menuOpen" @close="closeMenu" />
          </div>
        </div>
      </template>
    </nav>

    <!-- A thin progress line instead of an in-flow notice: switching screens
         no longer pushes the content down and back. -->
    <div v-if="loading" class="route-loading" data-testid="route-loading" role="status" aria-live="polite">
      <span class="route-loading__bar" aria-hidden="true"></span>
      <span class="sr-only">正在切换界面…</span>
    </div>

    <ScreenBoundary @error="screenFailed = true" @recovered="screenFailed = false">
      <router-view v-slot="{ Component, route: viewRoute }">
        <component :is="Component" v-if="Component" :key="viewRoute.path" />
      </router-view>
      <slot name="screen-extra" />
    </ScreenBoundary>
  </div>

  <AppOverlay
    v-if="ui.exitConfirmOpen"
    id="exit-confirm"
    :priority="250"
    labelledby="exit-confirm-title"
    @close="ui.cancelExit()"
  >
    <div class="confirm">
      <h2 id="exit-confirm-title" class="confirm__title">退出这一局？</h2>
      <p class="confirm__text">退出会中断当前对局，已经打出的进度不会保留。</p>
      <div class="confirm__actions">
        <button type="button" class="button" data-testid="exit-confirm-cancel" @click="ui.cancelExit()">继续对局</button>
        <button type="button" class="button button--danger" data-testid="exit-confirm-ok" @click="exitMatch">确认退出</button>
      </div>
    </div>
  </AppOverlay>

  <ToastHost />
</template>
