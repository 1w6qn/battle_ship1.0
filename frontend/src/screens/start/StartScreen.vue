<script setup lang="ts">
import ScreenScaffold from '../../components/ScreenScaffold.vue'
</script>

<template>
  <ScreenScaffold
    screen="start"
    title="首页"
    hint="首页入口与在线统计（#22 迁移）。"
  >
    <div class="screen__actions">
      <button type="button" class="button" data-testid="start-primary-action">寻找对局</button>
      <p class="screen__note">
        占位组件：路由 / 错误边界 / 构建产物门禁可用；业务逻辑见后续票据。
      </p>
    </div>
  </ScreenScaffold>
</template>
