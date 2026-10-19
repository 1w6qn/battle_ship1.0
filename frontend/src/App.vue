<script setup lang="ts">
import { computed } from 'vue'
import ScreenBoundary from './components/ScreenBoundary.vue'
import { routeLoading } from './router'

/**
 * Shell chrome: frozen route navigation, the route loading state and the
 * per-screen boundary. The `screen-extra` slot is inert in production; the
 * test root injects the crash probe there (see test-hooks.ts), so no test code
 * is imported by the production entry.
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
</script>

<template>
  <div class="app-shell" data-testid="app-shell" :data-route-loading="loading ? 'true' : 'false'">
    <nav class="app-nav" data-testid="app-nav" aria-label="主屏导航">
      <router-link
        v-for="item in nav"
        :key="item.name"
        :to="item.path"
        class="app-nav__link"
        :data-testid="'nav-' + item.name"
      >
        {{ item.label }}
      </router-link>
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
