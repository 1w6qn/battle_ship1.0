<script setup lang="ts">
import ScreenScaffold from '../../components/ScreenScaffold.vue'
</script>

<template>
  <ScreenScaffold
    screen="replay"
    title="回放"
    hint="只走 HTTP 的回放步骤播放器（#28 迁移）。"
  >
    <div class="screen__actions">
      <button type="button" class="button" data-testid="replay-primary-action">播放</button>
      <p class="screen__note">
        占位组件：路由 / 错误边界 / 构建产物门禁可用；业务逻辑见后续票据。
      </p>
    </div>
  </ScreenScaffold>
</template>
