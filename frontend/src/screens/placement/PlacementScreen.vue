<script setup lang="ts">
import ScreenScaffold from '../../components/ScreenScaffold.vue'
</script>

<template>
  <ScreenScaffold
    screen="placement"
    title="布船"
    hint="36 格部署与 #player-board 的替代选择器（#23 迁移）。"
  >
    <div class="screen__actions">
      <button type="button" class="button" data-testid="placement-primary-action">随机布船</button>
      <p class="screen__note">
        占位组件：路由 / 错误边界 / 构建产物门禁可用；业务逻辑见后续票据。
      </p>
    </div>
  </ScreenScaffold>
</template>
