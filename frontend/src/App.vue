<script setup lang="ts">
import { computed } from 'vue'
import AppWallpaper from './components/AppWallpaper.vue'
import CardCollectionOverlay from './components/CardCollectionOverlay.vue'
import ScreenBoundary from './components/ScreenBoundary.vue'
import { routeLoading } from './router'
import { useCollectionStore } from './stores/collection'

/**
 * Shell chrome: frozen route navigation, the route loading state and the
 * per-screen boundary. The `screen-extra` slot is inert in production; the
 * test root injects the crash probe there (see test-hooks.ts), so no test code
 * is imported by the production entry.
 *
 * Ticket #32: the chrome wears the C+ arena brand bar (mark + two-line wordmark,
 * inline route links, and a short meta cluster). Only existing routes are
 * linked; no route name or event name is added.
 */
const nav = [
  { name: 'start', path: '/', label: '首页' },
  { name: 'placement', path: '/placement', label: '布船' },
  { name: 'rps', path: '/rps', label: '猜拳' },
  { name: 'game', path: '/game', label: '对局' },
  { name: 'lobby', path: '/lobby', label: '大厅' },
  { name: 'leaderboard', path: '/leaderboard', label: '排行' },
  { name: 'profile', path: '/profile', label: '档案' },
  { name: 'settings', path: '/settings', label: '设置' },
  { name: 'replay', path: '/replay', label: '回放' },
  { name: 'spectate', path: '/spectate', label: '观战' },
  { name: 'game-over', path: '/game-over', label: '结算' },
]

const loading = computed(() => routeLoading.value)
const collection = useCollectionStore()
</script>

<template>
  <!-- Applied wallpaper layer (spec story 2); renders nothing until applied. -->
  <AppWallpaper />

  <!-- 图鉴 / 卡库 overlay: the 11 frozen routes have no slot for it. -->
  <CardCollectionOverlay v-if="collection.isOpen" @close="collection.close()" />

  <div class="app-shell" data-testid="app-shell" :data-route-loading="loading ? 'true' : 'false'">
    <nav class="app-nav" data-testid="app-nav" aria-label="主屏导航">
      <router-link class="app-brand" to="/" aria-label="回到首页">
        <span class="app-brand__mark" aria-hidden="true">⚓</span>
        <span class="app-brand__text">
          <b class="app-brand__title">战舰棋 · 竞技场</b>
          <small class="app-brand__sub">BATTLESHIP ARENA</small>
        </span>
      </router-link>

      <div class="app-nav__links">
        <router-link
          v-for="item in nav"
          :key="item.name"
          :to="item.path"
          class="app-nav__link"
          :data-testid="'nav-' + item.name"
        >
          {{ item.label }}
        </router-link>
      </div>

      <div class="app-nav__meta" aria-hidden="true">
        <span class="app-nav__pill">竞技场 <b>C+</b></span>
        <router-link class="app-nav__icon" :to="{ name: 'settings' }" title="设置" tabindex="-1">⚙</router-link>
        <router-link class="app-nav__icon" :to="{ name: 'replay' }" title="回放" tabindex="-1">▤</router-link>
      </div>
    </nav>

    <p v-if="loading" class="route-loading" data-testid="route-loading" role="status" aria-live="polite">
      正在切换界面…
    </p>

    <ScreenBoundary>
      <router-view v-slot="{ Component, route: viewRoute }">
        <component :is="Component" v-if="Component" :key="viewRoute.path" />
      </router-view>
      <slot name="screen-extra" />
    </ScreenBoundary>
  </div>
</template>
