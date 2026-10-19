<script setup lang="ts">
import ScreenScaffold from '../../components/ScreenScaffold.vue'
</script>

<template>
  <ScreenScaffold
    screen="rps"
    title="猜拳"
    hint="石头剪刀布定先手（#24 迁移）。"
  >
    <div class="screen__actions">
      <button type="button" class="button" data-testid="rps-primary-action">出石头</button>
      <p class="screen__note">
        占位组件：路由 / 错误边界 / 构建产物门禁可用；业务逻辑见后续票据。
      </p>
    </div>
  </ScreenScaffold>
</template>
