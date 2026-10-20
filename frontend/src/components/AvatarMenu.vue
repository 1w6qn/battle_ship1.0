<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useCollectionStore } from '../stores/collection'
import { THEME_LABELS, useUiStore, type ThemeName } from '../stores/ui'

/**
 * Avatar menu: the only home of settings, appearance, help and login (spec
 * story 13-15, ticket #42). Three intent groups, no new routes.
 */
const emit = defineEmits<{ (event: 'close'): void }>()

const ui = useUiStore()
const collection = useCollectionStore()
const panel = ref<HTMLElement | null>(null)

const themes: ThemeName[] = ['chart', 'journal', 'night']

onMounted(() => {
  panel.value?.querySelector<HTMLElement>('a, button')?.focus()
})

function chooseTheme(theme: ThemeName): void {
  ui.setTheme(theme)
  ui.notify({ code: 'theme-' + theme, tone: 'success', message: '已切换到「' + THEME_LABELS[theme] + '」主题' })
}

function toggleMotion(): void {
  const next = ui.motion === 'reduced' ? 'auto' : 'reduced'
  ui.setMotion(next)
  ui.notify({
    code: 'motion-' + next,
    tone: 'success',
    message: next === 'reduced' ? '已减少动效，只保留状态变化' : '已恢复完整动效',
  })
}

function openCollection(): void {
  collection.open()
  emit('close')
}

function close(): void {
  emit('close')
}
</script>

<template>
  <div class="app-menu-scrim" data-testid="avatar-menu-scrim" @click="close"></div>
  <section
    ref="panel"
    class="app-menu"
    data-testid="avatar-menu"
    role="menu"
    aria-label="账号与设置"
    @keydown.esc.stop.prevent="close"
  >
    <section class="app-menu__group" data-testid="avatar-group-mine" aria-labelledby="avatar-group-mine-title">
      <h2 id="avatar-group-mine-title" class="app-menu__title">我的</h2>
      <router-link class="app-menu__item" :to="{ name: 'profile' }" data-testid="avatar-item-profile" @click="close">
        名片与战绩
      </router-link>
      <button type="button" class="app-menu__item" data-testid="avatar-item-collection" @click="openCollection">
        收藏（图鉴）
      </button>
    </section>

    <section class="app-menu__group" data-testid="avatar-group-appearance" aria-labelledby="avatar-group-appearance-title">
      <h2 id="avatar-group-appearance-title" class="app-menu__title">外观与声音</h2>
      <div class="app-menu__themes" role="group" aria-label="主题">
        <button
          v-for="theme in themes"
          :key="theme"
          type="button"
          class="app-menu__theme"
          :class="{ 'is-active': ui.theme === theme }"
          :data-testid="'theme-' + theme"
          :aria-pressed="ui.theme === theme"
          @click="chooseTheme(theme)"
        >
          {{ THEME_LABELS[theme] }}
        </button>
      </div>
      <button
        type="button"
        class="app-menu__item app-menu__item--toggle"
        data-testid="avatar-item-motion"
        :aria-pressed="ui.motion === 'reduced'"
        @click="toggleMotion"
      >
        减少动效
      </button>
      <router-link class="app-menu__item" :to="{ name: 'settings' }" data-testid="avatar-item-settings" @click="close">
        声音与设置
      </router-link>
    </section>

    <section class="app-menu__group" data-testid="avatar-group-about" aria-labelledby="avatar-group-about-title">
      <h2 id="avatar-group-about-title" class="app-menu__title">帮助与关于</h2>
      <router-link class="app-menu__item" :to="{ name: 'settings' }" data-testid="avatar-item-help" @click="close">
        玩法与帮助
      </router-link>
      <a class="app-menu__item" href="/login" data-testid="avatar-item-login">登录 / 注册</a>
      <p class="app-menu__version" data-testid="avatar-version">深海作战室 · 基础版</p>
    </section>
  </section>
</template>
