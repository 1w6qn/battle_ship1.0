<script setup lang="ts">
import ScreenScaffold from '../../components/ScreenScaffold.vue'
</script>

<template>
  <ScreenScaffold
    screen="spectate"
    title="观战"
    hint="独立观战屏，绝不复用对局屏（#26 迁移）。"
  >
    <div class="screen__actions">
      <button type="button" class="button" data-testid="spectate-primary-action">离开观战</button>
      <p class="screen__note">
        占位组件：路由 / 错误边界 / 构建产物门禁可用；业务逻辑见后续票据。
      </p>
    </div>
  </ScreenScaffold>
</template>
