<script setup lang="ts">
import ScreenScaffold from '../../components/ScreenScaffold.vue'
</script>

<template>
  <ScreenScaffold
    screen="leaderboard"
    title="排行榜"
    hint="战绩榜与段位榜是两个独立数据源（#27 迁移）。"
  >
    <div class="screen__actions">
      <button type="button" class="button" data-testid="leaderboard-primary-action">切换榜单</button>
      <p class="screen__note">
        占位组件：路由 / 错误边界 / 构建产物门禁可用；业务逻辑见后续票据。
      </p>
    </div>
  </ScreenScaffold>
</template>
